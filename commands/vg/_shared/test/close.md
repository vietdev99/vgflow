# test close (STEP 8)

<!-- Exception: oversized ref (≈650 lines).
     close.md bundles 9 sub-steps (8.1 write_report → 8.3.9 tasklist
     close-on-complete) that MUST execute as one atomic terminal phase
     so the run-complete signal sees a consistent set of markers,
     telemetry events, and reports. Splitting would either fragment
     the Stop-hook contract (each piece running independently) or
     require fragile cross-file step ordering. Per review-v2 F3 nit. -->

Final 3 steps: write_report + bootstrap_reflection + complete (with
profile marker gate, traceability gate, flow compliance, tester-pro
D22/D23 reports, terminal telemetry, run-complete, tasklist clear).

<HARD-GATE>
You MUST execute all three steps. The Stop hook verifies:
- All `must_write` artifacts present + content_min_bytes met
- All `must_emit_telemetry` events present
- All `must_touch_markers` touched (per filter-steps profile)
- vg.block.fired count == vg.block.handled count
- State machine ordering valid

If ANY fails → exit 2 + diagnostic. Else → run successful + tasklist
projected closed/cleared per `close-on-complete`.
</HARD-GATE>

---

## STEP 8.1 — write_report

Assemble SANDBOX-TEST.md from runtime evidence: deploy SHA, contract
verify result, smoke check, goal table, fix-loop summary, codegen counts,
regression, security tier findings, weighted verdict.

**Verdict is COMPUTED — never AI-written.** Run the script below; read
`$VERDICT` from its output and embed verbatim. Do NOT re-evaluate or
override.

```bash
vg-orchestrator step-active write_report

VERDICT_JSON=$(${PYTHON_BIN} - <<'PYEOF'
import json, re, sys, glob
from pathlib import Path
import os

phase_dir = os.environ.get('PHASE_DIR')
vg_tmp = os.environ.get('VG_TMP')

# 1. Read TEST-GOALS.md — priority per goal.
# KEEP-FLAT: deterministic verdict computation, NOT AI/codegen context.
# Pure regex extraction of priority labels feeds the verdict math (review-v2
# D1 nit). vg-load --goal slice is unnecessary here because no AI agent
# consumes this read — the embedded Python is a verdict calculator.
tg_path = next(Path(phase_dir).glob('*TEST-GOALS*.md'), None)
if not tg_path:
    print(json.dumps({"error": "TEST-GOALS.md missing", "verdict": "FAILED"}))
    sys.exit(1)

tg = tg_path.read_text(encoding='utf-8')
goal_priority = {}
current = None
for line in tg.splitlines():
    m = re.match(r'^##\s*Goal\s+(G-\d+)', line)
    if m:
        current = m.group(1)
    mp = re.match(r'^\s*\*\*Priority:\*\*\s*(\w[\w-]*)', line, re.I)
    if mp and current:
        goal_priority[current] = mp.group(1).lower()

# 2. Read per-goal result JSONs
results = {}
for rf in glob.glob(f"{vg_tmp}/goal-*-result.json"):
    try:
        r = json.load(open(rf, encoding='utf-8'))
        results[r['goal_id']] = r['status']  # PASSED|FAILED|UNREACHABLE
    except Exception:
        pass

# 3. Bucket by priority
buckets = {'critical': {'pass': 0, 'total': 0},
           'important': {'pass': 0, 'total': 0},
           'nice-to-have': {'pass': 0, 'total': 0}}
for gid, prio in goal_priority.items():
    p = prio if prio in buckets else 'important'
    buckets[p]['total'] += 1
    if results.get(gid) == 'PASSED':
        buckets[p]['pass'] += 1

def pct(b):
    return 100.0 * b['pass'] / b['total'] if b['total'] > 0 else 100.0

crit_pct = pct(buckets['critical'])
imp_pct  = pct(buckets['important'])
nice_pct = pct(buckets['nice-to-have'])

# 4. Apply thresholds (critical 100%, important 80%, nice 50%)
verdict = 'PASSED'
reasons = []
if crit_pct < 100.0:
    verdict = 'FAILED'
    reasons.append(f"critical {crit_pct:.0f}% < 100%")
elif imp_pct < 80.0:
    verdict = 'GAPS_FOUND'
    reasons.append(f"important {imp_pct:.0f}% < 80%")
elif nice_pct < 50.0:
    verdict = 'GAPS_FOUND'
    reasons.append(f"nice {nice_pct:.0f}% < 50%")

print(json.dumps({
    "verdict": verdict,
    "reasons": reasons,
    "buckets": buckets,
    "counts": {"critical_pct": crit_pct, "important_pct": imp_pct,
               "nice_pct": nice_pct}
}))
PYEOF
)

VERDICT=$(echo "$VERDICT_JSON" | ${PYTHON_BIN} -c \
  "import json,sys; print(json.load(sys.stdin)['verdict'])")

# Persist — AI writer MUST embed this value verbatim
echo "$VERDICT_JSON" > "${PHASE_DIR}/.verdict-computed.json"
echo "Computed verdict: $VERDICT"
```

