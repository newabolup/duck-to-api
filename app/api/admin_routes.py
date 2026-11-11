import asyncio
import json

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.adapters.registry import AdapterRegistry
from app.api.deps import (
    SESSION_COOKIE_NAME,
    get_browser,
    get_jobs,
    get_log_bus,
    get_registry,
    get_settings_dep,
    get_storage,
    is_request_authenticated,
    require_api_key,
    verify_file_access,
)
from app.config import Settings
from app.core.browser import BrowserManager
from app.core.jobs import JobManager
from app.core.log_bus import LogBus
from app.core.security import create_session_cookie_value
from app.core.storage import ImageStorage

router = APIRouter(tags=["Operations"])


class BrowserModePayload(BaseModel):
    headless: bool


class AdapterSelectPayload(BaseModel):
    adapter: str | None = None


@router.get("/health")
async def health(
    settings: Settings = Depends(get_settings_dep),
    browser: BrowserManager = Depends(get_browser),
    jobs: JobManager = Depends(get_jobs),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    duck_api_session: str | None = Cookie(default=None),
) -> dict:
    if settings.api_key and not is_request_authenticated(
        settings.api_key, authorization, x_api_key, duck_api_session
    ):
        return {"status": "ok", "auth_required": True}
    return {
        "status": "ok",
        "auth_required": bool(settings.api_key),
        "browser": browser.state.to_dict(),
        "queue": await jobs.queue_snapshot(),
    }


@router.post("/api/v1/auth/session", dependencies=[Depends(require_api_key)])
async def establish_dashboard_session(
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    if settings.api_key:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=create_session_cookie_value(settings.api_key),
            httponly=True,
            samesite="strict",
            path="/",
        )
    return {"authenticated": True}


@router.delete("/api/v1/auth/session")
async def clear_dashboard_session(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"authenticated": False}


@router.get("/api/v1/adapters", dependencies=[Depends(require_api_key)])
async def list_adapters(registry: AdapterRegistry = Depends(get_registry)) -> dict:
    return {"adapters": registry.list_adapters()}


@router.get("/api/v1/browser/status", dependencies=[Depends(require_api_key)])
async def browser_status(browser: BrowserManager = Depends(get_browser)) -> dict:
    return browser.state.to_dict()


@router.post("/api/v1/browser/mode", dependencies=[Depends(require_api_key)])
async def set_browser_mode(
    payload: BrowserModePayload,
    browser: BrowserManager = Depends(get_browser),
) -> dict:
    try:
        return await browser.restart(headless=payload.headless)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/browser/open-login", dependencies=[Depends(require_api_key)])
async def open_manual_login(
    payload: AdapterSelectPayload | None = None,
    browser: BrowserManager = Depends(get_browser),
    registry: AdapterRegistry = Depends(get_registry),
) -> dict:
    adapter_name = payload.adapter if payload else None
    try:
        adapter = registry.get(adapter_name)
        return await browser.open_manual_auth(adapter)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/browser/check-session", dependencies=[Depends(require_api_key)])
async def check_session(
    payload: AdapterSelectPayload | None = None,
    browser: BrowserManager = Depends(get_browser),
    registry: AdapterRegistry = Depends(get_registry),
) -> dict:
    adapter_name = payload.adapter if payload else None
    try:
        adapter = registry.get(adapter_name)
        return await browser.check_adapter_session(adapter)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/browser/restart", dependencies=[Depends(require_api_key)])
async def restart_browser(browser: BrowserManager = Depends(get_browser)) -> dict:
    try:
        return await browser.restart()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/v1/logs", dependencies=[Depends(require_api_key)])
async def get_recent_logs(
    limit: int = Query(default=150, ge=1, le=400),
    log_bus: LogBus = Depends(get_log_bus),
) -> dict:
    return {"logs": log_bus.recent(limit=limit)}


@router.get("/api/v1/logs/stream", dependencies=[Depends(require_api_key)])
async def stream_logs(request: Request, log_bus: LogBus = Depends(get_log_bus)):
    async def event_generator():
        for entry in log_bus.recent(limit=80):
            yield f"data: {json.dumps(entry)}\n\n"
        async for entry in log_bus.subscribe():
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(entry.to_dict())}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/files/outputs/{filename}")
async def serve_output_file(
    request: Request,
    filename: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    duck_api_session: str | None = Cookie(default=None),
    storage: ImageStorage = Depends(get_storage),
):
    verify_file_access(request, f"outputs/{filename}", token, authorization, x_api_key, duck_api_session)
    try:
        path = storage.get_output_path(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Output file not found") from exc
    return FileResponse(
        path,
        media_type=storage.media_type_for_path(path),
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/files/uploads/{filename}")
async def serve_upload_file(
    request: Request,
    filename: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    duck_api_session: str | None = Cookie(default=None),
    storage: ImageStorage = Depends(get_storage),
):
    verify_file_access(request, f"uploads/{filename}", token, authorization, x_api_key, duck_api_session)
    try:
        path = storage.get_upload_path(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Upload file not found") from exc
    return FileResponse(
        path,
        media_type=storage.media_type_for_path(path),
        headers={"X-Content-Type-Options": "nosniff"},
    )
