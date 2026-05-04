#!/usr/bin/env bash
# UserPromptSubmit hook — closes Codex bypass #1.
# Detects /vg:<cmd> <args> in prompt text. Creates active-run state file
# BEFORE the model runs so Stop hook later has run context to validate.

set -euo pipefail

input="$(cat)"
prompt="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("prompt",""))' 2>/dev/null || true)"
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"

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
      # Tier 1 #108 — also emit JSON additionalContext on stdout for
      # Claude Code 2.0+ (richer surface, no 10K char clip).
      ctx_body=""
      ctx_body+="<vg-flow-context>"$'\n'
      ctx_body+="Active VG run detected: ${active_cmd} on phase ${active_phase} (run_id ${active_run_id:-?})."$'\n'
      if [ "$tasklist_projected" = "no" ]; then
        ctx_body+="STATE: tasklist NOT yet projected."$'\n'
        ctx_body+="BEFORE any tool call (Bash/etc), you MUST:"$'\n'
        ctx_body+="  1. Read .vg/runs/${active_run_id}/tasklist-contract.json"$'\n'
        ctx_body+="  2. Call the TodoWrite tool with hierarchical 2-layer projection (group + sub-items)"$'\n'
        ctx_body+="  3. Run: python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter claude"$'\n'
        ctx_body+="PreToolUse-bash hook will BLOCK step-active calls until evidence file exists with depth_valid=true and adapter='claude'."$'\n'
      elif [ "$adapter" != "claude" ] && [ -n "$adapter" ]; then
        ctx_body+="STATE: tasklist projected with adapter='${adapter}' — Claude Code session requires adapter='claude'. Re-call TodoWrite + tasklist-projected --adapter claude before next step-active or PreToolUse hook will BLOCK."$'\n'
      else
        ctx_body+="STATE: tasklist projected OK (adapter=claude). Continue executing the flow per slim-entry STEP order. DO NOT ad-hoc skip steps."$'\n'
      fi
      ctx_body+="Slim entry: commands/vg/${active_cmd#vg:}.md"$'\n'
      ctx_body+="</vg-flow-context>"

      # Emit JSON additionalContext on stdout (Claude Code 2.0+).
      VG_HOOK_CTX="$ctx_body" python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": os.environ.get("VG_HOOK_CTX", ""),
  }
}))
' 2>/dev/null || true

      # Stderr mirror (Claude Code 1.x compat + grep-friendly).
      printf '%s\n' "$ctx_body" >&2
    fi
  fi
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
      # Tier 1 #108 — emit JSON deny on stdout (Claude Code 2.0+).
      # UserPromptSubmit hook spec: `decision: "block"` halts processing of the prompt.
      VG_HOOK_REASON="vg-cross-run: active ${existing_cmd} on phase ${existing_phase}; finish or abort before invoking ${cmd} on same phase. Both are mainline pipeline commands (blueprint -> build -> review -> test -> accept) and intra-phase ordering must be preserved." \
      VG_HOOK_ADDL="VG cross-run conflict — finish or abort the active ${existing_cmd} run before starting ${cmd}." \
      python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({
  "decision": "block",
  "reason": os.environ.get("VG_HOOK_REASON", ""),
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": os.environ.get("VG_HOOK_ADDL", ""),
  }
}))
' 2>/dev/null || true

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
cat > "$run_file" <<JSON
{
  "run_id": "$run_id",
  "command": "$cmd",
  "phase": "$phase",
  "session_id": "$session_id",
  "started_at": "$ts"
}
JSON
