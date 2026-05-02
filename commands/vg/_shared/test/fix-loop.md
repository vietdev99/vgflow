# test fix-loop (STEP 6)

2 steps: 5c_fix, 5c_auto_escalate.

<HARD-GATE>
Both steps run for ALL profiles (web-fullstack, web-backend-only, web-frontend-only,
mobile-*). Each finishes with a marker touch + `vg-orchestrator mark-step test <step>`.
Skipping ANY step = Stop hook block.

If all goals PASSED after 5c_goal → skip BOTH steps; proceed to 5d.
</HARD-GATE>

---

## STEP 6.1 — minor fix only (5c_fix) [profile: all]

**If all goals PASSED → skip to 5d.**

### Pre-flight: emit fix-plans.json BEFORE editing code

Before any fix attempt, write `${PHASE_DIR}/.test-fix-plans.json`:

```json
[
  {
    "goal_id": "G-04",
    "failure_symptom": "Toast text wrong language",
    "files_to_edit": ["apps/web/src/i18n/vi.ts"],
    "change_type": "ui_cosmetic",
    "claimed_severity": "MINOR"
  }
]
```

`change_type` must be one of: `ui_cosmetic | logic | contract | shared | new_feature`.

### Auto-severity gate (deterministic — R4 enforcement)

```bash
FIX_PLAN="${PHASE_DIR}/.test-fix-plans.json"
if [ ! -f "$FIX_PLAN" ]; then
  echo "⛔ R4 gate: .test-fix-plans.json not emitted before fix."
  echo "   Format required: [{goal_id, files_to_edit[], change_type, claimed_severity}]"
  exit 1
fi

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$FIX_PLAN" "${PHASE_DIR}" <<'PY'
import json, sys
from pathlib import Path

plans = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
phase_dir = Path(sys.argv[2])

if isinstance(plans, dict):
    plans = [plans]

CONTRACT_PATHS = ('apps/api/src/modules/', 'apps/api/src/routes/', 'apps/api/src/schemas/', 'apps/api/src/contracts/')
SHARED_PATHS   = ('packages/', 'apps/web/src/lib/', 'apps/web/src/hooks/', 'apps/web/src/stores/')

auto_escalations = []
minor_plans = []
for plan in plans:
    gid = plan.get('goal_id', '?')
    files = plan.get('files_to_edit', []) or []
    ctype = plan.get('change_type', 'logic')
    claimed = plan.get('claimed_severity', 'MINOR')

    severity = 'MINOR'
    reasons = []

    if len(files) >= 3:
        severity = 'MODERATE'
        reasons.append(f"{len(files)} files >= 3 (wide scope)")

    if any(any(f.startswith(p) for p in CONTRACT_PATHS) for f in files):
        severity = 'MODERATE'
        reasons.append("touches API contract path (BE<->FE alignment risk)")

    if any(any(f.startswith(p) for p in SHARED_PATHS) for f in files):
        if severity != 'MAJOR':
            severity = 'MODERATE'
        reasons.append("touches shared path (ripple effect)")

    if ctype == 'new_feature':
        severity = 'MAJOR'
        reasons.append("new_feature (not a test concern)")

    if ctype == 'contract':
        severity = 'MAJOR'
        reasons.append("contract change (touches BE<->FE schema)")

    plan['computed_severity'] = severity
    plan['gate_reasons'] = reasons

    if severity in ('MODERATE', 'MAJOR'):
        auto_escalations.append(plan)
    else:
        minor_plans.append(plan)

Path(sys.argv[1]).write_text(json.dumps(plans, indent=2, ensure_ascii=False), encoding='utf-8')

if auto_escalations:
    feedback = phase_dir / "REVIEW-FEEDBACK.md"
    md = ["# Review Feedback — Auto-escalated from /vg:test R4 gate", ""]
    md.append(f"**{len(auto_escalations)} goal(s) auto-classified MODERATE/MAJOR — test will NOT fix; kick back to review.**")
    md.append("")
    md.append("| Goal | AI claimed | Computed | Reasons | Files |")
    md.append("|---|---|---|---|---|")
    for e in auto_escalations:
        files_str = ', '.join(e['files_to_edit'][:3])
        if len(e['files_to_edit']) > 3:
            files_str += f" (+{len(e['files_to_edit'])-3} more)"
        md.append(f"| {e['goal_id']} | {e.get('claimed_severity','?')} | **{e['computed_severity']}** | {'; '.join(e['gate_reasons'])} | {files_str} |")
    md.append("")
    md.append("## Next step")
    md.append("```bash")
    md.append(f"/vg:review {phase_dir.name.split('-')[0]} --retry-failed")
    md.append("```")
    feedback.write_text("\n".join(md), encoding='utf-8')

    print(f"⛔ R4 gate: {len(auto_escalations)} goal(s) auto-escalated -> REVIEW-FEEDBACK.md")
    print(f"   MINOR remaining: {len(minor_plans)} (test may fix)")
    print("")
    print("Test WILL NOT fix escalated goals. Continue with MINOR only + run /vg:review --retry-failed for MODERATE/MAJOR.")
    sys.exit(2)
