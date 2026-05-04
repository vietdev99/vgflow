#!/usr/bin/env bash
# Task 33 — Blocking-gate 2-leg wrapper. See _shared/lib/blocking-gate-prompt-contract.md.

# Severity → override-debt vocab mapping
_map_severity_to_debt() {
  case "$1" in
    critical) echo "critical" ;;
    error) echo "high" ;;
    warn) echo "medium" ;;
    *) echo "medium" ;;  # unknown defaults to medium (loud-fail-soft)
  esac
}

# Leg 1: emit structured prompt JSON
# Args: <gate_id> <evidence_path> <severity> [fix_hint_path]
blocking_gate_prompt_emit() {
  local gate_id="$1"
  local evidence_path="$2"
  local severity="${3:-error}"
  local fix_hint_path="${4:-}"

  if [[ -z "$gate_id" ]]; then
    echo "ERROR: blocking_gate_prompt_emit requires gate_id" >&2
    return 64
  fi
  if [[ "$severity" != "warn" && "$severity" != "error" && "$severity" != "critical" ]]; then
    echo "ERROR: severity must be warn|error|critical, got: $severity" >&2
    return 64
  fi

  # Non-interactive short-circuit
  if [[ "${ARGUMENTS:-}" =~ --non-interactive ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.aborted_non_interactive_block" --actor user --outcome BLOCK \
      --payload "{\"gate\":\"${gate_id}\",\"reason\":\"non-interactive auto-abort\"}" \
      >/dev/null 2>&1 || true
    cat <<EOF
{"gate_id": "${gate_id}", "severity": "${severity}", "non_interactive_auto_abort": true, "options": []}
EOF
    return 3
  fi

  # Read evidence + fix_hint snippets (truncated for prompt budget)
  local evidence_snippet=""
  if [[ -f "$evidence_path" ]]; then
    evidence_snippet=$(head -c 2000 "$evidence_path" | "${PYTHON_BIN:-python3}" -c '
import json, sys
sys.stdout.write(json.dumps(sys.stdin.read()))
')
  fi
  local fix_hint_snippet=""
  if [[ -n "$fix_hint_path" && -f "$fix_hint_path" ]]; then
    fix_hint_snippet=$(head -c 1000 "$fix_hint_path" | "${PYTHON_BIN:-python3}" -c '
import json, sys
sys.stdout.write(json.dumps(sys.stdin.read()))
')
  fi

  # If evidence_snippet is empty, use JSON null
  [[ -z "$evidence_snippet" ]] && evidence_snippet="null"
  # If fix_hint_snippet is empty, use JSON null
  [[ -z "$fix_hint_snippet" ]] && fix_hint_snippet="null"

  # Emit JSON describing the 4 options
  cat <<EOF
{
  "gate_id": "${gate_id}",
  "severity": "${severity}",
  "evidence_path": "${evidence_path}",
  "fix_hint_path": "${fix_hint_path}",
  "evidence_snippet": ${evidence_snippet},
  "fix_hint_snippet": ${fix_hint_snippet},
  "options": [
    {"key": "a", "label": "Auto-fix now (spawn subagent, max 3 attempts)"},
    {"key": "s", "label": "Skip with override (logs override-debt)"},
    {"key": "r", "label": "Route to /vg:amend (clean exit)"},
    {"key": "x", "label": "Abort review (clean exit)"}
  ]
}
EOF
  return 0
}

# Leg 2: dispatch based on user choice
# Args: <gate_id> --user-choice=<a|s|r|x> [--override-reason=<text>]
blocking_gate_prompt_resolve() {
  local gate_id="$1"; shift
  local user_choice="" override_reason=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user-choice=*) user_choice="${1#--user-choice=}" ;;
      --override-reason=*) override_reason="${1#--override-reason=}" ;;
    esac
    shift
  done

  case "$user_choice" in
    a)
      # Caller (orchestrator) MUST handle the subagent spawn before
      # invoking Leg 2. This branch is reached AFTER subagent returned.
      # Caller passes status via $VG_AUTOFIX_STATUS env.
      case "${VG_AUTOFIX_STATUS:-}" in
        FIXED)
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "review.gate_autofix_attempted" --actor agent --outcome PASS \
            --payload "{\"gate\":\"${gate_id}\",\"status\":\"FIXED\"}" \
            >/dev/null 2>&1 || true
          return 0
          ;;
        UNRESOLVED)
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "review.gate_autofix_attempted" --actor agent --outcome FAIL \
            --payload "{\"gate\":\"${gate_id}\",\"status\":\"UNRESOLVED\"}" \
            >/dev/null 2>&1 || true
          # Codex round-4 I-5 fix: env-driven JSON build (was injectable via
          # VG_AUTOFIX_BLOCKED_BY containing `","x":"`).
          local unresolved_payload
          unresolved_payload=$(VG_GATE_ID="$gate_id" VG_AB="${VG_AUTOFIX_BLOCKED_BY:-unknown}" VG_ATT="${VG_AUTOFIX_ATTEMPTS:-0}" \
            "${PYTHON_BIN:-python3}" -c 'import json, os; print(json.dumps({"gate": os.environ["VG_GATE_ID"], "reason": os.environ["VG_AB"], "attempts": int(os.environ["VG_ATT"]) if os.environ["VG_ATT"].isdigit() else 0}))')
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "review.gate_autofix_unresolved" --actor agent --outcome FAIL \
            --payload "$unresolved_payload" \
            >/dev/null 2>&1 || true
          return 4  # re-prompt needed
          ;;
        OUT_OF_SCOPE|*)
          # Includes blocked_by=contract_amendment_required (auto-route to amend)
          if [[ "${VG_AUTOFIX_BLOCKED_BY:-}" == "contract_amendment_required" ]]; then
            return 2
          fi
          return 4
          ;;
      esac
      ;;
    s)
      if [[ -z "$override_reason" || "${#override_reason}" -lt 10 ]]; then
        echo "ERROR: --override-reason required (>=10 chars) for --user-choice=s" >&2
        return 64
      fi
      local debt_severity
      debt_severity=$(_map_severity_to_debt "${VG_GATE_SEVERITY:-error}")
      # Codex round-4 I-5 fix: build payload via json.dumps from env, not
      # bash interpolation — was injectable via `--override-reason` containing
      # `","extra":"...` which produced malformed JSON and silently dropped
      # the audit trail. Now safely escaped.
      local override_payload
      override_payload=$(VG_GATE_ID="$gate_id" VG_OVERRIDE_REASON="$override_reason" VG_DEBT_SEVERITY="$debt_severity" \
        "${PYTHON_BIN:-python3}" -c 'import json, os; print(json.dumps({"gate": os.environ["VG_GATE_ID"], "reason": os.environ["VG_OVERRIDE_REASON"], "debt_severity": os.environ["VG_DEBT_SEVERITY"]}))')
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.gate_skipped_with_override" --actor user --outcome WARN \
        --payload "$override_payload" \
        >/dev/null 2>&1 || true
      # Log debt via the existing override-debt helper
      type log_override_debt >/dev/null 2>&1 && \
        log_override_debt "review.gate.${gate_id}" "${PHASE_NUMBER:-?}" "${override_reason}" >/dev/null 2>&1 || true
      return 1
      ;;
    r)
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.routed_to_amend" --actor user --outcome INFO \
        --payload "{\"gate\":\"${gate_id}\"}" \
        >/dev/null 2>&1 || true
      echo "-> Run \`/vg:amend ${PHASE_NUMBER:-<phase>}\` to address the underlying decision change, then re-run review."
      return 2
      ;;
    x)
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.aborted_by_user" --actor user --outcome WARN \
        --payload "{\"gate\":\"${gate_id}\"}" \
        >/dev/null 2>&1 || true
      return 3
      ;;
    *)
      echo "ERROR: --user-choice must be a|s|r|x, got: $user_choice" >&2
      return 64
      ;;
  esac
}
