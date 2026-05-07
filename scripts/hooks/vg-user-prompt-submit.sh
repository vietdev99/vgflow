#!/usr/bin/env bash
# UserPromptSubmit hook — closes Codex bypass #1.
# Detects /vg:<cmd> <args> in prompt text. Creates active-run state file
# BEFORE the model runs so Stop hook later has run context to validate.

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"
prompt="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("prompt",""))' 2>/dev/null || true)"
session_id="$(vg_resolve_session_id)"
required_adapter="claude"
if [ "${VG_RUNTIME:-${VG_PROVIDER:-}}" = "codex" ]; then
  required_adapter="codex"
fi

# Match /vg:<cmd> [<args>...]
if [[ ! "$prompt" =~ ^/vg:([a-z][a-z0-9_-]*)([[:space:]]+(.*))?$ ]]; then
  # Bug L mid-flow follow-up reminder (sếp dogfood discovery 2026-05-04):
  # When user replies mid-flow (non-slash prompt) and an active VG run exists,
  # the AI may "lose" flow context — it stops treating itself as inside the
  # pipeline and skips TodoWrite/tasklist enforcement. Inject a system
  # reminder so AI re-acquires context. Pattern follows superpowers'
  # using-superpowers always-fires-on-conversation pattern, but
  # deterministically file-based (active-run JSON) instead of skill-driven.
  active_run_file=".vg/active-runs/${session_id}.json"
  if [ -f "$active_run_file" ]; then
    active_cmd="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("command","?"))' "$active_run_file" 2>/dev/null || echo "?")"
    active_phase="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("phase","?"))' "$active_run_file" 2>/dev/null || echo "?")"
    active_run_id="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("run_id",""))' "$active_run_file" 2>/dev/null || echo "")"
    tasklist_projected="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("yes" if d.get("tasklist_projected") else "no")' "$active_run_file" 2>/dev/null || echo "no")"
    adapter="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("tasklist_projected_adapter",""))' "$active_run_file" 2>/dev/null || echo "")"

    # Skip injection if run is dead (stale or unhandled-block) — same logic
    # as the slash-command branch below would handle on next /vg:<cmd>.
    is_alive=1
    if [ -n "$active_run_id" ] && [ -f ".vg/events.db" ]; then
      term_count="$(sqlite3 .vg/events.db "SELECT COUNT(*) FROM events WHERE run_id='$active_run_id' AND event_type IN ('run.completed','run.aborted')" 2>/dev/null || echo 0)"
      [ "${term_count:-0}" -gt 0 ] && is_alive=0
    fi

    if [ "$is_alive" -eq 1 ]; then
      # Build reminder per state. Goes to stderr — Claude Code surfaces
      # UserPromptSubmit stderr as a system-reminder block to the AI.
      printf "<vg-flow-context>\n" >&2
      printf "Active VG run detected: %s on phase %s (run_id %s).\n" \
        "$active_cmd" "$active_phase" "${active_run_id:-?}" >&2
      if [ "$tasklist_projected" = "no" ]; then
        printf "STATE: tasklist NOT yet projected.\n" >&2
        printf "BEFORE any tool call (Bash/etc), you MUST:\n" >&2
        printf "  1. Read .vg/runs/%s/tasklist-contract.json\n" "$active_run_id" >&2
        printf "  2. Call the TodoWrite tool with hierarchical 2-layer projection (group + ↳ sub-items)\n" >&2
        printf "  3. Run: python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter %s\n" "$required_adapter" >&2
        printf "PreToolUse-bash hook will BLOCK step-active calls until evidence file exists with depth_valid=true and adapter='%s'.\n" "$required_adapter" >&2
      elif [ "$adapter" != "$required_adapter" ] && [ -n "$adapter" ]; then
        printf "STATE: tasklist projected with adapter='%s' — this runtime requires adapter='%s'. Re-project native tasklist + tasklist-projected --adapter %s before next step-active or PreToolUse hook will BLOCK.\n" "$adapter" "$required_adapter" "$required_adapter" >&2
      else
        printf "STATE: tasklist projected OK (adapter=%s). Continue executing the flow per slim-entry STEP order. DO NOT ad-hoc skip steps.\n" "$required_adapter" >&2
      fi
      printf "Slim entry: commands/vg/%s.md\n" "${active_cmd#vg:}" >&2
      printf "</vg-flow-context>\n" >&2
      exit 0
    fi
  fi

  # Natural-language continuation after `/vg:build X --wave N` partial runs.
  # Partial-wave run-complete clears active-run state, so the normal active-run
  # reminder above has nothing to read. The continuation token carries the
  # canonical next command.
  continuation_context="$(python3 .claude/scripts/build-continuation.py resolve \
    --root "." \
    --prompt "$prompt" \
    --adapter "$required_adapter" 2>/dev/null || true)"
  if [ -n "$continuation_context" ]; then
    printf "%s\n" "$continuation_context" >&2
  fi
  exit 0
fi