else:
    print(f"✓ R4 pre-flight: {len(minor_plans)} plan(s) in MINOR scope — proceed with fix.")
PY

SEV_RC=$?
if [ "$SEV_RC" = "2" ]; then
  # Filter escalated plans out — keep MINOR only
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$FIX_PLAN" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
plans = json.loads(path.read_text(encoding='utf-8'))
if isinstance(plans, dict):
    plans = [plans]
minor = [p for p in plans if p.get('computed_severity') == 'MINOR']
path.write_text(json.dumps(minor, indent=2, ensure_ascii=False), encoding='utf-8')
PY
fi
```

### Severity reference

```
MINOR (test fixes directly):
  - Wrong text/label (typo, translation key)
  - CSS/layout issue (z-index, overflow, display)
  - Off-by-one (pagination, count)
  - Missing null check (undefined in edge case)
  → FIX immediately, commit: "fix({phase}): {description}"
  → Re-verify THIS goal only

MODERATE (auto-escalate to review):
  - API returns wrong status code (touches contract path)
  - Form validation missing (touches shared hooks/lib)
  - Data not refreshing after mutation (touches multiple files)
  - Touches >=3 files — ripple outside test scope

MAJOR (auto-escalate to review):
  - Feature completely missing (change_type=new_feature)
  - Contract schema change (change_type=contract)
  - Navigation path broken
  - Auth/permissions wrong
```

**Fix iteration (max 2 — MINOR only):**
```
Iteration 1:
  1. Fix all MINOR issues → commit each
  2. Re-verify affected goals only (not full suite)
  3. Update RUNTIME-MAP.json with fixes

Iteration 2 (if still MINOR failures):
  1. Remaining MINOR → fix + commit
  2. Re-verify
  3. If STILL failing → reclassify as MODERATE → escalate
```

Display:
```
5c Fix:
  Goals attempted: {N}
  MINOR fixed: {N}
  MODERATE/MAJOR escalated: {N} -> REVIEW-FEEDBACK.md
  Result: {PROCEED|ESCALATED}
```

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_fix" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_fix.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_fix 2>/dev/null || true
```

---

## STEP 6.2 — auto-loop to resolution (5c_auto_escalate) [profile: all]

**Goal: avoid stopping at "gaps found" and requiring user to manually chain test → review → build. Auto-chain until PASSED or budget hit.**

Loop counter: `TOTAL_ITER` — persisted in `${PHASE_DIR}/.fix-loop-state.json`, survives re-invocations (OHOK B5 B8 2026-04-23: real persistent counter, not prose fiction).

