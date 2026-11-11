import asyncio
import base64
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.async_api import Page

from app.adapters.base import (
    AdapterCapabilities,
    AdapterExecutionError,
    AdapterImageResult,
    AdapterManualAuthRequired,
    EditRequest,
    GenerationRequest,
    SessionCheckResult,
    SiteAdapter,
)
from app.config import Settings
from app.main import create_app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_demo_site_app() -> FastAPI:
    site = FastAPI()

    @site.get("/login", response_class=HTMLResponse)
    async def login_page():
        return """
        <!doctype html>
        <html><body>
          <h1>Demo Auth</h1>
          <button id="auth-btn" onclick="localStorage.setItem('demo_auth', 'ok'); document.cookie='demo_session=verified; path=/; max-age=86400'; document.getElementById('msg').textContent='authenticated';">Sign In</button>
          <p id="msg">signed out</p>
        </body></html>
        """

    @site.get("/studio", response_class=HTMLResponse)
    async def studio_page():
        return """
        <!doctype html>
        <html><body>
          <h1>Demo Image Studio</h1>
          <div id="auth-state">checking</div>
          <textarea id="prompt-box"></textarea>
          <input id="file-box" type="file" accept="image/*">
          <button id="run-btn" type="button">Generate</button>
          <div id="status">idle</div>
          <div id="output"></div>
          <script>
            const hasCookie = document.cookie.includes('demo_session=verified');
            const hasLs = localStorage.getItem('demo_auth') === 'ok';
            document.getElementById('auth-state').textContent = (hasCookie && hasLs) ? 'ready' : 'locked';

            let uploadedName = '';
            let uploadedDataUrl = '';
            document.getElementById('file-box').addEventListener('change', (e) => {
              const f = e.target.files[0];
              if (!f) return;
              uploadedName = f.name;
              const r = new FileReader();
              r.onload = () => { uploadedDataUrl = r.result; };
              r.readAsDataURL(f);
            });

            document.getElementById('run-btn').addEventListener('click', () => {
              const prompt = document.getElementById('prompt-box').value;
              if (prompt.includes('FORCE_FAIL')) {
                document.getElementById('status').textContent = 'error: simulated failure';
                return;
              }
              if (prompt.includes('FORCE_AUTH')) {
                document.getElementById('auth-state').textContent = 'locked';
                return;
              }
              const delayMs = prompt.includes('SLOW_JOB') ? 1800 : 250;
              document.getElementById('status').textContent = 'running';
              setTimeout(() => {
                const canvas = document.createElement('canvas');
                canvas.width = 256;
                canvas.height = 256;
                const ctx = canvas.getContext('2d');
                ctx.fillStyle = uploadedDataUrl ? '#225588' : '#b45309';
                ctx.fillRect(0, 0, 256, 256);
                ctx.fillStyle = '#ffffff';
                ctx.font = '16px sans-serif';
                ctx.fillText(prompt.slice(0, 24), 16, 120);
                if (uploadedName) {
                  ctx.fillText('edited:' + uploadedName, 16, 150);
                }
                const img = document.createElement('img');
                img.id = 'result-img';
                img.width = 256;
                img.height = 256;
                img.src = canvas.toDataURL('image/png');
                const out = document.getElementById('output');
                out.replaceChildren(img);
                document.getElementById('status').textContent = 'done';
              }, delayMs);
            });
          </script>
        </body></html>
        """

    return site


class LocalStudioAdapter(SiteAdapter):
    """Test adapter driving the local demo web studio through real Playwright Chromium."""

    name = "local-studio"
    display_name = "Local Test Studio"
    model_aliases = ("local-studio", "test-model")
    capabilities = AdapterCapabilities(
        text_to_image=True,
        image_edit=True,
        models=["local-studio"],
        sizes=["256x256", "1024x1024"],
        max_images=1,
    )

    def __init__(self, base_url: str) -> None:
        self.home_url = f"{base_url}/studio"
        self.login_url = f"{base_url}/login"
        self.max_observed_concurrency = 0
        self._active = 0

    async def open_for_manual_auth(self, page: Page) -> None:
        await page.goto(self.login_url, wait_until="domcontentloaded")
        await page.click("#auth-btn")
        await page.wait_for_function("document.getElementById('msg').textContent === 'authenticated'")
        await page.wait_for_timeout(300)

    async def check_session(self, page: Page) -> SessionCheckResult:
        await page.goto(self.home_url, wait_until="domcontentloaded")
        state_text = await page.text_content("#auth-state")
        if state_text == "ready":
            return SessionCheckResult(status="ready", message="Cookie and localStorage verified.", url=page.url)
        return SessionCheckResult(status="needs_auth", message="Session locked; sign in required.", url=page.url)

    async def _run_studio(self, page: Page, prompt: str, image_path: Path | None) -> bytes:
        self._active += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self._active)
        try:
            await page.goto(self.home_url, wait_until="domcontentloaded")
            if await page.text_content("#auth-state") != "ready":
                raise AdapterManualAuthRequired("Demo studio session is locked")
            if image_path is not None:
                await page.set_input_files("#file-box", str(image_path))
                await page.wait_for_timeout(150)
            await page.fill("#prompt-box", prompt)
            await page.click("#run-btn")
            for _ in range(40):
                await asyncio.sleep(0.15)
                if await page.text_content("#auth-state") == "locked":
                    raise AdapterManualAuthRequired("Demo studio requested re-auth")
                status_text = await page.text_content("#status")
                if status_text and status_text.startswith("error:"):
                    raise AdapterExecutionError(status_text)
                if status_text == "done":
                    src = await page.get_attribute("#result-img", "src")
                    assert src and src.startswith("data:image/png;base64,")
                    return base64.b64decode(src.split(",", 1)[1])
            raise AdapterExecutionError("Timed out waiting for demo studio")
        finally:
            self._active -= 1

    async def generate_image(self, page: Page, req: GenerationRequest) -> AdapterImageResult:
        raw = await self._run_studio(page, req.prompt, None)
        return AdapterImageResult(images_bytes=[raw])

    async def edit_image(self, page: Page, req: EditRequest) -> AdapterImageResult:
        raw = await self._run_studio(page, req.prompt, req.image_path)
        return AdapterImageResult(images_bytes=[raw])


class BackgroundServer:
    def __init__(self, app: FastAPI, port: int, host: str = "127.0.0.1") -> None:
        self.config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("Server failed to start")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture()
def live_env(tmp_path: Path):
    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    adapter = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")

    settings = Settings(
        host="127.0.0.1",
        port=api_port,
        api_key=None,  # isolate tests from the project's real .env
        default_adapter="local-studio",
        data_dir=tmp_path / "data",
        browser_headless=True,
        max_concurrent_jobs=1,
        job_timeout_seconds=30,
        enable_browser_on_startup=True,
    )
    api_app = create_app(settings=settings, extra_adapters=[adapter])

    with BackgroundServer(demo_app, demo_port), BackgroundServer(api_app, api_port):
        yield f"http://127.0.0.1:{api_port}", adapter, settings


@pytest.fixture()
def env_factories():
    return {
        "free_port": free_port,
        "build_demo_site_app": build_demo_site_app,
        "LocalStudioAdapter": LocalStudioAdapter,
        "BackgroundServer": BackgroundServer,
    }
