# UAT quorum gate — STEP 6

Maps to step `5_uat_quorum_gate` (203 lines). Validates
`.uat-responses.json` against critical-skip threshold + runs
rationalization-guard.

<HARD-GATE>
You MUST run this AFTER STEP 5 (interactive UAT) and BEFORE STEP 7
(audit + UAT.md write). Counts SKIPs on critical items (Section A
decisions, Section B READY goals); blocks unless `--allow-uat-skips`
is set AND rationalization-guard passes.

Override-debt entry is logged for every `--allow-uat-skips` invocation —
it is NOT free.
</HARD-GATE>

---

<step name="5_uat_quorum_gate">
**⛔ UAT QUORUM GATE (OHOK Batch 3 B4 — block theatre UAT).**

Before Batch 3 UAT was pure theatre — every AskUserQuestion offered `[s] Skip`, user could skip decisions + goals + ripples + designs all via `[s]`, phase ships with "DEFERRED" verdict, next phase reads note and proceeds. No mechanism enforced minimum due diligence.

This gate counts SKIPs on critical sections (A decisions, B READY goals) and BLOCKs if over threshold. Config-driven via `config.accept.max_uat_skips_critical` (default 0 — strict).

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 5_uat_quorum_gate 2>/dev/null || true

# Config thresholds (default strict: 0 critical skips allowed)
MAX_CRIT_SKIPS=$(${PYTHON_BIN:-python3} - <<'PY' 2>/dev/null || echo 0
import re
from pathlib import Path
p = Path(".claude/vg.config.md")
if not p.exists():
    print(0); exit()
text = p.read_text(encoding="utf-8", errors="replace")
m = re.search(r"^\s*accept\s*:\s*\n(?:\s+[a-z_]+:.*\n)*?\s+max_uat_skips_critical\s*:\s*(\d+)", text, re.MULTILINE)
print(m.group(1) if m else "0")
PY
)

RESP_JSON="${PHASE_DIR}/.uat-responses.json"

# Helper: resolve --override-reason="..." (canonical) with --reason='...' fallback (legacy).
_uat_extract_reason() {
  local reason
  reason=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason=\"[^\"]+\"" | sed "s/--override-reason=\"//; s/\"$//")
  [ -z "$reason" ] && reason=$(echo "$ARGUMENTS" | grep -oE -- "--override-reason='[^']+'" | sed "s/--override-reason='//; s/'$//")
  if [ -z "$reason" ]; then
    reason=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
    [ -n "$reason" ] && echo "⚠ --reason='...' is legacy; prefer --override-reason=\"...\" (entry contract)" >&2
  fi
  printf '%s' "$reason"
}

# Source rationalization-guard + override-debt helpers up front for all 3 paths.
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/rationalization-guard.sh" 2>/dev/null || true

# Gate 1: response file must exist with content
if [ ! -s "$RESP_JSON" ]; then
  echo "⛔ UAT quorum gate: .uat-responses.json missing or empty." >&2
  echo "   AI must persist each AskUserQuestion response in step 5." >&2
  echo "   Silence / verbal-only answers = BLOCK (prevents theatre UAT)." >&2
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-uat ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"no_response_json\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  EMPTY_REASON=$(_uat_extract_reason)
  if [ -z "$EMPTY_REASON" ]; then
    echo "⛔ --allow-empty-uat requires --override-reason=\"<why shipping with no UAT responses>\"" >&2
    exit 1
  fi
  # Rationalization guard — empty UAT = theatre vector, highest risk.
  if type -t rationalization_guard_check >/dev/null 2>&1; then
    RATGUARD_RESULT=$(rationalization_guard_check "uat-empty" \
      "Skipping UAT response persistence = theatre. The Section A/B answers were never captured." \
      "phase=${PHASE_NUMBER} reason=${EMPTY_REASON}")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "uat-empty" "--allow-empty-uat" "$PHASE_NUMBER" "accept.uat_quorum_gate" "$EMPTY_REASON"; then
      exit 1
    fi
  fi
  # Canonical override emit — fires override.used + OVERRIDE-DEBT entry.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    --flag "--allow-empty-uat" --reason "$EMPTY_REASON" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-empty" "${PHASE_NUMBER}" "$EMPTY_REASON" "${PHASE_DIR}"
