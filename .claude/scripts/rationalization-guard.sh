#!/usr/bin/env bash
# rationalization-guard.sh — extracted from _shared/rationalization-guard.md
#
# This script is the SOURCE OF TRUTH for rationalization_guard_* bash functions.
# The .md file is user-facing documentation; this .sh is what callers source.
#
# OHOK v2 Day 1 fix: Codex audit found callers invoked these functions without
# sourcing any definition → bash "command not found" silently skipped → every
# override flag bypassed guard. This file closes that gap.
#
# USAGE (callers must source this before invoking guard functions):
#
#   source "${REPO_ROOT:-.}/.claude/scripts/rationalization-guard.sh"
#   RATGUARD_RESULT=$(rationalization_guard_check "gate-id" "gate-spec" "skip-reason")
#   if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "gate-id" "--flag" "$PHASE" "$STEP" "$REASON"; then
#     exit 1  # guard ESCALATE — override blocked
#   fi
#
# FAIL-CLOSED POLICY:
# - Task tool unavailable (pure-shell context) → ESCALATE (user adjudicates).
# - Guard function itself crashes → caller MUST treat as ESCALATE (not skip).
# - Callers MUST NOT wrap guard invocation with `|| true` — that inverts fail-closed.

set +e  # callers handle return codes explicitly

# Check if rationalization guard is enabled for this gate (config-driven)
rationalization_guard_enabled() {
  local gate_id="$1"
  [ "${CONFIG_RATIONALIZATION_GUARD_ENABLED:-true}" = "true" ] || return 1
  # Optional per-gate allowlist via config; if not set, guard applies to ALL gates
  local allowed="${CONFIG_RATIONALIZATION_GUARD_GATES:-*}"
  [ "$allowed" = "*" ] && return 0
  case " $allowed " in *" $gate_id "*) return 0 ;; *) return 1 ;; esac
}

# Main API — spawn isolated Haiku subagent to adjudicate a gate-skip
# Usage: result=$(rationalization_guard_check "$gate_id" "$gate_spec_text" "$skip_reason")
# Result format (single line): {"verdict":"PASS|FLAG|ESCALATE","reason":"...","confidence":"low|medium|high"}
rationalization_guard_check() {
  local gate_id="$1"
  local gate_spec_text="$2"
  local skip_reason="$3"

  if ! rationalization_guard_enabled "$gate_id"; then
    echo '{"verdict":"PASS","reason":"guard disabled for this gate","confidence":"low"}'
    return 0
  fi

  local subagent_model="${CONFIG_RATIONALIZATION_GUARD_MODEL:-haiku}"

  # Spawn subagent via Task tool with ZERO parent context.
  # The orchestrator layer calling this function MUST use the Task tool with:
  #   subagent_type: "general-purpose"
  #   model: $subagent_model  (default: haiku)
  #   prompt: <<PROMPT below — embedded only, no reference to session state>>
  #
  # Because shell cannot invoke Task directly, callers embed the prompt file path and
  # the orchestrator (VG command) invokes Task before this helper returns. See
  # "Caller integration" section below for the required wrapper pattern.
  #
  # This function writes the prompt to a tmp file and emits the path on fd 3 so the
  # VG command can pick it up, dispatch to Task, and pipe the subagent's output back.

  local prompt_path="${VG_TMP:-/tmp}/ratguard-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true
  cat > "$prompt_path" <<PROMPT
You are a Rationalization Guard subagent. You have ZERO context about the parent session.
Your ONLY job: decide whether a proposed gate-skip justification is concrete enough to proceed.

═════════════════════════════════════════════════════════════════════════
GATE UNDER REVIEW (id: ${gate_id})
═════════════════════════════════════════════════════════════════════════
${gate_spec_text}

═════════════════════════════════════════════════════════════════════════
PROPOSED SKIP JUSTIFICATION (from executor)
═════════════════════════════════════════════════════════════════════════
${skip_reason}

═════════════════════════════════════════════════════════════════════════
YOUR DECISION
═════════════════════════════════════════════════════════════════════════
Classify the justification as exactly ONE of:

• PASS — reason is CONCRETE and gate-appropriate. Examples: cites issue ID/URL, names
  specific failing test + known flakiness, identifies infra blocker beyond this phase.

• FLAG — reason is plausible but VAGUE or partially rationalizing. Examples:
  "tests were green yesterday", "minor issue", "will fix next phase", "not blocking".
  Override proceeds but debt escalated to critical severity.

• ESCALATE — reason is a RATIONALIZATION pattern. Examples:
  "should work now" (no verification), "agent reported success" (no independent check),
  "small fix, won't hurt" (scope creep), "confident it passes" (confidence ≠ evidence),
  "I'll verify later" (later = never), "close enough", time-pressure excuses,
  unrelated to the actual gate.

Also consider confidence: "low" if reason ambiguous, "medium" if reason typical-but-checkable,
"high" if reason clearly concrete OR clearly rationalizing.

OUTPUT FORMAT — exactly ONE line of strict JSON, no prose before/after:
{"verdict":"PASS|FLAG|ESCALATE","reason":"<one sentence ≤ 120 chars>","confidence":"low|medium|high"}
PROMPT

  # Emit prompt path on fd 3 for orchestrator to pick up; also on stderr for debugging
  echo "$prompt_path" >&3 2>/dev/null || true
  echo "ratguard-prompt: $prompt_path" >&2

  # Orchestrator (VG command) is responsible for:
  #   1. Reading the prompt at $prompt_path
  #   2. Dispatching Task tool (subagent_type=general-purpose, model=$subagent_model)
  #   3. Capturing subagent stdout (one JSON line)
  #   4. Returning that JSON to the caller
  #
  # When called from inside the Claude harness (not raw shell), the VG command MUST
  # replace this shell function with a direct Task-tool invocation — see pattern below.
  #
  # Fallback for pure-shell contexts (no Task available): return ESCALATE to force
  # user adjudication rather than silently passing (fail-closed).
  echo '{"verdict":"ESCALATE","reason":"Task tool unavailable — guard failed closed, user must adjudicate","confidence":"high"}'
}

