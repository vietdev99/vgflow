#!/usr/bin/env bash
# UserPromptSubmit hook — closes Codex bypass #1.
# Detects /vg:<cmd> <args> in prompt text. Creates active-run state file
# BEFORE the model runs so Stop hook later has run context to validate.

set -euo pipefail

input="$(cat)"
prompt="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("prompt",""))' 2>/dev/null || true)"

# Match /vg:<cmd> [<args>...]
if [[ ! "$prompt" =~ ^/vg:([a-z][a-z0-9_-]*)([[:space:]]+(.*))?$ ]]; then
  exit 0
fi

cmd="vg:${BASH_REMATCH[1]}"
args="${BASH_REMATCH[3]:-}"
phase="$(printf '%s' "$args" | awk '{print $1}')"
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"

mkdir -p ".vg/active-runs"

# Cross-run guard:
# - Different phase → independent run, overwrite silently (e.g., blueprint 4.1 active, user starts build 2).
# - Same phase + different command → intra-phase pipeline conflict, block (e.g., blueprint 4.1 active, user starts build 4.1 before blueprint completes).
# - Same phase + same command → idempotent restart, overwrite silently.
# Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
if [ -f "$run_file" ]; then
  existing_cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" 2>/dev/null || true)"
  existing_phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("phase",""))' "$run_file" 2>/dev/null || true)"
  if [ -n "$existing_cmd" ] && [ "$existing_cmd" != "$cmd" ] && [ "$existing_phase" = "$phase" ]; then
    printf "\033[38;5;208mvg-cross-run: active %s on phase %s; finish or abort before invoking %s on same phase\033[0m\n" \
      "$existing_cmd" "$existing_phase" "$cmd" >&2
    exit 2
  fi
fi

run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$run_file" <<JSON
{
  "run_id": "$run_id",
  "command": "$cmd",
  "phase": "$phase",
  "session_id": "$session_id",
  "started_at": "$ts"
}
JSON
