#!/usr/bin/env bash
# Stop hook — verifies runtime contract + state machine + diagnostic pairing.

set -euo pipefail

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"

# No active VG run — no-op (don't block ordinary work).
if [ ! -f "$run_file" ]; then
  exit 0
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
command="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file")"
db=".vg/events.db"

failures=()

# 1. Diagnostic pairing: vg.block.fired count must equal vg.block.handled count.
if [ -f "$db" ]; then
  fired="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null || echo 0)"
  handled="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.handled'" 2>/dev/null || echo 0)"
  if [ "$fired" -gt "$handled" ]; then
    unpaired="$(sqlite3 "$db" "SELECT payload FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" 2>/dev/null)"
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
if command -v vg-orchestrator >/dev/null 2>&1; then
  if ! vg-orchestrator run-status --check-contract "$run_id" >/tmp/contract-err.$$ 2>&1; then
    failures+=("CONTRACT: $(cat /tmp/contract-err.$$)")
  fi
  rm -f /tmp/contract-err.$$
fi

if [ "${#failures[@]}" -gt 0 ]; then
  echo "═══════════════════════════════════════════" >&2
  echo "STOP BLOCKED — runtime contract incomplete for run ${run_id} (${command})" >&2
  echo "═══════════════════════════════════════════" >&2
  for f in "${failures[@]}"; do
    echo "  ✗ $f" >&2
  done
  echo "" >&2
  echo "Resolve each above before completing the run." >&2
  exit 2
fi

exit 0
