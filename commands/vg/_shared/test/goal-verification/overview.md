# test goal-verification (STEP 4 — HEAVY, subagent)

HEAVY step. You MUST delegate goal verification to
`vg-test-goal-verifier` subagent (tool name `Agent`, not `Task`).

<HARD-GATE>
DO NOT verify goals inline. DO NOT replay goal sequences in the main agent.
You MUST spawn `vg-test-goal-verifier` for step 5c_goal_verification.

The subagent handles:
- TRUST REVIEW mode (v1.14.0+ B.1 default): trust /vg:review's 100% gate;
  skip full replay loop; run baseline console check + spot-check non-READY goals.
- Legacy mode (TRUST_REVIEW=false / skip_ready_reverify=false in vg.config.md):
  full replay loop with topological sort + per-step console/network checks.

You MUST NOT generate goal verdicts, screenshots, or GOAL-COVERAGE-MATRIX
updates inline in the main agent. All verification output comes from the
subagent's return JSON.

Skipping requires `--skip-goal-verification` + override-debt log.
</HARD-GATE>

---

## Orchestration order

1. **Pre-spawn**: `vg-orchestrator step-active 5c_goal_verification`. Read
   GOAL-COVERAGE-MATRIX.md to determine trust-review mode vs legacy mode.
2. **Spawn**: `Agent(subagent_type="vg-test-goal-verifier", prompt=<from delegation.md>)`
3. **Post-spawn validation**:
   - Validate output JSON schema (goals_verified array + baseline_console_check_pass).
   - Update GOAL-COVERAGE-MATRIX.md with test verdicts.
   - Emit telemetry.
4. **Mark step 5c_goal_verification**.

---

## STEP 4.1 — pre-spawn checklist

```bash
vg-orchestrator step-active 5c_goal_verification

# Inject rule cards (harness v2.6.1)
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-test" "5c_goal_verification" 2>&1 || true

# Verify TEST-GOALS.md exists (written by /vg:blueprint)
[ -f "${PHASE_DIR}/TEST-GOALS.md" ] || {
  echo "⛔ TEST-GOALS.md missing — run /vg:blueprint ${PHASE_NUMBER} first."
  exit 1
}

# Verify RUNTIME-MAP.json exists (written by /vg:review)
[ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || {
  echo "⛔ RUNTIME-MAP.json missing — run /vg:review ${PHASE_NUMBER} first."
  echo "   (RUNTIME-MAP.json is written by the review step; test reads it.)"
  exit 1
}

# Verify GOAL-COVERAGE-MATRIX.md exists (written by /vg:review)
[ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ] || {
  echo "⛔ GOAL-COVERAGE-MATRIX.md missing — run /vg:review ${PHASE_NUMBER} first."
  exit 1
}

# Determine trust-review mode (v1.14.0+ B.1)
SKIP_REVERIFY=$(${PYTHON_BIN:-python3} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'skip_ready_reverify\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'true')  # default true for v1.14.0+
except Exception:
    print('true')
")
export TRUST_REVIEW="${SKIP_REVERIFY}"

if [ "$TRUST_REVIEW" = "true" ]; then
  echo ""
  echo "━━━ v1.14.0+ B.1: TRUST REVIEW mode ━━━"
  echo "Review 100% gate verified goals — vg-test-goal-verifier runs baseline"
  echo "console check + spot-check non-READY goals only."
  echo ""
else
  echo "ℹ skip_ready_reverify=false — legacy replay loop (pre-v1.14 behavior)."
fi

# Discover goal IDs via vg-load --list (cheap index), then slice ONE goal at a
# time via `vg-load --goal G-NN` for the subagent. NEVER cat flat TEST-GOALS.md
# for AI consumption — per-goal slice keeps verifier context bounded and lets
# evidence cite stable goal-id paths. See review-v2 D1/D2.
GOAL_INDEX=$(vg-load --phase "${PHASE_NUMBER}" --artifact goals --list 2>/dev/null)
if [ -z "$GOAL_INDEX" ]; then
  echo "⛔ vg-load --list returned empty — run /vg:blueprint ${PHASE_NUMBER} first."
  exit 1
fi
GOAL_IDS=$(echo "$GOAL_INDEX" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(' '.join(g.get('id','') for g in d.get('goals',[]) if g.get('id')))" 2>/dev/null)
GOAL_COUNT=$(echo "$GOAL_IDS" | wc -w | tr -d ' ')
[ "$GOAL_COUNT" -gt 0 ] || { echo "⛔ no goal ids parsed from vg-load --list"; exit 1; }

# Pre-fetch each goal's slice once into VG_TMP — verifier reads slice files
# (per-goal vg-load --goal output), never the flat TEST-GOALS.md.
VG_TMP_DIR="${VG_TMP:-${PHASE_DIR}/.vg-tmp}"
mkdir -p "${VG_TMP_DIR}/goals" 2>/dev/null
for GID in $GOAL_IDS; do
  vg-load --phase "${PHASE_NUMBER}" --artifact goals --goal "$GID" \
    > "${VG_TMP_DIR}/goals/${GID}.json" 2>/dev/null || true
done
echo "✓ Goals sliced via vg-load --goal: ${GOAL_COUNT} goal(s) in ${VG_TMP_DIR}/goals/"
```