Write `${PHASE_DIR}/SANDBOX-TEST.md` using **only** the computed
`$VERDICT` and runtime counters. The path MUST exactly match the
`must_write` declaration in `commands/vg/test.md` runtime_contract — Stop
hook performs an exact-path check on this artifact and any deviation
(e.g. `{num}-SANDBOX-TEST.md`) will block run-complete.

```markdown
---
phase: "{phase}"
tested: "{ISO timestamp}"
status: "{PASSED | GAPS_FOUND | FAILED}"
deploy_sha: "{sha}"
environment: "{env}"
---

# Sandbox Test Report — Phase {phase}

## 5a Deploy
- SHA: {sha}
- Health: {OK|FAIL}

## 5b Runtime Contract Verify
- Endpoints: {N}/{total}
- Result: {PASS|BLOCK}

## 5c Smoke Check
- Views checked: 5
- Matches: {N}/5

## 5c Goal Verification
| Goal | Priority | Criteria | Passed | Failed | Status |
|------|----------|----------|--------|--------|--------|
(populated from goal verification — values from runtime)

### Goal Details
(per-goal breakdown with specific failures and screenshots)

### Fix Loop
- Minor fixes: {N}
- Escalated to review: {N}

### Feedback to Review
(if REVIEW-FEEDBACK.md was written — reference it here)

## 5d Codegen
- Files generated: {N}
- Tests generated: {N}

## 5e Regression
- Tests: {passed}/{total}

## 5f Security
- Tier 1: {findings}
- Tier 2: {tool|skipped}

## Verdict: {PASSED | GAPS_FOUND | FAILED}

Gate (weighted):
- Critical goals: {passed}/{total} (threshold: 100%)
- Important goals: {passed}/{total} (threshold: 80%)
- Nice-to-have goals: {passed}/{total} (threshold: 50%)
- Overall: {passed}/{total} ({percentage}%)
```

Commit artifacts:

```bash
git add "${PHASE_DIR}/SANDBOX-TEST.md" "${SCREENSHOTS_DIR}/" \
        "${GENERATED_TESTS_DIR}/" 2>/dev/null || true
git commit -m "test(${PHASE_NUMBER}): goal verification — ${VERDICT}, ${PASSED_GOALS:-?}/${TOTAL_GOALS:-?} goals passed"

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER:-unknown}" "write_report" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/write_report.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  mark-step test write_report 2>/dev/null || true
```

---

## STEP 8.2 — bootstrap_reflection (Human-Curated Learning)

End-of-test reflection: spawns **vg-reflector** subagent (isolated Haiku)
to analyze artifacts + telemetry slice + override-debt and draft learning
candidates for human review via `/vg:learn`.

