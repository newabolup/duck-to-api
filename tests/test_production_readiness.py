import base64
import concurrent.futures
import io
import logging
import socket
import sqlite3
import time
from pathlib import Path

import httpx
import openai
from PIL import Image

from app.config import Settings
from app.main import create_app


def _img_bytes(fmt: str, color: tuple[int, int, int] = (40, 140, 210), size: tuple[int, int] = (48, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format=fmt)
    return buf.getvalue()


def _detect_lan_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip if ip and not ip.startswith("127.") else None
    except OSError:
        return None


def test_openai_sdk_compatibility_and_formats(tmp_path: Path, env_factories):
    free_port = env_factories["free_port"]
    build_demo_site_app = env_factories["build_demo_site_app"]
    LocalStudioAdapter = env_factories["LocalStudioAdapter"]
    BackgroundServer = env_factories["BackgroundServer"]

    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    adapter = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")

    settings = Settings(
        host="127.0.0.1",
        port=api_port,
        api_key="sdk-secret-123",
        default_adapter="local-studio",
        data_dir=tmp_path / "sdk_data",
        max_upload_bytes=1024 * 1024,
        enable_browser_on_startup=True,
    )
    app = create_app(settings=settings, extra_adapters=[adapter])

    with BackgroundServer(demo_app, demo_port), BackgroundServer(app, api_port):
        base = f"http://127.0.0.1:{api_port}"
        auth_headers = {"Authorization": "Bearer sdk-secret-123"}

        with httpx.Client(base_url=base, timeout=30.0) as http:
            # Authenticate browser session
            assert http.post(
                "/api/v1/browser/open-login",
                json={"adapter": "local-studio"},
                headers=auth_headers,
            ).status_code == 200

            # Health must not leak profile_dir without auth
            anon_health = http.get("/health").json()
            assert anon_health == {"status": "ok", "auth_required": True}

        client = openai.OpenAI(base_url=f"{base}/v1", api_key="sdk-secret-123", timeout=30.0)

        # Model listing & retrieval
        models = client.models.list()
        assert any(m.id == "local-studio" for m in models.data)
        retrieved = client.models.retrieve("local-studio")
        assert retrieved.id == "local-studio"

        # OpenAI SDK images.generate (url + b64_json)
        gen_url = client.images.generate(
            model="local-studio",
            prompt="sdk url duck",
            size="1024x1024",
            response_format="url",
        )
        assert len(gen_url.data) == 1
        returned_url = gen_url.data[0].url
        assert returned_url and "?token=" in returned_url

        # Signed URL downloads without master Authorization header; tampering or stripping token fails with 401
        with httpx.Client(timeout=15.0) as anon:
            r_signed = anon.get(returned_url)
            assert r_signed.status_code == 200
            assert r_signed.headers["content-type"].startswith("image/png")
            assert r_signed.headers.get("x-content-type-options") == "nosniff"

            bare_url = returned_url.split("?")[0]
            assert anon.get(bare_url).status_code == 401
            assert anon.get(f"{bare_url}?token=1999999999.deadbeef").status_code == 401

        gen_b64 = client.images.generate(
            model="local-studio",
            prompt="sdk b64 duck",
            response_format="b64_json",
        )
        raw_out = base64.b64decode(gen_b64.data[0].b64_json)
        with Image.open(io.BytesIO(raw_out)) as im:
            assert im.format == "PNG"

        # OpenAI SDK images.edit with JPEG and BMP (BMP normalized to PNG)
        for fmt, ext in [("JPEG", "photo.jpg"), ("BMP", "bitmap.bmp"), ("WEBP", "pic.webp")]:
            img_io = io.BytesIO(_img_bytes(fmt))
            img_io.name = ext
            edit_res = client.images.edit(
                image=img_io,
                prompt=f"edit from {fmt}",
                model="local-studio",
                response_format="url",
            )
            assert edit_res.data[0].url and "?token=" in edit_res.data[0].url

        # Corrupt and oversized uploads must return structured 400 / 413 errors
        with httpx.Client(base_url=base, headers=auth_headers, timeout=15.0) as http:
            r_bad = http.post(
                "/v1/images/edits",
                data={"prompt": "bad upload", "model": "local-studio"},
                files={"image": ("bad.png", b"not-a-real-image", "image/png")},
            )
            assert r_bad.status_code == 400
            assert "error" in r_bad.json()

            r_big = http.post(
                "/v1/images/edits",
                data={"prompt": "too large", "model": "local-studio"},
                files={"image": ("huge.bin", b"A" * (1024 * 1024 + 16), "application/octet-stream")},
            )
            assert r_big.status_code == 413
            assert r_big.json()["error"]["code"] == "payload_too_large"

            # Dashboard HttpOnly cookie flow allows authenticated file & log access
            sess = http.post("/api/v1/auth/session")
            assert sess.status_code == 200
            assert "duck_api_session" in http.cookies
            bare_path = returned_url.replace(base, "").split("?")[0]
            assert httpx.get(f"{base}{bare_path}", cookies=http.cookies).status_code == 200


def test_crash_recovery_running_jobs_and_browser_relaunch(tmp_path: Path, env_factories):
    free_port = env_factories["free_port"]
    build_demo_site_app = env_factories["build_demo_site_app"]
    LocalStudioAdapter = env_factories["LocalStudioAdapter"]
    BackgroundServer = env_factories["BackgroundServer"]

    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    data_dir = tmp_path / "crash_data"

    # Pre-seed SQLite with a job stuck in 'running' and a job left in 'queued'
    db_path = data_dir / "jobs.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                adapter TEXT NOT NULL,
                model TEXT,
                prompt TEXT NOT NULL,
                size TEXT,
                n INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                input_filename TEXT,
                output_filenames TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                duration_ms INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "INSERT INTO jobs (id, job_type, adapter, model, prompt, size, n, status, created_at) "
            "VALUES ('job_stuck_run', 'generate', 'local-studio', 'local-studio', 'crashed mid run', '1024x1024', 1, 'running', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO jobs (id, job_type, adapter, model, prompt, size, n, status, created_at) "
            "VALUES ('job_left_queue', 'generate', 'local-studio', 'local-studio', 'resume after boot', '1024x1024', 1, 'queued', '2026-01-01T00:00:01+00:00')"
        )

    # Plant a stale lockfile inside browser_profile to simulate abrupt Windows restart
    profile_dir = data_dir / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "SingletonLock").write_text("stale-pid", encoding="utf-8")

    with BackgroundServer(demo_app, demo_port):
        adapter = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")
        settings = Settings(
            host="127.0.0.1",
            port=api_port,
            api_key=None,  # isolate tests from the project's real .env
            default_adapter="local-studio",
            data_dir=data_dir,
            browser_headless=True,
            enable_browser_on_startup=True,
        )
        app = create_app(settings=settings, extra_adapters=[adapter])
        with BackgroundServer(app, api_port):
            with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=30.0) as client:
                # Leftover 'running' job must be failed on startup, and 'queued' job must be drained (not stuck queued)
                stuck = client.get("/api/v1/jobs/job_stuck_run").json()
                assert stuck["status"] == "failed"
                assert "Interrupted" in stuck["error"]

                for _ in range(50):
                    resumed = client.get("/api/v1/jobs/job_left_queue").json()
                    if resumed["status"] not in ("queued", "running"):
                        break
                    time.sleep(0.1)
                assert resumed["status"] == "needs_auth"

                # Authenticate once, then simulate sudden browser window closure
                assert client.post("/api/v1/browser/open-login", json={"adapter": "local-studio"}).status_code == 200

                # Simulate external crash/close of browser context via stop(), then verify next job auto-recovers
                import asyncio
                fut = asyncio.run_coroutine_threadsafe(app.state.browser._close_context(), app.state.log_bus._loop)
                fut.result(timeout=10)
                assert client.get("/api/v1/browser/status").json()["running"] is False

                r = client.post("/v1/images/generations", json={"prompt": "after browser close"})
                assert r.status_code == 200
                assert client.get("/api/v1/browser/status").json()["running"] is True


