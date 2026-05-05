from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from websockets.asyncio.client import connect


class GrokClient:
    def __init__(self, base_url: str = "http://localhost:19998") -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))

    @property
    def base_url(self) -> str:
        return self._base_url

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def chat(
        self,
        prompt: str,
        timeout: int = 120,
        files: Optional[List[str]] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt, "timeout": timeout}
        if files:
            body["files"] = files
        resp = await self._http.post(self._url("/chat"), json=body)
        resp.raise_for_status()
        return resp.json()

    async def agent(
        self,
        prompt: str,
        timeout: int = 120,
        tools: Optional[List[str]] = None,
        max_steps: int = 10,
        attach_files: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": prompt,
            "timeout": timeout,
            "max_steps": max_steps,
            "attach_files": attach_files,
        }
        if tools:
            body["tools"] = tools
        resp = await self._http.post(self._url("/agent"), json=body)
        resp.raise_for_status()
        return resp.json()

    async def new_conversation(self) -> dict[str, Any]:
        resp = await self._http.post(self._url("/new"), json={})
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> dict[str, Any]:
        resp = await self._http.get(self._url("/health"))
        resp.raise_for_status()
        return resp.json()

    async def history(self) -> dict[str, Any]:
        resp = await self._http.get(self._url("/history"))
        resp.raise_for_status()
        return resp.json()

    async def list_sessions(self) -> list[dict[str, Any]]:
        resp = await self._http.get(self._url("/sessions"))
        resp.raise_for_status()
        return resp.json()

    async def load_session(self, session_id: int) -> dict[str, Any]:
        resp = await self._http.post(
            self._url("/sessions/load"), json={"session_id": session_id}
        )
        if not resp.is_success:
            detail: str = str(resp.text)
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        return resp.json()

    async def delete_session(self, session_id: int) -> dict[str, Any]:
        resp = await self._http.delete(self._url(f"/sessions/{session_id}"))
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()


class GrokWSClient:
    def __init__(self, base_url: str = "http://localhost:19998") -> None:
        rest_url: str = base_url.rstrip("/")
        self._ws_url: str = rest_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        ) + "/ws"

    async def run_prompt(
        self,
        prompt: str,
        mode: str = "chat",
        files: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        attach_files: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        msg: Dict[str, Any] = {
            "type": "prompt",
            "content": prompt,
            "mode": mode,
        }
        if files:
            msg["files"] = files
        if tools:
            msg["tools"] = tools
        if mode == "agent":
            msg["attach_files"] = attach_files
        try:
            async with connect(self._ws_url) as ws:
                await ws.send(json.dumps(msg))
                async for raw in ws:
                    data: str = raw if isinstance(raw, str) else raw.decode()
                    event: Dict[str, Any] = json.loads(data)
                    yield event
                    t: str = event.get("type", "")
                    if t in ("done", "error", "timeout", "status"):
                        break
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