**Terminology:** Previously "Self-Healing" — corrected to
**Human-Curated Learning**. Loop: reflector → candidate →
`/vg:learn --promote` (human gate) → ACCEPTED.md → inject next phase.
No autonomous rule promotion.

**Skip conditions** (exit 0, do nothing):
- `.vg/bootstrap/` directory absent (project not opted in)
- `config.bootstrap.reflection_enabled == false`
- Test verdict = fatal crash (reflect on next success)

```bash
vg-orchestrator step-active bootstrap_reflection

BOOTSTRAP_DIR=".vg/bootstrap"
if [ ! -d "$BOOTSTRAP_DIR" ]; then
  echo "Bootstrap not opted in — skipping reflection"
else
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-test-${REFLECT_TS}.yaml"
  USER_MSG_FILE="${VG_TMP}/reflect-user-msgs-${REFLECT_TS}.txt"
  : > "$USER_MSG_FILE"

  # Filter telemetry to this phase + command=test within last 4 hours
  TELEMETRY_SLICE="${VG_TMP}/reflect-telemetry-${REFLECT_TS}.jsonl"
  grep -E "\"phase\":\"${PHASE_NUMBER}\".*\"command\":\"vg:test\"" \
    "${PLANNING_DIR}/telemetry.jsonl" 2>/dev/null | tail -200 > "$TELEMETRY_SLICE" || true

  # Override-debt entries created during test
  OVERRIDE_SLICE="${VG_TMP}/reflect-overrides-${REFLECT_TS}.md"
  grep -E "\"step\":\"test\"" "${PLANNING_DIR}/OVERRIDE-DEBT.md" 2>/dev/null \
    > "$OVERRIDE_SLICE" || true

  bash scripts/vg-narrate-spawn.sh vg-reflector spawning \
    "phase ${PHASE_NUMBER} test reflection"
fi
```

### Spawn reflector (isolated Haiku, fresh context)

```
Agent(
  description="End-of-step reflection for test phase {PHASE_NUMBER}",
  subagent_type="general-purpose",
  prompt="""
Use skill: vg-reflector

Arguments:
  STEP           = "test"
  PHASE          = "{PHASE_NUMBER}"
  PHASE_DIR      = "{PHASE_DIR absolute path}"
  USER_MSG_FILE  = "{USER_MSG_FILE}"
  TELEMETRY_FILE = "{TELEMETRY_SLICE}"
  OVERRIDE_FILE  = "{OVERRIDE_SLICE}"
  ACCEPTED_MD    = ".vg/bootstrap/ACCEPTED.md"
  REJECTED_MD    = ".vg/bootstrap/REJECTED.md"
  OUT_FILE       = "{REFLECT_OUT}"

Read .claude/skills/vg-reflector/SKILL.md and follow workflow exactly.
Do NOT read parent conversation transcript — echo chamber forbidden.
Output max 3 candidates with evidence to OUT_FILE.
"""
)
```

After spawn exits:

```bash
bash scripts/vg-narrate-spawn.sh vg-reflector returned \
  "${CANDIDATE_COUNT:-0} candidates"
```

### Interactive promote flow (human gates)

After reflector exits, parse OUT_FILE. If candidates found, show:

```
Reflection — test phase {PHASE_NUMBER} found {N} learning(s):

[1] {title}
    Type: {type}  Scope: {scope}  Confidence: {confidence}
    Evidence: {count} items — {sample}
    → Proposed: {target summary}

    [y] ghi sổ tay  [n] reject  [e] edit inline  [s] skip lần này

[2] ...

User gõ: y/n/e/s cho từng item, hoặc "all-defer" để bỏ qua toàn bộ.
```

- `y` → delegate to `/vg:learn --promote L-{id}` (validates schema, dry-run preview, git commit)
- `n` → append to REJECTED.md with user reason
- `e` → interactive field-by-field edit loop
- `s` → leave candidate in `.vg/bootstrap/CANDIDATES.md`, review via `/vg:learn --review`

### Emit telemetry