fi

# Gate 1b: response JSON coverage cross-check (CrossAI R6 fix).
# Without this, attacker could write {"decisions":{"skip":0,"total":0}} and
# pass quorum trivially. Now: responses must cover every expected decision
# + READY goal derived from artifacts.
COVERAGE_CHECK=$(${PYTHON_BIN:-python3} - "$RESP_JSON" "$PHASE_DIR" 2>/dev/null <<'PY' || echo "PARSE_ERROR"
import json, re, sys
from pathlib import Path

resp_path = Path(sys.argv[1])
phase_dir = Path(sys.argv[2])

# Expected decisions = count of D-XX / P{phase}.D-XX headings in CONTEXT.md
expected_dec = 0
ctx = phase_dir / "CONTEXT.md"
if ctx.exists():
    t = ctx.read_text(encoding="utf-8", errors="replace")
    expected_dec = len(re.findall(r'^###\s+(?:P[0-9.]+\.)?D-\d+', t, re.MULTILINE))

# Expected READY goals = count of READY rows in GOAL-COVERAGE-MATRIX.md
expected_goals = 0
matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
if matrix.exists():
    t = matrix.read_text(encoding="utf-8", errors="replace")
    expected_goals = len(re.findall(r'\|\s*READY\s*\|', t))

# Responses actually recorded
try:
    data = json.loads(resp_path.read_text(encoding="utf-8"))
except Exception:
    print(f"MALFORMED:expected_dec={expected_dec},expected_goals={expected_goals}")
    sys.exit()

dec_section = data.get("decisions") or {}
goal_section = data.get("goals") or {}
# Sum of all verdicts (a/y/s/n) in decisions — attacker can't shrink this
# without removing items. Use items[] if present, else summed counters.
dec_items = dec_section.get("items") or []
dec_covered = len(dec_items) if dec_items else sum(
    int(dec_section.get(k, 0)) for k in ("accept", "edit", "skip", "reject", "a", "y", "s", "n")
)
goal_items = goal_section.get("items") or []
goal_covered = len(goal_items) if goal_items else sum(
    int(goal_section.get(k, 0)) for k in ("a", "y", "s", "n", "accept", "skip")
)

missing_dec = max(0, expected_dec - dec_covered)
missing_goal = max(0, expected_goals - goal_covered)
print(f"expected_dec={expected_dec},dec_covered={dec_covered},missing_dec={missing_dec},"
      f"expected_goals={expected_goals},goal_covered={goal_covered},missing_goal={missing_goal}")
PY
)

# Parse coverage output
MISSING_DEC=$(echo "$COVERAGE_CHECK" | sed -n 's/.*missing_dec=\([0-9]*\).*/\1/p')
MISSING_GOAL=$(echo "$COVERAGE_CHECK" | sed -n 's/.*missing_goal=\([0-9]*\).*/\1/p')
MISSING_DEC=${MISSING_DEC:-0}
MISSING_GOAL=${MISSING_GOAL:-0}

