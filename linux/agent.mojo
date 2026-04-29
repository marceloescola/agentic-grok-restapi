from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

# Allow importing the tools package from the project root (parent of linux/)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import httpx

from tools.registry import get_tool_defs, ALL_TOOLS


def _parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    idx = 0
    while True:
        start = text.find("TOOL_CALL", idx)
        if start == -1:
            break
        brace = text.find("{", start)
        if brace == -1:
            idx = start + 9
            continue
        depth = 0
        json_end = -1
        for i in range(brace, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break
        if json_end == -1:
            idx = brace + 1
            continue
        try:
            obj = json.loads(text[brace:json_end])
            if isinstance(obj, dict) and ("name" in obj or "tool" in obj):
                if "tool" in obj and "name" not in obj:
                    obj["name"] = obj.pop("tool")
                if "args" in obj and "arguments" not in obj:
                    obj["arguments"] = obj.pop("args")
                results.append(obj)
        except json.JSONDecodeError:
            pass
        idx = json_end
    return results


def extract_first_tool_call(text: str) -> Optional[Dict[str, Any]]:
    calls = _parse_tool_calls(text)
    for c in calls:
        if isinstance(c, dict) and "name" in c:
            return c
    return None


def build_tool_result_message(tool_name: str, result: str) -> str:
    return f"Here's the tool result ({tool_name}): {result}"


class GrokAgent:
    def __init__(self, engine, tool_server_url: str = "http://localhost:19997") -> None:
        self._engine = engine
        self._tool_server_url = tool_server_url.rstrip("/")

    async def _call_tool(self, tool_name: str, args: dict) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            try:
                response = await client.post(
                    f"{self._tool_server_url}/tools/run",
                    json={"tool": tool_name, "args": args},
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    return f"Error: {data['error']}"
                return data.get("result", str(data))
            except httpx.ConnectError:
                return f"Error: Cannot reach tool server at {self._tool_server_url}. Is it running?"
            except httpx.TimeoutException:
                return f"Error: Tool server timed out for tool '{tool_name}'"
            except httpx.HTTPStatusError as exc:
                return f"Error: Tool server returned {exc.response.status_code}"
            except Exception as exc:
                return f"Error calling tool '{tool_name}': {exc}"

    async def run(
        self,
        user_prompt: str,
        timeout: int = 120,
        tools: Optional[Sequence[str]] = None,
        max_steps: int = 10,
    ) -> Dict[str, Any]:
        tool_defs = get_tool_defs(tools if tools else None)

        if not tool_defs:
            return await self._engine.chat(prompt=user_prompt, timeout=timeout)

        # Send the user question directly; instructions come from project
        result = await self._engine.send_and_wait(prompt=user_prompt, timeout=timeout)

        steps: List[Dict[str, Any]] = []
        for step in range(max_steps):
            response_text = result.get("response", "")

            tool_call = extract_first_tool_call(response_text)

            if tool_call is None:
                result["step_count"] = step + 1
                result["steps"] = steps
                return result

            tool_name = tool_call.get("name", "")
            args = tool_call.get("arguments", {})

            if not tool_name:
                err_msg = (
                    "That format didn't parse. Use TOOL_CALL with a name field, "
                    f"like: TOOL_CALL {{\"name\":\"calculator\",\"arguments\":{{\"expression\":\"...\"}}}}"
                )
                result = await self._engine.send_and_wait(prompt=err_msg, timeout=timeout)
                continue

            if tool_name not in ALL_TOOLS:
                err_msg = (
                    f"Unknown tool '{tool_name}'. "
                    f"Available: {', '.join(ALL_TOOLS)}. Try again?"
                )
                result = await self._engine.send_and_wait(prompt=err_msg, timeout=timeout)
                continue

            print(
                f"[agent] step {step + 1}: calling tool '{tool_name}' "
                f"with args {json.dumps(args)}",
                flush=True,
            )
            tool_result = await self._call_tool(tool_name, args)
            print(
                f"[agent] step {step + 1}: tool result ({len(tool_result)} chars)",
                flush=True,
            )

            steps.append({
                "step": step + 1,
                "tool": tool_name,
                "args": args,
                "result": tool_result,
            })

            result = await self._engine.send_and_wait(
                prompt=build_tool_result_message(tool_name, tool_result),
                timeout=timeout,
            )

        result["step_count"] = max_steps
        result["steps"] = steps
        result["status"] = "max_steps"
        return result
