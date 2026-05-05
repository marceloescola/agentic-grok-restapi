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
ALLOW_HOME=""
EXTENSION_ONLY=""

# Parse custom flags before forwarding "$@"
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --allow-home) ALLOW_HOME="1" ;;
        --extension-only) EXTENSION_ONLY="1" ;;
        *) ARGS+=("$arg") ;;
    esac
done
set -- "${ARGS[@]}"

export TOOL_SERVER_URL="http://localhost:${TOOL_PORT}"

TOOL_ARGS="--port $TOOL_PORT"
if [ -n "$ALLOW_HOME" ]; then
    TOOL_ARGS="$TOOL_ARGS --allowed-paths ~"
fi

echo "Starting tool server on :${TOOL_PORT}..."
uv run python tools/tool_server.py $TOOL_ARGS &
TOOL_PID=$!

BRIDGE_ARGS="--port $BRIDGE_PORT"
if [ -z "$EXTENSION_ONLY" ]; then
    BRIDGE_ARGS="$BRIDGE_ARGS --project-url $PROJECT_URL"
fi
if [ -n "$EXTENSION_ONLY" ]; then
    BRIDGE_ARGS="$BRIDGE_ARGS --extension-only"
fi

echo "Starting bridge on :${BRIDGE_PORT}${EXTENSION_ONLY:+" (extension-only)"}..."
uv run python linux/grok_bridge_l.py $BRIDGE_ARGS "$@" &
BRIDGE_PID=$!

wait
