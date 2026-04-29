# multi-grok-bridge — File Map

Grok reads this file to discover what's in the project. Use `file_read` to inspect any file listed below.

```
multi-grok-bridge/
├── .python-version         Python 3.14
├── codebaseMap.md          ← this file — project file map
├── LICENSE                 MIT license
├── main.py                 Placeholder entrypoint
├── pyproject.toml          Deps: duckduckgo-search, fastapi, httpx, playwright, uvicorn
├── README.md               Project docs
├── SKILL.md                macOS Safari docs (Chinese)
├── uv.lock                 Dependency lockfile

├── linux/
│   ├── agent.py            ReAct loop — extracts TOOL_CALL, calls tool server
│   ├── grok_bridge_l.py    FastAPI bridge (:19998) — POST /chat, /agent, /new
│   ├── grok_chat.sh        CLI chat (Swift CGEvent)
│   ├── grok_engine_l.py    Playwright engine — stealth JS, DOM polling, send/wait
│   └── requirements.txt    fastapi, uvicorn, playwright

├── mac/
│   ├── grok_bridge_m.py    macOS HTTP bridge (Safari + AppleScript)
│   └── grok_chat.sh        macOS CLI chat

├── windows/
│   ├── grok_bridge_w.py    Placeholder
│   └── grok_chat.sh        Placeholder

├── tools/
│   ├── __init__.py         Package init
│   ├── base.py             ToolDef dataclass + Tool protocol
│   ├── calculator.py       Safe math eval (AST whitelist, pi/e, ^ → **)
│   ├── file_read.py        File reader — sandboxed to project dir
│   ├── registry.py         ALL_TOOLS = {calculator, web_search, file_read}
│   ├── tool_server.py      Tool server (:19997) — POST /tools/run
│   └── web_search.py       DuckDuckGo search (5 results)

├── plans/
│   └── toolsImpl.md        Original tool-calling design doc
```
