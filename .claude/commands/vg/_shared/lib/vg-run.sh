# shellcheck shell=bash
# VG run lifecycle — preferred path is vg-orchestrator binary (v2.2).
# Falls back to bash-native primitives (v1.15.2) when binary absent.
#
# Exposed functions:
#   vg_run_start   CMD PHASE [ARGS]   — write current-run.json + emit run.started
#   vg_run_complete [OUTCOME]         — emit completed + delete current-run.json
#   vg_emit        EVENT [PAYLOAD]    — emit event via orchestrator (or lazy-source telemetry.sh fallback)
#   vg_mark_step   NAMESPACE NAME     — touch step marker via orchestrator

VG_RUN_FILE="${VG_RUN_FILE:-${REPO_ROOT:-.}/.vg/current-run.json}"
VG_ORCHESTRATOR="${VG_ORCHESTRATOR:-${REPO_ROOT:-.}/.claude/scripts/vg-orchestrator}"

_vg_orchestrator_available() {
  [ -f "${VG_ORCHESTRATOR}/__main__.py" ] && command -v "${PYTHON_BIN:-python3}" >/dev/null 2>&1
}

vg_run_start() {
  local cmd="$1" phase="$2"; shift 2
  local args="$*"
  [ -z "$cmd" ] && return 0

  if _vg_orchestrator_available; then
    # Orchestrator writes current-run.json + emits run.started + {cmd}.started
    "${PYTHON_BIN:-python3}" "$VG_ORCHESTRATOR" run-start "$cmd" "$phase" $args 2>/dev/null | head -1 >/dev/null || true
    return 0
  fi

  # v1.15.2 bash fallback
  mkdir -p "$(dirname "$VG_RUN_FILE")" 2>/dev/null || true
  local run_id ts
  ts=$(date -u +%FT%TZ)
  run_id=$("${PYTHON_BIN:-python3}" -c "import uuid; print(uuid.uuid4())" 2>/dev/null \
           || printf '%08x-%04x-%04x-%04x-%012x' $RANDOM $RANDOM $RANDOM $RANDOM $RANDOM$RANDOM)
  local tmp="${VG_RUN_FILE}.tmp.$$"
  "${PYTHON_BIN:-python3}" - "$tmp" "$cmd" "$phase" "$args" "$run_id" "$ts" <<'PY' 2>/dev/null
import json, sys
tmp, cmd, phase, args, rid, ts = sys.argv[1:7]
with open(tmp, "w", encoding="utf-8") as f:
  json.dump({"command": cmd, "phase": phase, "args": args,
             "run_id": rid, "started_at": ts}, f, indent=2)
PY
  mv "$tmp" "$VG_RUN_FILE" 2>/dev/null || true
  export VG_RUN_ID="$run_id" VG_CURRENT_COMMAND="$cmd" VG_CURRENT_PHASE="$phase"
  vg_emit "${cmd#vg:}.started" "{\"phase\":\"${phase}\"}" 2>/dev/null || true
}

vg_run_complete() {
  local outcome="${1:-PASS}"
  if _vg_orchestrator_available; then
    "${PYTHON_BIN:-python3}" "$VG_ORCHESTRATOR" run-complete --outcome "$outcome" 2>&1
    return $?
  fi
  # v1.15.2 fallback
  local cmd="${VG_CURRENT_COMMAND:-unknown}" phase="${VG_CURRENT_PHASE:-}"
  vg_emit "${cmd#vg:}.completed" "{\"phase\":\"${phase}\",\"outcome\":\"${outcome}\"}" 2>/dev/null || true
  rm -f "$VG_RUN_FILE" 2>/dev/null || true
  unset VG_RUN_ID VG_CURRENT_COMMAND VG_CURRENT_PHASE
  return 0
}

vg_emit() {
  local event_type="$1" payload="${2:-{}}"
  [ -z "$event_type" ] && return 0

  if _vg_orchestrator_available && [ -f "$VG_RUN_FILE" ]; then
    "${PYTHON_BIN:-python3}" "$VG_ORCHESTRATOR" emit-event "$event_type" --payload "$payload" >/dev/null 2>&1
    return 0
  fi

  # v1.15.2 telemetry.sh fallback
  if ! type -t emit_telemetry_v2 >/dev/null 2>&1; then
    local tel_sh="${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/telemetry.sh"
    [ -f "$tel_sh" ] && source "$tel_sh" 2>/dev/null
    type -t telemetry_init >/dev/null 2>&1 && telemetry_init 2>/dev/null
  fi
  local phase="${VG_CURRENT_PHASE:-}" command="${VG_CURRENT_COMMAND:-unknown}"
  local step="${VG_SESSION_CURRENT_STEP:-}"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "$event_type" "$phase" "$step" "" "" "$payload" "" "$command" 2>/dev/null || true
  fi
}

vg_mark_step() {
  local namespace="$1" step_name="$2"
  [ -z "$namespace" ] || [ -z "$step_name" ] && return 0

  if _vg_orchestrator_available && [ -f "$VG_RUN_FILE" ]; then
    "${PYTHON_BIN:-python3}" "$VG_ORCHESTRATOR" mark-step "$namespace" "$step_name" >/dev/null 2>&1
    return 0
  fi

  # v1.15.2 fallback — just touch file directly
  local phase_dir
  phase_dir=$("${PYTHON_BIN:-python3}" -c "
import os, sys
from pathlib import Path
root = Path(os.environ.get('REPO_ROOT') or os.getcwd())
phases = root / '.vg' / 'phases'
phase = os.environ.get('VG_CURRENT_PHASE', '')
if phase and phases.exists():
  cands = list(phases.glob(f'{phase}-*')) or list(phases.glob(f'{phase.zfill(2)}-*'))
  if cands: print(cands[0])
" 2>/dev/null)
  [ -z "$phase_dir" ] && return 0
  mkdir -p "${phase_dir}/.step-markers/${namespace}" 2>/dev/null
  touch "${phase_dir}/.step-markers/${namespace}/${step_name}.done"
}

vg_ensure_override_debt_register() {
  local register="${REPO_ROOT:-.}/.vg/OVERRIDE-DEBT.md"
  [ -f "$register" ] && return 0
  mkdir -p "$(dirname "$register")" 2>/dev/null
  cat > "$register" <<'EOF'
# VG Override Debt Register

Managed by vg-orchestrator (events.db `override.used` + `override.resolved`)
and `log_override_debt` bash helper. Do NOT edit by hand.

`/vg:accept` MUST verify this register is clean before approving a phase.

<!-- entries appended below -->
EOF
}
