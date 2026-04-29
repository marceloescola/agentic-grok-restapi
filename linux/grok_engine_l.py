#!/usr/bin/env python3
"""
Linux browser automation engine for grok.com.
Playwright + Chromium (async API for use with FastAPI/Uvicorn).
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence

GROK_URL: str = "https://grok.com/"
ENGINE_VERSION: str = "v3-linux-playwright-chromium"

INPUT_SELECTORS: List[str] = [
    "textarea",
    'div[contenteditable="true"]',
    '[data-testid="text-input"]',
    '[role="textbox"]',
]

SEND_SELECTORS: List[str] = [
    'button[aria-label="Send"]',
    'button[data-testid="send-button"]',
    '[data-testid="send-button"] button',
]

FILE_INPUT_SELECTORS: List[str] = [
    'input[type="file"]',
    'input[accept]',
    '[data-testid*="file"] input[type="file"]',
]

ATTACH_BUTTON_SELECTORS: List[str] = [
    'button[aria-label*="Attach"]',
    'button[aria-label*="Upload"]',
    'button[data-testid*="attach"]',
    'button[data-testid*="upload"]',
]

SEND_TEXT_PATTERN: re.Pattern[str] = re.compile(r"send|submit|发送", re.IGNORECASE)

STEALTH_JS: str = """
(() => {
  // Kill webdriver flag at the blink layer
  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (_) {}

  // Fake plugin array (real Chrome has >= 5)
  try {
    const len = navigator.plugins.length;
    if (len < 5) {
      const fakePlugins = [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
        { name: 'Widevine Content Decryption Module', filename: 'widevinecdm' },
      ];
      Object.defineProperty(navigator, 'plugins', {
        get: () => {
          const arr = [...Array.from(navigator.plugins), ...fakePlugins];
          arr.item = (i) => arr[i];
          arr.namedItem = (n) => arr.find(p => p.name === n) || null;
          arr.refresh = () => {};
          return arr;
        },
      });
    }
  } catch (_) {}

  // Chrome runtime object
  if (!window.chrome) {
    try { window.chrome = { runtime: {} }; } catch (_) {}
  }

  // Languages
  try {
    if (!navigator.languages || navigator.languages.length === 0) {
      Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    }
  } catch (_) {}

  // Patch permissions so automation checks pass
  try {
    const origQuery = Permissions.prototype.query;
    Permissions.prototype.query = (opts) =>
      origQuery.call(navigator.permissions, opts).then(r => {
        if (['camera','microphone','notifications','geolocation'].includes(opts.name)) {
          r.onchange = null;
        }
        return r;
      });
  } catch (_) {}
})();
"""

INSERT_TEXT_JS: str = """
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

BODY_TEXT_JS: str = "() => (document && document.body && document.body.innerText) ? document.body.innerText : ''"

