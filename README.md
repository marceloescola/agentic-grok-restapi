# multi-grok-bridge

Turn **SuperGrok** into a REST API + WebSocket service + TUI + browser extension. No API key needed.
Uses Playwright + Chromium to automate grok.com in the browser.

> Originally inspired by [grok-bridge v3.0](https://github.com/anthropics/grok-bridge) — this is a complete from-scratch rewrite with a different architecture (Python/FastAPI, Playwright Chromium, Linux, tool-calling agent, WebSocket streaming, TUI, browser extension).

## Quick Start

```bash
# Install dependencies
uv sync
playwright install chromium

# Start everything (tool server + bridge)
./start.sh

# Or start the bridge directly
uv run linux/grok_bridge_l.py --port 19998
```

On first run, a persistent Chromium profile is created. Log into grok.com once, subsequent requests reuse the session.

### Send a message

```bash
curl -X POST http://localhost:19998/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the mass of the sun?", "timeout": 60}'

# Start a new conversation
curl -X POST http://localhost:19998/new

# Health check
curl http://localhost:19998/health
```

### File attachments

```bash
curl -X POST http://localhost:19998/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize this file", "files": ["/path/to/file.txt"]}'
```

## Agent Mode (Tool Calling)

Grok can call tools during a conversation. Tools are executed by a separate tool server:

```bash
# start.sh handles both; or manually:
uv run python tools/tool_server.py --port 19997
uv run linux/grok_bridge_l.py --port 19998 --tool-server-url http://localhost:19997

# Agent prompt — Grok can invoke calculator, web_search, file_read
curl -X POST http://localhost:19998/agent \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Search the web for AI news and calculate 2+2", "tools": ["web_search", "calculator"]}'
```

Available tools: `calculator`, `web_search`, `file_read`.

### File attachment for tool results

When `attach_files: true` (default), tool results are uploaded to Grok as files instead of pasted as text —
saves tokens for large results (e.g. file_read):

```bash
# File-based (default) — result attached as file, short message sent
curl -X POST http://localhost:19998/agent \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Read README.md and summarize", "attach_files": true}'

# Text-based (legacy) — full result pasted as text
curl -X POST http://localhost:19998/agent-legacy \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Read README.md and summarize"}'
```

To disable file attachment, set `"attach_files": false` in the agent request body.

## Browser Extension

A Firefox/Chrome extension that intercepts `TOOL_CALL{...}` JSON from grok.com and executes
tools automatically — no bridge Playwright needed.

### Install (Firefox)

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `browser-extension/manifest.json`

### Usage

1. Start the tool server: `./start.sh --extension-only` (no Playwright browser — saves ~300MB RAM)
2. Browse to grok.com and log in
3. Type a prompt like *"Read README.md and summarize"*
4. The extension detects `TOOL_CALL`, executes the tool, uploads the result as a file attachment

### Popup controls

| Control | Action |
|---------|--------|
| **Active/Paused** toggle | Enable/disable tool interception |
| **Scan now** | Force-scan the page for TOOL_CALL |
| **Reset** | Clear processed calls (re-process) |
| **Attach files** checkbox | Toggle file vs text result injection |

File upload uses the hidden `<input type="file">` on grok.com via `DataTransfer` — works like a real user pasting a file.

### Files

- `background.js` — proxies tool calls to `http://localhost:19997/tools/run`
- `content.js` — observes DOM, parses `TOOL_CALL`, injects results
- `popup.html` / `popup.js` — toggle UI, debug log, attach-files setting

## start.sh flags

```bash
# Full stack (tool server + bridge + Playwright browser)
./start.sh

# Extension-only — no Playwright browser, saves ~300MB RAM
./start.sh --extension-only

# Allow file_read access to home directory
./start.sh --allow-home

# Combine flags
./start.sh --extension-only --allow-home
```

Custom flags are consumed by `start.sh` and not forwarded to the bridge. All other arguments
(e.g. `--headless`, `--port`) are forwarded to the bridge.

## WebSocket Streaming

For real-time streaming of Grok responses (partial output, tool calls, intermediate results):

```python
import json
from websockets.asyncio.client import connect

async def stream():
    async with connect("ws://localhost:19998/ws") as ws:
        await ws.send(json.dumps({"type": "prompt", "content": "Explain quantum computing", "mode": "chat"}))
        async for msg in ws:
            event = json.loads(msg)
            print(event["type"], event.get("content", ""))
            if event["type"] in ("done", "error", "timeout", "status"):
                break
```

Event types: `partial` (streaming text), `done` (final), `tool_call`, `tool_result`, `message`, `status`.

## TUI (Textual Terminal UI)

A full terminal user interface with chat, agent mode, settings, and file picker:

```bash
uv run -m tui
```

- **Main screen**: chat with Grok, file attachments, history
- **Agent screen**: toggle tool buttons, file browser for `file_read`, streaming agent output
- **Settings**: server URL, timeouts, WebSocket toggle
- **Ctrl+Shift+Y** or **Menu button**: open menu

Toggle WebSocket mode in Settings for real-time response streaming in the chat.

## Web UI (Experimental)

A Jinja2-based web interface for chatting with Grok (port 19999):

```bash
uv run -m linux.web_ui --port 19999 --bridge-url http://localhost:19998
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send prompt, wait for response |
| POST | `/agent` | Agent loop with tool calling (file attachment by default) |
| POST | `/agent-legacy` | Agent loop with text-only result injection (deprecated) |
| POST | `/new` | Start new conversation |
| GET | `/health` | Bridge health + Grok connection status |
| GET | `/history` | Current page conversation text |
| GET | `/sessions` | List saved sessions |
| POST | `/sessions/load` | Load a saved session by ID |
| DELETE | `/sessions/{id}` | Delete a saved session |
| GET | `/debug/scrape` | Debug: scrape current page messages |
| GET | `/debug/inspect-dom` | Debug: inspect DOM structure |
| GET | `/debug/input` | Debug: test input/send selectors |
| GET | `/debug/buttons` | Debug: list all visible buttons |
| WS | `/ws` | WebSocket streaming (chat + agent) |

### Agent request fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | string | required | The user message |
| `timeout` | int | 120 | Max wait time (5-900s) |
| `tools` | string[] | all | Tool names to enable |
| `max_steps` | int | 10 | Max tool call iterations (1-20) |
| `attach_files` | bool | true | Upload tool results as files vs text |

## Architecture

```
┌──────────────────┐     POST /chat        ┌─────────────────────────────┐
│  HTTP Client     │     POST /agent       │  Bridge (FastAPI)           │
│  (curl / code)   │ ─────────────────────→│                             │
│                  │     WS /ws            │  grok_bridge_l.py           │
│  WebSocket       │ ◄═══════════════════  │  grok_engine_l.py           │
│  Client          │    streaming events   │  ↓ Playwright + Chromium    │
└──────────────────┘                       │  ↓ grok.com                 │
                                           │                             │
┌──────────────────┐                       │  Agent loop:                │
│  TUI (Textual)   │ ── REST / WS ───────→│  send → TOOL_CALL → execute │
│  -tui/           │                       │  → attach file → repeat    │
└──────────────────┘                       └──────┬──────────────────────┘
                                                  │
┌──────────────────┐                              │
│  Browser Ext.    │ ── DOM observes ────────────→│  grok.com tab
│  content.js      │    TOOL_CALL{...}            │
│  background.js   │ ← injects result ────────────│
└────────┬─────────┘                              │
         │ POST /tools/run                        │
         ▼                                        │
┌──────────────────────┐                          │
│  Tool Server         │                          │
│  tools/tool_server.py│                          │
│  calculator          │                          │
│  web_search          │                          │
│  file_read           │                          │
└──────────────────────┘                          │
```

### Extension-only mode

When running with `--extension-only`, the bridge starts without Playwright (no browser).
Only the tool server is available — the bridge returns `"browser not available"` for
any endpoint that needs the browser (`/chat`, `/agent`, `/ws`, etc.).
Use this when you only need the browser extension.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROK_HOST` | 0.0.0.0 | Bridge bind address |
| `GROK_PORT` | 19998 | Bridge bind port |
| `TOOL_PORT` | 19997 | Tool server port (used by start.sh) |
| `BRIDGE_PORT` | 19998 | Bridge port (used by start.sh) |
| `GROK_PROFILE_DIR` | ~/.grok-bridge/firefox-profile | Chromium profile path |
| `GROK_HEADLESS` | 0 | Run browser headless (1=yes) |
| `GROK_PAGE_TIMEOUT` | 60 | Page/script timeout (seconds) |
| `TOOL_SERVER_URL` | http://localhost:19997 | Tool server for /agent |
| `GROK_PROJECT_URL` | — | Grok project URL for persistent instructions |
| `GROK_USER_DATA_DIR` | — | Existing Chromium user data dir |
| `GROK_BROWSER_PATH` | — | Path to Chromium binary |
| `GROK_PROFILE_NAME` | Default | Profile name within user data dir |

## License

MIT