```bash
# Load or initialize persistent counter
FIX_LOOP_STATE="${PHASE_DIR}/.fix-loop-state.json"
MAX_ITER=$(vg_config_get test.max_fix_loop_iterations 3 2>/dev/null || echo 3)

if [ ! -f "$FIX_LOOP_STATE" ]; then
  ${PYTHON_BIN:-python3} - <<PY > "$FIX_LOOP_STATE"
import json
from datetime import datetime, timezone
ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(json.dumps({
    "iteration_count": 0,
    "first_run_ts": ts_now,
    "last_run_ts": ts_now,
    "max_iterations": ${MAX_ITER},
    "escalations": [],
}, indent=2))
PY
  TOTAL_ITER=0
else
  TOTAL_ITER=$(${PYTHON_BIN:-python3} -c "
import json; d=json.load(open('${FIX_LOOP_STATE}', encoding='utf-8'))
print(d.get('iteration_count', 0))
" 2>/dev/null || echo 0)
fi

echo "Fix loop: iteration ${TOTAL_ITER}/${MAX_ITER}"

# Budget enforcement — hard stop at MAX_ITER
if [ "${TOTAL_ITER:-0}" -ge "${MAX_ITER:-3}" ]; then
  echo "⛔ Auto-resolve budget exhausted (${TOTAL_ITER}/${MAX_ITER} iterations)." >&2
  echo "   See FINAL GUIDANCE below for next actions." >&2

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test.fix_loop_exhausted" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"iterations\":${TOTAL_ITER},\"max\":${MAX_ITER}}" >/dev/null 2>&1 || true

  # Don't exit here — let step write SANDBOX-TEST.md verdict=GAPS_FOUND + REVIEW-FEEDBACK.md
  # To reset: rm ${PHASE_DIR}/.fix-loop-state.json && /vg:test ${PHASE_NUMBER}
  BUDGET_EXHAUSTED=true
fi

# Increment counter (only if not at budget)
if [ "${BUDGET_EXHAUSTED:-false}" != "true" ]; then
  TOTAL_ITER=$((TOTAL_ITER + 1))
  ${PYTHON_BIN:-python3} - <<PY > "$FIX_LOOP_STATE"
import json
from datetime import datetime, timezone
from pathlib import Path
d = json.loads(Path("${FIX_LOOP_STATE}").read_text(encoding="utf-8"))
d["iteration_count"] = ${TOTAL_ITER}
d["last_run_ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
d.setdefault("escalations", []).append({
    "iteration": ${TOTAL_ITER},
    "ts": d["last_run_ts"],
})
print(json.dumps(d, indent=2))
PY
  echo "  Incremented -> ${TOTAL_ITER}/${MAX_ITER}"
fi
```

After 5c_fix completes, classify remaining failures and route:

```
remaining_failures = goals still NOT READY after MINOR fixes

IF remaining_failures == 0:
  -> skip to 5d (codegen)

IF TOTAL_ITER >= 3:
  -> STOP auto-loop. Write SANDBOX-TEST.md verdict=GAPS_FOUND.
  -> Write REVIEW-FEEDBACK.md with "What to do next" section.
  -> Print FINAL GUIDANCE block (below).
  -> Do NOT escalate further.

ELSE classify remaining_failures and auto-invoke:

  (A) MODERATE/MAJOR code bugs (API wrong, validation missing, data mismatch):
      -> TOTAL_ITER += 1
      -> Auto-invoke: /vg:review {phase} --retry-failed
      -> After review -> re-evaluate goals -> loop back

  (B) UNREACHABLE goals resurface (view not found even with codegen):
      -> Cross-reference code (grep pattern/route files):
         IF code missing -> auto-invoke: /vg:build {phase} --gaps-only
         IF code exists  -> route as MODERATE (type A)
      -> After build/review -> re-evaluate -> loop back

  (C) NOT_SCANNED persisting (wizard not walked by Playwright):
      -> Inspect test file for selector / wait timing issues
      -> TOTAL_ITER += 1
      -> Regenerate specific test: /vg:test {phase} --skip-deploy
      -> After regen -> rerun -> loop back

  (D) Goal marked SKIPPED (not E2E-verifiable — perf/worker/cross-system):
      -> Do NOT loop. Mark in SANDBOX-TEST.md with reason.
      -> Delegate to: k6 (perf), vitest integration (worker), manual UAT
      -> Update GOAL-COVERAGE-MATRIX: status=SKIPPED with justification
```

