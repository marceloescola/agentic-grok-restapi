#!/usr/bin/env python3
"""
grok_bridge_l.py v2 - Linux REST bridge for grok.com.

This entrypoint exposes a FastAPI service while browser automation lives in
the dedicated linux engine module.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import List, Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

from grok_engine_l import ENGINE_VERSION, EngineConfig, GrokEngineManager

EngineMode = Literal["auto", "selenium", "playwright"]


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    timeout: int = Field(default=120, ge=5, le=900)
    files: List[str] = Field(default_factory=list)
    engine: EngineMode = "auto"


class NewRequest(BaseModel):
    engine: EngineMode = "auto"


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(manager: GrokEngineManager) -> FastAPI:
    app = FastAPI(title="Grok Bridge Linux", version=ENGINE_VERSION)

    @app.on_event("startup")
    def _startup() -> None:
        # Warm up preferred engine early so auth/profile issues surface fast.
        manager.warmup()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        manager.shutdown()

    @app.post("/chat")
    def chat(req: ChatRequest):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] >> {req.prompt[:80]}", flush=True)
        result = manager.chat(
            prompt=req.prompt,
            timeout=req.timeout,
            files=req.files,
            engine=req.engine,
        )
        print(
            f"[{ts}] << [{result.get('status')}] "
            f"{str(result.get('response', result.get('error', '')))[:80]}",
            flush=True,
        )
        return result

    @app.post("/new")
    def new(req: Optional[NewRequest] = None):
        mode: EngineMode = req.engine if req else "auto"
        return manager.new_conversation(mode)

    @app.get("/health")
    def health():
        return manager.health()

    @app.get("/history")
    def history():
        return manager.history()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Linux Grok REST bridge")
    parser.add_argument("--host", default=os.getenv("GROK_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GROK_PORT", "19998")))
    parser.add_argument(
        "--engine",
        choices=["auto", "selenium", "playwright"],
        default=os.getenv("GROK_ENGINE", "auto"),
        help="Preferred runtime engine. auto uses selenium primary and playwright fallback.",
    )
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("GROK_PROFILE_DIR", "~/.grok-bridge/firefox-profile"),
        help="Persistent profile root for automation engines.",
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
    args = parser.parse_args()

    cfg = EngineConfig(
        profile_root=args.profile_dir,
        headless=bool(args.headless),
        page_timeout_seconds=max(10, int(args.page_timeout)),
    )
    manager = GrokEngineManager(cfg=cfg, default_engine=args.engine)
    app = create_app(manager)

    print(f"Grok Bridge Linux {ENGINE_VERSION} {args.host}:{args.port}", flush=True)
    print(
        "Endpoints: POST /chat, POST /new, GET /health, GET /history",
        flush=True,
    )
    print(
        "Chat supports optional fields: files (list[str]), engine (auto|selenium|playwright)",
        flush=True,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