def test_multiclient_concurrent_requests_and_lan_bind(tmp_path: Path, env_factories, caplog):
    free_port = env_factories["free_port"]
    build_demo_site_app = env_factories["build_demo_site_app"]
    LocalStudioAdapter = env_factories["LocalStudioAdapter"]
    BackgroundServer = env_factories["BackgroundServer"]

    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    adapter = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")

    # Verify LAN security warning when host=0.0.0.0 without api_key
    with caplog.at_level(logging.WARNING, logger="duck_to_api.main"):
        warn_app = create_app(
            settings=Settings(
                host="0.0.0.0",
                port=free_port(),
                api_key=None,
                data_dir=tmp_path / "warn_only",
                enable_browser_on_startup=False,
            )
        )
        assert warn_app is not None
    assert any("0.0.0.0" in rec.message for rec in caplog.records)

    settings = Settings(
        host="0.0.0.0",
        port=api_port,
        api_key="lan-key",
        default_adapter="local-studio",
        data_dir=tmp_path / "lan_data",
        max_concurrent_jobs=1,
        enable_browser_on_startup=True,
    )
    app = create_app(settings=settings, extra_adapters=[adapter])
    lan_ip = _detect_lan_ipv4() or "127.0.0.1"

    with BackgroundServer(demo_app, demo_port), BackgroundServer(app, api_port, host="0.0.0.0"):
        # The server binds 0.0.0.0, so prefer the LAN IP — but in sandboxed
        # environments the host's own LAN IP may not route back to itself
        # (connections hang or reset), so probe it first and fall back to
        # loopback. The 0.0.0.0 bind and the concurrency checks still run
        # either way; only the reachability path changes.
        base = f"http://{lan_ip}:{api_port}"
        try:
            with httpx.Client(timeout=3.0) as probe:
                probe_ok = probe.get(f"{base}/health").status_code == 200
        except Exception:
            probe_ok = False
        if not probe_ok:
            base = f"http://127.0.0.1:{api_port}"
        headers = {"Authorization": "Bearer lan-key"}
        with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
            assert client.post("/api/v1/browser/open-login", json={"adapter": "local-studio"}).status_code == 200

        def call_openai_sync(idx: int) -> str:
            sdk = openai.OpenAI(base_url=f"{base}/v1", api_key="lan-key", timeout=60.0)
            res = sdk.images.generate(model="local-studio", prompt=f"SLOW_JOB sdk {idx}", response_format="url")
            return res.data[0].url or ""

        def call_telegram_async(idx: int) -> str:
            with httpx.Client(base_url=base, headers=headers, timeout=30.0) as c:
                j = c.post("/api/v1/jobs/generate", json={"prompt": f"SLOW_JOB tg {idx}", "adapter": "local-studio"}).json()
                jid = j["id"]
                for _ in range(80):
                    st = c.get(f"/api/v1/jobs/{jid}").json()
                    if st["status"] == "completed":
                        return st["output_urls"][0]
                    time.sleep(0.2)
                raise TimeoutError(f"Telegram job {jid} timed out")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futs = [
                pool.submit(call_openai_sync, 1),
                pool.submit(call_telegram_async, 1),
                pool.submit(call_openai_sync, 2),
                pool.submit(call_telegram_async, 2),
            ]
            urls = [f.result(timeout=60) for f in futs]

        assert len(urls) == 4
        assert adapter.max_observed_concurrency == 1


