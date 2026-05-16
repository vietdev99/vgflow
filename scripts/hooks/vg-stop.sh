#!/usr/bin/env bash
# Stop hook — verifies runtime contract + state machine + diagnostic pairing.

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

session_id="$(vg_resolve_session_id)"
run_file=".vg/active-runs/${session_id}.json"

# No active VG run — no-op for run-specific checks, but still emit dream reminder
# (consolidation gate is project-level, independent of any specific run).
if [ ! -f "$run_file" ]; then
  DREAM_HELPER=".claude/scripts/vg-dream-reminder.py"
  [ -f "$DREAM_HELPER" ] || DREAM_HELPER="scripts/vg-dream-reminder.py"
  [ -f "$DREAM_HELPER" ] && python3 "$DREAM_HELPER" 2>&1 || true
  exit 0
fi

# Race-safe JSON parse: tolerate concurrent writes from parallel sessions
# (mid-rename, partial flush). The next Stop fire will re-evaluate once settled.
parse_field() {
  python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))[sys.argv[2]])
except (json.JSONDecodeError, FileNotFoundError, KeyError, OSError):
    sys.exit(99)
' "$run_file" "$1" 2>/dev/null
}
run_id="$(parse_field run_id)" || { echo "vg-stop: run_file unreadable; skipping" >&2; exit 0; }
command="$(parse_field command)" || { echo "vg-stop: run_file unreadable; skipping" >&2; exit 0; }
db=".vg/events.db"

failures=()

# 1. Diagnostic pairing: vg.block.fired count must equal vg.block.handled count.
if [ -f "$db" ]; then
  fired="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null || echo 0)"
  handled="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.handled'" 2>/dev/null || echo 0)"
  if [ "$fired" -gt "$handled" ]; then
    # Production schema uses payload_json; test fixtures use payload. Try both.
    unpaired="$(sqlite3 "$db" "SELECT payload_json FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null \
               || sqlite3 "$db" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null)"
    failures+=("UNHANDLED DIAGNOSTIC: ${fired} blocks fired but only ${handled} handled. Open: ${unpaired}")
  fi
fi

# 2. State machine ordering check (best-effort — script may not have command sequence defined).
hook_dir="$(cd "$(dirname "$0")" && pwd)"
sm_validator="${hook_dir}/../vg-state-machine-validator.py"
if [ ! -f "$sm_validator" ]; then
  sm_validator="scripts/vg-state-machine-validator.py"
fi
if [ -x "$sm_validator" ] && [ -f "$db" ]; then
  if ! python3 "$sm_validator" --db "$db" --command "$command" --run-id "$run_id" 2>/tmp/sm-err.$$; then
    failures+=("STATE MACHINE: $(cat /tmp/sm-err.$$)")
  fi
  rm -f /tmp/sm-err.$$
fi

# 3. Contract verify (delegated to existing vg-orchestrator if present).
# Note: legacy `run-status --check-contract <run_id>` was removed in v4.x.
# The real spawn-count / wave-completion checks moved into `wave-complete`
# (see vg-orchestrator/__main__.py near line 1966). Probe with --help so this
# stays a no-op until/unless a runtime-contract subcommand is reintroduced.
if command -v vg-orchestrator >/dev/null 2>&1; then
  if vg-orchestrator run-status --help 2>/dev/null | grep -q -- '--check-contract'; then
    if ! vg-orchestrator run-status --check-contract "$run_id" >/tmp/contract-err.$$ 2>&1; then
      failures+=("CONTRACT: $(cat /tmp/contract-err.$$)")
    fi
    rm -f /tmp/contract-err.$$
  fi
fi

