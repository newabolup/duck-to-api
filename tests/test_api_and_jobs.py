import base64
import io
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.main import create_app


def _make_png_bytes(color: tuple[int, int, int] = (220, 120, 40), size: tuple[int, int] = (64, 64)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_full_end_to_end_pipeline(live_env):
    base_url, adapter, _ = live_env
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # 1. Initial session check reports needs_auth before manual auth
        r = client.post("/api/v1/browser/check-session", json={"adapter": "local-studio"})
        assert r.status_code == 200
        assert r.json()["status"] == "needs_auth"

        # 2. Generating while unauthenticated returns 503 manual_auth_required
        r = client.post("/v1/images/generations", json={"prompt": "orange duck", "model": "local-studio"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "manual_auth_required"

        # 3. Perform manual auth in persistent profile, switch back to headless, confirm persistence
        r = client.post("/api/v1/browser/open-login", json={"adapter": "local-studio"})
        assert r.status_code == 200
        assert r.json()["manual_auth_mode"] is True

        r = client.post("/api/v1/browser/mode", json={"headless": True})
        assert r.status_code == 200
        assert r.json()["headless"] is True

        r = client.post("/api/v1/browser/check-session", json={"adapter": "local-studio"})
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

        # 4. OpenAI-compatible image generation (url and b64_json)
        r = client.post(
            "/v1/images/generations",
            json={"prompt": "amber geometric duck", "model": "test-model", "response_format": "url"},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["data"]) == 1
        img_url = body["data"][0]["url"]
        img_resp = client.get(img_url.replace(base_url, ""))
        assert img_resp.status_code == 200
        with Image.open(io.BytesIO(img_resp.content)) as im:
            assert im.size == (256, 256)

        r_b64 = client.post(
            "/v1/images/generations",
            json={"prompt": "b64 test", "response_format": "b64_json"},
        )
        assert r_b64.status_code == 200
        decoded = base64.b64decode(r_b64.json()["data"][0]["b64_json"])
        with Image.open(io.BytesIO(decoded)) as im:
            assert im.size == (256, 256)

        # 5. OpenAI-compatible image upload + edit
        src_png = _make_png_bytes()
        r_edit = client.post(
            "/v1/images/edits",
            data={"prompt": "make it ocean blue", "model": "local-studio", "response_format": "url"},
            files={"image": ("source.png", src_png, "image/png")},
        )
        assert r_edit.status_code == 200
        edit_job_id = r_edit.json()["job_id"]
        job_detail = client.get(f"/api/v1/jobs/{edit_job_id}").json()
        assert job_detail["job_type"] == "edit"
        assert job_detail["status"] == "completed"
        assert job_detail["input_url"].startswith("/files/uploads/")

        # 6. Concurrency & Job Management (enqueue 3 async jobs, verify single concurrency, cancel)
        j1 = client.post("/api/v1/jobs/generate", json={"prompt": "SLOW_JOB first"}).json()
        j2 = client.post("/api/v1/jobs/generate", json={"prompt": "SLOW_JOB second"}).json()
        j3 = client.post("/api/v1/jobs/generate", json={"prompt": "SLOW_JOB cancel me"}).json()

        c_resp = client.post(f"/api/v1/jobs/{j3['id']}/cancel")
        assert c_resp.status_code == 200
        assert c_resp.json()["status"] == "cancelled"

        for jid in (j1["id"], j2["id"]):
            for _ in range(60):
                st = client.get(f"/api/v1/jobs/{jid}").json()
                if st["status"] in ("completed", "failed"):
                    assert st["status"] == "completed"
                    break
                time.sleep(0.2)
            else:
                pytest.fail(f"Job {jid} did not complete in time")

        assert adapter.max_observed_concurrency == 1

        # 7. Error reporting + Retry
        r_fail = client.post("/v1/images/generations", json={"prompt": "FORCE_FAIL"})
        assert r_fail.status_code == 502
        failed_id = r_fail.json()["error"]["job_id"]
        assert client.get(f"/api/v1/jobs/{failed_id}").json()["status"] == "failed"

        r_retry = client.post(f"/api/v1/jobs/{failed_id}/retry")
        assert r_retry.status_code == 202
        retried_id = r_retry.json()["id"]
        assert retried_id != failed_id

        # 8. OpenAI Models listing reflects registered adapters
        models = client.get("/v1/models").json()["data"]
        ids = {m["id"] for m in models}
        assert "duck-ai" in ids
        assert "local-studio" in ids


def test_session_and_history_persist_across_server_restart(tmp_path: Path, env_factories):
    free_port = env_factories["free_port"]
    build_demo_site_app = env_factories["build_demo_site_app"]
    LocalStudioAdapter = env_factories["LocalStudioAdapter"]
    BackgroundServer = env_factories["BackgroundServer"]

    demo_port = free_port()
    api_port = free_port()
    demo_app = build_demo_site_app()
    data_dir = tmp_path / "persistent_data"

    with BackgroundServer(demo_app, demo_port):
        adapter1 = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")
        s1 = Settings(
            host="127.0.0.1",
            port=api_port,
            api_key=None,  # isolate tests from the project's real .env
            default_adapter="local-studio",
            data_dir=data_dir,
            browser_headless=True,
            max_concurrent_jobs=2,
            enable_browser_on_startup=True,
        )
        app1 = create_app(settings=s1, extra_adapters=[adapter1])
        with BackgroundServer(app1, api_port):
            with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=30.0) as client:
                assert client.post("/api/v1/browser/open-login", json={"adapter": "local-studio"}).status_code == 200
                # Fire 2 concurrent requests to confirm max_concurrent_jobs=2 actually runs concurrently
                j1 = client.post("/api/v1/jobs/generate", json={"prompt": "SLOW_JOB parallel a"}).json()["id"]
                j2 = client.post("/api/v1/jobs/generate", json={"prompt": "SLOW_JOB parallel b"}).json()["id"]
                for jid in (j1, j2):
                    for _ in range(60):
                        if client.get(f"/api/v1/jobs/{jid}").json()["status"] == "completed":
                            break
                        time.sleep(0.2)
                    else:
                        pytest.fail(f"Parallel job {jid} timed out")
                assert adapter1.max_observed_concurrency == 2

        # Second server instance reusing the exact same data_dir
        adapter2 = LocalStudioAdapter(f"http://127.0.0.1:{demo_port}")
        s2 = Settings(
            host="127.0.0.1",
            port=api_port,
            api_key=None,  # isolate tests from the project's real .env
            default_adapter="local-studio",
            data_dir=data_dir,
            browser_headless=True,
            enable_browser_on_startup=True,
        )
        app2 = create_app(settings=s2, extra_adapters=[adapter2])
        with BackgroundServer(app2, api_port):
            with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=30.0) as client:
                check = client.post("/api/v1/browser/check-session", json={"adapter": "local-studio"}).json()
                assert check["status"] == "ready"
                history = client.get("/api/v1/jobs").json()["jobs"]
                assert len(history) == 2


def test_api_key_protection(tmp_path: Path, env_factories):
    free_port = env_factories["free_port"]
    BackgroundServer = env_factories["BackgroundServer"]
    port = free_port()
    settings = Settings(
        host="127.0.0.1",
        port=port,
        api_key="secret-telegram-token",
        data_dir=tmp_path / "auth_data",
        enable_browser_on_startup=False,
    )
    app = create_app(settings=settings)
    with BackgroundServer(app, port):
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as client:
            assert client.get("/v1/models").status_code == 401
            assert client.get("/api/v1/jobs").status_code == 401
            ok = client.get("/v1/models", headers={"Authorization": "Bearer secret-telegram-token"})
            assert ok.status_code == 200