---

## STEP 4.2 — spawn vg-test-goal-verifier

Read `goal-verification/delegation.md` for the full prompt template.
**MANDATORY**: emit colored-tag narration before + after the spawn
(per vg-meta-skill).

```bash
bash scripts/vg-narrate-spawn.sh vg-test-goal-verifier spawning \
  "phase ${PHASE_NUMBER} goals (trust_review=${TRUST_REVIEW})"
```

Then call:
```
Agent(subagent_type="vg-test-goal-verifier", prompt=<rendered template>)
```

The subagent:
- In TRUST REVIEW mode: runs baseline console check, spot-checks non-READY
  goals (BLOCKED/UNREACHABLE/DEFERRED), emits goals_verified array with
  status derived from GOAL-COVERAGE-MATRIX review verdicts.
- In legacy mode: replays all goals in topological order with per-step
  console/network checks, emits full goals_verified array.

Returns JSON with goals_verified array + baseline_console_check_pass bool.

```bash
bash scripts/vg-narrate-spawn.sh vg-test-goal-verifier returned \
  "goal verdicts ready"
```

If subagent error JSON or empty output:
```bash
bash scripts/vg-narrate-spawn.sh vg-test-goal-verifier failed "<one-line cause>"
```

---

## STEP 4.3 — post-spawn validation

### Validate output contract

```bash
# goals_verified must be a non-empty array
GOALS_VERIFIED=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('goals_verified',[])))" 2>/dev/null || echo 0)

[ "${GOALS_VERIFIED:-0}" -gt 0 ] || {
  echo "⛔ vg-test-goal-verifier returned empty goals_verified array."
  echo "   Re-spawn or check delegation.md input contract."
  exit 1
}

# baseline_console_check_pass must be present
CONSOLE_PASS=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('baseline_console_check_pass','MISSING'))" 2>/dev/null || echo "MISSING")

[ "$CONSOLE_PASS" != "MISSING" ] || {
  echo "⛔ vg-test-goal-verifier did not return baseline_console_check_pass."
  exit 1
}

echo "✓ Output validated: ${GOALS_VERIFIED} goal verdicts, console_pass=${CONSOLE_PASS}"
```

### Update GOAL-COVERAGE-MATRIX.md

```bash
# Merge test verdicts back into GOAL-COVERAGE-MATRIX.md
# Each entry in goals_verified has: goal_id, status, evidence_ref
${PYTHON_BIN:-python3} - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" "${SUBAGENT_OUTPUT}" <<'PY'
import json, sys, re
from pathlib import Path

matrix_path = Path(sys.argv[1])
results = json.loads(sys.argv[2])
text = matrix_path.read_text(encoding='utf-8')

for item in results.get('goals_verified', []):
    gid = item.get('goal_id', '')
    status = item.get('status', 'UNKNOWN')
    status_map = {
        'PASSED': 'TEST-PASSED',
        'FAILED': 'TEST-FAILED',
        'UNREACHABLE': 'TEST-UNREACHABLE',
        'SKIPPED': 'TEST-SKIPPED (trust-review)',
    }
    label = status_map.get(status, status)
    # Replace review-time status with test verdict inline
    text = re.sub(
        rf'(\|\s*{re.escape(gid)}\s*\|[^|]*\|)[^|]*(\|)',
        lambda m: m.group(1) + f' {label} ' + m.group(2),
        text
    )

matrix_path.write_text(text, encoding='utf-8')
print(f"Updated GOAL-COVERAGE-MATRIX.md with {len(results.get('goals_verified', []))} verdicts")
PY
```

### Emit telemetry

```bash
PASSED_N=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; v=json.load(sys.stdin).get('goals_verified',[]); print(sum(1 for g in v if g.get('status')=='PASSED'))" 2>/dev/null || echo 0)
FAILED_N=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; v=json.load(sys.stdin).get('goals_verified',[]); print(sum(1 for g in v if g.get('status')=='FAILED'))" 2>/dev/null || echo 0)

type -t emit_telemetry_v2 >/dev/null 2>&1 && \
  emit_telemetry_v2 "test_goal_verification" "${PHASE_NUMBER}" \
    "test.5c_goal_verification" "goal_verification" \
    "${FAILED_N:+FAIL}${FAILED_N:-PASS}" \
    "{\"passed\":${PASSED_N},\"failed\":${FAILED_N},\"trust_review\":${TRUST_REVIEW}}" \
  2>/dev/null || true
```

### Mark step 5c_goal_verification

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER:-unknown}" "5c_goal_verification" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/5c_goal_verification.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  mark-step test 5c_goal_verification 2>/dev/null || true
```

After marker touched, return to test.md entry skill → STEP 5 (codegen B.2).
