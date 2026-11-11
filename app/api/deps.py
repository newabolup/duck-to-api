from fastapi import Cookie, Header, HTTPException, Request, status

from app.adapters.registry import AdapterRegistry
from app.config import Settings
from app.core.browser import BrowserManager
from app.core.jobs import JobManager
from app.core.log_bus import LogBus
from app.core.security import constant_time_equals, verify_file_token, verify_session_cookie_value
from app.core.storage import ImageStorage

SESSION_COOKIE_NAME = "duck_api_session"


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> AdapterRegistry:
    return request.app.state.registry


def get_browser(request: Request) -> BrowserManager:
    return request.app.state.browser


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def get_storage(request: Request) -> ImageStorage:
    return request.app.state.storage


def get_log_bus(request: Request) -> LogBus:
    return request.app.state.log_bus


def _extract_token(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_key:
        return x_api_key.strip()
    return None


def is_request_authenticated(
    expected_api_key: str | None,
    authorization: str | None,
    x_api_key: str | None,
    session_cookie: str | None,
) -> bool:
    if not expected_api_key:
        return True
    token = _extract_token(authorization, x_api_key)
    if constant_time_equals(token, expected_api_key):
        return True
    if verify_session_cookie_value(expected_api_key, session_cookie):
        return True
    return False


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    duck_api_session: str | None = Cookie(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    if not is_request_authenticated(expected, authorization, x_api_key, duck_api_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def verify_file_access(
    request: Request,
    resource_path: str,
    file_token: str | None,
    authorization: str | None,
    x_api_key: str | None,
    session_cookie: str | None,
) -> None:
    expected = request.app.state.settings.api_key
    if not expected:
        return
    if is_request_authenticated(expected, authorization, x_api_key, session_cookie):
        return
    if verify_file_token(expected, resource_path, file_token):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing file access credentials",
    )
