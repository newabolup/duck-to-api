import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.base import SiteAdapter
from app.adapters.duck_ai import DuckAiAdapter
from app.adapters.registry import AdapterRegistry
from app.api import admin_routes, jobs_routes, openai_compat
from app.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.jobs import JobManager, JobStore
from app.core.log_bus import LogBus
from app.core.storage import ImageStorage

WEB_DIR = Path(__file__).resolve().parent / "web"


def _configure_logging(log_bus: LogBus) -> None:
    root = logging.getLogger("duck_to_api")
    root.setLevel(logging.INFO)
    if not any(isinstance(h, LogBus) for h in root.handlers):
        log_bus.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(log_bus)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, LogBus) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(stream)


def create_app(
    settings: Settings | None = None,
    extra_adapters: Sequence[SiteAdapter] | None = None,
) -> FastAPI:
    """Build and configure the FastAPI application with modular adapters and background workers."""
    cfg = settings or get_settings()
    log_bus = LogBus()
    _configure_logging(log_bus)

    if cfg.host in ("0.0.0.0", "::") and not cfg.api_key:
        logging.getLogger("duck_to_api.main").warning(
            "Service configured to bind on '%s' without DUCK_API_API_KEY; endpoints and browser controls are unprotected on the LAN.",
            cfg.host,
        )

    registry = AdapterRegistry(default_adapter=cfg.default_adapter)
    registry.register(DuckAiAdapter())
    if extra_adapters:
        for adapter in extra_adapters:
            registry.register(adapter)

    storage = ImageStorage(cfg.uploads_dir, cfg.outputs_dir, max_upload_bytes=cfg.max_upload_bytes)
    store = JobStore(cfg.db_path)
    browser = BrowserManager(
        profile_dir=cfg.profile_dir,
        headless=cfg.browser_headless,
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        channel=cfg.browser_channel,
        no_sandbox=cfg.chromium_no_sandbox,
    )
    jobs = JobManager(
        store=store,
        browser=browser,
        registry=registry,
        storage=storage,
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        job_timeout_seconds=cfg.job_timeout_seconds,
        sync_wait_timeout_seconds=cfg.sync_wait_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_bus.attach_loop(asyncio.get_running_loop())
        if cfg.enable_browser_on_startup:
            try:
                await browser.start()
            except Exception as exc:
                logging.getLogger("duck_to_api.main").error(
                    "Browser startup failed; API remains up for manual recovery: %s", exc
                )
        await jobs.start()
        try:
            yield
        finally:
            await jobs.stop()
            await browser.stop()

    app = FastAPI(
        title="duck-to-api",
        version="0.1.0",
        description="Modular browser-to-OpenAI image generation and editing service",
        lifespan=lifespan,
    )
    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=False if "*" in cfg.cors_origins else True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.state.settings = cfg
    app.state.log_bus = log_bus
    app.state.registry = registry
    app.state.storage = storage
    app.state.store = store
    app.state.browser = browser
    app.state.jobs = jobs

    app.include_router(openai_compat.router)
    app.include_router(jobs_routes.router)
    app.include_router(admin_routes.router)

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index_file = WEB_DIR / "index.html"
        if not index_file.is_file():
            return {"service": "duck-to-api", "docs": "/docs"}
        return FileResponse(index_file)

    return app


app = create_app()