# Post-verdict dispatcher — call immediately after rationalization_guard_check
# Usage: rationalization_guard_dispatch "$result_json" "$gate_id" "$flag" "$phase" "$step" "$skip_reason"
# Returns: 0 if override may proceed (PASS or FLAG), 1 if must block (ESCALATE)
rationalization_guard_dispatch() {
  local result="$1" gate_id="$2" flag="$3" phase="$4" step="$5" skip_reason="$6"
  local verdict reason confidence subagent_model="${CONFIG_RATIONALIZATION_GUARD_MODEL:-haiku}"
  verdict=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('verdict',''))" "$result" 2>/dev/null || echo "")
  reason=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('reason',''))" "$result" 2>/dev/null || echo "")
  confidence=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('confidence',''))" "$result" 2>/dev/null || echo "")

  # Telemetry — event type MUST be "rationalization_guard_check"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "rationalization_guard_check" "$phase" "$step" "$gate_id" "$verdict" \
      "{\"flag\":\"$flag\",\"confidence\":\"$confidence\",\"subagent_model\":\"$subagent_model\",\"subagent_reason\":\"${reason//\"/\\\"}\"}"
  fi

  # Emit to events.db via vg-orchestrator (v2.2 canonical — OHOK Day 1 addition).
  # Silent fail on error — telemetry is fallback; orchestrator is primary.
  if [ -x ".claude/scripts/vg-orchestrator" ] || [ -d ".claude/scripts/vg-orchestrator" ]; then
    ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
      "rationalization_guard.checked" \
      --step "$step" \
      --actor "orchestrator" \
      --outcome "$verdict" \
      --payload "{\"gate_id\":\"$gate_id\",\"flag\":\"$flag\",\"confidence\":\"$confidence\",\"reason\":\"${reason//\"/\\\"}\"}" \
      2>/dev/null || true
  fi

  case "$verdict" in
    PASS)
      echo "✓ Rationalization guard (bảo vệ biện minh): PASS — ${reason}"
      return 0
      ;;
    FLAG)
      echo "⚠ Rationalization guard (bảo vệ biện minh): FLAG — ${reason}"
      echo "   Override sẽ proceed nhưng debt ghi nhận ở severity CRITICAL (thay vì default)."
      # Caller log_override_debt will tag severity=critical via env var
      export VG_RATGUARD_FORCE_CRITICAL=1
      return 0
      ;;
    ESCALATE|"")
      echo "⛔ Rationalization guard (bảo vệ biện minh): ESCALATE — ${reason:-reason missing}"
      echo "   Override BLOCKED. Skip justification is a rationalization pattern or guard failed closed."
      echo "   Gate: $gate_id | Phase: $phase | Step: $step"
      echo "   Options: (a) provide concrete evidence (link ticket, failing test, infra blocker"
      echo "            — then retry), (b) abandon the override and fix the root cause."
      return 1
      ;;
    *)
      echo "⛔ Rationalization guard: unknown verdict '$verdict' — blocking fail-closed"
      return 1
      ;;
  esac
}

# Back-compat stub for legacy callers that invoke guard without dispatch.
# Emits a deprecation telemetry event so we can track remaining call sites.
rationalization_guard_legacy_skip() {
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "rationalization_guard_check" "${2:-}" "${3:-}" "${1:-legacy}" "LEGACY_SKIP" \
      "{\"deprecated\":true}"
  fi
  return 0
}
