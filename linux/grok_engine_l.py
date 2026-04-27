#!/usr/bin/env python3
"""
Linux browser automation engine for grok.com.
Playwright + Firefox (async API for use with FastAPI/Uvicorn).
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

GROK_URL = "https://grok.com/"
ENGINE_VERSION = "v3-linux-playwright-async"

INPUT_SELECTORS = [
    "textarea",
    'div[contenteditable="true"]',
    '[data-testid="text-input"]',
    '[role="textbox"]',
]

SEND_SELECTORS = [
    'button[aria-label="Send"]',
    'button[data-testid="send-button"]',
    '[data-testid="send-button"] button',
]

FILE_INPUT_SELECTORS = [
    'input[type="file"]',
    'input[accept]',
    '[data-testid*="file"] input[type="file"]',
]

ATTACH_BUTTON_SELECTORS = [
    'button[aria-label*="Attach"]',
    'button[aria-label*="Upload"]',
    'button[data-testid*="attach"]',
    'button[data-testid*="upload"]',
]

SEND_TEXT_PATTERN = re.compile(r"send|submit|发送", re.IGNORECASE)

STEALTH_JS = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (_) {}
})();
"""

INSERT_TEXT_JS = """
(args) => {
  const selector = args.selector;
  const text = args.text;
  const el = document.querySelector(selector);
  if (!el) return 'NO_INPUT';

  el.focus();
  el.click();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    el.value = '';
  } else {
    el.textContent = '';
  }

  let inserted = false;
  try {
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
  } catch (_) {}

  try {
    inserted = document.execCommand('insertText', false, text) || inserted;
  } catch (_) {}

  if (!inserted) {
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      el.value = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      el.textContent = text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
    }
  }

  return 'OK';
}
"""

BODY_TEXT_JS = "() => (document && document.body && document.body.innerText) ? document.body.innerText : ''"

GET_RESPONSE_VIA_DOM_JS = """
() => {
  const selectors = [
    '[data-message-author-role="assistant"]',
    '[data-testid="assistant-message"]',
    '.message-assistant',
    '.assistant-message',
    '[class*="assistant-message"]',
    '[class*="AssistantMessage"]',
    '[class*="response-text"]',
  ];
  for (const sel of selectors) {
    const els = document.querySelectorAll(sel);
    if (els.length > 0) {
      return els[els.length - 1].innerText;
    }
  }
  return null;
}
"""


class EngineRuntimeError(RuntimeError):
    pass


@dataclass
class EngineConfig:
    profile_root: str
    headless: bool = False
    page_timeout_seconds: int = 60


