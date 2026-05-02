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
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from grok_engine_l import ENGINE_VERSION, EngineConfig, GrokEngineManager
from pydantic import BaseModel, Field

from db import SessionDB


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


class NewRequest(BaseModel):
    agentic: bool = Field(default=False)


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(manager: GrokEngineManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> None:
        await manager.warmup()
        yield
        await manager.shutdown()

    app: FastAPI = FastAPI(
        title="Grok Bridge Linux", version=ENGINE_VERSION, lifespan=lifespan
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
        )
        print(
            f"[{ts}] AGT<< [{result.get('status')}] "
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

    class LoadSessionRequest(BaseModel):
        id: int

    @app.post("/sessions/load")
    async def load_session(req: LoadSessionRequest) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] SES>> load session {req.id}", flush=True)
        result: dict[str, Any] = await manager.load_session(req.id)
        print(f"[{ts}] SES<< {result.get('status', 'error')}", flush=True)
        return result

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: int) -> dict[str, Any]:
        ts: str = time.strftime("%H:%M:%S")
        print(f"[{ts}] SES>> delete session {session_id}", flush=True)
        result: dict[str, Any] = await manager.delete_session(session_id)
        print(f"[{ts}] SES<< {result.get('status', 'error')}", flush=True)
        return result

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

                    if mode == "agent":
                        async for event in manager.stream_agent(
                            prompt=prompt,
                            timeout=timeout,
                            tools=tools,
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
        cfg=cfg, tool_server_url=args.tool_server_url
    )
    manager.set_db(db)
    app: FastAPI = create_app(manager)

    print(f"Grok Bridge Linux {ENGINE_VERSION} {args.host}:{args.port}", flush=True)
    print(
        "Endpoints: POST /chat, POST /agent, POST /new, GET /health, GET /history,"
        " GET /sessions, POST /sessions/load, DELETE /sessions/{id}, WS /ws",
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
