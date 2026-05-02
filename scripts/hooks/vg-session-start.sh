#!/usr/bin/env bash
# SessionStart hook for VGFlow harness.
# Matchers: startup|resume|clear|compact (per Claude Code hooks docs)
# Injects vg-meta-skill.md content + open diagnostics from events.db.

set -euo pipefail

# Default PLUGIN_ROOT to the directory containing this script — vg-meta-skill.md
# sits next to it. Avoids relative-path failure when hook fires from arbitrary CWD.
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
META_SKILL_PATH="${PLUGIN_ROOT}/vg-meta-skill.md"
EVENTS_DB="${VG_EVENTS_DB:-.vg/events.db}"
ACTIVE_RUN_PATH=".vg/active-runs/${CLAUDE_HOOK_SESSION_ID:-default}.json"

if [ ! -f "$META_SKILL_PATH" ]; then
  echo "ERROR: meta-skill missing at $META_SKILL_PATH" >&2
  exit 1
fi

base_text="$(cat "$META_SKILL_PATH")"

diagnostics=""
if [[ "${CLAUDE_HOOK_EVENT:-}" =~ ^(compact|resume)$ ]] && [ -f "$ACTIVE_RUN_PATH" ] && [ -f "$EVENTS_DB" ]; then
  run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$ACTIVE_RUN_PATH" 2>/dev/null || true)"
  if [ -n "$run_id" ]; then
    # Production schema uses payload_json; test fixtures use payload. Try both.
    fired="$(sqlite3 "$EVENTS_DB" "SELECT payload_json FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null \
            || sqlite3 "$EVENTS_DB" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null \
            || true)"
    if [ -n "$fired" ]; then
      diagnostics=$'\n\n## OPEN DIAGNOSTICS for current run '"${run_id}"$'\n'"${fired}"$'\nYou MUST close each diagnostic before continuing other work.\n'
    fi
  fi
fi

session_context=$'<EXTREMELY_IMPORTANT>\nYou have VGFlow harness loaded.\n\n'"${base_text}${diagnostics}"$'\n</EXTREMELY_IMPORTANT>'

escaped="$(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])' <<< "$session_context")"

printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$escaped"