```bash
emit_telemetry "bootstrap.reflection_ran" PASS \
  "{\"step\":\"test\",\"phase\":\"${PHASE_NUMBER}\",\"candidates\":${CANDIDATE_COUNT:-0}}"
```

### Failure mode

Reflector crash/timeout → log warning, continue to `complete`. Never
blocks test completion.

```
⚠ Reflection failed — test completes normally. Check .vg/bootstrap/logs/
```

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER:-unknown}" "bootstrap_reflection" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/bootstrap_reflection.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  mark-step test bootstrap_reflection 2>/dev/null || true
```

---

## STEP 8.3 — complete

### 8.3.1 — Artifact cleanup (tightened 2026-04-17)

Test runs accumulate transient screenshot/html/json artifacts. After
SANDBOX-TEST.md commits official evidence, clean up aggressively.

| Type | Path | Action |
|------|------|--------|
| Goal PASS/FAIL evidence | `${SCREENSHOTS_DIR}/{phase}-goal-*.png` | **KEEP** (committed) |
| Generated .spec.ts | `${GENERATED_TESTS_DIR}/{phase}-goal-*.spec.ts` | **KEEP** |
| Playwright test-results | `apps/*/test-results/`, `**/test-results/` | DELETE |
| Playwright report HTML | `playwright-report/`, `**/playwright-report/` | DELETE |
| Root-leaked screenshots | `./*.png`, `./screenshot-*.png` | DELETE (BANNED) |
| Probe retry dupes | `${SCREENSHOTS_DIR}/*-probe-*-retry[2+].png` | DELETE |
| Goal result JSONs | `${VG_TMP}/goal-*-result.json` | DELETE (verdict folded) |
| Baseline JSONs | `${VG_TMP}/goal-*-baseline.json` | DELETE |
| MCP snapshot dumps | `**/.playwright-mcp/`, `./snapshot-*.yaml` | DELETE |
| Debug videos/traces | `**/videos/*.webm`, `**/traces/*.zip` | DELETE if PASSED/GAPS |

```bash
vg-orchestrator step-active complete

echo "=== Test cleanup — removing transient artifacts ==="

# 1. Playwright junk dirs
find . -type d \( -name "test-results" -o -name "playwright-report" \
  -o -name ".playwright-mcp" \) \
  -not -path "./node_modules/*" -not -path "./.git/*" \
  -exec rm -rf {} + 2>/dev/null

# 2. Root-leaked screenshots (BANNED)
rm -f ./*.png ./screenshot-*.png ./snapshot-*.yaml 2>/dev/null

# 3. Probe retry dupes (keep retry=1, drop 2+)
if [ -d "${SCREENSHOTS_DIR}" ]; then
  find "${SCREENSHOTS_DIR}" -name "*-probe-*-retry[2-9]*.png" -delete 2>/dev/null
  find "${SCREENSHOTS_DIR}" -name "*-probe-*-retry[1-9][0-9]*.png" -delete 2>/dev/null
fi

# 4. VG_TMP artifacts (verdict already folded into .verdict-computed.json)
rm -f "${VG_TMP}"/goal-*-result.json 2>/dev/null
rm -f "${VG_TMP}"/goal-*-baseline.json 2>/dev/null
rm -f "${VG_TMP}"/vg-crossai-${PHASE_NUMBER}-*.md 2>/dev/null

# 5. Videos/traces — keep ONLY if FAILED (debug value)
if [ "$VERDICT" = "PASSED" ] || [ "$VERDICT" = "GAPS_FOUND" ]; then
  find . -type f \( -name "*.webm" -o -name "trace.zip" \) \
    -not -path "./node_modules/*" -not -path "./.git/*" -delete 2>/dev/null
else
  echo "Verdict = $VERDICT — keeping videos/traces for debug"
fi

echo "Cleanup complete. Evidence preserved: SANDBOX-TEST.md, goal-*.png, *.spec.ts"
```

### 8.3.2 — Update PIPELINE-STATE.json + ROADMAP.md

```bash
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'tested'; s['pipeline_step'] = 'test-complete'
s['test_verdict'] = '${VERDICT}'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

if [ -f "${PLANNING_DIR}/ROADMAP.md" ]; then
  sed -i "s/\*\*Status:\*\* .*/\*\*Status:\*\* tested/" \
    "${PLANNING_DIR}/ROADMAP.md" 2>/dev/null || true
