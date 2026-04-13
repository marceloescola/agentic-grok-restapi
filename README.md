# 🌉 grok-bridge v3.0

Turn **SuperGrok** into a REST API + CLI tool. No API key needed.

## Linux Status

Linux now has a dedicated REST bridge based on FastAPI with split automation engines:

- Selenium + Firefox (primary)
- Playwright + Firefox (fallback)

The Linux bridge keeps endpoint compatibility with mac (`/chat`, `/new`, `/health`, `/history`) and adds optional inline attachments and engine selection on `/chat`.

### Linux Setup

```bash
# 1) Python dependencies
pip install -r linux/requirements.txt

# 2) Playwright runtime (required for fallback engine)
playwright install firefox

# 3) Install geckodriver for Selenium (example on Debian/Ubuntu)
sudo apt-get install -y firefox-esr geckodriver

# 4) Start Linux bridge (headed mode by default)
python3 linux/grok_bridge_l.py --port 19998
```

On first run, a persistent profile is created under `~/.grok-bridge/firefox-profile`.
Log into `https://grok.com` once in that profile and subsequent requests reuse the session.

### Linux `/chat` Payload

```json
{
  "prompt": "Summarize this repo",
  "timeout": 120,
  "files": ["/absolute/path/to/file.txt"],
  "engine": "auto"
}
```

// Little note, selenium mightttt be broken, and its midnight, so I wont fix it rn. Just use playwright and call it a day ok?

`engine` can be `auto`, `selenium`, or `playwright`.
`auto` uses Selenium first and falls back to Playwright when needed.

## How it works

```
Your Terminal/Script → Safari JS injection → grok.com → Response extracted via DOM
```

Two modes:

### REST API (recommended)
```bash
# Start the server on your Mac
python3 scripts/grok_bridge.py --port 19998

# Query from anywhere
curl -X POST http://your-mac:19998/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is the mass of the sun?","timeout":60}'

# Health check
curl http://your-mac:19998/health

# Read current conversation
curl http://your-mac:19998/history
```

### CLI (legacy)
```bash
# Local
bash scripts/grok_chat.sh "Explain quantum tunneling"

# Remote via SSH
MAC_SSH="ssh user@your-mac" bash scripts/grok_chat.sh "Write a haiku" --timeout 90
```

## Requirements

- macOS with Safari
- Logged into [grok.com](https://grok.com) (free or SuperGrok)
- Safari > Settings > Advanced > Show features for web developers ✓
- Safari > Develop > Allow JavaScript from Apple Events ✓
- **No Accessibility permission needed** (v3 uses JS injection, not System Events)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send prompt, wait for response |
| POST | `/new` | Start new conversation |
| GET | `/health` | Health check (Safari URL, grok status) |
| GET | `/history` | Read current page conversation |

## Version History

| | v1 | v2 | v3 |
|---|---|---|---|
| Input | Peekaboo UI | pbcopy + Cmd+V | JS `execCommand('insertText')` |
| Submit | UI click | System Events Return | JS `button.click()` |
| Permissions | Peekaboo + Accessibility | Accessibility | **None** (pure JS injection) |
| Interface | CLI only | CLI only | **REST API** + CLI |
| Dependencies | Peekaboo (brew) | None | None (stdlib only) |
| Speed | ~30s | ~3s | ~3s |

## Architecture

```
┌──────────────┐                     ┌───────────────────────┐
│  HTTP Client │  POST /chat         │      macOS            │
│  (anywhere)  │ ──────────────────→ │                       │
└──────────────┘                     │  grok_bridge.py       │
                                     │  ↓ osascript          │
                                     │  Safari do JavaScript │
                                     │  ↓ execCommand        │
                                     │  grok.com textarea    │
                                     │  ↓ button.click()     │
                                     │  Grok responds        │
                                     │  ↓ DOM poll           │
                                     │  Response extracted   │
                                     └───────────────────────┘
```

## Key Insight (v3)

React controlled inputs ignore JavaScript `value` setter, synthetic `InputEvent`, and even `nativeInputValueSetter`.

What **doesn't** work from SSH:
- ❌ `osascript keystroke` — blocked by macOS Accessibility
- ❌ CGEvent (Swift) — HID events don't reach web content
- ❌ JS `InputEvent` / `nativeInputValueSetter` — React ignores synthetic events

What **does** work:
- ✅ `document.execCommand('insertText')` — triggers real input in the browser
- ✅ JS `button.click()` on Send button — no System Events needed

Zero permissions, zero dependencies, pure JavaScript injection via AppleScript.

## Credits

v3 architecture designed by Claude Opus 4.6 (via [Antigravity](https://antigravity.so)), System Events bypass by 小灵 🦞.

## License

MIT
