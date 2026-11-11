import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, Playwright, async_playwright

from app.adapters.base import SiteAdapter

logger = logging.getLogger("duck_to_api.browser")

STALE_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile")


@dataclass(slots=True)
class BrowserState:
    running: bool = False
    headless: bool = True
    manual_auth_mode: bool = False
    active_jobs: int = 0
    max_concurrent_jobs: int = 1
    profile_dir: str = ""
    current_url: str | None = None
    last_error: str | None = None
    needs_auth_adapters: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "headless": self.headless,
            "manual_auth_mode": self.manual_auth_mode,
            "active_jobs": self.active_jobs,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "profile_dir": self.profile_dir,
            "current_url": self.current_url,
            "last_error": self.last_error,
            "needs_auth_adapters": sorted(self.needs_auth_adapters),
        }


class BrowserManager:
    """Owns a single persistent Chromium profile and recovers cleanly from window closures."""

    def __init__(
        self,
        profile_dir: Path,
        headless: bool = True,
        max_concurrent_jobs: int = 1,
        channel: str | None = None,
        no_sandbox: bool = False,
    ) -> None:
        self.profile_dir = profile_dir.resolve()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.channel = channel
        self.no_sandbox = no_sandbox
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_jobs))
        self.state = BrowserState(
            headless=headless,
            max_concurrent_jobs=max(1, max_concurrent_jobs),
            profile_dir=str(self.profile_dir),
        )

    async def start(self, headless: bool | None = None) -> dict:
        async with self._lifecycle_lock:
            if headless is not None:
                self.state.headless = headless
            if self._context is not None:
                return self.state.to_dict()
            await self._launch_context()
            return self.state.to_dict()

    def _clear_stale_locks(self) -> None:
        for name in STALE_LOCK_FILES:
            lock_path = self.profile_dir / name
            if lock_path.exists() or lock_path.is_symlink():
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _launch_context(self) -> None:
        if (
            not self.state.headless
            and sys.platform.startswith("linux")
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        ):
            raise RuntimeError(
                "Cannot open headed Chromium on Linux without DISPLAY or WAYLAND_DISPLAY. "
                "Start the service under Xvfb/VNC or use SSH X11 forwarding."
            )

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        args = ["--disable-blink-features=AutomationControlled"]
        if sys.platform.startswith("linux"):
            args.append("--disable-dev-shm-usage")
            is_root = hasattr(os, "geteuid") and os.geteuid() == 0
            if self.no_sandbox or is_root:
                args.extend(["--no-sandbox", "--disable-setuid-sandbox"])

        launch_kwargs: dict = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.state.headless,
            "accept_downloads": True,
            "viewport": {"width": 1366, "height": 900},
            "args": args,
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        except PlaywrightError as exc:
            if "ProcessSingleton" in str(exc) or "lock" in str(exc).lower():
                logger.warning("Detected Chromium profile lock; clearing stale lock files and retrying launch")
                self._clear_stale_locks()
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            else:
                self.state.running = False
                self.state.last_error = str(exc)
                logger.exception("Failed to launch persistent Chromium")
                raise
        except Exception as exc:
            self.state.running = False
            self.state.last_error = str(exc)
            logger.exception("Failed to launch persistent Chromium")
            raise

        self._context.on("close", self._on_context_closed)
        self.state.running = True
        self.state.last_error = None
        if self._context.pages:
            self.state.current_url = self._context.pages[0].url
        logger.info(
            "Persistent Chromium started (headless=%s, profile=%s)",
            self.state.headless,
            self.profile_dir,
        )

    def _on_context_closed(self) -> None:
        self._context = None
        self.state.running = False
        self.state.manual_auth_mode = False
        self.state.current_url = None
        logger.warning("Chromium persistent context closed")

    async def stop(self) -> dict:
        async with self._lifecycle_lock:
            await self._close_context()
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            return self.state.to_dict()

    async def _close_context(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:
                logger.warning("Error closing Chromium context: %s", exc)
            finally:
                self._context = None
                self.state.running = False
                self.state.manual_auth_mode = False
                self.state.current_url = None

    async def restart(self, headless: bool | None = None) -> dict:
        async with self._lifecycle_lock:
            if self.state.active_jobs > 0:
                raise RuntimeError("Cannot switch browser mode or restart while jobs are running")
            if headless is not None:
                self.state.headless = headless
            await self._close_context()
            await self._launch_context()
            return self.state.to_dict()

    async def _new_page_with_recovery(self) -> Page:
        if self._context is None:
            await self._launch_context()
        assert self._context is not None
        try:
            return await self._context.new_page()
        except PlaywrightError as exc:
            logger.warning("Chromium context unreachable when opening page (%s); relaunching", exc)
            await self._close_context()
            await self._launch_context()
            assert self._context is not None
            return await self._context.new_page()

    async def open_manual_auth(self, adapter: SiteAdapter) -> dict:
        """Open a visible Chromium window on the adapter's site for manual login or consent."""
        async with self._lifecycle_lock:
            if self.state.active_jobs > 0:
                raise RuntimeError("Wait for active jobs to finish before opening manual auth")
            if not self.state.running or self.state.headless or self._context is None:
                self.state.headless = False
                await self._close_context()
                await self._launch_context()

            assert self._context is not None
            try:
                page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                await adapter.open_for_manual_auth(page)
            except PlaywrightError:
                await self._close_context()
                self.state.headless = False
                await self._launch_context()
                assert self._context is not None
                page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                await adapter.open_for_manual_auth(page)

            self.state.manual_auth_mode = True
            self.state.current_url = page.url
            self.state.needs_auth_adapters.discard(adapter.name)
            logger.info("Manual auth window opened for adapter '%s' at %s", adapter.name, page.url)
            return self.state.to_dict()

    async def check_adapter_session(self, adapter: SiteAdapter) -> dict:
        async with self.acquire_page() as page:
            res = await adapter.check_session(page)
            self.state.current_url = res.url
            if res.status == "needs_auth":
                self.state.needs_auth_adapters.add(adapter.name)
            elif res.status == "ready":
                self.state.needs_auth_adapters.discard(adapter.name)
            return {
                "adapter": adapter.name,
                "status": res.status,
                "message": res.message,
                "url": res.url,
            }

    def mark_needs_auth(self, adapter_name: str) -> None:
        self.state.needs_auth_adapters.add(adapter_name)

    def clear_needs_auth(self, adapter_name: str) -> None:
        self.state.needs_auth_adapters.discard(adapter_name)

    @asynccontextmanager
    async def acquire_page(self) -> AsyncIterator[Page]:
        """Acquire a concurrency slot and a clean page, relaunching Chromium if closed."""
        await self._semaphore.acquire()
        page: Page | None = None
        try:
            async with self._lifecycle_lock:
                self.state.active_jobs += 1
                page = await self._new_page_with_recovery()
            yield page
        finally:
            if page is not None:
                try:
                    self.state.current_url = page.url
                except Exception:
                    pass
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception as exc:
                    logger.debug("Ignoring page close error: %s", exc)
            async with self._lifecycle_lock:
                self.state.active_jobs = max(0, self.state.active_jobs - 1)
            self._semaphore.release()