# 4. Post-wave continuation gate (v4.21.0 — dogfood feedback PrintwayV3 Phase 7).
# When /vg:build waves complete on the final-wave run, AI must immediately
# proceed to STEP 5 (post-execution) in same turn. Prose instruction at
# commands/vg/build.md:315 is not hook-enforced — AI can end turn after waves.
# This block detects: build command + waves done + post-execution missing +
# is_final_wave=true, BLOCK Stop with continuation prompt.
#
# B68 (v4.56.0): extended with cascade checks 4b + 4c covering STEP 6
# (CrossAI) + STEP 7 (run_complete). Previously check #4 only caught
# STEP 5 missing. User reported AI marked STEP 5 done but ended turn
# without STEP 6 CrossAI + STEP 7 close → "build done" announced but
# CrossAI never ran, run_complete marker missing.
if [ "$command" = "vg:build" ] || [ "$command" = "build" ]; then
  # Locate phase_dir from active-run
  phase_dir="$(parse_field phase_dir 2>/dev/null || echo "")"
  if [ -n "$phase_dir" ] && [ -d "$phase_dir/.step-markers" ]; then
    waves_done=$(ls "$phase_dir/.step-markers"/wave-*.done 2>/dev/null | wc -l | tr -d ' ')
    post_exec_done="0"
    [ -f "$phase_dir/.step-markers/9_post_execution.done" ] && post_exec_done="1"
    crossai_done="0"
    [ -f "$phase_dir/.step-markers/11_crossai_build_verify_loop.done" ] && crossai_done="1"
    postmortem_done="0"
    [ -f "$phase_dir/.step-markers/10_postmortem_sanity.done" ] && postmortem_done="1"
    run_complete_done="0"
    [ -f "$phase_dir/.step-markers/12_run_complete.done" ] && run_complete_done="1"
    is_final_wave="true"
    [ -f ".vg/runs/${run_id}/.is-final-wave" ] && is_final_wave=$(cat ".vg/runs/${run_id}/.is-final-wave" 2>/dev/null)

    # 4a — STEP 5 post-execution missing
    if [ "$waves_done" -gt 0 ] && [ "$post_exec_done" = "0" ] && [ "$is_final_wave" = "true" ]; then
      failures+=("POST-WAVE CONTINUATION (4a): ${waves_done} wave(s) done but STEP 5 post-execution not run. AI MUST continue in same turn: spawn vg-build-post-executor + STEP 5.1 spec reviewers + STEP 5.5 fix-loop + STEP 6/7. Do NOT end turn after waves return. See commands/vg/build.md:315.")
    fi

    # 4b — STEP 6 CrossAI missing (B68 v4.56.0; codex MAJOR #1 fix)
    # Bug: AI completes STEP 5 then ends turn before CrossAI loop.
    # CrossAI is HARD-GATE per commands/vg/_shared/build/crossai-loop.md:11-18.
    # Reference: events.db `build.crossai_loop_complete` (terminal) +
    # `build.crossai_iteration_started` (per iteration) events expected.
    # NOT `crossai.verdict` (incorrect name from earlier draft).
    if [ "$post_exec_done" = "1" ] && [ "$crossai_done" = "0" ] && [ "$is_final_wave" = "true" ]; then
      failures+=("POST-WAVE CONTINUATION (4b): STEP 5 post_execution done but STEP 6 CrossAI verify-loop not run. AI MUST continue in same turn: read commands/vg/_shared/build/crossai-loop.md and spawn CrossAI verification. CrossAI is a HARD-GATE — events.db build.crossai_loop_complete terminal event required at run-complete (validated by scripts/validators/build-crossai-required.py). Do NOT announce 'build done' before CrossAI verdict.")
    fi

    # 4c — STEP 7 postmortem_sanity missing (B68 v4.56.0; codex BLOCKER #1 fix)
    # Postmortem is part of STEP 7 close group and was previously not gated.
    # Marker 10_postmortem_sanity required per close.md L1 final-reviewer.
    if [ "$crossai_done" = "1" ] && [ "$postmortem_done" = "0" ] && [ "$is_final_wave" = "true" ]; then
      failures+=("POST-WAVE CONTINUATION (4c): STEP 6 CrossAI done but STEP 7 postmortem_sanity (10_postmortem_sanity marker) not run. AI MUST continue in same turn: read commands/vg/_shared/build/close.md and execute postmortem-sanity step before run-complete. Postmortem catches recovery-bypass + silent-gate-failure + UI drift.")
    fi

    # 4d — STEP 7 run_complete missing (B68 v4.56.0)
    # Bug: AI completes postmortem then ends turn before final close steps.
    # 12_run_complete marker is the CANONICAL build-truly-done marker.
    if [ "$postmortem_done" = "1" ] && [ "$run_complete_done" = "0" ] && [ "$is_final_wave" = "true" ]; then
      failures+=("POST-WAVE CONTINUATION (4d): STEP 7 postmortem done but 12_run_complete marker not written. AI MUST continue in same turn: read commands/vg/_shared/build/close.md and complete final gates including vg-orchestrator run-complete. The 12_run_complete marker is the CANONICAL build-truly-done marker.")
    fi

    # 4e — STEP 7 run-complete event missing despite marker present
    # (B68 v4.56.0; codex BLOCKER #2 fix)
    # Marker 12_run_complete is touched at close.md:275-277 BEFORE actual
    # `vg-orchestrator run-complete` invocation at close.md:818-821. If AI
    # stops between marker write and real run-complete, 4d won't fire but
    # the run isn't truly complete. Check active-run state — if run still
    # active despite marker → BLOCK.
    if [ "$run_complete_done" = "1" ] && [ "$is_final_wave" = "true" ]; then
      # vg-orchestrator run-status outputs `state: active|completed|...`
      run_state="$(vg-orchestrator run-status "$run_id" 2>/dev/null | grep -E '^state:' | head -1 | awk '{print $2}' | tr -d ' ')"
      if [ "$run_state" = "active" ] || [ -z "$run_state" ]; then
        # state still active OR couldn't read — marker is preliminary, not canonical
        # Only block if we can confirm state=active (else might be eventual-consistency race)
        if [ "$run_state" = "active" ]; then
          failures+=("POST-WAVE CONTINUATION (4e): 12_run_complete marker exists but run state is still 'active'. Marker is preliminary (close.md:275-277) — actual vg-orchestrator run-complete (close.md:818-821) has NOT yet executed. AI MUST complete close.md remaining steps (validators + truthcheck + run-complete + PIPELINE-STATE flip + ROADMAP update).")
        fi
      fi
    fi
  fi
