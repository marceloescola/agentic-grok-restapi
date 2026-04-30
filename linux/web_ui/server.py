from __future__ import annotations

import html as html_mod
import json
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .client import BridgeClient

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))


def nl2br(text: Optional[str]) -> Markup:
    if not text:
        return Markup("")
    return Markup(html_mod.escape(str(text)).replace("\n", "<br>"))


def escape_sse(data: str) -> str:
    return json.dumps(data, ensure_ascii=False)


def format_chat_html(content: str) -> str:
    escaped = html_mod.escape(content).replace("\n", "<br>")
    return (
        '<div class="message bot">'
        '<div class="sender">Grok:</div>'
        f'<div class="text">{escaped}</div>'
        "</div>"
    )


templates.env.filters["nl2br"] = nl2br

stream_params: Dict[str, dict] = {}


def create_app(bridge_url: str = "http://localhost:19998") -> FastAPI:
    client = BridgeClient(base_url=bridge_url)

    app = FastAPI(title="Grok Bridge Web UI")

    app.mount(
        "/static",
        StaticFiles(directory=str(HERE / "static")),
        name="static",
    )

    # --- Page routes ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"request": request})

    @app.get("/agent", response_class=HTMLResponse)
    async def agent_page(request: Request):
        return templates.TemplateResponse(request, "agent.html", {"request": request})

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(request, "settings.html", {"request": request})

    # --- API partial routes ---

    @app.post("/api/chat", response_class=HTMLResponse)
    async def api_chat(request: Request):
        form = await request.form()
        prompt: str = form.get("prompt", "").strip()
        if not prompt:
            return '<div class="error">Prompt is required</div>'

        streaming: bool = form.get("streaming", "false") == "true"
        timeout: int = int(form.get("timeout", 120))
        files_str: str = form.get("files", "")
        files: Optional[list[str]] = (
            [f.strip() for f in files_str.split(",") if f.strip()]
            if files_str.strip()
            else None
        )

        if streaming:
            sid: str = uuid.uuid4().hex
            stream_params[sid] = {
                "prompt": prompt,
                "mode": "chat",
                "timeout": timeout,
                "files": files,
            }
            return templates.TemplateResponse(
                request, "partials/chat_stream.html",
                {"request": request, "stream_id": sid, "prompt": prompt},
            )

        try:
            result: Dict[str, Any] = await client.chat(
                prompt=prompt, timeout=timeout, files=files
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "response": None}

        return templates.TemplateResponse(
            request, "partials/chat_response.html",
            {"request": request, "result": result, "prompt": prompt},
        )

    @app.post("/api/agent", response_class=HTMLResponse)
    async def api_agent(request: Request):
        form = await request.form()
        prompt: str = form.get("prompt", "").strip()
        if not prompt:
            return '<div class="error">Prompt is required</div>'

        streaming: bool = form.get("streaming", "false") == "true"
        timeout: int = int(form.get("timeout", 120))
        max_steps: int = int(form.get("max_steps", 10))
        tools_raw: str = form.get("tools", "")
        tools: Optional[list[str]] = (
            [t.strip() for t in tools_raw.split(",") if t.strip()]
            if tools_raw.strip()
            else None
        )
        file_path: str = form.get("file_path", "").strip()
        files: Optional[list[str]] = [file_path] if file_path else None

        if streaming:
            sid: str = uuid.uuid4().hex
            stream_params[sid] = {
                "prompt": prompt,
                "mode": "agent",
                "timeout": timeout,
                "tools": tools,
                "files": files,
            }
            return templates.TemplateResponse(
                request, "partials/agent_stream.html",
                {
                    "request": request,
                    "stream_id": sid,
                    "prompt": prompt,
                    "tools": tools or [],
                },
            )

        try:
            result = await client.agent(
                prompt=prompt, timeout=timeout, tools=tools, max_steps=max_steps
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "response": None}

        return templates.TemplateResponse(
            request, "partials/agent_result.html",
            {
                "request": request,
                "result": result,
                "prompt": prompt,
            },
        )

    @app.post("/api/new", response_class=HTMLResponse)
    async def api_new():
        try:
            await client.new_conversation()
            return (
                '<div class="welcome" id="chat-welcome">'
                "--- New conversation started ---</div>"
            )
        except Exception as exc:
            return f'<div class="error">Failed: {html_mod.escape(str(exc))}</div>'

    @app.get("/api/health", response_class=HTMLResponse)
    async def api_health(request: Request):
        try:
            info = await client.health()
            return templates.TemplateResponse(
                request, "partials/health_panel.html",
                {"request": request, "info": info},
            )
        except Exception as exc:
            return f'<span class="error">Disconnected: {html_mod.escape(str(exc))}</span>'

    @app.get("/api/history", response_class=HTMLResponse)
    async def api_history(request: Request):
        try:
            result = await client.history()
            return templates.TemplateResponse(
                request, "partials/history_panel.html",
                {"request": request, "result": result},
            )
        except Exception as exc:
            return f'<div class="error">Failed: {html_mod.escape(str(exc))}</div>'

    # --- SSE streaming endpoint ---

    @app.get("/api/stream/{stream_id}")
    async def api_stream(stream_id: str):
        params: Optional[dict] = stream_params.pop(stream_id, None)
        if not params:
            return HTMLResponse("stream not found", status_code=404)

        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                async for event in client.stream_prompt(
                    prompt=params["prompt"],
                    mode=params.get("mode", "chat"),
                    files=params.get("files"),
                    tools=params.get("tools"),
                ):
                    t: str = event.get("type", "")

                    if t == "partial":
                        content: str = event.get("content", "")
                        yield f"event: message\ndata: {escape_sse(content)}\n\n"

                    elif t == "tool_call":
                        tool: str = event.get("tool", "?")
                        args: Any = event.get("arguments", {})
                        html = (
                            f'<div class="tool-call">'
                            f"Calling: <strong>{html_mod.escape(tool)}</strong>"
                            f" {html_mod.escape(str(args))}"
                            f"</div>"
                        )
                        yield f"event: tool_call\ndata: {escape_sse(html)}\n\n"

                    elif t == "tool_result":
                        raw: str = event.get("result", "")
                        preview: str = raw[:200]
                        if len(raw) > 200:
                            preview += "..."
                        html = (
                            '<div class="tool-result">'
                            f"Result: {html_mod.escape(preview)}"
                            f"</div>"
                        )
                        yield f"event: tool_result\ndata: {escape_sse(html)}\n\n"

                    elif t == "done":
                        content = event.get("content", "")
                        html = format_chat_html(content)
                        yield f"event: done\ndata: {escape_sse(html)}\n\n"
                        return

                    elif t == "message":
                        content = event.get("content", "")
                        html = format_chat_html(content)
                        yield f"event: done\ndata: {escape_sse(html)}\n\n"
                        return

                    elif t == "error":
                        err = event.get("content", "Unknown error")
                        err_html = (
                            f'<div class="error">{html_mod.escape(err)}</div>'
                        )
                        yield f"event: error\ndata: {escape_sse(err_html)}\n\n"
                        return

                    elif t == "status":
                        state: str = event.get("state", "")
                        if state in ("done", "max_steps"):
                            return

            except Exception as exc:
                yield (
                    "event: error\ndata: "
                    f'{escape_sse(f"<div class=error>{html_mod.escape(str(exc))}</div>")}'
                    "\n\n"
                )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app
