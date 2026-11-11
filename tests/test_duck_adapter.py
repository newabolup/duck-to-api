import io
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.adapters.duck_ai import DuckAiAdapter


def _make_png(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _build_duck_mirror_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def duck_page(mode: str = "ok"):
        if mode == "challenge":
            return """
            <!doctype html>
            <html><body>
              <p>Unfortunately, bots use DuckDuckGo too.</p>
              <p>Please complete the following challenge to confirm this prompt was made by a human.</p>
              <p>Select all squares containing a duck:</p>
              <button type="button">Submit</button>
            </body></html>
            """
        return """
        <!doctype html>
        <html><body>
          <button type="button" id="new-img-btn">New Image</button>
          <div id="mode-chips"></div>
          <div id="messages"></div>
          <textarea aria-label="Ask anything privately" placeholder="Ask anything privately"></textarea>
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf">
          <button type="submit" aria-label="Create">Create</button>
          <button type="button" aria-label="Stop generating" disabled></button>
          <script>
            const chips = document.getElementById('mode-chips');
            const messages = document.getElementById('messages');
            const ta = document.querySelector('textarea');
            const fileInput = document.querySelector('input[type="file"]');
            const submitBtn = document.querySelector('button[aria-label="Create"]');
            const stopBtn = document.querySelector('button[aria-label="Stop generating"]');

            let uploadedPreviewSrc = '';
            document.getElementById('new-img-btn').addEventListener('click', () => {
              if (!document.querySelector('button[aria-label="Remove Create Image"]')) {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.setAttribute('aria-label', 'Remove Create Image');
                chip.textContent = 'Create Image';
                chips.appendChild(chip);
              }
            });

            fileInput.addEventListener('change', (e) => {
              const f = e.target.files[0];
              if (!f) return;
              const previewCanvas = document.createElement('canvas');
              previewCanvas.width = 300;
              previewCanvas.height = 300;
              const pctx = previewCanvas.getContext('2d');
              pctx.fillStyle = '#cc2222';
              pctx.fillRect(0, 0, 300, 300);
              previewCanvas.toBlob((blob) => {
                uploadedPreviewSrc = URL.createObjectURL(blob);
                const previewImg = document.createElement('img');
                previewImg.src = uploadedPreviewSrc;
                previewImg.width = 300;
                previewImg.height = 300;
                messages.appendChild(previewImg);
              }, 'image/png');
            });

            submitBtn.addEventListener('click', () => {
              const prompt = ta.value || '';
              if (prompt.includes('TRIGGER_ERR')) {
                const p = document.createElement('p');
                p.textContent = 'Duck.ai is temporarily unavailable. Please try again later.';
                messages.appendChild(p);
                return;
              }
              if (prompt.includes('TRIGGER_CHALLENGE')) {
                const p = document.createElement('p');
                p.textContent = 'Unfortunately, bots use DuckDuckGo too. Select all squares containing a duck:';
                messages.appendChild(p);
                return;
              }
              stopBtn.disabled = false;
              setTimeout(() => {
                const c = document.createElement('canvas');
                c.width = 320;
                c.height = 320;
                const ctx = c.getContext('2d');
                ctx.fillStyle = uploadedPreviewSrc ? '#0f766e' : '#d97706';
                ctx.fillRect(0, 0, 320, 320);
                c.toBlob((blob) => {
                  const outImg = document.createElement('img');
                  outImg.src = URL.createObjectURL(blob);
                  outImg.width = 320;
                  outImg.height = 320;
                  messages.appendChild(outImg);
                  stopBtn.disabled = true;
                }, 'image/png');
              }, 350);
            });
          </script>
        </body></html>
        """

    return app


def test_duck_ai_adapter_dom_branches(tmp_path: Path, env_factories):
    free_port = env_factories["free_port"]
    BackgroundServer = env_factories["BackgroundServer"]

    mirror_port = free_port()
    api_port = free_port()
    mirror_app = _build_duck_mirror_app()

    duck_sim = DuckAiAdapter()
    duck_sim.name = "duck-sim"
    duck_sim.model_aliases = ("duck-sim",)
    duck_sim.home_url = f"http://127.0.0.1:{mirror_port}/"

    duck_challenge = DuckAiAdapter()
    duck_challenge.name = "duck-challenge"
    duck_challenge.model_aliases = ("duck-challenge",)
    duck_challenge.home_url = f"http://127.0.0.1:{mirror_port}/?mode=challenge"

    settings = Settings(
        host="127.0.0.1",
        port=api_port,
        api_key=None,  # isolate tests from the project's real .env
        default_adapter="duck-sim",
        data_dir=tmp_path / "duck_sim_data",
        browser_headless=True,
        enable_browser_on_startup=True,
    )
    api_app = create_app(settings=settings, extra_adapters=[duck_sim, duck_challenge])

    with BackgroundServer(mirror_app, mirror_port), BackgroundServer(api_app, api_port):
        with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=30.0) as client:
            # 1. Ready check
            chk_ok = client.post("/api/v1/browser/check-session", json={"adapter": "duck-sim"}).json()
            assert chk_ok["status"] == "ready"

            # 2. Challenge check -> needs_auth
            chk_gate = client.post("/api/v1/browser/check-session", json={"adapter": "duck-challenge"}).json()
            assert chk_gate["status"] == "needs_auth"

            # 3. Generate image via blob: URL extraction
            r_gen = client.post("/v1/images/generations", json={"prompt": "warm amber duck", "model": "duck-sim"})
            assert r_gen.status_code == 200
            out_path = r_gen.json()["data"][0]["url"].replace(f"http://127.0.0.1:{api_port}", "")
            out_bytes = client.get(out_path).content
            with Image.open(io.BytesIO(out_bytes)) as im:
                assert im.size == (320, 320)
                assert im.getpixel((10, 10))[:3] == (217, 119, 6)  # #d97706 generated color

            # 4. Edit image: ensures uploaded 300x300 preview is ignored and edited 320x320 #0f766e output is returned
            r_edit = client.post(
                "/v1/images/edits",
                data={"prompt": "turn teal", "model": "duck-sim"},
                files={"image": ("in.png", _make_png((200, 20, 20)), "image/png")},
            )
            assert r_edit.status_code == 200
            edit_path = r_edit.json()["data"][0]["url"].replace(f"http://127.0.0.1:{api_port}", "")
            edit_bytes = client.get(edit_path).content
            with Image.open(io.BytesIO(edit_bytes)) as im:
                assert im.size == (320, 320)
                assert im.getpixel((10, 10))[:3] == (15, 118, 110)  # #0f766e edited color

            # 5. Site error marker raises execution error -> 502
            r_err = client.post("/v1/images/generations", json={"prompt": "TRIGGER_ERR", "model": "duck-sim"})
            assert r_err.status_code == 502

            # 6. Runtime challenge marker raises manual auth required -> 503
            r_chal = client.post("/v1/images/generations", json={"prompt": "TRIGGER_CHALLENGE", "model": "duck-sim"})
            assert r_chal.status_code == 503
            assert r_chal.json()["error"]["code"] == "manual_auth_required"