def test_openai_no_retry_header_and_linux_display_guard(tmp_path: Path, monkeypatch, env_factories):
    free_port = env_factories["free_port"]
    build_demo_site_app = env_factories["build_demo_site_app"]
    LocalStudioAdapter = env_factories["LocalStudioAdapter"]
    BackgroundServer = env_factories["BackgroundServer"]

    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    adapter = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")
    settings = Settings(
        host="127.0.0.1",
        port=api_port,
        api_key=None,  # isolate tests from the project's real .env
        default_adapter="local-studio",
        data_dir=tmp_path / "guard_data",
        browser_headless=True,
        enable_browser_on_startup=True,
    )
    app = create_app(settings=settings, extra_adapters=[adapter])

    with BackgroundServer(demo_app, demo_port), BackgroundServer(app, api_port):
        with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=20.0) as client:
            r = client.post("/v1/images/generations", json={"prompt": "fail once", "model": "local-studio"})
            assert r.status_code == 503
            assert r.headers.get("x-should-retry") == "false"

    # Simulate Linux without DISPLAY/WAYLAND_DISPLAY when requesting headed mode
    import asyncio
    import app.core.browser as browser_mod

    monkeypatch.setattr(browser_mod.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    bm = browser_mod.BrowserManager(profile_dir=tmp_path / "linux_prof", headless=False)
    try:
        asyncio.run(bm.start())
        assert False, "Expected RuntimeError when DISPLAY and WAYLAND_DISPLAY are unset on Linux"
    except RuntimeError as exc:
        assert "DISPLAY" in str(exc)
