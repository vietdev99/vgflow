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
# - Same phase + same command → idempotent restart, overwrite silently.
# - Same phase + different command → intra-phase pipeline conflict, USED to hard-block.
#   Hotfix 2026-05-04 (loop-bug trace): two escape clauses added so dead runs
#   don't lock the user out indefinitely:
#     1. STALE — started_at older than STALE_MINUTES (mirrors orchestrator's
#        run-start auto-clear at 30min). Soft-warn + allow overwrite.
#     2. BLOCKED-UNHANDLED — events.db has run.blocked for the existing
#        run_id with NO subsequent run.aborted/run.completed/vg.block.handled.
#        That run is logically dead; the Stop hook returned exit 2 and the
#        active-runs file was never cleared (Stop only clears on PASS).
#        Soft-warn + allow overwrite.
#   Otherwise (fresh + alive + intra-phase conflict) → block as before.
# Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
STALE_MINUTES=30
if [ -f "$run_file" ]; then
  existing_cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" 2>/dev/null || true)"
  existing_phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("phase",""))' "$run_file" 2>/dev/null || true)"
  existing_run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("run_id",""))' "$run_file" 2>/dev/null || true)"
  existing_started="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("started_at",""))' "$run_file" 2>/dev/null || true)"

  is_dead=0
  death_reason=""

  # Check 1 — stale by age
  if [ -n "$existing_started" ]; then
    age_min="$(python3 -c "
import datetime
ts='$existing_started'
if ts.endswith('Z'): ts=ts[:-1]+'+00:00'
try:
    started=datetime.datetime.fromisoformat(ts)
    if started.tzinfo is None: started=started.replace(tzinfo=datetime.timezone.utc)
    print(int((datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()/60))
except Exception:
    print(0)
" 2>/dev/null || echo 0)"
    if [ "$age_min" -gt "$STALE_MINUTES" ]; then
      is_dead=1
      death_reason="stale ${age_min}min"
    fi
  fi

  # Check 2 — run.blocked unhandled in events.db
  if [ "$is_dead" -eq 0 ] && [ -n "$existing_run_id" ] && [ -f ".vg/events.db" ]; then
    block_state="$(sqlite3 .vg/events.db "SELECT (SELECT COUNT(*) FROM events WHERE run_id='$existing_run_id' AND event_type='run.blocked'),(SELECT COUNT(*) FROM events WHERE run_id='$existing_run_id' AND event_type IN ('run.aborted','run.completed','vg.block.handled'))" 2>/dev/null || echo "0|0")"
    blocked_count="$(printf '%s' "$block_state" | cut -d'|' -f1)"
    cleared_count="$(printf '%s' "$block_state" | cut -d'|' -f2)"
    if [ "${blocked_count:-0}" -gt 0 ] && [ "${cleared_count:-0}" -eq 0 ]; then
      is_dead=1
      death_reason="run.blocked unhandled"
    fi
  fi

  if [ "$is_dead" -eq 1 ]; then
    # Soft-warn (yellow); fall through to overwrite the dead run-file.
    printf "\033[33mvg-cross-run: previous %s on phase %s is dead (%s); continuing with %s\033[0m\n" \
      "$existing_cmd" "$existing_phase" "$death_reason" "$cmd" >&2
  elif [ -n "$existing_cmd" ] && [ "$existing_cmd" != "$cmd" ] && [ "$existing_phase" = "$phase" ]; then
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
