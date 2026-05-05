#!/usr/bin/env python3
"""
grok_bridge_l.py v3 - Linux REST bridge for grok.com.

This entrypoint exposes a FastAPI service while browser automation lives in
the dedicated linux engine module.

As you can see, it is a bit of a weird style of code. I did a lot of typing, even though we are on python

But once you get used it, you'll love it!
"""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional
from typing import Sequence as Seq

import uvicorn
from db import SessionDB
from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from grok_engine_l import (
    ENGINE_VERSION,
    INPUT_SELECTORS,
    INSERT_TEXT_JS,
    SCRAPE_MESSAGES_JS,
    SEND_SELECTORS,
    SESSION_NAME_JS,
    EngineConfig,
    GrokEngineManager,
)
from pydantic import BaseModel, Field


# Classes that will hold the model of chat request and agent request. Very good build the
# Endpoint later
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    timeout: int = Field(default=120, ge=5, le=900)
    files: List[str] = Field(default_factory=list)


class AgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    timeout: int = Field(default=120, ge=5, le=900)
    tools: List[str] = Field(default_factory=list)
    max_steps: int = Field(default=10, ge=1, le=20)
    attach_files: bool = Field(default=True)


class NewRequest(BaseModel):
    agentic: bool = Field(default=False)


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(manager: GrokEngineManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> None:
        await manager.warmup()
        await manager.new_conversation(agentic=False)
        yield
        await manager.shutdown()

    app: FastAPI = FastAPI(
        title="Grok Bridge Linux", version=ENGINE_VERSION, lifespan=lifespan
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] VALIDATION ERROR: {exc.errors()}", flush=True)
        print(f"[{ts}] Body: {await request.body()}", flush=True)
        traceback.print_exc()
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "body": str(await request.body())},
        )

    @app.post("/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] >> {req.prompt[:80]}", flush=True)
        result: dict[str, Any] = await manager.chat(
            prompt=req.prompt,
            timeout=req.timeout,
            files=req.files,
        )
        print(
            f"[{ts}] << [{result.get('status')}] "
            f"{str(result.get('response', result.get('error', '')))[:80]}",
            flush=True,
        )
        return result

    @app.post("/agent")
    async def agent(req: AgentRequest) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] AGT>> {req.prompt[:80]}", flush=True)
        result: dict[str, Any] = await manager.agent_chat(
            prompt=req.prompt,
            timeout=req.timeout,
            tools=req.tools or None,
            max_steps=req.max_steps,
            attach_files=req.attach_files,
        )
        print(
            f"[{ts}] AGT<< [{result.get('status')}] "
            f"{str(result.get('response', result.get('error', '')))[:80]}",
            flush=True,
        )
        return result

    @app.post("/agent-legacy")
    async def agent_legacy(req: AgentRequest) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] LEGACY>> {req.prompt[:80]}", flush=True)
        result: dict[str, Any] = await manager.agent_chat(
            prompt=req.prompt,
            timeout=req.timeout,
            tools=req.tools or None,
            max_steps=req.max_steps,
            attach_files=False,
        )
        print(
            f"[{ts}] LEGACY<< [{result.get('status')}] "
            f"{str(result.get('response', result.get('error', '')))[:80]}",
            flush=True,
        )
        return result

    @app.post("/new")
    async def new(req: Optional[NewRequest] = None) -> dict[str, Any]:
        agentic: bool = req.agentic if req else False
        return await manager.new_conversation(agentic=agentic)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return await manager.health()

    @app.get("/history")
    async def history() -> dict[str, Any]:
        return await manager.history()

    @app.get("/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return await manager.list_sessions()

    @app.post("/sessions/load")
    async def load_session(session_id: int = Body(embed=True)) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] SES>> load session {session_id}", flush=True)
        result: dict[str, Any] = await manager.load_session(session_id)
        print(f"[{ts}] SES<< {result.get('status', 'error')}", flush=True)
        return result

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: int) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] SES>> delete session {session_id}", flush=True)
        result: dict[str, Any] = await manager.delete_session(session_id)
        print(f"[{ts}] SES<< {result.get('status', 'error')}", flush=True)
        return result

    @app.get("/debug/scrape")
    async def debug_scrape() -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] DEBUG>> scrape test", flush=True)
        try:
            url: str = await manager._engine.get_current_url()
            raw: Any = await manager._engine.page.evaluate(SCRAPE_MESSAGES_JS)
            name_raw: Any = await manager._engine.page.evaluate(SESSION_NAME_JS)
            body: str = await manager._engine.page.evaluate(
                "() => document.body.innerText.substring(0, 2000)"
            )
            return {
                "url": url,
                "scrape_result": raw,
                "session_name": name_raw,
                "body_preview": body,
            }
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

    @app.get("/debug/inspect-dom")
    async def debug_inspect_dom() -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] DEBUG>> inspect DOM", flush=True)
        try:
            result: dict[str, Any] = {}
            result["url"] = await manager._engine.get_current_url()
            snippets: dict[str, str] = {}
            queries = [
                ("data-message-author-role", "[data-message-author-role]"),
                ("main", "main"),
                ("prose", "[class*='prose']"),
                ("conversation", "[class*='conversation']"),
                ("chat-container", "[class*='chat']"),
                ("message-group", "div[class*='group']"),
                ("article", "article"),
            ]
            for label, sel in queries:
                try:
                    html: str = await manager._engine.page.evaluate(
                        "(s) => { const el = document.querySelector(s); return el ? el.outerHTML.substring(0, 1500) : null; }",
                        sel,
                    )
                    if html:
                        snippets[label] = html
                except Exception:
                    pass
            result["elements"] = snippets
            result["body_start"] = await manager._engine.page.evaluate(
                "() => document.body.innerHTML.substring(0, 3000)"
            )
            return result
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

    @app.get("/debug/input")
    async def debug_input() -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] DEBUG>> test input selectors", flush=True)
        try:
            result: dict[str, Any] = {}
            result["url"] = await manager._engine.get_current_url()
            page = manager._engine.page
            result["input_selectors"] = {}
            for sel in INPUT_SELECTORS:
                try:
                    el_count: int = await page.evaluate(
                        "(s) => document.querySelectorAll(s).length", sel
                    )
                    if el_count > 0:
                        html: str = await page.evaluate(
                            "(s) => { const e = document.querySelector(s); return e ? e.outerHTML.substring(0, 800) : null; }",
                            sel,
                        )
                        tag: str = await page.evaluate(
                            "(s) => { const e = document.querySelector(s); return e ? e.tagName + '.' + (e.className || '') : null; }",
                            sel,
                        )
                        placeholder: Optional[str] = await page.evaluate(
                            "(s) => { const e = document.querySelector(s); return e ? (e.getAttribute('placeholder') || e.getAttribute('aria-label') || '') : null; }",
                            sel,
                        )
                        visible: bool = await page.evaluate(
                            "(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }",
                            sel,
                        )
                        result["input_selectors"][sel] = {
                            "count": el_count,
                            "tag": tag,
                            "html_preview": html[:400],
                            "placeholder": placeholder,
                            "visible": visible,
                        }
                except Exception as e:
                    result["input_selectors"][sel] = {"error": str(e)}
            result["send_selectors"] = {}
            for sel in SEND_SELECTORS:
                try:
                    el_count = await page.evaluate(
                        "(s) => document.querySelectorAll(s).length", sel
                    )
                    if el_count > 0:
                        html = await page.evaluate(
                            "(s) => { const e = document.querySelector(s); return e ? e.outerHTML.substring(0, 400) : null; }",
                            sel,
                        )
                        result["send_selectors"][sel] = {
                            "count": el_count,
                            "html_preview": html,
                        }
                except Exception as e:
                    result["send_selectors"][sel] = {"error": str(e)}
            return result
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

    @app.get("/debug/buttons")
    async def debug_buttons() -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] DEBUG>> list buttons", flush=True)
        try:
            buttons: list[dict[str, Any]] = await manager._engine.page.evaluate("""
                () => Array.from(document.querySelectorAll('button')).slice(0, 30).map(b => ({
                    tag: b.tagName,
                    id: b.id,
                    class: (b.className || '').substring(0, 120),
                    text: (b.innerText || '').substring(0, 60),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    dataTestid: b.getAttribute('data-testid') || '',
                    type: b.getAttribute('type') || '',
                    visible: b.offsetParent !== null,
                    rect: (() => { const r = b.getBoundingClientRect(); return {w: r.width, h: r.height, top: r.top, left: r.left}; })(),
                }))
            """)
            return {"url": await manager._engine.get_current_url(), "buttons": buttons}
        except Exception as exc:
            return {"error": str(exc), "traceback": traceback.format_exc()}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                raw: str = await ws.receive_text()
                data: dict = json.loads(raw)
                msg_type: str = data.get("type", "")

                if msg_type == "prompt":
                    prompt: str = data.get("content", "")
                    if not prompt:
                        await ws.send_json(
                            {"type": "error", "message": "content required"}
                        )
                        continue

                    mode: str = data.get("mode", "chat")
                    timeout: int = data.get("timeout", 120)
                    tools: list | None = data.get("tools")
                    attach_files: bool = data.get("attach_files", True)

                    if mode == "agent":
                        async for event in manager.stream_agent(
                            prompt=prompt,
                            timeout=timeout,
                            tools=tools,
                            attach_files=attach_files,
                        ):
                            await ws.send_json(event)
                    else:
                        files: list = data.get("files", [])
                        async for event in manager.stream_chat(
                            prompt=prompt,
                            timeout=timeout,
                            files=files,
                        ):
                            await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            try:
                await ws.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass

    return app


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Linux Grok REST bridge"
    )
    parser.add_argument("--host", default=os.getenv("GROK_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("GROK_PORT", "19998"))
    )
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("GROK_PROFILE_DIR", "~/.grok-bridge/firefox-profile"),
        help="Persistent profile root for Playwright Firefox.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=_as_bool(os.getenv("GROK_HEADLESS", "0")),
        help="Run browser headless. Default is headed for better reliability.",
    )
    parser.add_argument(
        "--page-timeout",
        type=int,
        default=int(os.getenv("GROK_PAGE_TIMEOUT", "60")),
        help="Page/script timeout in seconds.",
    )
    parser.add_argument(
        "--tool-server-url",
        default=os.getenv("TOOL_SERVER_URL", "http://localhost:19997"),
        help="URL of the tool server for /agent endpoint.",
    )
    parser.add_argument(
        "--user-data-dir",
        default=os.getenv("GROK_USER_DATA_DIR", ""),
        help="Path to existing Chromium user data dir (e.g. ~/.config/chromium).",
    )
    parser.add_argument(
        "--browser-path",
        default=os.getenv("GROK_BROWSER_PATH", ""),
        help="Path or name of the Chromium binary (default: Playwright bundled).",
    )
    parser.add_argument(
        "--profile-name",
        default=os.getenv("GROK_PROFILE_NAME", "Default"),
        help="Profile directory name within user data dir (default: Default).",
    )
    parser.add_argument(
        "--project-url",
        default=os.getenv("GROK_PROJECT_URL", ""),
        help="Grok project URL for persistent instructions (e.g. https://grok.com/project/UUID).",
    )
    parser.add_argument(
        "--extension-only",
        action="store_true",
        help="Skip Playwright browser startup (for use with browser extension only).",
    )
    args = parser.parse_args()

    cfg: EngineConfig = EngineConfig(
        profile_root=args.profile_dir,
        headless=bool(args.headless),
        page_timeout_seconds=max(10, int(args.page_timeout)),
        user_data_dir=args.user_data_dir.strip() or None,
        browser_binary=args.browser_path.strip() or None,
        profile_name=args.profile_name.strip() or "Default",
        project_url=args.project_url.strip() or None,
    )
    db: SessionDB = SessionDB()
    db.init_db()
    manager: GrokEngineManager = GrokEngineManager(
        cfg=cfg, tool_server_url=args.tool_server_url, extension_only=bool(args.extension_only)
    )
    manager.set_db(db)
    app: FastAPI = create_app(manager)

    if args.extension_only:
        print(f"Grok Bridge (extension-only mode) {args.host}:{args.port}", flush=True)
    else:
        print(f"Grok Bridge Linux {ENGINE_VERSION} {args.host}:{args.port}", flush=True)
    print(
        "Endpoints: POST /chat, POST /agent, POST /agent-legacy (deprecated),"
        " POST /new, GET /health, GET /history, GET /sessions,"
        " POST /sessions/load, DELETE /sessions/{id},"
        " GET /debug/scrape, GET /debug/inspect-dom, GET /debug/input,"
        " GET /debug/buttons, WS /ws",
        flush=True,
    )
    print(
        "Chat supports optional fields: files (list[str])",
        flush=True,
    )
    print(
        'WS /ws accepts JSON: {"type":"prompt","content":"...","mode":"chat|agent"}',
        flush=True,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
