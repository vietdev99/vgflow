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
