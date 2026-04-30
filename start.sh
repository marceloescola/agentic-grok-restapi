#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
    echo "Shutting down..."
    kill $TOOL_PID $BRIDGE_PID 2>/dev/null
    wait $TOOL_PID $BRIDGE_PID 2>/dev/null
}
trap cleanup EXIT INT TERM

TOOL_PORT="${TOOL_PORT:-19997}"
BRIDGE_PORT="${BRIDGE_PORT:-19998}"
PROJECT_URL="${GROK_PROJECT_URL:-https://grok.com/project/9efb0fb6-91f8-4c05-b599-7358db44c7bf}"

export TOOL_SERVER_URL="http://localhost:${TOOL_PORT}"

echo "Starting tool server on :${TOOL_PORT}..."
uv run python tools/tool_server.py --port "$TOOL_PORT" &
TOOL_PID=$!

echo "Starting bridge on :${BRIDGE_PORT}..."
uv run python linux/grok_bridge_l.py --port "$BRIDGE_PORT" --project-url "$PROJECT_URL" "$@" &
BRIDGE_PID=$!

wait
