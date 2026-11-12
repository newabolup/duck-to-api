from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import get_jobs, get_settings_dep, require_api_key
from app.config import Settings
from app.core.jobs import JobManager

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"], dependencies=[Depends(require_api_key)])


class CreateGenerateJobPayload(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    adapter: str | None = Field(default=None)
    model: str | None = Field(default=None)
    size: str | None = Field(default="1024x1024")
    n: int = Field(default=1, ge=1, le=4)


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_generate_job(
    payload: CreateGenerateJobPayload,
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    try:
        job = await jobs.enqueue_generate(
            prompt=payload.prompt,
            adapter_or_model=payload.adapter or payload.model,
            size=payload.size,
            n=payload.n,
        )
        return job.to_dict(api_key=settings.api_key)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/edit", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_edit_job(
    image: UploadFile | None = File(default=None),
    image_array: list[UploadFile] | None = File(default=None, alias="image[]"),
    prompt: str = Form(..., min_length=1, max_length=8000),
    adapter: str | None = Form(default=None),
    model: str | None = Form(default=None),
    size: str | None = Form(default="1024x1024"),
    n: int = Form(default=1, ge=1, le=4),
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    uploads: list[UploadFile] = []
    if image is not None:
        uploads.append(image)
    if image_array:
        uploads.extend(image_array)
    if not uploads:
        raise HTTPException(status_code=400, detail="Missing uploaded image file")
    raw_list: list[bytes] = []
    for source_file in uploads:
        raw_bytes = await source_file.read(settings.max_upload_bytes + 1)
        if not raw_bytes:
            raise HTTPException(status_code=400, detail=f"Uploaded image file '{source_file.filename}' is empty")
        if len(raw_bytes) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds max size of {settings.max_upload_bytes // (1024 * 1024)} MB",
            )
        raw_list.append(raw_bytes)
    try:
        job = await jobs.enqueue_edit(
            prompt=prompt,
            image_bytes=raw_list,
            adapter_or_model=adapter or model,
            size=size,
            n=n,
        )
        return job.to_dict(api_key=settings.api_key)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    records = await jobs.store.list(status=status_filter, limit=limit, offset=offset)
    snapshot = await jobs.queue_snapshot()
    return {
        "jobs": [item.to_dict(api_key=settings.api_key) for item in records],
        "queue": snapshot,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    job = await jobs.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict(api_key=settings.api_key)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    job = await jobs.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict(api_key=settings.api_key)


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    job_id: str,
    jobs: JobManager = Depends(get_jobs),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    try:
        job = await jobs.retry_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict(api_key=settings.api_key)
