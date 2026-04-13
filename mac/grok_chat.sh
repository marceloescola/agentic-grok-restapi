#!/bin/bash
# grok_chat.sh v3 — Turn SuperGrok into a CLI tool
# Sends a prompt to grok.com via Safari automation, waits for response
#
# Usage: bash grok_chat.sh "your question" [--timeout 60] [--screenshot]
#
# How it works:
#   1. Navigate Safari to grok.com (new conversation)
#   2. Focus textarea via JS
#   3. Paste via pbcopy + CGEvent Cmd+V (bypasses Accessibility restrictions)
#   4. Submit via CGEvent Enter
#   5. Poll DOM until response stabilizes
#   6. Extract and output Grok's reply
#
# Requirements:
#   - macOS with Safari logged into grok.com (SuperGrok for best results)
#   - If running remotely: MAC_SSH="ssh user@host" bash grok_chat.sh "question"
#
# v1: Peekaboo UI automation — slow, fragile
# v2: Safari JS + System Events — faster, but needs Accessibility permission
# v3: Safari JS + CGEvent (Swift) — no Accessibility permission needed

set -euo pipefail

PROMPT="${1:?Usage: grok_chat.sh 'question' [--timeout 60] [--screenshot]}"
TIMEOUT=60
SCREENSHOT=false
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --screenshot) SCREENSHOT=true; shift ;;
    *) shift ;;
  esac
done

MAC_SSH="${MAC_SSH:-}"

run_cmd() {
  if [[ -n "$MAC_SSH" ]]; then
    $MAC_SSH "$*"
  else
    eval "$*"
  fi
}

run_js() {
  local js="$1"
  run_cmd "osascript -e 'tell application \"Safari\" to do JavaScript \"${js}\" in current tab of window 1'" 2>/dev/null
}

# Ensure the CGEvent helper exists on the Mac
ensure_swift_helper() {
  run_cmd "cat > /tmp/grok_keys.swift" << 'SWIFT'
import Foundation
import CoreGraphics

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("Usage: grok_keys paste|enter|paste_enter")
    exit(1)
}

func pressKey(_ keyCode: CGKeyCode, flags: CGEventFlags = [], delayUs: UInt32 = 30000) {
    let src = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: true)!
    let up = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: false)!
    if !flags.isEmpty { down.flags = flags; up.flags = flags }
    down.post(tap: .cghidEventTap)
    usleep(delayUs)
    up.post(tap: .cghidEventTap)
    usleep(delayUs)
}

switch args[1] {
case "paste":
    pressKey(9, flags: .maskCommand)  // Cmd+V
case "enter":
    pressKey(36)  // Enter/Return
case "paste_enter":
    pressKey(9, flags: .maskCommand)
    usleep(500000)  // 0.5s between paste and enter
    pressKey(36)
default:
    print("Unknown command: \(args[1])")
    exit(1)
}
SWIFT
  run_cmd "swift -O /tmp/grok_keys.swift paste 2>/dev/null && echo 'helper ok'" >/dev/null 2>&1 || true
}

# --- Step 0: Prepare Swift helper ---
ensure_swift_helper

# --- Step 1: New conversation ---
echo "[grok] New conversation..." >&2
run_cmd "osascript -e 'tell application \"Safari\" to set URL of current tab of window 1 to \"https://grok.com/\"'" 2>/dev/null
sleep 5

# --- Step 2: Activate Safari + focus textarea ---
echo "[grok] Sending (${#PROMPT} chars)..." >&2
run_cmd "osascript -e 'tell application \"Safari\" to activate'" 2>/dev/null
sleep 1
run_js "var ta=document.querySelector('textarea');if(ta){ta.focus();ta.click();}"
sleep 0.5

# --- Step 3: Paste + Submit via CGEvent ---
printf '%s' "$PROMPT" | run_cmd pbcopy
sleep 0.3

run_cmd "swift /tmp/grok_keys.swift paste_enter" 2>/dev/null

# --- Step 4: Poll for response ---
echo "[grok] Waiting (max ${TIMEOUT}s)..." >&2
PREV=""
STABLE=0
HAS_REPLY=false
INITIAL_LEN=0
sleep 8

# Get baseline page length (before Grok replies)
INITIAL_LEN=$(run_js "document.body.innerText.length" 2>/dev/null | tr -d '.' | grep -oE '[0-9]+' || echo "500")

for ((i=1; i<=TIMEOUT; i++)); do
  sleep 2
  CURRENT=$(run_js "document.body.innerText.substring(0,8000)" 2>/dev/null || echo "")
  CURRENT_LEN=${#CURRENT}

  # Wait until page content grows significantly (Grok started replying)
  if [[ "$HAS_REPLY" == "false" ]]; then
    if [[ $CURRENT_LEN -gt $((INITIAL_LEN + 100)) ]]; then
      HAS_REPLY=true
      echo "[grok] Response detected, waiting for completion..." >&2
    fi
    PREV="$CURRENT"
    ((i % 10 == 0)) && echo "[grok] Waiting for response... ${i}x2s" >&2
    continue
  fi

  # Once reply detected, check for stability
  if [[ -n "$CURRENT" && "$CURRENT" == "$PREV" ]]; then
    STABLE=$((STABLE + 1))
    [[ $STABLE -ge 3 ]] && { echo "[grok] Done (${i}x2s)" >&2; break; }
  else
    STABLE=0
  fi
  PREV="$CURRENT"
  ((i % 5 == 0)) && echo "[grok] Polling... ${i}x2s (stable=$STABLE)" >&2
done

[[ "$HAS_REPLY" == "false" ]] && { echo "[grok] Error: no response detected (submit may have failed)" >&2; exit 1; }
[[ $STABLE -lt 3 ]] && echo "[grok] Warning: timeout, response may be incomplete" >&2

# --- Step 5: Extract reply ---
FULL=$(run_js "document.body.innerText" 2>/dev/null || echo "")

PROMPT_PREFIX=$(echo "$PROMPT" | head -c 40)
echo "$FULL" | awk -v prefix="$PROMPT_PREFIX" '
  BEGIN { found=0 }
  !found && index($0, prefix) > 0 { found=1; next }
  found { print }
' | grep -vE "^(Think Harder|Auto|Upgrade to|Toggle|Share|Like|Dislike|Are you satisfied|Get notified|Expert|Fast|Enable|Quick Answer|Explain|Compare|Make it|Executing code|Submit|Attach|Model select|Start dictation|Enter voice mode|Private|Imagine)$" \
  | grep -vE "^[0-9]+(\.[0-9]+)?s$" \
  | grep -vE "^[0-9]+ sources$" \
  | sed '/^$/d' \
  | head -100

# --- Step 6: Optional screenshot ---
if $SCREENSHOT; then
  TS=$(date +%s)
  SHOT="/tmp/grok_${TS}.jpg"
  if [[ -n "$MAC_SSH" ]]; then
    $MAC_SSH "/usr/sbin/screencapture -x -t jpg /tmp/grok_shot.jpg && cat /tmp/grok_shot.jpg" > "$SHOT" 2>/dev/null
  else
    /usr/sbin/screencapture -x -t jpg "$SHOT" 2>/dev/null
  fi
  echo "[grok] Screenshot: $SHOT" >&2
fi