fi
```

### 8.3.3 — Display summary

```
Test complete for Phase {N}.
  Deploy: {OK}
  Contract (runtime): {PASS}
  Smoke check: {N}/5 match
  Goals: {passed}/{total} (critical: {N}/{N}, important: {N}/{N})
  Fix loop: {minor_fixed} minor fixed, {escalated} escalated to review
  Regression: {passed}/{total} generated tests
  Security: {verdict}
  Verdict: {PASSED | GAPS_FOUND | FAILED}
```

### 8.3.4 — Verdict-aware Next routing (v2.43.2)

**MANDATORY** — print the Next block matching `$VERDICT`. Do NOT print a
generic `/vg:accept` when verdict ≠ PASSED (v2.43.1 footgun: users hit
accept-blocks-on-gaps loops).

```bash
case "${VERDICT:-UNKNOWN}" in
  PASSED)
    cat <<EOF
  Next:
    /vg:accept ${PHASE_NUMBER}    # All goals READY — proceed to human UAT
EOF
    ;;

  GAPS_FOUND)
    REMAINING=$(${PYTHON_BIN:-python3} -c "
import json; from pathlib import Path
p = Path('${PHASE_DIR}/.verdict-computed.json')
if p.exists():
    d = json.loads(p.read_text(encoding='utf-8'))
    print(len(d.get('goals_remaining', [])))
else: print('?')
" 2>/dev/null || echo "?")

    cat <<EOF
  Next (pick the matching path — DO NOT run /vg:accept blindly;
  it will register OVERRIDE-DEBT for ${REMAINING} non-critical gaps
  OR BLOCK if any are critical):

    ▸ FIRST — read root cause:
        cat ${PHASE_DIR}/REVIEW-FEEDBACK.md
        cat ${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md

    A) Code bugs you fixed manually:
       /vg:test ${PHASE_NUMBER} --regression-only
    B) Test spec wrong (selector / wait / data setup):
       /vg:test ${PHASE_NUMBER} --skip-deploy
    C) Root cause is runtime bug review didn't catch:
       /vg:review ${PHASE_NUMBER} --retry-failed
    D) Goal needs non-E2E verification (perf / worker):
       # Mark SKIPPED in GOAL-COVERAGE-MATRIX.md + /vg:accept
    E) Goal spec unrealistic / scope drift:
       /vg:amend ${PHASE_NUMBER}
    F) Fix-loop budget exhausted but root cause resolved:
       rm ${PHASE_DIR}/.fix-loop-state.json
       /vg:test ${PHASE_NUMBER}
    G) Accept with documented debt (NON-critical only):
       /vg:accept ${PHASE_NUMBER}

    Don't do:
      ❌ /vg:build ${PHASE_NUMBER} --gaps-only   (code exists — review confirmed)
      ❌ /vg:review ${PHASE_NUMBER}              (full re-review wastes tokens)
      ❌ Loop /vg:test without changes           (budget won't reset)
EOF
    ;;

  FAILED)
    cat <<EOF
  ⛔ Verdict FAILED — /vg:accept WILL BLOCK with hard-gate redirect.

  Next (mandatory — /vg:accept is NOT a valid path):

    A) Critical assertion failure (data / auth / contract):
       cat ${PHASE_DIR}/REVIEW-FEEDBACK.md
       /vg:test ${PHASE_NUMBER} --regression-only
    B) Service / infra crash:
       /vg:doctor
    C) Security finding blocks (Tier 0 / OWASP critical):
       cat ${PHASE_DIR}/.security-findings.json
    D) Test framework / codegen bug (false positive):
       /vg:bug-report
    E) Disagree with verdict (rare, justify in writing):
       /vg:test ${PHASE_NUMBER} --override-reason "<text>" --allow-failed=G-XX