**Termination conditions (hard stops):**
```
1. All goals READY -> PASSED -> proceed to 5d
2. TOTAL_ITER == 3 -> STOP with GAPS_FOUND + REVIEW-FEEDBACK.md
3. Pre-flight fail (service crashed mid-loop) -> STOP, user fixes infra
4. User interrupts (Ctrl+C / cancel) -> STOP, save state for resume
```

**FINAL GUIDANCE when budget exhausted:**

```
⛔ Auto-resolve budget exhausted (3/3 iterations).

Remaining failures: {N} goals still NOT READY
  - [BLOCKED]     {goal_id}: {reason}
  - [NOT_SCANNED] {goal_id}: {reason}
  - [UNREACHABLE] {goal_id}: {reason}

Root cause is usually DEEPER than code bugs:
  (a) Goal criteria too strict / not achievable with current design
  (b) Test strategy mismatch (needs k6/vitest, not E2E)
  (c) Spec bug (blueprint missed a requirement)
  (d) Cross-phase dependency (other phase broken)

Step 1 — INVESTIGATE first:
  cat ${PLANNING_DIR}/phases/{phase}/REVIEW-FEEDBACK.md
  cat ${PLANNING_DIR}/phases/{phase}/GOAL-COVERAGE-MATRIX.md

Then choose:

A) Code bugs you can fix manually:
   /vg:test {phase} --regression-only

B) Test spec wrong (selector, wait, data setup):
   /vg:test {phase} --skip-deploy    # re-codegen + run

C) Goal spec unrealistic:
   # Edit TEST-GOALS.md -> loosen criteria or reclassify priority
   /vg:test {phase} --regression-only

D) Goal needs non-E2E verification (perf, worker, cross-system):
   # Write dedicated test (k6/vitest/integration)
   # Mark SKIPPED in GOAL-COVERAGE-MATRIX.md with link to alt test
   /vg:accept {phase}

E) Reset budget + retry (only after fixing root cause):
   rm ${PHASE_DIR}/.fix-loop-state.json
   /vg:test {phase}

F) Root cause is upstream (infra / prior phase broken):
   /vg:review {phase} --retry-failed
   /vg:test {phase} --regression-only

Don't:
  ❌ /vg:build {phase} --gaps-only       (code exists — check REVIEW-FEEDBACK first)
  ❌ /vg:review {phase}                  (use --retry-failed, not full re-review)
  ❌ Loop /vg:test again without changes (budget won't reset)
```

**Progress display (per iteration):**
```
[Auto-escalate 1/3] MODERATE bug found -> invoking /vg:review --retry-failed ...
[Auto-escalate 2/3] UNREACHABLE + code missing -> /vg:build --gaps-only ...
[Auto-escalate 3/3] Still 2 goals failing -> STOP. See FINAL GUIDANCE above.
```

**Why budget = 3:** iteration 1 = test fix; iteration 2 = review/build; iteration 3 = final verify. More = loop hides real problem.

Display:
```
5c Fix Loop:
  Minor fixes: {N} (resolved: {N})
  Moderate escalated: {N} -> REVIEW-FEEDBACK.md
  Major escalated: {N} -> REVIEW-FEEDBACK.md
  Iterations: {N}/3
  Goals improved: {before_pass}/{total} -> {after_pass}/{total}
```

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5c_auto_escalate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5c_auto_escalate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5c_auto_escalate 2>/dev/null || true
```

---

After both step markers touched, return to entry SKILL.md -> STEP 7 (5d codegen).
