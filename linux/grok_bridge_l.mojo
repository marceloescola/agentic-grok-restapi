#!/usr/bin/env python3
"""
grok_bridge_l.py v3 - Linux REST bridge for grok.com.

This entrypoint exposes a FastAPI service while browser automation lives in
the dedicated linux engine module.
"""

from __future__ import annotations

import argparse
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

from grok_engine_l import ENGINE_VERSION, EngineConfig, GrokEngineManager


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
    pass


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(manager: GrokEngineManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await manager.warmup()
        yield
        await manager.shutdown()

    app = FastAPI(title="Grok Bridge Linux", version=ENGINE_VERSION, lifespan=lifespan)

    @app.post("/chat")
    async def chat(req: ChatRequest):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] >> {req.prompt[:80]}", flush=True)
        result = await manager.chat(
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
    async def agent(req: AgentRequest):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] AGT>> {req.prompt[:80]}", flush=True)
        result = await manager.agent_chat(
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
    async def new(req: Optional[NewRequest] = None):
        return await manager.new_conversation()

    @app.get("/health")
    async def health():
        return await manager.health()

    @app.get("/history")
    async def history():
        return await manager.history()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Linux Grok REST bridge")
    parser.add_argument("--host", default=os.getenv("GROK_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GROK_PORT", "19998")))
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

    cfg = EngineConfig(
        profile_root=args.profile_dir,
        headless=bool(args.headless),
        page_timeout_seconds=max(10, int(args.page_timeout)),
        user_data_dir=args.user_data_dir.strip() or None,
        browser_binary=args.browser_path.strip() or None,
        profile_name=args.profile_name.strip() or "Default",
        project_url=args.project_url.strip() or None,
    )
    manager = GrokEngineManager(cfg=cfg, tool_server_url=args.tool_server_url)
    app = create_app(manager)

    print(f"Grok Bridge Linux {ENGINE_VERSION} {args.host}:{args.port}", flush=True)
    print(
        "Endpoints: POST /chat, POST /agent, POST /new, GET /health, GET /history",
        flush=True,
    )
    print(
        "Chat supports optional fields: files (list[str])",
        flush=True,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