EOF
    ;;

  *)
    echo "  Verdict UNKNOWN — read SANDBOX-TEST.md for state, then re-run /vg:test."
    ;;
esac
```

### 8.3.5 — Profile marker gate + traceability + flow compliance

```bash
# v2.46 — test-traces-to-rule gate
TRACE_MODE="${VG_TRACEABILITY_MODE:-block}"
TTRACE_VAL=".claude/scripts/validators/verify-test-traces-to-rule.py"
if [ -f "$TTRACE_VAL" ]; then
  TTRACE_FLAGS="--severity ${TRACE_MODE}"
  [[ "${ARGUMENTS}" =~ --allow-test-untraced ]] && \
    TTRACE_FLAGS="$TTRACE_FLAGS --allow-test-untraced"
  ${PYTHON_BIN:-python3} "$TTRACE_VAL" --phase "${PHASE_NUMBER}" $TTRACE_FLAGS
  TTRACE_RC=$?
  if [ "$TTRACE_RC" -ne 0 ] && [ "$TRACE_MODE" = "block" ]; then
    echo "⛔ Test-traces-to-rule gate failed: .spec.ts files don't cite goal_id + BR-NN."
    echo "   Header format: '// Goal: G-XX | Rule: BR-NN | Assertion: <verbatim quote>'"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
      emit-event "test.trace_blocked" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

# Profile-aware marker gate — blocks if any profile-scoped step missed marker
EXPECTED_TEST_STEPS=$(${PYTHON_BIN:-python3} .claude/scripts/filter-steps.py \
  --command .claude/commands/vg/test.md \
  --profile "${PROFILE:-web-fullstack}" \
  --output-ids 2>/dev/null || echo "")
MISSING_TEST_MARKERS=""
for STEP_ID in $(echo "$EXPECTED_TEST_STEPS" | tr ',' ' '); do
  [ -z "$STEP_ID" ] && continue
  [ "$STEP_ID" = "complete" ] && continue
  if [ -f "${PHASE_DIR}/.step-markers/test/${STEP_ID}.done" ] || \
     [ -f "${PHASE_DIR}/.step-markers/${STEP_ID}.done" ]; then
    :
  else
    MISSING_TEST_MARKERS="${MISSING_TEST_MARKERS} ${STEP_ID}"
  fi
done
if [ -n "$(echo "$MISSING_TEST_MARKERS" | xargs)" ]; then
  echo "⛔ /vg:test profile marker gate BLOCKED — missing for ${PROFILE:-web-fullstack}:"
  for STEP_ID in $MISSING_TEST_MARKERS; do echo "   - ${STEP_ID}"; done
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
    emit-event "test.marker_gate_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"profile\":\"${PROFILE:-web-fullstack}\",\"missing\":\"$(echo "$MISSING_TEST_MARKERS" | xargs)\"}" \
    >/dev/null 2>&1 || true
  exit 1
