import asyncio
import base64
import logging
from playwright.async_api import Error as PlaywrightError, Locator, Page

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

logger = logging.getLogger("duck_to_api.adapters.duck_ai")

CHALLENGE_MARKERS = (
    "complete the following challenge",
    "confirm this prompt was made by a human",
    "unfortunately, bots use duckduckgo",
    "select all squares",
    "verify you are human",
)

ERROR_MARKERS = (
    "duck.ai is temporarily unavailable",
    "daily limit",
    "rate limit",
    "too many requests",
    "couldn't generate",
    "could not generate",
    "something went wrong",
    "failed to fetch",
    "network error",
)


class DuckAiAdapter(SiteAdapter):
    """Browser adapter for Duck.ai text-to-image generation and image editing."""

    name = "duck-ai"
    display_name = "Duck.ai (DuckDuckGo)"
    home_url = "https://duck.ai/"
    model_aliases = ("duck-ai", "duck", "gpt-image-1", "dall-e-3")
    capabilities = AdapterCapabilities(
        text_to_image=True,
        image_edit=True,
        models=["duck-ai"],
        sizes=["1024x1024"],
        max_images=1,
    )

    async def open_for_manual_auth(self, page: Page) -> None:
        await page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)

    async def _visible_body_text(self, page: Page) -> str:
        if page.is_closed():
            raise AdapterExecutionError("Browser page closed before response completed")
        try:
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            return (text or "").strip()
        except PlaywrightError as exc:
            if page.is_closed():
                raise AdapterExecutionError("Browser page closed during automation") from exc
            return ""

    async def _detect_challenge_or_error(self, page: Page) -> None:
        body_lower = (await self._visible_body_text(page)).lower()
        for marker in CHALLENGE_MARKERS:
            if marker in body_lower:
                raise AdapterManualAuthRequired(
                    "Duck.ai presented a human verification challenge. "
                    "Open the manual auth window from the Dashboard to verify the browser session."
                )
        for marker in ERROR_MARKERS:
            if marker in body_lower:
                snippet = await self._extract_error_snippet(page)
                raise AdapterExecutionError(f"Duck.ai reported an error: {snippet}")

    async def _extract_error_snippet(self, page: Page) -> str:
        text = await self._visible_body_text(page)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            low = line.lower()
            if any(m in low for m in ERROR_MARKERS) or "oops" in low:
                snippet = " ".join(lines[idx : idx + 2])
                return snippet[:280]
        return text[:280]

    async def check_session(self, page: Page) -> SessionCheckResult:
        try:
            await page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            await self._detect_challenge_or_error(page)
            composer = await self._find_prompt_box(page)
            if await composer.count() > 0:
                return SessionCheckResult(
                    status="ready",
                    message="Duck.ai composer is loaded and ready.",
                    url=page.url,
                )
            return SessionCheckResult(
                status="error",
                message="Duck.ai loaded without a visible prompt composer (DOM may have changed).",
                url=page.url,
            )
        except AdapterManualAuthRequired as exc:
            return SessionCheckResult(status="needs_auth", message=str(exc), url=page.url)
        except Exception as exc:
            return SessionCheckResult(status="error", message=str(exc), url=page.url)

    async def _enter_image_mode(self, page: Page) -> None:
        try:
            await page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError as exc:
            raise AdapterExecutionError(f"Failed to load {self.home_url}: {exc}") from exc
        await page.wait_for_timeout(1800)
        await self._detect_challenge_or_error(page)

        remove_chip = page.locator('button[aria-label="Remove Create Image"]')
        if await remove_chip.count() == 0:
            new_image_btn = page.get_by_role("button", name="New Image").first
            if await new_image_btn.count() > 0:
                await new_image_btn.click()
                await page.wait_for_timeout(1200)

        await self._detect_challenge_or_error(page)
        composer = await self._find_prompt_box(page)
        try:
            await composer.wait_for(state="visible", timeout=15000)
        except PlaywrightError as exc:
            raise AdapterExecutionError(
                "Duck.ai DOM selector mismatch: prompt composer textarea not found."
            ) from exc

    async def _find_prompt_box(self, page: Page) -> Locator:
        candidates = (
            'textarea[aria-label="Ask anything privately"]',
            'textarea[placeholder*="Ask"]',
            "textarea",
        )
        for sel in candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                return loc
        return page.locator("textarea").first

    async def _find_submit_button(self, page: Page) -> Locator:
        candidates = (
            'button[type="submit"][aria-label="Create"]',
            'button[type="submit"][aria-label="Ask"]',
            'button[type="submit"]',
        )
        for sel in candidates:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                return loc
        raise AdapterExecutionError("Duck.ai DOM selector mismatch: submit button not found.")

    async def _snapshot_image_sources(self, page: Page) -> set[str]:
        srcs = await page.evaluate(
            """() => Array.from(document.querySelectorAll('img')).map(img => img.currentSrc || img.src || '')"""
        )
        return {s for s in srcs if s}

    async def _submit_and_collect_image(self, page: Page, prompt: str, baseline_srcs: set[str]) -> bytes:
        prompt_box = await self._find_prompt_box(page)
        await prompt_box.click()
        await prompt_box.fill(prompt)
        await page.wait_for_timeout(300)

        submit_btn = await self._find_submit_button(page)
        try:
            await submit_btn.wait_for(state="visible", timeout=5000)
            await submit_btn.click()
        except PlaywrightError as exc:
            raise AdapterExecutionError(f"Could not submit prompt to Duck.ai: {exc}") from exc
        logger.debug("Submitted prompt to Duck.ai (%d chars)", len(prompt))

        for _ in range(120):
            await asyncio.sleep(1.0)
            await self._detect_challenge_or_error(page)

            candidate = await page.evaluate(
                """(baseline) => {
                    const known = new Set(baseline);
                    const imgs = Array.from(document.querySelectorAll('img'));
                    for (const img of imgs) {
                        const src = img.currentSrc || img.src || '';
                        if (!src || known.has(src)) continue;
                        if (src.includes('react-assets/') && src.endsWith('.gif')) continue;
                        if (img.naturalWidth >= 256 && img.naturalHeight >= 256) {
                            return { src, width: img.naturalWidth, height: img.naturalHeight };
                        }
                    }
                    return null;
                }""",
                list(baseline_srcs),
            )
            if candidate:
                stop_disabled = await page.evaluate(
                    """() => {
                        const btn = document.querySelector('button[aria-label="Stop generating"]');
                        return !btn || btn.disabled;
                    }"""
                )
                if stop_disabled:
                    return await self._download_image_bytes(page, candidate["src"])

        raise AdapterExecutionError("Timed out waiting for Duck.ai to produce a generated image.")

    async def _download_image_bytes(self, page: Page, img_src: str) -> bytes:
        if img_src.startswith("data:"):
            _, b64_part = img_src.split(",", 1)
            return base64.b64decode(b64_part)

        # Fetch via page context first so blob: URLs resolve directly; fall back to page.request for CORS URLs.
        try:
            b64_data = await page.evaluate(
                """async (src) => {
                    const resp = await fetch(src);
                    if (!resp.ok) throw new Error('Image fetch failed: ' + resp.status);
                    const buf = await resp.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    const chunk = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunk) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                    }
                    return btoa(binary);
                }""",
                img_src,
            )
            return base64.b64decode(b64_data)
        except Exception:
            if img_src.startswith(("http://", "https://")):
                resp = await page.request.get(img_src, timeout=30000)
                if resp.ok:
                    return await resp.body()
            raise

    async def generate_image(self, page: Page, req: GenerationRequest) -> AdapterImageResult:
        await self._enter_image_mode(page)
        baseline_srcs = await self._snapshot_image_sources(page)
        image_bytes = await self._submit_and_collect_image(page, req.prompt, baseline_srcs)
        return AdapterImageResult(
            images_bytes=[image_bytes],
            metadata={"source_url": page.url},
        )

    async def edit_image(self, page: Page, req: EditRequest) -> AdapterImageResult:
        await self._enter_image_mode(page)
        baseline_srcs = await self._snapshot_image_sources(page)

        file_input = page.locator('input[type="file"]').first
        if await file_input.count() == 0:
            raise AdapterExecutionError("Duck.ai DOM selector mismatch: image upload input not found.")

        await file_input.set_input_files(str(req.image_path))
        await page.wait_for_timeout(1500)

        # Record the uploaded preview thumbnail so it is never mistaken for the edited output.
        after_upload_srcs = await self._snapshot_image_sources(page)
        baseline_srcs.update(after_upload_srcs)

        image_bytes = await self._submit_and_collect_image(page, req.prompt, baseline_srcs)
        return AdapterImageResult(
            images_bytes=[image_bytes],
            metadata={"source_url": page.url, "uploaded_file": req.image_path.name},
        )
