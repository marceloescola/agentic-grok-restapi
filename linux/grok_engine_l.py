#!/usr/bin/env python3
"""
Linux browser automation engine for grok.com.

Primary: Selenium + Firefox
Fallback: Playwright + Firefox
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

GROK_URL = "https://grok.com/"
ENGINE_VERSION = "v2-linux-multi"

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

BODY_TEXT_JS = """
() => (document && document.body && document.body.innerText) ? document.body.innerText : ''
"""


class EngineRuntimeError(RuntimeError):
    pass


@dataclass
class EngineConfig:
    profile_root: str
    headless: bool = False
    page_timeout_seconds: int = 60


class BaseLinuxEngine:
    name = "base"

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def ensure_grok(self) -> str:
        raise NotImplementedError

    def new_conversation(self) -> None:
        raise NotImplementedError

    def chat(self, prompt: str, timeout: int, files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def history(self) -> Dict[str, Any]:
        raise NotImplementedError

    def health(self) -> Dict[str, Any]:
        raise NotImplementedError

    def export_cookies(self) -> List[Dict[str, Any]]:
        return []

    def import_cookies(self, cookies: Sequence[Dict[str, Any]]) -> None:
        del cookies

    @staticmethod
    def _sleep_jitter(base_seconds: float = 0.08, max_extra_seconds: float = 0.24) -> None:
        time.sleep(base_seconds + random.uniform(0.0, max_extra_seconds))

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
        parts = body.split(marker)
        after = parts[-1] if len(parts) >= 2 else body
        return cls._clean(after)

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


class SeleniumFirefoxEngine(BaseLinuxEngine):
    name = "selenium"

    def __init__(self, cfg: EngineConfig) -> None:
        super().__init__(cfg)
        self.driver = None
        self.By = None
        self.Keys = None
        self.ActionChains = None

    @staticmethod
    def available() -> bool:
        try:
            import selenium  # noqa: F401
            return True
        except Exception:
            return False

    def _profile_dir(self) -> str:
        path = Path(self.cfg.profile_root).expanduser() / "selenium"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def start(self) -> None:
        if self.driver is not None:
            return

        try:
            from selenium import webdriver
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.firefox.options import Options as FirefoxOptions
        except Exception as exc:
            raise EngineRuntimeError(
                "selenium imports failed. Install with: pip install selenium"
            ) from exc

        profile_dir = self._profile_dir()

        options = FirefoxOptions()
        options.add_argument("-profile")
        options.add_argument(profile_dir)
        if self.cfg.headless:
            options.add_argument("-headless")

        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("media.peerconnection.enabled", False)
        options.set_preference("toolkit.telemetry.reportingpolicy.firstRun", False)

        try:
            self.driver = webdriver.Firefox(options=options)
        except Exception as exc:
            raise EngineRuntimeError(f"failed to start selenium firefox: {exc}") from exc

        self.By = By
        self.Keys = Keys
        self.ActionChains = ActionChains
        self.driver.set_page_load_timeout(self.cfg.page_timeout_seconds)
        self.driver.set_script_timeout(self.cfg.page_timeout_seconds)

        try:
            self.driver.execute_script(STEALTH_JS)
        except Exception:
            pass

    def stop(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.quit()
        finally:
            self.driver = None

    def _js(self, script: str, *args: Any) -> Any:
        if self.driver is None:
            raise EngineRuntimeError("selenium driver is not started")
        return self.driver.execute_script(script, *args)

    def _find_input_selector(self, timeout_seconds: int = 20) -> Optional[str]:
        if self.driver is None:
            return None

        end = time.time() + timeout_seconds
        while time.time() < end:
            for selector in INPUT_SELECTORS:
                try:
                    elements = self.driver.find_elements(self.By.CSS_SELECTOR, selector)
                    if elements:
                        return selector
                except Exception:
                    continue
            self._sleep_jitter(0.16, 0.24)
        return None

    def _find_file_input(self) -> Any:
        if self.driver is None:
            return None

        for selector in FILE_INPUT_SELECTORS:
            try:
                elements = self.driver.find_elements(self.By.CSS_SELECTOR, selector)
            except Exception:
                elements = []
            if elements:
                return elements[0]
        return None

    def _click_selector(self, selector: str) -> bool:
        if self.driver is None:
            return False

        try:
            elements = self.driver.find_elements(self.By.CSS_SELECTOR, selector)
        except Exception:
            return False

        for element in elements:
            try:
                if not element.is_enabled():
                    continue
                self.ActionChains(self.driver).move_to_element(element).pause(
                    random.uniform(0.05, 0.18)
                ).click(element).perform()
                return True
            except Exception:
                try:
                    self._js("arguments[0].click()", element)
                    return True
                except Exception:
                    continue

        return False

    def _attach_files(self, files: Sequence[str]) -> None:
        if self.driver is None:
            raise EngineRuntimeError("selenium driver is not started")

        file_paths = self._validate_files(files)
        if not file_paths:
            return

        for selector in ATTACH_BUTTON_SELECTORS:
            if self._click_selector(selector):
                self._sleep_jitter(0.2, 0.3)
                break

        input_el = self._find_file_input()
        if input_el is None:
            raise EngineRuntimeError("file input not found on page")

        try:
            self._js(
                "arguments[0].style.display='block';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].style.opacity='1';",
                input_el,
            )
        except Exception:
            pass

        payload = "\n".join(file_paths)
        try:
            input_el.send_keys(payload)
        except Exception as exc:
            raise EngineRuntimeError(f"failed to attach files via selenium: {exc}") from exc

        self._sleep_jitter(0.4, 0.4)

    def _type_and_send(self, prompt: str, input_selector: str) -> None:
        if self.driver is None:
            raise EngineRuntimeError("selenium driver is not started")

        result = self._js(INSERT_TEXT_JS, {"selector": input_selector, "text": prompt})
        if "OK" not in str(result):
            try:
                element = self.driver.find_element(self.By.CSS_SELECTOR, input_selector)
                element.clear()
                element.send_keys(prompt)
            except Exception as exc:
                raise EngineRuntimeError(f"failed to type prompt in selenium: {exc}") from exc

        self._sleep_jitter(0.2, 0.3)

        for selector in SEND_SELECTORS:
            if self._click_selector(selector):
                return

        try:
            buttons = self.driver.find_elements(self.By.CSS_SELECTOR, "button")
        except Exception:
            buttons = []

        for button in buttons:
            try:
                label = (button.text or "") + " " + (button.get_attribute("aria-label") or "")
                if SEND_TEXT_PATTERN.search(label) and button.is_enabled():
                    self.ActionChains(self.driver).move_to_element(button).pause(
                        random.uniform(0.05, 0.18)
                    ).click(button).perform()
                    return
            except Exception:
                continue

        try:
            element = self.driver.find_element(self.By.CSS_SELECTOR, input_selector)
            element.send_keys(self.Keys.ENTER)
        except Exception as exc:
            raise EngineRuntimeError(f"failed to submit prompt in selenium: {exc}") from exc

    def _get_body(self) -> str:
        body = self._js(BODY_TEXT_JS)
        return str(body or "")

    def ensure_grok(self) -> str:
        self.start()
        assert self.driver is not None
        self.driver.get(GROK_URL)
        selector = self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found on grok page")
        return selector

    def new_conversation(self) -> None:
        self.start()
        assert self.driver is not None
        self.driver.get(GROK_URL)
        selector = self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found after opening new conversation")

    def chat(self, prompt: str, timeout: int, files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        input_selector = self.ensure_grok()
        body_before = self._get_body()

        if files:
            self._attach_files(files)

        self._type_and_send(prompt, input_selector)

        start = time.time()
        last = ""
        stable = 0

        while time.time() - start < timeout:
            time.sleep(2)
            body = self._get_body()
            if body != body_before and body == last:
                stable += 1
                if stable >= 3:
                    return {
                        "status": "ok",
                        "response": self._extract(body, prompt),
                        "elapsed": round(time.time() - start, 1),
                    }
            else:
                stable = 0
            last = body

        partial = self._extract(last, prompt) if last else ""
        return {
            "status": "timeout",
            "response": partial,
            "elapsed": round(time.time() - start, 1),
        }

    def history(self) -> Dict[str, Any]:
        self.start()
        body = self._get_body()
        return {"status": "ok", "content": self._clean(body), "raw_length": len(body)}

    def health(self) -> Dict[str, Any]:
        if self.driver is None:
            return {
                "status": "error",
                "error": "selenium firefox not started",
                "url": "",
                "on_grok": False,
                "version": ENGINE_VERSION,
            }

        try:
            url = self.driver.current_url
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

    def export_cookies(self) -> List[Dict[str, Any]]:
        if self.driver is None:
            return []
        try:
            return self.driver.get_cookies()
        except Exception:
            return []

    def import_cookies(self, cookies: Sequence[Dict[str, Any]]) -> None:
        if not cookies:
            return

        self.start()
        assert self.driver is not None
        self.driver.get(GROK_URL)

        allowed = {
            "name",
            "value",
            "path",
            "domain",
            "secure",
            "httpOnly",
            "expiry",
            "sameSite",
        }

        for cookie in cookies:
            normalized = {k: v for k, v in cookie.items() if k in allowed and v is not None}
            if "expiry" not in normalized and cookie.get("expires") is not None:
                try:
                    normalized["expiry"] = int(float(cookie["expires"]))
                except Exception:
                    pass
            if "sameSite" in normalized:
                value = str(normalized["sameSite"]).capitalize()
                if value in {"Lax", "Strict", "None"}:
                    normalized["sameSite"] = value
                else:
                    normalized.pop("sameSite", None)

            try:
                self.driver.add_cookie(normalized)
            except Exception:
                continue

        self.driver.get(GROK_URL)


class PlaywrightFirefoxEngine(BaseLinuxEngine):
    name = "playwright"

    def __init__(self, cfg: EngineConfig) -> None:
        super().__init__(cfg)
        self._playwright = None
        self.context = None
        self.page = None

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

    def start(self) -> None:
        if self.page is not None and self.context is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise EngineRuntimeError(
                "playwright imports failed. Install with: pip install playwright && playwright install firefox"
            ) from exc

        profile_dir = self._profile_dir()

        try:
            self._playwright = sync_playwright().start()
            self.context = self._playwright.firefox.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=self.cfg.headless,
                viewport={"width": 1366, "height": 900},
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(self.cfg.page_timeout_seconds * 1000)
            self.page.add_init_script(STEALTH_JS)
        except Exception as exc:
            self.stop()
            raise EngineRuntimeError(f"failed to start playwright firefox: {exc}") from exc

    def stop(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        self.context = None
        self.page = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    def _find_input_selector(self, timeout_seconds: int = 20) -> Optional[str]:
        if self.page is None:
            return None

        end = time.time() + timeout_seconds
        while time.time() < end:
            for selector in INPUT_SELECTORS:
                try:
                    element = self.page.query_selector(selector)
                except Exception:
                    element = None
                if element is not None:
                    return selector
            self._sleep_jitter(0.14, 0.22)
        return None

    def _find_file_input(self) -> Any:
        if self.page is None:
            return None

        for selector in FILE_INPUT_SELECTORS:
            try:
                element = self.page.query_selector(selector)
            except Exception:
                element = None
            if element is not None:
                return element
        return None

    def _click_selector(self, selector: str) -> bool:
        if self.page is None:
            return False

        try:
            elements = self.page.query_selector_all(selector)
        except Exception:
            elements = []

        for element in elements:
            try:
                element.scroll_into_view_if_needed()
                self._sleep_jitter(0.05, 0.15)
                element.click(timeout=1200)
                return True
            except Exception:
                try:
                    self.page.evaluate("(el) => el.click()", element)
                    return True
                except Exception:
                    continue
        return False

    def _attach_files(self, files: Sequence[str]) -> None:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")

        file_paths = self._validate_files(files)
        if not file_paths:
            return

        for selector in ATTACH_BUTTON_SELECTORS:
            if self._click_selector(selector):
                self._sleep_jitter(0.2, 0.3)
                break

        input_el = self._find_file_input()
        if input_el is None:
            raise EngineRuntimeError("file input not found on page")

        try:
            input_el.set_input_files(file_paths)
        except Exception as exc:
            raise EngineRuntimeError(f"failed to attach files via playwright: {exc}") from exc

        self._sleep_jitter(0.3, 0.35)

    def _type_and_send(self, prompt: str, input_selector: str) -> None:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")

        result = self.page.evaluate(INSERT_TEXT_JS, {"selector": input_selector, "text": prompt})
        if "OK" not in str(result):
            try:
                self.page.fill(input_selector, prompt)
            except Exception as exc:
                raise EngineRuntimeError(f"failed to type prompt in playwright: {exc}") from exc

        self._sleep_jitter(0.2, 0.3)

        for selector in SEND_SELECTORS:
            if self._click_selector(selector):
                return

        try:
            buttons = self.page.query_selector_all("button")
        except Exception:
            buttons = []

        for button in buttons:
            try:
                text = (button.inner_text() or "") + " " + (button.get_attribute("aria-label") or "")
                if SEND_TEXT_PATTERN.search(text):
                    button.click(timeout=1200)
                    return
            except Exception:
                continue

        try:
            element = self.page.query_selector(input_selector)
            if element is None:
                raise EngineRuntimeError("input selector not found before Enter fallback")
            element.press("Enter")
        except Exception as exc:
            raise EngineRuntimeError(f"failed to submit prompt in playwright: {exc}") from exc

    def _get_body(self) -> str:
        if self.page is None:
            raise EngineRuntimeError("playwright page is not started")
        body = self.page.evaluate(BODY_TEXT_JS)
        return str(body or "")

    def ensure_grok(self) -> str:
        self.start()
        assert self.page is not None
        self.page.goto(GROK_URL, wait_until="domcontentloaded", timeout=self.cfg.page_timeout_seconds * 1000)
        selector = self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found on grok page")
        return selector

    def new_conversation(self) -> None:
        self.start()
        assert self.page is not None
        self.page.goto(GROK_URL, wait_until="domcontentloaded", timeout=self.cfg.page_timeout_seconds * 1000)
        selector = self._find_input_selector(timeout_seconds=25)
        if not selector:
            raise EngineRuntimeError("input not found after opening new conversation")

    def chat(self, prompt: str, timeout: int, files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        input_selector = self.ensure_grok()
        body_before = self._get_body()

        if files:
            self._attach_files(files)

        self._type_and_send(prompt, input_selector)

        start = time.time()
        last = ""
        stable = 0

        while time.time() - start < timeout:
            time.sleep(2)
            body = self._get_body()
            if body != body_before and body == last:
                stable += 1
                if stable >= 3:
                    return {
                        "status": "ok",
                        "response": self._extract(body, prompt),
                        "elapsed": round(time.time() - start, 1),
                    }
            else:
                stable = 0
            last = body

        partial = self._extract(last, prompt) if last else ""
        return {
            "status": "timeout",
            "response": partial,
            "elapsed": round(time.time() - start, 1),
        }

    def history(self) -> Dict[str, Any]:
        self.start()
        body = self._get_body()
        return {"status": "ok", "content": self._clean(body), "raw_length": len(body)}

    def health(self) -> Dict[str, Any]:
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

    def export_cookies(self) -> List[Dict[str, Any]]:
        if self.context is None:
            return []
        try:
            return self.context.cookies()
        except Exception:
            return []

    def import_cookies(self, cookies: Sequence[Dict[str, Any]]) -> None:
        if not cookies:
            return

        self.start()
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
            self.context.add_cookies(translated)
        except Exception:
            pass


class GrokEngineManager:
    """Orchestrates selenium primary and playwright fallback."""

    def __init__(self, cfg: EngineConfig, default_engine: str = "auto") -> None:
        self.cfg = cfg
        self.default_engine = default_engine if default_engine in {"auto", "selenium", "playwright"} else "auto"
        self.lock = threading.Lock()
        self._engines: Dict[str, BaseLinuxEngine] = {}
        self.active_engine: Optional[str] = None

    def _engine_order(self, engine: str) -> List[str]:
        selected = engine if engine in {"auto", "selenium", "playwright"} else self.default_engine
        if selected in {"selenium", "playwright"}:
            return [selected]

        if self.active_engine in {"selenium", "playwright"}:
            other = "playwright" if self.active_engine == "selenium" else "selenium"
            return [self.active_engine, other]

        return ["selenium", "playwright"]

    def _build_engine(self, name: str) -> BaseLinuxEngine:
        if name == "selenium":
            return SeleniumFirefoxEngine(self.cfg)
        if name == "playwright":
            return PlaywrightFirefoxEngine(self.cfg)
        raise EngineRuntimeError(f"unsupported engine: {name}")

    def _get_engine(self, name: str) -> BaseLinuxEngine:
        if name not in self._engines:
            self._engines[name] = self._build_engine(name)
        return self._engines[name]

    def _transfer_cookies(self, source_name: str, target_name: str) -> None:
        source = self._engines.get(source_name)
        if source is None:
            return
        cookies = source.export_cookies()
        if not cookies:
            return

        target = self._get_engine(target_name)
        target.import_cookies(cookies)

    def warmup(self) -> None:
        with self.lock:
            for name in self._engine_order(self.default_engine):
                try:
                    self._get_engine(name).start()
                    self.active_engine = name
                    return
                except Exception:
                    continue

    def shutdown(self) -> None:
        with self.lock:
            for engine in self._engines.values():
                try:
                    engine.stop()
                except Exception:
                    continue
            self._engines.clear()
            self.active_engine = None

    def chat(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[Sequence[str]] = None,
        engine: str = "auto",
    ) -> Dict[str, Any]:
        if not (prompt or "").strip():
            return {"status": "error", "error": "prompt is required"}

        timeout = int(timeout or 120)
        if timeout < 5:
            timeout = 5

        with self.lock:
            errors: Dict[str, str] = {}
            previous_name: Optional[str] = None

            for name in self._engine_order(engine):
                current = self._get_engine(name)
                try:
                    current.start()

                    if previous_name and previous_name != name:
                        self._transfer_cookies(previous_name, name)

                    result = current.chat(prompt=prompt, timeout=timeout, files=files)
                    result["engine"] = name
                    self.active_engine = name
                    return result
                except Exception as exc:
                    errors[name] = str(exc)
                    previous_name = name

            return {"status": "error", "error": f"all engines failed: {errors}"}

    def new_conversation(self, engine: str = "auto") -> Dict[str, Any]:
        with self.lock:
            errors: Dict[str, str] = {}
            previous_name: Optional[str] = None

            for name in self._engine_order(engine):
                current = self._get_engine(name)
                try:
                    current.start()
                    if previous_name and previous_name != name:
                        self._transfer_cookies(previous_name, name)
                    current.new_conversation()
                    self.active_engine = name
                    return {"status": "ok", "engine": name}
                except Exception as exc:
                    errors[name] = str(exc)
                    previous_name = name

            return {"status": "error", "error": f"all engines failed: {errors}"}

    def history(self, engine: str = "auto") -> Dict[str, Any]:
        with self.lock:
            errors: Dict[str, str] = {}

            for name in self._engine_order(engine):
                current = self._get_engine(name)
                try:
                    current.start()
                    result = current.history()
                    result["engine"] = name
                    self.active_engine = name
                    return result
                except Exception as exc:
                    errors[name] = str(exc)

            return {"status": "error", "error": f"all engines failed: {errors}"}

    def health(self) -> Dict[str, Any]:
        with self.lock:
            availability = {
                "selenium": SeleniumFirefoxEngine.available(),
                "playwright": PlaywrightFirefoxEngine.available(),
            }

            names = self._engine_order("auto")
            if not names:
                return {
                    "status": "error",
                    "error": "no engines configured",
                    "url": "",
                    "on_grok": False,
                    "version": ENGINE_VERSION,
                    "active_engine": None,
                    "available_engines": availability,
                }

            errors: Dict[str, str] = {}
            for name in names:
                current = self._get_engine(name)
                try:
                    current.start()
                    result = current.health()
                    result["active_engine"] = name
                    result["available_engines"] = availability
                    self.active_engine = name
                    return result
                except Exception as exc:
                    errors[name] = str(exc)

            return {
                "status": "error",
                "error": f"all engines failed: {errors}",
                "url": "",
                "on_grok": False,
                "version": ENGINE_VERSION,
                "active_engine": self.active_engine,
                "available_engines": availability,
            }