fi
```

### 8.3.6 — Tester-pro D22/D23 reports (RFC v9)

```bash
TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ]; then
  echo "━━━ D22 — TEST-SUMMARY-REPORT.md ━━━"
  "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" summary render \
    --phase "${PHASE_NUMBER}" 2>&1 | sed 's/^/  D22: /' || true

  echo "━━━ D23 — RTM.md (bi-directional traceability) ━━━"
  GOALS_FIRST_COMMIT_TS=$(git log --reverse --format=%ct -- \
    "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null | head -1)
  GRANDFATHER_CUTOFF=$(date -u -j -f "%Y-%m-%d" "2026-05-01" +%s 2>/dev/null \
    || date -u -d "2026-05-01" +%s 2>/dev/null || echo "0")
  if [ -n "$GOALS_FIRST_COMMIT_TS" ] && \
     [ "$GOALS_FIRST_COMMIT_TS" -lt "$GRANDFATHER_CUTOFF" ]; then
    RTM_SEVERITY="warn"
  else
    RTM_SEVERITY="block"
  fi
  "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" rtm render \
    --phase "${PHASE_NUMBER}" --severity "$RTM_SEVERITY" 2>&1 | sed 's/^/  D23: /' || true
  RTM_RC=$?
  if [ "${RTM_RC:-0}" -eq 1 ] && [ "$RTM_SEVERITY" = "block" ]; then
    echo "⛔ D23 BLOCK: RTM has orphan goals or orphan requirements."
    echo "   Every goal must trace to a D-XX decision; every D-XX needs ≥1 goal."
    exit 1
  fi
fi
```

### 8.3.7 — Flow compliance audit (v2.38.0)

```bash
if [[ "$ARGUMENTS" =~ --skip-compliance=\"([^\"]*)\" ]]; then
  COMP_REASON="${BASH_REMATCH[1]}"
else
  COMP_REASON=""
fi
COMP_SEV=$(vg_config_get "flow_compliance.severity" "warn" 2>/dev/null || echo "warn")
COMP_ARGS=( "--phase-dir" "$PHASE_DIR" "--command" "test" "--severity" "$COMP_SEV" )
[ -n "$COMP_REASON" ] && COMP_ARGS+=( "--skip-compliance=$COMP_REASON" )

${PYTHON_BIN:-python3} .claude/scripts/verify-flow-compliance.py "${COMP_ARGS[@]}"
COMP_RC=$?
if [ "$COMP_RC" -ne 0 ] && [ "$COMP_SEV" = "block" ]; then
  echo "⛔ Test flow compliance failed. Pass --skip-compliance=\"<reason>\" to override."
  exit 1
fi
```

### 8.3.8 — Terminal telemetry + run-complete

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER:-unknown}" "complete" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/complete.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  mark-step test complete 2>/dev/null || true
# NOTE: 0_parse_and_validate is marked exactly once during preflight STEP 1.3
# (see _shared/test/preflight.md). Re-marking it here would double-count and
# confuse the marker timeline — review-v2 B4.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  emit-event "test.completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"verdict\":\"${VERDICT}\"}" >/dev/null

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ test run-complete BLOCK — review orchestrator output + fix" >&2
  exit $RUN_RC
fi
```

### 8.3.9 — Tasklist close-on-complete

Mark all checklist items completed via TodoWrite. Then clear the list or
replace with sentinel: `vg:test phase ${PHASE_NUMBER} complete`.

The PostToolUse TodoWrite hook captures the final state for evidence.

---

## Success criteria

- SANDBOX-TEST.md written with computed verdict (STEP 8.1)
- Verdict script ran — `$VERDICT` embedded verbatim, not AI-guessed (STEP 8.1)
- Bootstrap reflection spawned via narrate-spawn (STEP 8.2)
- Candidates presented to user for y/n/e/s approval (STEP 8.2)
- `bootstrap.reflection_ran` telemetry emitted (STEP 8.2)
- Transient artifacts cleaned: test-results/, playwright-report/, VG_TMP JSONs (STEP 8.3.1)
- PIPELINE-STATE.json updated to `tested` (STEP 8.3.2)
- Verdict-aware Next block printed (STEP 8.3.4)
- Test-traces-to-rule gate PASS (STEP 8.3.5)
- Profile marker gate PASS (STEP 8.3.5)
- D22 TEST-SUMMARY-REPORT.md + D23 RTM.md generated (STEP 8.3.6)
- Flow compliance PASS or WARN (STEP 8.3.7)
- `test.completed` telemetry emitted (STEP 8.3.8)
- `vg-orchestrator run-complete` exits 0 (STEP 8.3.8)
- Stop hook verifies runtime_contract + state-machine + diagnostic pairing
- Tasklist closed/cleared (STEP 8.3.9)
- Next step guidance is verdict-specific (STEP 8.3.4)
