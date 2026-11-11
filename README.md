# duck-to-api

Modular browser-to-API bridge built with Python, FastAPI, and Playwright. It runs a dedicated Chromium instance with a persistent profile, automates image generation and image editing through pluggable site adapters (`duck-ai` included in v1), manages requests as persistent queued jobs, exposes OpenAI-compatible endpoints, and serves an operations dashboard.

## Linux Quick Install

```bash
chmod +x install.sh start.sh
./install.sh
./start.sh
```

For LAN deployment with auto-generated API key and a `systemd` service:

```bash
./install.sh --host 0.0.0.0 --port 8000 --generate-key --systemd
```

`install.sh` creates `.venv`, installs Python dependencies, downloads Playwright Chromium + Linux OS dependencies (`install-deps chromium`), installs `xvfb` when available so headed Chromium runs cleanly on headless Linux servers via `start.sh`, initializes `data/`, and creates `.env` from `.env.example`.

## Manual Setup (Windows / Linux)

```bash
pip install -e ".[dev]"
playwright install chromium
python -m app
```

Open `http://127.0.0.1:8000/` for the Web Dashboard or `http://127.0.0.1:8000/docs` for interactive OpenAPI documentation.

## Browser Mode Note for Duck.ai

Duck.ai currently rejects Playwright headless browser sessions with a temporary-unavailable error (`Oops...`). Keep `DUCK_API_BROWSER_HEADLESS=false` in `.env`. On headless Linux servers without a monitor, `./start.sh` automatically runs the service inside `xvfb-run` so Chromium operates in headed mode on a virtual display.

## Exposing on LAN

Set `DUCK_API_HOST=0.0.0.0` and set a strong `DUCK_API_API_KEY` in `.env`, then run `./start.sh` (or `python -m app`). When `DUCK_API_API_KEY` is configured:
- All `/v1/*`, `/api/v1/*`, and `/files/*` endpoints require `Authorization: Bearer <key>`, `X-API-Key`, an `HttpOnly` dashboard session cookie, or an expiry-bound HMAC file token (`?token=...`) automatically embedded into returned image URLs.

## Manual Login and Persistent Session

1. Click **Open Manual Auth Window** in the Dashboard (or call `POST /api/v1/browser/open-login`).
2. Chromium opens a visible window using `data/browser_profile/` on the target site.
3. Complete any manual login, terms confirmation, or human verification directly inside the Chromium window.
4. Cookies, `localStorage`, and `IndexedDB` stay saved in `data/browser_profile/` across browser, server, and OS restarts.

## Key Endpoints

- `GET /v1/models` and `GET /v1/models/{model_id}`: OpenAI model discovery mapped to registered adapters.
- `POST /v1/images/generations`: OpenAI Images generation endpoint (`url` or `b64_json`). Pass header `X-Async-Mode: true` to return `202` with `job_id` immediately for Telegram bots.
- `POST /v1/images/edits`: OpenAI Images edit endpoint (`multipart/form-data` with `image` + `prompt`). Supports PNG, JPEG, WebP, and normalizes BMP/GIF/TIFF uploads to PNG.
- `POST /api/v1/jobs/generate` and `POST /api/v1/jobs/edit`: Queue async jobs directly and receive `job_id`.
- `GET /api/v1/jobs/{job_id}`: Poll job status (`queued`, `running`, `completed`, `failed`, `cancelled`, `needs_auth`), output URLs, and error messages.
- `POST /api/v1/jobs/{job_id}/cancel` and `POST /api/v1/jobs/{job_id}/retry`: Control queued or failed jobs.
- `GET /files/outputs/{filename}`: Download generated or edited images.
- `GET /api/v1/browser/status`, `POST /api/v1/browser/mode`, `POST /api/v1/browser/open-login`, `POST /api/v1/browser/check-session`, `POST /api/v1/browser/restart`: Manage the Chromium instance.

## Adding a New Site Adapter

1. Subclass `SiteAdapter` from `app/adapters/base.py`.
2. Implement `open_for_manual_auth`, `check_session`, `generate_image`, and `edit_image`.
3. Register the adapter in `app/main.py` using `registry.register(YourAdapter())`.

## Telegram Bot Example (Async Job Polling)

```python
import asyncio
import httpx

async def generate_for_telegram(prompt: str, api_key: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", headers=headers, timeout=30) as client:
        resp = await client.post("/api/v1/jobs/generate", json={"prompt": prompt, "adapter": "duck-ai"})
        resp.raise_for_status()
        job_id = resp.json()["id"]

        while True:
            job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
            if job["status"] == "completed":
                img_resp = await client.get(job["output_urls"][0])
                img_resp.raise_for_status()
                return img_resp.content
            if job["status"] in ("failed", "cancelled", "needs_auth"):
                raise RuntimeError(job["error"] or job["status"])
            await asyncio.sleep(2)
```