cmd="vg:${BASH_REMATCH[1]}"
args="${BASH_REMATCH[3]:-}"
phase="$(printf '%s' "$args" | awk '{print $1}')"
# Re-resolve in slash branch (helper is idempotent; re-run picks up any
# context migration that fired earlier in this hook).
session_id="$(vg_resolve_session_id)"
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
# Hotfix 2026-05-04: interactive commands span hours by design.
INTERACTIVE_CMDS=" vg:debug vg:amend vg:scope vg:accept "
INTERACTIVE_STALE_MINUTES=360
if [ -f "$run_file" ]; then
  existing_cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" 2>/dev/null || true)"
  existing_phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("phase",""))' "$run_file" 2>/dev/null || true)"
  existing_run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("run_id",""))' "$run_file" 2>/dev/null || true)"
  existing_started="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("started_at",""))' "$run_file" 2>/dev/null || true)"

  case "$INTERACTIVE_CMDS" in
    *" $existing_cmd "*) effective_stale_min=$INTERACTIVE_STALE_MINUTES ;;
    *) effective_stale_min=$STALE_MINUTES ;;
  esac

  is_dead=0
  death_reason=""

  # Check 1 — stale by age (per-command threshold)
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
    if [ "$age_min" -gt "$effective_stale_min" ]; then
      is_dead=1
      death_reason="stale ${age_min}min (threshold ${effective_stale_min}m)"
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

  # Mainline pipeline commands have strict intra-phase ordering:
  #   blueprint → build → review → test → accept
  # Auxiliary commands are run-anytime/optional/standalone:
  #   deploy (optional between build and review/test/roam)
  #   roam (post-review/test janitor)
  #   debug (standalone, phase=standalone)
  #   amend (mid-phase change request, designed to interrupt)
  #   polish (optional cleanup)
  #   scope, specs (pre-pipeline, before blueprint)
  # Hotfix 2026-05-04: cross-run conflict ONLY blocks when BOTH cmds are
  # in mainline. Auxiliary↔mainline or auxiliary↔auxiliary → soft-warn +
  # allow. Lost-track issue (overwriting an active mainline run-file with
  # auxiliary cmd) is acceptable: the orphaned mainline run gets cleaned
  # up via stale (>30min) on next user-prompt-submit, and Stop hook on
  # session exit picks up whichever run-file is current.
  MAINLINE_CMDS=" vg:blueprint vg:build vg:review vg:test vg:accept "

  if [ "$is_dead" -eq 1 ]; then
    # Soft-warn (yellow); fall through to overwrite the dead run-file.
    printf "\033[33mvg-cross-run: previous %s on phase %s is dead (%s); continuing with %s\033[0m\n" \
      "$existing_cmd" "$existing_phase" "$death_reason" "$cmd" >&2
  elif [ -n "$existing_cmd" ] && [ "$existing_cmd" != "$cmd" ] && [ "$existing_phase" = "$phase" ]; then
    case "$MAINLINE_CMDS" in *" $existing_cmd "*) is_existing_mainline=1 ;; *) is_existing_mainline=0 ;; esac
    case "$MAINLINE_CMDS" in *" $cmd "*) is_new_mainline=1 ;; *) is_new_mainline=0 ;; esac
    if [ "$is_existing_mainline" -eq 1 ] && [ "$is_new_mainline" -eq 1 ]; then
      # Both mainline → hard-block (preserve pipeline ordering)
      printf "\033[38;5;208mvg-cross-run: active %s on phase %s; finish or abort before invoking %s on same phase\033[0m\n" \
        "$existing_cmd" "$existing_phase" "$cmd" >&2
      exit 2
    fi
    # At least one auxiliary → soft-warn, allow overwrite.
    if [ "$is_existing_mainline" -eq 1 ]; then
      role_note="auxiliary $cmd does not block mainline $existing_cmd"
    elif [ "$is_new_mainline" -eq 1 ]; then
      role_note="auxiliary $existing_cmd does not block mainline $cmd"
    else
      role_note="both auxiliary; concurrent allowed"
    fi
    printf "\033[33mvg-cross-run: %s active on phase %s; %s — previous run_id may need run-complete/abort manually\033[0m\n" \
      "$existing_cmd" "$existing_phase" "$role_note" >&2
  fi
fi

run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Issue #113 fix: when no real session id is available, synthesize a
# per-run sentinel (mirrors vg-orchestrator OHOK-9 path) so two parallel
# Claude Code sessions with unset CLAUDE_HOOK_SESSION_ID don't collide
# on the legacy `default.json` slot. Cross-session detection in state.py
# `_is_unknown_orphan_session` already understands this prefix.
if [ "$session_id" = "unknown" ]; then
  session_id="session-unknown-${run_id:0:8}"
  run_file=".vg/active-runs/${session_id}.json"
fi

cat > "$run_file" <<JSON
{
  "run_id": "$run_id",
  "command": "$cmd",
  "phase": "$phase",
  "session_id": "$session_id",
  "started_at": "$ts"
}
JSON

# Issue #105 #4 — propagate session_id to orchestrator subprocess via
# .vg/.session-context.json. Claude Code does NOT export
# CLAUDE_SESSION_ID to user-spawned bash, only CLAUDE_HOOK_SESSION_ID
# inside the hook process. state._session_id_from_session_context() reads
# this file as a fallback so orchestrator run-start tags the same
# session_id as the active-runs file written above (preventing
# session-unknown-* synthetic ids + cross-session run_id divergence).
mkdir -p ".vg" 2>/dev/null
python3 - "$session_id" "$run_id" "$cmd" "$phase" <<'PY' 2>/dev/null || true
import json, os, sys
from pathlib import Path
sid, rid, command, phase = sys.argv[1:5]
ctx_path = Path(".vg/.session-context.json")
ctx = {}
if ctx_path.exists():
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8")) or {}
    except Exception:
        ctx = {}
old_run_id = ctx.get("run_id")
ctx["session_id"] = sid
ctx["run_id"] = rid
ctx["command"] = command
ctx["phase"] = phase
if old_run_id != rid:
    ctx["started_at"] = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx["current_step"] = None
    ctx["step_history"] = []
    ctx["telemetry_emitted"] = []
tmp = ctx_path.with_suffix(ctx_path.suffix + ".tmp")
tmp.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
os.replace(str(tmp), str(ctx_path))
PY
