#!/usr/bin/env python3
"""Standalone tool server for Grok Bridge tool execution.

Start with: python tools/tool_server.py --port 19997
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

# Allow running from anywhere — add project root to path
_project_root: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from tools.base import Tool
from tools.calculator import CalculatorTool
from tools.file_read import FileReadTool, set_allowed_dirs
from tools.registry import ALL_TOOLS
from tools.web_search import WebSearchTool

_tool_instances: Dict[str, Tool] = {
    "calculator": CalculatorTool(),
    "web_search": WebSearchTool(),
    "file_read": FileReadTool(),
}


class ToolRunRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


def create_app() -> FastAPI:
    app = FastAPI(title="Grok Tool Server", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/tools/run")
    async def run_tool(req: ToolRunRequest) -> Dict[str, str]:
        tool: Tool | None = _tool_instances.get(req.tool)
        if not tool:
            return {"error": f"Unknown tool '{req.tool}'. Available: {list(_tool_instances)}"}
        try:
            result: str = await tool.run(**req.args)
            return {"result": str(result)}
        except TypeError as exc:
            return {"error": f"Invalid arguments for tool '{req.tool}': {exc}"}
        except Exception as exc:
            return {"error": f"Tool '{req.tool}' failed: {exc}"}

    @app.get("/tools/list")
    async def list_tools() -> List[Dict[str, str | Dict[str, str]]]:
        return [t.to_dict() for t in ALL_TOOLS.values()]

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "tools": list(_tool_instances)}

    return app


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Grok Bridge Tool Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=19997)
    parser.add_argument(
        "--allowed-paths",
        nargs="*",
        default=[],
        help="Extra directories to allow file_read access to (project root is always allowed)",
    )
    args = parser.parse_args()

    allowed: List[str] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    allowed.extend(args.allowed_paths)
    set_allowed_dirs(allowed)

    app: FastAPI = create_app()
    print(f"Tool Server running on {args.host}:{args.port}", flush=True)
    print(f"  POST /tools/run  — execute a tool", flush=True)
    print(f"  GET  /tools/list — list available tools", flush=True)
    print(f"  Allowed paths for file_read: {allowed}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
