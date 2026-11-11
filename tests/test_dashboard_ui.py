from PIL import Image
from playwright.sync_api import sync_playwright


def test_dashboard_interactive_clickthrough_and_responsive(live_env, tmp_path):
    base_url, _, _ = live_env
    console_errors: list[str] = []
    page_errors: list[str] = []

    sample_png = tmp_path / "sample.png"
    Image.new("RGB", (96, 96), color=(30, 120, 200)).save(sample_png, format="PNG")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        page = context.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        page.goto(base_url, wait_until="domcontentloaded")
        assert page.title() == "duck-to-api | Operations Console"

        # 1. Verify empty state and default adapter hydration on initial boot
        page.wait_for_selector("#jobs-empty-state:not(.hidden)")
        page.wait_for_function("document.getElementById('pg-adapter').value === 'local-studio'")

        # 2. Authenticate demo studio via browser control buttons
        page.click("#btn-manual-auth")
        page.wait_for_function(
            "document.getElementById('browser-action-feedback').textContent.includes('Chromium window')"
        )
        page.click("#btn-toggle-headless")
        page.wait_for_function(
            "document.getElementById('browser-action-feedback').textContent.includes('headless')"
        )
        page.click("#btn-check-session")
        page.wait_for_function(
            "document.getElementById('browser-action-feedback').textContent.includes('ready')"
        )

        # 3. Test Theme toggle (Dark -> Light -> Dark)
        assert page.get_attribute("html", "data-theme") == "dark"
        page.click("#theme-toggle-btn")
        assert page.get_attribute("html", "data-theme") == "light"
        page.click("#theme-toggle-btn")
        assert page.get_attribute("html", "data-theme") == "dark"

        # 4. Test API Key dialog opens and closes on Escape
        page.click("#open-apikey-btn")
        assert page.evaluate("document.getElementById('apikey-modal').open") is True
        page.keyboard.press("Escape")
        assert page.evaluate("document.getElementById('apikey-modal').open") is False

        # 5. Switch to Playground tab and test Generate workflow + Copy curl
        page.click("#tab-playground")
        page.wait_for_selector("#panel-playground:not(.hidden)")
        page.fill("#pg-prompt", "copper owl telemetry")
        assert "copper owl telemetry" in page.inner_text("#pg-curl-preview")
        page.click("#pg-copy-curl-btn")
        page.wait_for_function("document.getElementById('pg-form-feedback').textContent.length > 0")
        page.click("#pg-submit-btn")

        # Wait for generated image to render on Visual Output Stage
        page.wait_for_selector("#pg-output-img[src*='/files/outputs/']", timeout=20000)
        assert page.is_visible("#pg-download-link")
        assert page.is_visible("#pg-send-to-edit-btn")

        # 6. Chain Output -> Edit mode and test Edit workflow
        page.click("#pg-send-to-edit-btn")
        page.wait_for_function(
            "document.getElementById('pg-mode-edit').getAttribute('aria-pressed') === 'true'"
        )
        assert page.is_visible("#pg-upload-group")
        page.fill("#pg-prompt", "add evening slate")
        page.click("#pg-submit-btn")
        page.wait_for_function(
            "document.getElementById('pg-stage-status').textContent.includes('Completed') && "
            "document.querySelectorAll('#gallery-grid .gallery-card').length >= 2",
            timeout=20000,
        )

        # 6b. Trigger an error job from Playground, inspect error state, and click Retry Job
        page.click("#pg-mode-generate")
        page.fill("#pg-prompt", "FORCE_FAIL playground test")
        page.click("#pg-submit-btn")
        page.wait_for_selector("#pg-stage-error:not(.hidden)", timeout=20000)
        assert "simulated failure" in page.inner_text("#pg-stage-error-text")
        page.click("#pg-stage-retry-btn")
        page.wait_for_function(
            "document.querySelectorAll('#jobs-tbody tr').length >= 3",
            timeout=15000,
        )

        # 7. Open Image Inspection Modal from gallery and close with Escape
        page.click("#gallery-grid .gallery-thumb-btn")
        assert page.evaluate("document.getElementById('image-modal').open") is True
        page.keyboard.press("Escape")
        assert page.evaluate("document.getElementById('image-modal').open") is False

        # 8. Switch to Adapters & API tab
        page.click("#tab-adapters")
        page.wait_for_selector("#adapters-list .adapter-card")
        adapters_text = page.inner_text("#adapters-list")
        assert "Duck.ai" in adapters_text
        assert "Local Test Studio" in adapters_text

        # 9. Switch back to Operations tab, test job filter & log controls
        page.click("#tab-operations")
        page.wait_for_selector("#jobs-tbody tr")
        page.select_option("#jobs-status-filter", "failed")
        page.wait_for_selector("#jobs-tbody tr")
        page.select_option("#jobs-status-filter", "cancelled")
        page.wait_for_selector("#jobs-empty-state:not(.hidden)")
        page.click("#btn-reset-job-filters")
        page.wait_for_selector("#jobs-tbody tr")

        page.click("#btn-toggle-logs-stream")
        assert "Paused" in page.inner_text("#logs-stream-status")
        page.click("#btn-toggle-logs-stream")
        page.click("#btn-clear-logs")

        # 10. Verify zero horizontal overflow at Desktop (1280), Tablet (820), and Mobile (375) in both themes
        for theme in ("dark", "light"):
            if page.get_attribute("html", "data-theme") != theme:
                page.click("#theme-toggle-btn")
            for width, height in [(1280, 850), (820, 900), (375, 812)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(150)
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                )
                assert overflow is False, f"Horizontal overflow detected at {width}x{height} ({theme})"

        browser.close()

    assert console_errors == [], f"Console errors observed: {console_errors}"
    assert page_errors == [], f"Uncaught page errors observed: {page_errors}"
