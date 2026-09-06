from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ..errors import AdapterError
from ..models import ActionContext, ActionResult
from ..safety import assert_observation_url_safe


class BrowserAdapter:
    """Small optional Playwright bridge for configured preview pages."""

    name = "browser"

    def __init__(self, project_dir: Path, base_url: str, observation: dict[str, Any]):
        self.project_dir = project_dir
        self.observation = observation if isinstance(observation, dict) else {}
        browser_config = self.observation.get("browser", {}) if isinstance(self.observation.get("browser"), dict) else {}
        configured_base_url = browser_config.get("base_url")
        self.base_url = str(configured_base_url or base_url).rstrip("/") + "/"
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}
        self._current = None

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterError("BROWSER_ADAPTER_UNAVAILABLE: install devsim[browser] and run playwright install chromium") from exc
        try:
            action = context.values.get("_devsim_browser_action")
            # The runner passes the complete action name through this private field.
            if action == "browser.open":
                return await self._open(payload, async_playwright)
            if action == "browser.expect":
                return await self._expect(payload, PlaywrightTimeoutError)
            if action == "browser.screenshot":
                return await self._screenshot(context, payload)
            if action == "browser.click":
                return await self._click(payload, PlaywrightTimeoutError)
            raise AdapterError("unsupported browser action")
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"browser action failed: {exc}") from exc

    async def _ensure(self, async_playwright: Any) -> None:
        if self._context is not None:
            return
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception:
            await self._playwright.stop()
            self._playwright = None
            raise AdapterError("BROWSER_ADAPTER_UNAVAILABLE: Chromium is not installed; run playwright install chromium")
        self._context = await self._browser.new_context()

    async def _open(self, payload: dict[str, Any], async_playwright: Any) -> ActionResult:
        page_name = payload.get("page", "default")
        if not isinstance(page_name, str):
            raise AdapterError("browser.open requires with.page")
        pages = self.observation.get("browser", {}).get("pages", {}) if isinstance(self.observation.get("browser"), dict) else {}
        page_config = pages.get(page_name, {}) if isinstance(pages, dict) else {}
        path = page_config.get("path", "/") if isinstance(page_config, dict) else "/"
        if not isinstance(path, str) or not path.startswith("/"):
            raise AdapterError(f"browser page {page_name!r} must define a path starting with '/'")
        url = urljoin(self.base_url, path.lstrip("/"))
        assert_observation_url_safe(url)
        await self._ensure(async_playwright)
        page = self._pages.get(page_name) or await self._context.new_page()
        self._pages[page_name] = page
        self._current = page
        await page.goto(url, wait_until="domcontentloaded")
        return ActionResult(True, {"page": page_name, "url": page.url, "status": 200})

    async def _expect(self, payload: dict[str, Any], timeout_error: Any) -> ActionResult:
        page = self._current
        if page is None:
            raise AdapterError("browser.expect requires a preceding browser.open")
        selector = payload.get("selector")
        if not isinstance(selector, str) or not selector.strip():
            raise AdapterError("browser.expect requires with.selector")
        timeout = float(payload.get("timeout", 10)) * 1000
        locator = page.locator(selector)
        try:
            await locator.first.wait_for(state="attached", timeout=timeout)
            visible = await locator.first.is_visible()
            expected_visible = payload.get("visible")
            if expected_visible is True and not visible:
                raise AdapterError(f"browser.expect selector {selector!r} is not visible")
            if expected_visible is False and visible:
                raise AdapterError(f"browser.expect selector {selector!r} is visible")
            expected_text = payload.get("text")
            actual_text = await locator.first.inner_text() if visible else ""
            if expected_text is not None and str(expected_text) not in actual_text:
                raise AdapterError(f"browser.expect selector {selector!r} text mismatch: {actual_text!r}")
            expected_count = payload.get("count")
            actual_count = await locator.count()
            if expected_count is not None and actual_count != expected_count:
                raise AdapterError(f"browser.expect selector {selector!r} count mismatch: {actual_count}")
        except timeout_error as exc:
            raise AdapterError(f"browser.expect timed out waiting for {selector!r}") from exc
        return ActionResult(True, {"selector": selector, "visible": visible, "text": actual_text, "count": actual_count, "url": page.url})

    async def _click(self, payload: dict[str, Any], timeout_error: Any) -> ActionResult:
        if self._current is None:
            raise AdapterError("browser.click requires a preceding browser.open")
        selector = payload.get("selector")
        if not isinstance(selector, str) or not selector:
            raise AdapterError("browser.click requires with.selector")
        try:
            await self._current.locator(selector).click(timeout=float(payload.get("timeout", 10)) * 1000)
        except timeout_error as exc:
            raise AdapterError(f"browser.click timed out for {selector!r}") from exc
        return ActionResult(True, {"selector": selector, "url": self._current.url})

    async def _screenshot(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        if self._current is None:
            raise AdapterError("browser.screenshot requires a preceding browser.open")
        name = payload.get("name", f"screenshot-{context.event_sequence}")
        if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
            raise AdapterError("browser.screenshot name must be a simple filename")
        directory = self.project_dir / ".devsim" / "runs" / context.run_id / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.png"
        await self._current.screenshot(path=str(path))
        return ActionResult(True, {"name": name, "path": str(path), "url": self._current.url})

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = self._browser = self._playwright = None
