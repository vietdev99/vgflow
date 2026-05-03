#!/usr/bin/env bash
# Stop hook — verifies runtime contract + state machine + diagnostic pairing.

set -euo pipefail

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"

# No active VG run — no-op (don't block ordinary work).
if [ ! -f "$run_file" ]; then
  exit 0
fi

# Race-safe JSON parse — tolerate concurrent writes from parallel sessions
# (mid-rename, partial flush). Fall back to exit 0 silently rather than
# crashing; the next stop fire will re-evaluate once file settles.
parse_field() {
  python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))[sys.argv[2]])
except (json.JSONDecodeError, FileNotFoundError, KeyError, OSError):
    sys.exit(99)
' "$run_file" "$1" 2>/dev/null
}
run_id="$(parse_field run_id)" || { echo "▸ vg-stop: run_file unreadable (race or partial write) — skipping" >&2; exit 0; }
command="$(parse_field command)" || { echo "▸ vg-stop: run_file unreadable (race or partial write) — skipping" >&2; exit 0; }
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
if command -v vg-orchestrator >/dev/null 2>&1; then
  if ! vg-orchestrator run-status --check-contract "$run_id" >/tmp/contract-err.$$ 2>&1; then
    failures+=("CONTRACT: $(cat /tmp/contract-err.$$)")
  fi
  rm -f /tmp/contract-err.$$
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

exit 0
