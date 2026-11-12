import time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.registry import AdapterRegistry
from app.api.deps import get_jobs, get_registry, get_settings_dep, get_storage, require_api_key
from app.config import Settings
from app.core.jobs import JobManager, JobRecord
from app.core.security import sign_file_token
from app.core.storage import ImageStorage

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"], dependencies=[Depends(require_api_key)])


class ImageGenerationPayload(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    model: str | None = Field(default=None)
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = Field(default="1024x1024")
    response_format: Literal["url", "b64_json"] = Field(default="url")
    quality: str | None = Field(default=None)
    style: str | None = Field(default=None)
    output_format: str | None = Field(default=None)
    user: str | None = Field(default=None)
    async_mode: bool = Field(default=False)


def _public_base_url(request: Request, settings: Settings) -> str:
    if settings.base_url:
        return settings.base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _openai_error(
    status_code: int,
    message: str,
    code: str,
    err_type: str = "api_error",
    job_id: str | None = None,
) -> JSONResponse:
    error_body: dict = {
        "message": message,
        "type": err_type,
        "code": code,
    }
    if job_id:
        error_body["job_id"] = job_id
    return JSONResponse(
        status_code=status_code,
        content={"error": error_body},
        headers={"X-Should-Retry": "false"},
    )


def _format_openai_success(
    job: JobRecord,
    response_format: str,
    base_url: str,
    storage: ImageStorage,
    api_key: str | None,
) -> dict:
    items = []
    for fname in job.output_filenames:
        if response_format == "b64_json":
            items.append({"b64_json": storage.read_output_b64(fname), "revised_prompt": job.prompt})
        else:
            url = f"{base_url}/files/outputs/{fname}"
            if api_key:
                tok = sign_file_token(api_key, f"outputs/{fname}")
                url = f"{url}?token={tok}"
            items.append({"url": url, "revised_prompt": job.prompt})
    return {
        "created": int(time.time()),
        "job_id": job.id,
        "adapter": job.adapter,
        "data": items,
    }


def _resolve_terminal_job(
    job: JobRecord,
    response_format: str,
    base_url: str,
    storage: ImageStorage,
    api_key: str | None,
) -> JSONResponse | dict:
    if job.status == "completed":
        return _format_openai_success(job, response_format, base_url, storage, api_key)
    if job.status == "needs_auth":
        return _openai_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            job.error or "Manual browser verification required",
            "manual_auth_required",
            job_id=job.id,
        )
    if job.status == "cancelled":
        return _openai_error(409, job.error or "Job was cancelled", "job_cancelled", job_id=job.id)
    return _openai_error(
        status.HTTP_502_BAD_GATEWAY,
        job.error or "Image job failed",
        "generation_failed",
        job_id=job.id,
    )


@router.get("/models")
async def list_models(registry: AdapterRegistry = Depends(get_registry)) -> dict:
    created = int(time.time())
    data = []
    for item in registry.list_adapters():
        data.append({
            "id": item["name"],
            "object": "model",
            "created": created,
            "owned_by": item["display_name"],
            "capabilities": item["capabilities"],
        })
    return {"object": "list", "data": data}


@router.get("/models/{model_id}")
async def get_model(model_id: str, registry: AdapterRegistry = Depends(get_registry)):
    try:
        adapter = registry.get(model_id)
    except KeyError as exc:
        return _openai_error(404, str(exc), "model_not_found", err_type="invalid_request_error")
    return {
        "id": adapter.name,
        "object": "model",
        "created": int(time.time()),
        "owned_by": adapter.display_name,
    }


@router.post("/images/generations")
async def create_image_generation(
    request: Request,
    payload: ImageGenerationPayload,
    x_async_mode: str | None = Header(default=None),
    jobs: JobManager = Depends(get_jobs),
    storage: ImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings_dep),
):
    try:
        job = await jobs.enqueue_generate(
            prompt=payload.prompt,
            adapter_or_model=payload.model,
            size=payload.size,
            n=payload.n,
        )
    except (KeyError, ValueError) as exc:
        return _openai_error(400, str(exc), "invalid_request", err_type="invalid_request_error")

    is_async = payload.async_mode or (x_async_mode or "").strip().lower() in ("1", "true", "yes")
    if is_async:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job.id,
                "status": job.status,
                "adapter": job.adapter,
                "status_url": f"/api/v1/jobs/{job.id}",
            },
        )

    try:
        completed = await jobs.wait_for_job(job.id)
    except TimeoutError:
        return _openai_error(504, "Timed out waiting for image generation job", "job_timeout", job_id=job.id)

    return _resolve_terminal_job(
        completed,
        payload.response_format,
        _public_base_url(request, settings),
        storage,
        settings.api_key,
    )


@router.post("/images/edits")
async def create_image_edit(
    request: Request,
    image: UploadFile | None = File(default=None),
    image_array: list[UploadFile] | None = File(default=None, alias="image[]"),
    mask: UploadFile | None = File(default=None),
    prompt: str = Form(..., min_length=1, max_length=8000),
    model: str | None = Form(default=None),
    n: int = Form(default=1, ge=1, le=4),
    size: str | None = Form(default="1024x1024"),
    response_format: Literal["url", "b64_json"] = Form(default="url"),
    quality: str | None = Form(default=None),
    output_format: str | None = Form(default=None),
    async_mode: bool = Form(default=False),
    x_async_mode: str | None = Header(default=None),
    jobs: JobManager = Depends(get_jobs),
    storage: ImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings_dep),
):
    uploads: list[UploadFile] = []
    if image is not None:
        uploads.append(image)
    if image_array:
        uploads.extend(image_array)
    if not uploads:
        return _openai_error(400, "Missing uploaded image file", "missing_image", err_type="invalid_request_error")

    raw_list: list[bytes] = []
    for source_file in uploads:
        raw_bytes = await source_file.read(settings.max_upload_bytes + 1)
        if not raw_bytes:
            return _openai_error(
                400,
                f"Uploaded image file '{source_file.filename}' is empty",
                "empty_image",
                err_type="invalid_request_error",
            )
        if len(raw_bytes) > settings.max_upload_bytes:
            return _openai_error(
                413,
                f"Uploaded image exceeds max size of {settings.max_upload_bytes // (1024 * 1024)} MB",
                "payload_too_large",
                err_type="invalid_request_error",
            )
        raw_list.append(raw_bytes)

    try:
        job = await jobs.enqueue_edit(
            prompt=prompt,
            image_bytes=raw_list,
            adapter_or_model=model,
            size=size,
            n=n,
        )
    except (KeyError, ValueError) as exc:
        return _openai_error(400, str(exc), "invalid_image", err_type="invalid_request_error")

    is_async = async_mode or (x_async_mode or "").strip().lower() in ("1", "true", "yes")
    if is_async:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job.id,
                "status": job.status,
                "adapter": job.adapter,
                "status_url": f"/api/v1/jobs/{job.id}",
            },
        )

    try:
        completed = await jobs.wait_for_job(job.id)
    except TimeoutError:
        return _openai_error(504, "Timed out waiting for image edit job", "job_timeout", job_id=job.id)

    return _resolve_terminal_job(
        completed,
        response_format,
        _public_base_url(request, settings),
        storage,
        settings.api_key,
    )