GET_RESPONSE_VIA_DOM_JS: str = """
() => {
  const selectors = [
    '[data-message-author-role="assistant"]',
    '[data-testid="assistant-message"]',
    '.message-assistant',
    '.assistant-message',
    '[class*="assistant-message"]',
    '[class*="AssistantMessage"]',
    '[class*="response-text"]',
    '[class*="message-content"]',
    '[class*="grok-response"]',
    '.grok-message',
    '.prose',
    'article[class*="message"]',
  ];
  for (const sel of selectors) {
    const els = document.querySelectorAll(sel);
    if (els.length > 0) {
      const t = els[els.length - 1].innerText;
      if (t && t.trim().length > 0) return t;
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
    user_data_dir: Optional[str] = None
    browser_binary: Optional[str] = None
    profile_name: str = "Default"
    project_url: Optional[str] = None


class GrokPlaywrightEngine:
    name: str = "playwright"

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg: EngineConfig = cfg
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
        path: Path = Path(self.cfg.profile_root).expanduser() / "playwright"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    async def start(self) -> None:
        if self.page is not None and self.context is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise EngineRuntimeError(
                "playwright imports failed. Install with: pip install playwright && playwright install chromium"
            ) from exc

        launch_kwargs: Dict[str, Any] = {
            "headless": self.cfg.headless,
            "viewport": {"width": 1366, "height": 900},
            "args": [
                "--no-first-run",
                f"--profile-directory={self.cfg.profile_name}",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-default-browser-check",
            ],
        }

        if self.cfg.user_data_dir:
            resolved: Path = Path(self.cfg.user_data_dir).expanduser().resolve()
            if not (resolved / "Local State").is_file() and not (resolved / "First Run").is_file():
                raise EngineRuntimeError(
                    f"chromium user data dir not found or invalid: {resolved}\n"
                    f"  Set to the parent of 'Default/' (e.g. ~/.config/chromium)"
                )
            launch_kwargs["user_data_dir"] = str(resolved)
        else:
            launch_kwargs["user_data_dir"] = self._profile_dir()

        if self.cfg.browser_binary:
            resolved_bin: Optional[str] = shutil.which(self.cfg.browser_binary)
            if not resolved_bin:
                raise EngineRuntimeError(
                    f"browser binary not found: {self.cfg.browser_binary}"
                )
            launch_kwargs["executable_path"] = resolved_bin

        try:
            self._playwright = await async_playwright().start()
            self.context = await self._playwright.chromium.launch_persistent_context(
                **launch_kwargs,
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

        end: float = time.time() + timeout_seconds
        while time.time() < end:
            for selector in INPUT_SELECTORS:
                try:
                    element: Any = await self.page.query_selector(selector)
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
                element: Any = await self.page.query_selector(selector)
            except Exception:
                element = None
            if element is not None:
                return element
        return None

    async def _click_selector(self, selector: str) -> bool:
        if self.page is None:
            return False

        try:
            elements: List[Any] = await self.page.query_selector_all(selector)
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

        file_paths: List[str] = self._validate_files(files)
        if not file_paths:
            return

        for selector in ATTACH_BUTTON_SELECTORS:
            if await self._click_selector(selector):
                await self._sleep_jitter(0.2, 0.3)
                break

        input_el: Any = await self._find_file_input()
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

        result: Any = await self.page.evaluate(INSERT_TEXT_JS, {"selector": input_selector, "text": prompt})
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
            buttons: List[Any] = await self.page.query_selector_all("button")
        except Exception:
            buttons = []

        for button in buttons:
            try:
                text: str = (await button.inner_text() or "") + " " + (await button.get_attribute("aria-label") or "")
                if SEND_TEXT_PATTERN.search(text):
                    await button.click(timeout=1200)
                    return
            except Exception:
                continue

        try:
            element: Any = await self.page.query_selector(input_selector)
            if element is None:
                raise EngineRuntimeError("input selector not found before Enter fallback")
            await element.press("Enter")
        except Exception as exc:
            raise EngineRuntimeError(f"failed to submit prompt in playwright: {exc}") from exc

    async def _get_body(self) -> str:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")
        body: Any = await self.page.evaluate(BODY_TEXT_JS)
        return str(body or "")

    async def _get_response_via_dom(self) -> Optional[str]:
        if self.page is None:
            return None
        try:
            result: Any = await self.page.evaluate(GET_RESPONSE_VIA_DOM_JS)
            return str(result) if result else None
        except Exception:
            return None

    async def ensure_grok(self) -> str:
        return await self._ensure_on_grok()

    def _grok_url(self) -> str:
        return self.cfg.project_url or GROK_URL

    async def _ensure_on_grok(self, force_navigate: bool = False) -> str:
        await self.start()
        assert self.page is not None

        target: str = self._grok_url()
        if force_navigate or not self.page.url.startswith(target):
            try:
                await self.page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=self.cfg.page_timeout_seconds * 1000,
                )
            except Exception as exc:
                raise EngineRuntimeError(f"failed to navigate to grok.com: {exc}") from exc

            await self._sleep_jitter(0.5, 1.0)

        selector: Optional[str] = await self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found on grok page")
        return selector

    async def new_conversation(self) -> None:
        await self.start()
        assert self.page is not None
        target: str = self._grok_url()
        try:
            await self.page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self.cfg.page_timeout_seconds * 1000,
            )
        except Exception as exc:
            raise EngineRuntimeError(f"failed to navigate to grok.com: {exc}") from exc

        await self._sleep_jitter(0.5, 1.0)

        selector: Optional[str] = await self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found after opening new conversation")

    async def chat(self, prompt: str, timeout: int, files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        input_selector: str = await self.ensure_grok()
        body_before: str = await self._get_body()
        initial_len: int = len(body_before)

        if files:
            await self._attach_files(files)

        await self._type_and_send(prompt, input_selector)

        start: float = time.time()
        last: str = ""
        stable: int = 0
        has_response: bool = False
        poll_interval: float = 2.0
        min_growth: int = 50  # chars: threshold to consider grok started responding

        while time.time() - start < timeout:
            await asyncio.sleep(poll_interval)
            body: str = await self._get_body()
            current_len: int = len(body)

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
                    extracted: str = self._extract(body, prompt)
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

        partial: str = self._extract(last, prompt) if last else ""
        if not partial:
            partial = await self._get_response_via_dom() or ""
        return {
            "status": "timeout",
            "response": partial,
            "elapsed": round(time.time() - start, 1),
        }

    async def send_and_wait(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        input_selector: str = await self._ensure_on_grok(force_navigate=False)
        start: float = time.time()

        if files:
            await self._attach_files(files)

        await self._type_and_send(prompt, input_selector)

        last_dom: Optional[str] = None
        dom_stable: int = 0
        last_body: str = ""
        body_stable: int = 0
        entered_body_fallback: bool = False

        while time.time() - start < timeout:
            await _async_sleep(0.3)
            elapsed: float = time.time() - start

            # Fast path: DOM extraction — requires stability to avoid partial reads
            extracted: Optional[str] = await self._get_response_via_dom()
            if extracted:
                if extracted == last_dom:
                    dom_stable += 1
                    if dom_stable >= 2:  # ~0.6s of identical text → generation done
                        return {
                            "status": "ok",
                            "response": self._clean(extracted),
                            "_raw": extracted,
                            "elapsed": round(elapsed, 1),
                        }
                else:
                    last_dom = extracted
                    dom_stable = 0
                continue

            # DOM selectors didn't match — fall back to body-text polling
            if elapsed < 3.0 and not entered_body_fallback:
                continue

            entered_body_fallback = True
            body: str = await self._get_body()
            if body == last_body:
                body_stable += 1
                if body_stable >= 2:  # ~0.6s stable on body text
                    extracted = await self._get_response_via_dom()
                    if extracted:
                        return {
                            "status": "ok",
                            "response": self._clean(extracted),
                            "_raw": extracted,
                            "elapsed": round(elapsed, 1),
                        }
                    return {
                        "status": "ok",
                        "response": self._extract(body, prompt) or "",
                        "_raw": body[:2000],
                        "elapsed": round(elapsed, 1),
                    }
            else:
                body_stable = 0
            last_body = body

        # Timeout — return whatever we have
        partial: Optional[str] = await self._get_response_via_dom()
        if partial:
            return {
                "status": "timeout",
                "response": self._clean(partial),
                "_raw": partial,
                "elapsed": round(time.time() - start, 1),
            }
        return {
            "status": "error",
            "error": "no response detected",
            "elapsed": round(time.time() - start, 1),
        }

    async def watch_response(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[Sequence[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        input_selector: str = await self._ensure_on_grok(force_navigate=False)
        if files:
            await self._attach_files(files)

        old_dom: Optional[str] = await self._get_response_via_dom()

        await self._type_and_send(prompt, input_selector)

        start: float = time.time()
        last_dom: Optional[str] = old_dom
        dom_stable: int = 0
        has_new: bool = False
        body_before: str = await self._get_body()
        initial_len: int = len(body_before)
        has_response: bool = False
        last_body_text: Optional[str] = None
        body_stable: int = 0
        entered_body_fallback: bool = False

        while time.time() - start < timeout:
            await _async_sleep(0.3)
            elapsed: float = time.time() - start

            extracted: Optional[str] = await self._get_response_via_dom()

            if extracted:
                if has_new:
                    if extracted != last_dom:
                        yield {"type": "partial", "content": extracted}
                        last_dom = extracted
                        dom_stable = 0
                    else:
                        dom_stable += 1
                        if dom_stable >= 2:
                            yield {"type": "done", "content": extracted}
                            return
                elif extracted != old_dom:
                    has_new = True
                    has_response = True
                    yield {"type": "partial", "content": extracted}
                    last_dom = extracted
                elif old_dom is None:
                    has_new = True
                    has_response = True
                    yield {"type": "partial", "content": extracted}
                    last_dom = extracted
                continue

            if elapsed < 3.0 and not entered_body_fallback:
                continue
            entered_body_fallback = True

            body: str = await self._get_body()

            if not has_response:
                if len(body) <= initial_len + 50:
                    continue
                has_response = True
                has_new = True

            if body == last_body_text:
                body_stable += 1
                if body_stable >= 2:
                    extracted = await self._get_response_via_dom()
                    if extracted:
                        yield {"type": "done", "content": extracted}
                    else:
                        content: str = self._extract(body, prompt) or ""
                        yield {"type": "done", "content": content}
                    return
            else:
                body_stable = 0
            last_body_text = body

        partial: Optional[str] = await self._get_response_via_dom()
        if partial:
            yield {"type": "timeout", "content": partial}
        else:
            yield {"type": "error", "content": "no response detected"}

    async def history(self) -> Dict[str, Any]:
        await self.start()
        body: str = await self._get_body()
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
            url: str = self.page.url or ""
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
            item: Dict[str, Any] = {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": cookie.get("domain"),
                "path": cookie.get("path", "/"),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", True),
                "sameSite": cookie.get("sameSite", "Lax"),
            }
            expires: Any = cookie.get("expires", cookie.get("expiry"))
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
            idx: int = text.rfind(marker)
            if idx > 0:
                text = text[:idx]

        # Strip thinking/evaluating lines: "Evaluating expression • 2s"
        text = re.sub(r"(?m)^.*?•\s*\d+(\.\d+)?[ms]?\n?", "", text)
        # Strip naked timing: " • 2s" or "• 2s" in the middle of text
        text = re.sub(r"\s*•\s*\d+(\.\d+)?[ms]?\n?", "\n", text)
        # Generic "Thinking..." / "Evaluating..." headings
        text = re.sub(r"(?m)^(Thinking|Evaluating|Calculating|Analyzing|Searching|Looking up).*\n?", "", text)
        # Strip "Detecting..." jailbreak warnings
        text = re.sub(r"(?m)^Detecting.*\n?", "", text)
        text = re.sub(r"\n[0-9]+(\.[0-9]+)?s\n", "\n", text)
        text = re.sub(r"\n(Share|Compare|Make it|Explain|Toggle|Like|Dislike).*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _extract(cls, body: str, prompt: str) -> str:
        marker: str = prompt[:60]
        idx: int = body.find(marker)
        if idx >= 0:
            after: str = body[idx + len(marker) :]
            return cls._clean(after)
        return cls._clean(body)

    @staticmethod
    def _validate_files(files: Optional[Sequence[str]]) -> List[str]:
        if not files:
            return []

        absolute: List[str] = []
        missing: List[str] = []
        for file_path in files:
            resolved: str = os.path.abspath(os.path.expanduser(file_path))
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

    def __init__(self, cfg: EngineConfig, tool_server_url: str = "http://localhost:19997") -> None:
        self.cfg: EngineConfig = cfg
        self._engine: GrokPlaywrightEngine = GrokPlaywrightEngine(cfg)
        self._tool_server_url: str = tool_server_url

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
            result: Dict[str, Any] = await self._engine.chat(prompt=prompt, timeout=timeout, files=files)
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
            result: Dict[str, Any] = await self._engine.history()
            result["engine"] = self._engine.name
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def health(self) -> Dict[str, Any]:
        availability: Dict[str, bool] = {
            "playwright": GrokPlaywrightEngine.available(),
        }
        result: Dict[str, Any] = await self._engine.health()
        result["available_engines"] = availability
        result["active_engine"] = self._engine.name
        return result

    async def agent_chat(
        self,
        prompt: str,
        timeout: int = 120,
        tools: Optional[Sequence[str]] = None,
        max_steps: int = 10,
    ) -> Dict[str, Any]:
        from agent import GrokAgent

        if not (prompt or "").strip():
            return {"status": "error", "error": "prompt is required"}

        timeout = int(timeout or 120)
        if timeout < 5:
            timeout = 5

        try:
            agent: GrokAgent = GrokAgent(self._engine, self._tool_server_url)
            result: Dict[str, Any] = await agent.run(
                user_prompt=prompt,
                timeout=timeout,
                tools=list(tools) if tools else None,
                max_steps=max_steps,
            )
            result["engine"] = self._engine.name
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def stream_chat(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[Sequence[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for event in self._engine.watch_response(
            prompt=prompt, timeout=timeout, files=files,
        ):
            yield event

    async def stream_agent(
        self,
        prompt: str,
        timeout: int = 120,
        tools: Optional[Sequence[str]] = None,
        max_steps: int = 10,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from agent import GrokAgent

        agent: GrokAgent = GrokAgent(self._engine, self._tool_server_url)
        async for event in agent.run_streaming(
            user_prompt=prompt,
            timeout=timeout,
            tools=list(tools) if tools else None,
            max_steps=max_steps,
        ):
            yield event
