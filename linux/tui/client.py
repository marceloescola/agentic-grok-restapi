from __future__ import annotations

from typing import Any, List, Optional

import httpx


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
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": prompt,
            "timeout": timeout,
            "max_steps": max_steps,
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

    async def close(self) -> None:
        await self._http.aclose()