fi

if [ "${#failures[@]}" -gt 0 ]; then
  gate_id="Stop-runtime-contract"
  block_dir=".vg/blocks/${run_id}"
  block_file="${block_dir}/${gate_id}.md"

  mkdir -p "$block_dir" 2>/dev/null
  {
    echo "# Block diagnostic — ${gate_id}"
    echo ""
    echo "## Cause"
    echo "Runtime contract incomplete for run ${run_id} (${command})."
    echo ""
    echo "## Failures (${#failures[@]})"
    for f in "${failures[@]}"; do
      echo "- $f"
    done
    echo ""
    echo "## Required fix"
    echo "Resolve each failure above. Common patterns:"
    echo "- UNHANDLED DIAGNOSTIC → emit \`vg.block.handled\` for each unpaired \`vg.block.fired\`."
    echo "- STATE MACHINE → events emitted out of expected order; investigate which step ran late."
    echo "- CONTRACT → check \`runtime_contract.must_write\` artifacts + \`must_touch_markers\`."
  } > "$block_file"

  # Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
  printf "\033[38;5;208m%s: %d failure(s) for run %s (%s)\033[0m\n→ Read %s for details + fix\n" \
    "$gate_id" "${#failures[@]}" "$run_id" "$command" "$block_file" >&2
  exit 2
fi

# Soft reminder: meta-memory consolidation gate (independent of run-file guard).
DREAM_HELPER=".claude/scripts/vg-dream-reminder.py"
[ -f "$DREAM_HELPER" ] || DREAM_HELPER="scripts/vg-dream-reminder.py"
[ -f "$DREAM_HELPER" ] && python3 "$DREAM_HELPER" 2>&1 || true

exit 0