if [ "${MISSING_DEC:-0}" -gt 0 ] || [ "${MISSING_GOAL:-0}" -gt 0 ]; then
  echo "⛔ UAT coverage gate: responses don't cover all expected items" >&2
  echo "   $COVERAGE_CHECK" >&2
  echo "   Missing decisions=${MISSING_DEC}, Missing READY goals=${MISSING_GOAL}" >&2
  echo "   AI must ask + record ONE response per expected item. Partial-coverage" >&2
  echo "   JSON = attacker bypass, rejected." >&2
  if [[ ! "${ARGUMENTS}" =~ --allow-empty-uat ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_coverage_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing_dec\":${MISSING_DEC},\"missing_goal\":${MISSING_GOAL}}" >/dev/null 2>&1 || true
    exit 1
  fi
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-undercoverage" "${PHASE_NUMBER}" \
    "responses missing: dec=${MISSING_DEC}, goals=${MISSING_GOAL}" "${PHASE_DIR}"
fi

# Gate 2: count critical skips (decisions + READY goals)
CRITICAL_SKIPS=$(${PYTHON_BIN:-python3} - "$RESP_JSON" 2>/dev/null <<'PY' || echo 999
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0); exit()
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print(999); exit()  # malformed = treat as max skips

dec_skip = (data.get("decisions") or {}).get("skip", 0)
# Only count READY-goal skips as critical; BLOCKED/UNREACHABLE goals aren't asked
goal_items = (data.get("goals") or {}).get("items", [])
goal_skip_ready = sum(
    1 for it in goal_items
    if it.get("verdict") == "s" and it.get("status_before") == "READY"
)
# Fallback: if items[] not populated, use overall skip count
if not goal_items:
    goal_skip_ready = (data.get("goals") or {}).get("skip", 0)

print(int(dec_skip) + int(goal_skip_ready))
PY
)

TOTAL_SKIPS=$(${PYTHON_BIN:-python3} - "$RESP_JSON" 2>/dev/null <<'PY' || echo 0
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0); exit()
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print(0); exit()
total = 0
for section in ("decisions", "goals", "designs"):
    total += (data.get(section) or {}).get("skip", 0)
print(total)
PY
)

echo "▸ UAT quorum: critical skips=${CRITICAL_SKIPS} (threshold=${MAX_CRIT_SKIPS}), total skips=${TOTAL_SKIPS}"

if [ "${CRITICAL_SKIPS:-0}" -gt "${MAX_CRIT_SKIPS:-0}" ]; then
  echo "⛔ UAT quorum FAILED: ${CRITICAL_SKIPS} critical skips > ${MAX_CRIT_SKIPS} (max)." >&2
  echo "" >&2
  echo "Critical = decisions (A) + READY goals (B). These MUST be verified, not skipped." >&2
  echo "" >&2
  echo "Options:" >&2
  echo "  (a) Re-run /vg:accept ${PHASE_NUMBER} and actually verify the [s]-skipped items" >&2
  echo "  (b) Raise threshold in config: accept.max_uat_skips_critical: N" >&2
  echo "  (c) --allow-uat-skips override (logs to debt, DEFERRED verdict forced)" >&2

  if [[ ! "${ARGUMENTS}" =~ --allow-uat-skips ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"critical_skips\":${CRITICAL_SKIPS},\"threshold\":${MAX_CRIT_SKIPS}}" >/dev/null 2>&1 || true
    exit 1
  fi

  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "accept-uat-quorum" "${PHASE_NUMBER}" \
    "${CRITICAL_SKIPS} critical UAT skips (threshold ${MAX_CRIT_SKIPS})" "${PHASE_DIR}"

  echo "⚠ --allow-uat-skips — proceeding, forced DEFERRED verdict (not ACCEPTED)" >&2
  # Rewrite final verdict to DEFER so downstream /vg:next still blocks
  ${PYTHON_BIN:-python3} - "$RESP_JSON" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding="utf-8"))
d.setdefault("final", {})
d["final"]["verdict"] = "DEFER"
d["final"]["forced_by"] = "uat_quorum_override"
d["final"]["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
p.write_text(json.dumps(d, indent=2))
PY
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "accept.uat_quorum_passed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"critical_skips\":${CRITICAL_SKIPS},\"total_skips\":${TOTAL_SKIPS}}" >/dev/null 2>&1 || true

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_uat_quorum_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_uat_quorum_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 5_uat_quorum_gate 2>/dev/null || true
```
</step>