class GrokPlaywrightEngine:
    name = "playwright"

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._playwright: Any = None
        self.context: Any = None
        self.page: Any = None

    @staticmethod
    def available() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except Exception:
            return False

    def _profile_dir(self) -> str:
        path = Path(self.cfg.profile_root).expanduser() / "playwright"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    async def start(self) -> None:
        if self.page is not None and self.context is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise EngineRuntimeError(
                "playwright imports failed. Install with: pip install playwright && playwright install firefox"
            ) from exc

        profile_dir = self._profile_dir()

        try:
            self._playwright = await async_playwright().start()
            self.context = await self._playwright.firefox.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=self.cfg.headless,
                viewport={"width": 1366, "height": 900},
                args=["--no-first-run"],
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.page.set_default_timeout(self.cfg.page_timeout_seconds * 1000)
            await self.page.add_init_script(STEALTH_JS)
        except Exception as exc:
            await self.stop()
            raise EngineRuntimeError(f"failed to start playwright firefox: {exc}") from exc

    async def stop(self) -> None:
        if self.context is not None:
            try:
                await self.context.close()
            except Exception:
                pass
        self.context = None
        self.page = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    async def _find_input_selector(self, timeout_seconds: int = 20) -> Optional[str]:
        if self.page is None:
            return None

        end = time.time() + timeout_seconds
        while time.time() < end:
            for selector in INPUT_SELECTORS:
                try:
                    element = await self.page.query_selector(selector)
                except Exception:
                    element = None
                if element is not None:
                    return selector
            await self._sleep_jitter(0.14, 0.22)
        return None

    async def _find_file_input(self) -> Any:
        if self.page is None:
            return None

        for selector in FILE_INPUT_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
            except Exception:
                element = None
            if element is not None:
                return element
        return None

    async def _click_selector(self, selector: str) -> bool:
        if self.page is None:
            return False

        try:
            elements = await self.page.query_selector_all(selector)
        except Exception:
            elements = []

        for element in elements:
            try:
                await element.scroll_into_view_if_needed()
                await self._sleep_jitter(0.05, 0.15)
                await element.click(timeout=1200)
                return True
            except Exception:
                try:
                    await self.page.evaluate("(el) => el.click()", element)
                    return True
                except Exception:
                    continue
        return False

    async def _attach_files(self, files: Sequence[str]) -> None:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")

        file_paths = self._validate_files(files)
        if not file_paths:
            return

        for selector in ATTACH_BUTTON_SELECTORS:
            if await self._click_selector(selector):
                await self._sleep_jitter(0.2, 0.3)
                break

        input_el = await self._find_file_input()
        if input_el is None:
            raise EngineRuntimeError("file input not found on page")

        try:
            await input_el.set_input_files(file_paths)
        except Exception as exc:
            raise EngineRuntimeError(f"failed to attach files via playwright: {exc}") from exc

        await self._sleep_jitter(0.3, 0.35)

    async def _type_and_send(self, prompt: str, input_selector: str) -> None:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")

        result = await self.page.evaluate(INSERT_TEXT_JS, {"selector": input_selector, "text": prompt})
        if "OK" not in str(result):
            try:
                await self.page.fill(input_selector, prompt)
            except Exception as exc:
                raise EngineRuntimeError(f"failed to type prompt in playwright: {exc}") from exc

        await self._sleep_jitter(0.2, 0.3)

        for selector in SEND_SELECTORS:
            if await self._click_selector(selector):
                return

        try:
            buttons = await self.page.query_selector_all("button")
        except Exception:
            buttons = []

        for button in buttons:
            try:
                text = (await button.inner_text() or "") + " " + (await button.get_attribute("aria-label") or "")
                if SEND_TEXT_PATTERN.search(text):
                    await button.click(timeout=1200)
                    return
            except Exception:
                continue

        try:
            element = await self.page.query_selector(input_selector)
            if element is None:
                raise EngineRuntimeError("input selector not found before Enter fallback")
            await element.press("Enter")
        except Exception as exc:
            raise EngineRuntimeError(f"failed to submit prompt in playwright: {exc}") from exc

    async def _get_body(self) -> str:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")
        body = await self.page.evaluate(BODY_TEXT_JS)
        return str(body or "")

    async def _get_response_via_dom(self) -> Optional[str]:
        if self.page is None:
            return None
        try:
            result = await self.page.evaluate(GET_RESPONSE_VIA_DOM_JS)
            return str(result) if result else None
        except Exception:
            return None

    async def ensure_grok(self) -> str:
        await self.start()
        assert self.page is not None
        try:
            await self.page.goto(
                GROK_URL,
                wait_until="domcontentloaded",
                timeout=self.cfg.page_timeout_seconds * 1000,
            )
        except Exception as exc:
            raise EngineRuntimeError(f"failed to navigate to grok.com: {exc}") from exc

        await self._sleep_jitter(0.5, 1.0)

        selector = await self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found on grok page")
        return selector

    async def new_conversation(self) -> None:
        await self.start()
        assert self.page is not None
        try:
            await self.page.goto(
                GROK_URL,
                wait_until="domcontentloaded",
                timeout=self.cfg.page_timeout_seconds * 1000,
            )
        except Exception as exc:
            raise EngineRuntimeError(f"failed to navigate to grok.com: {exc}") from exc

        await self._sleep_jitter(0.5, 1.0)

        selector = await self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found after opening new conversation")

    async def chat(self, prompt: str, timeout: int, files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        input_selector = await self.ensure_grok()
        body_before = await self._get_body()
        initial_len = len(body_before)

        if files:
            await self._attach_files(files)

        await self._type_and_send(prompt, input_selector)

        start = time.time()
        last = ""
        stable = 0
        has_response = False
        poll_interval = 2.0
        min_growth = 50  # chars: threshold to consider grok started responding

        while time.time() - start < timeout:
            time.sleep(poll_interval)
            body = await self._get_body()
            current_len = len(body)

            # Phase 1: Detect when Grok starts responding.
            if not has_response:
                if current_len > initial_len + min_growth:
                    has_response = True
                else:
                    # Still waiting for grok to begin
                    continue

            # Phase 2: Wait for stability once response has started.
            if body == last:
                stable += 1
                if stable >= 3:
                    extracted = self._extract(body, prompt)
                    if not extracted:
                        extracted = await self._get_response_via_dom() or ""
                    return {
                        "status": "ok",
                        "response": extracted,
                        "elapsed": round(time.time() - start, 1),
                    }
            else:
                stable = 0
            last = body

        # Exited loop: either timeout or no response detected.
        if not has_response:
            return {
                "status": "error",
                "error": "no response detected (submit may have failed or grok is not responding)",
                "elapsed": round(time.time() - start, 1),
            }

        partial = self._extract(last, prompt) if last else ""
        if not partial:
            partial = await self._get_response_via_dom() or ""
        return {
            "status": "timeout",
            "response": partial,
            "elapsed": round(time.time() - start, 1),
        }

    async def history(self) -> Dict[str, Any]:
        await self.start()
        body = await self._get_body()
        return {"status": "ok", "content": self._clean(body), "raw_length": len(body)}

    async def health(self) -> Dict[str, Any]:
        if self.page is None:
            return {
                "status": "error",
                "error": "playwright firefox not started",
                "url": "",
                "on_grok": False,
                "version": ENGINE_VERSION,
            }

        try:
            url = self.page.url or ""
            return {
                "status": "ok",
                "url": url,
                "on_grok": "grok.com" in url,
                "version": ENGINE_VERSION,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "url": "",
                "on_grok": False,
                "version": ENGINE_VERSION,
            }

    async def export_cookies(self) -> List[Dict[str, Any]]:
        if self.context is None:
            return []
        try:
            return await self.context.cookies()
        except Exception:
            return []

    async def import_cookies(self, cookies: Sequence[Dict[str, Any]]) -> None:
        if not cookies:
            return

        await self.start()
        assert self.context is not None

        translated: List[Dict[str, Any]] = []
        for cookie in cookies:
            item = {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": cookie.get("domain"),
                "path": cookie.get("path", "/"),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", True),
                "sameSite": cookie.get("sameSite", "Lax"),
            }
            expires = cookie.get("expires", cookie.get("expiry"))
            if expires is not None:
                try:
                    item["expires"] = float(expires)
                except Exception:
                    pass
            translated.append(item)

        try:
            await self.context.add_cookies(translated)
        except Exception:
            pass

    @staticmethod
    async def _sleep_jitter(base_seconds: float = 0.08, max_extra_seconds: float = 0.24) -> None:
        await _async_sleep(base_seconds + random.uniform(0.0, max_extra_seconds))

    @staticmethod
    def _clean(text: str) -> str:
        for marker in [
            "\nAsk anything",
            "\nDeepSearch",
            "\nThink Harder",
            "\nThink\n",
            "\nAttach",
            "\nGrok",
            "\nFast\n",
            "\nAuto\n",
            "\nUpgrade to",
            "\nStart dictation",
            "\nEnter voice mode",
            "\nModel select",
            "\nQuick Answer",
            "\nExplain",
            "\nCompare",
            "\nMake it",
            "\nShare\n",
            "\nLike\n",
            "\nDislike\n",
        ]:
            idx = text.rfind(marker)
            if idx > 0:
                text = text[:idx]

        text = re.sub(r"\n[0-9]+(\.[0-9]+)?s\n", "\n", text)
        text = re.sub(r"\n(Share|Compare|Make it|Explain|Toggle|Like|Dislike).*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _extract(cls, body: str, prompt: str) -> str:
        marker = prompt[:60]
        idx = body.find(marker)
        if idx >= 0:
            after = body[idx + len(marker) :]
            return cls._clean(after)
        return cls._clean(body)

    @staticmethod
    def _validate_files(files: Optional[Sequence[str]]) -> List[str]:
        if not files:
            return []

        absolute: List[str] = []
        missing: List[str] = []
        for file_path in files:
            resolved = os.path.abspath(os.path.expanduser(file_path))
            if not os.path.isfile(resolved):
                missing.append(file_path)
            else:
                absolute.append(resolved)

        if missing:
            raise EngineRuntimeError(f"file(s) not found: {missing}")

        return absolute


# Small helper so we can call await _async_sleep(...) from static methods
import asyncio as _asyncio


async def _async_sleep(seconds: float) -> None:
    await _asyncio.sleep(seconds)


class GrokEngineManager:
    """Thin async wrapper around the single Playwright engine."""

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._engine = GrokPlaywrightEngine(cfg)

    async def warmup(self) -> None:
        await self._engine.start()

    async def shutdown(self) -> None:
        await self._engine.stop()

    async def chat(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        if not (prompt or "").strip():
            return {"status": "error", "error": "prompt is required"}

        timeout = int(timeout or 120)
        if timeout < 5:
            timeout = 5

        try:
            result = await self._engine.chat(prompt=prompt, timeout=timeout, files=files)
            result["engine"] = self._engine.name
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def new_conversation(self) -> Dict[str, Any]:
        try:
            await self._engine.new_conversation()
            return {"status": "ok", "engine": self._engine.name}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def history(self) -> Dict[str, Any]:
        try:
            result = await self._engine.history()
            result["engine"] = self._engine.name
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def health(self) -> Dict[str, Any]:
        availability = {
            "playwright": GrokPlaywrightEngine.available(),
        }
        result = await self._engine.health()
        result["available_engines"] = availability
        result["active_engine"] = self._engine.name
        return result
