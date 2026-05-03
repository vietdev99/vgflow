---
name: vg:regression
description: Full regression sweep — re-run ALL tests from accepted phases, detect regressions, auto-fix loop
argument-hint: "[--phase X] [--fix] [--report-only] [--max-fix-iterations N]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
  - TaskCreate
  - TaskUpdate
observation_only: true
contract_exempt_reason: "read-only in --report-only mode: scans prior phase test results to detect regressions. NOTE: --fix flag mutates, but default is read-only. Document split mode separately later."
---

<rules>
1. **Full suite** — runs ALL vitest + ALL E2E from the repo, not a subset. Regression hides in unexpected places.
2. **Baselines from SANDBOX-TEST.md** — each accepted phase's last-known goal verdicts are the baseline. PASS→FAIL = regression.
3. **Fix loop** — when `--fix` (default ON): detect → AI fix → re-run affected tests → repeat. Max 3 iterations.
4. **Atomic fix commits** — each fix is 1 commit with message: `fix(regression): {goal} — {root cause}`.
5. **Git blame for triage** — regressions are traced to causal commits via `git log`. Clusters same-cause regressions.
6. **Never break passing tests** — fix loop re-runs the FULL suite after each fix batch, not just the fixed tests. A fix that causes a new regression → revert.
7. **Zero hardcode** — test commands from config: `config.build_gates.test_unit_cmd`, `config.build_gates.test_e2e_cmd`.
</rules>

<objective>
Cuối milestone hoặc on-demand: replay toàn bộ test suite, so sánh với baseline, fix regression.

Dùng khi:
- Sắp ship milestone (final regression gate)
- Nghi ngờ phase mới phá phase cũ
- Sau nhiều phase build liên tiếp muốn verify toàn vẹn
</objective>

<process>

<step name="0_load_config">
Follow `.claude/commands/vg/_shared/config-loader.md`.

Parse flags:
```bash
FIX_MODE="true"       # default ON
REPORT_ONLY="false"
MAX_FIX_ITER=3
PHASE_FILTER=""

for arg in $ARGUMENTS; do
  case "$arg" in
    --report-only) FIX_MODE="false"; REPORT_ONLY="true" ;;
    --no-fix)      FIX_MODE="false" ;;
    --fix)         FIX_MODE="true" ;;
    --max-fix-iterations=*) MAX_FIX_ITER="${arg#*=}" ;;
    --phase=*)     PHASE_FILTER="${arg#*=}" ;;
    *)             PHASE_FILTER="$arg" ;;
  esac
done

VG_TMP="${REPO_ROOT}/.vg-tmp"
mkdir -p "$VG_TMP"
```
</step>

<step name="1_collect_baselines">
**Collect baselines from all accepted phases.**

```bash
COLLECT_ARGS="--phases-dir ${PHASES_DIR} --repo-root ${REPO_ROOT} --output ${VG_TMP}/regression-baselines.json"
[ -n "$PHASE_FILTER" ] && COLLECT_ARGS="$COLLECT_ARGS --phase $PHASE_FILTER"

${PYTHON_BIN} .claude/scripts/regression-collect.py $COLLECT_ARGS
```

Read output — show phase count + goal count + test file count to user.
If 0 accepted phases → STOP: "No accepted phases. Run /vg:accept first."
</step>

<step name="2_run_full_suite">
**Run ALL tests (full suite — vitest + E2E).**

```bash
# Vitest (all unit/integration tests)
VITEST_CMD="${config.build_gates.test_unit_cmd:-pnpm turbo test}"
echo "Running vitest: $VITEST_CMD"
$VITEST_CMD -- --reporter=json --outputFile="${VG_TMP}/vitest-results.json" 2>&1 \
  | tee "${VG_TMP}/vitest-stdout.log"
VITEST_EXIT=$?

# E2E (all Playwright specs)
E2E_CMD="${config.build_gates.test_e2e_cmd:-pnpm --filter web e2e}"
echo "Running E2E: $E2E_CMD"
PLAYWRIGHT_JSON_OUTPUT_DIR="${VG_TMP}" $E2E_CMD -- --reporter=json 2>&1 \
  | tee "${VG_TMP}/e2e-stdout.log"
E2E_EXIT=$?

echo "Vitest exit: $VITEST_EXIT  |  E2E exit: $E2E_EXIT"
```

Note: vitest/E2E may fail (exit != 0) — that's expected when regressions exist.
Continue to compare step regardless.
</step>

<step name="3_compare_and_classify">
**Compare current results against baselines.**

```bash
${PYTHON_BIN} .claude/scripts/regression-compare.py \
  --baselines "${VG_TMP}/regression-baselines.json" \
  --vitest-results "${VG_TMP}/vitest-results.json" \
  --e2e-results "${VG_TMP}/e2e-results.json" \
  --output-dir "${PLANNING_DIR}"
COMPARE_EXIT=$?
```

Read `${PLANNING_DIR}/regression-results.json` to get counts.

```bash
REGRESSION_COUNT=$(${PYTHON_BIN} -c "
import json
r = json.load(open('${PLANNING_DIR}/regression-results.json', encoding='utf-8'))
print(r['summary']['REGRESSION'])
")
```

Display REGRESSION-REPORT.md summary to user.

**If REGRESSION_COUNT == 0:**
```
✓ No regressions detected. All {N} goals stable across {M} phases.
```
→ Write final report, mark clean, STOP.

**If REGRESSION_COUNT > 0 AND REPORT_ONLY:**
```
⚠ {REGRESSION_COUNT} regressions found. See REGRESSION-REPORT.md.
   Re-run with --fix to enter fix loop.
```
→ STOP.

**If REGRESSION_COUNT > 0 AND FIX_MODE:**
→ Proceed to fix loop (step 4).
</step>

<step name="4_fix_loop">
**Fix loop: detect → fix → re-verify. Max ${MAX_FIX_ITER} iterations.**

```
ITERATION = 0

WHILE ITERATION < MAX_FIX_ITER AND REGRESSION_COUNT > 0:
  ITERATION += 1

  ## 4a. Parse fix targets
  Read regression-results.json → extract fix targets (REGRESSION items only):
  - goal_id, phase, test_files, errors, blame_commits

  ## 4b. Cluster by root cause
  Group regressions by blame commit (from clusters in report).
  Present clusters to user:

  ```
  Fix iteration {ITERATION}/{MAX_FIX_ITER}

  Regressions: {REGRESSION_COUNT}
  Clusters:
    Cluster 1: commit {sha} "{message}" — affects {N} goals
    Cluster 2: commit {sha} "{message}" — affects {N} goals
    ...

  [1] Auto-fix all clusters (AI attempts fix per cluster)
  [2] Fix manually (I'll fix, then re-run: /vg:regression --phase X)
  [3] Accept regressions (record in report, proceed)
  ```

  ## 4c. Auto-fix per cluster
  If user chose [1]:

  For each cluster:
    1. Read error messages + affected test files + blame commit diff
    2. Spawn Agent (subagent_type="general-purpose") with context:
       # general-purpose is the canonical debug-agent slot in VG (framework-neutral, allow-list-clean).
       # Operator can also invoke /vg:debug interactively for the same loop.
       - Error: {error_message}
       - Test file: {path}
       - Blame: {commit_sha} — {commit_message}
       - Instruction: "Fix this regression. The test used to pass before commit {sha}.
         Read the commit diff, understand what changed, fix the root cause.
         Do NOT modify the test — fix the source code."
    3. Agent fixes code → commits: `fix(regression): {goal_id} — {root_cause_1_line}`
    4. After ALL cluster fixes applied:

  ## 4d. Re-run full suite (verify fix didn't break anything else)
  Re-run step 2 (full vitest + E2E) → step 3 (compare).

  Read new REGRESSION_COUNT.

  If REGRESSION_COUNT == 0:
    ```
    ✓ All regressions fixed in {ITERATION} iteration(s).
    Commits: {list of fix commits}
    ```
    BREAK.

  If REGRESSION_COUNT decreased:
    ```
    ⚠ {FIXED_THIS_ROUND} regressions fixed, {REGRESSION_COUNT} remaining.
    Continuing to iteration {ITERATION+1}...
    ```
    CONTINUE loop.

  If REGRESSION_COUNT same or increased:
    ```
    ⛔ Fix attempt did not reduce regressions (or introduced new ones).
    Reverting fix commits from this iteration...
    ```
    git revert all fix commits from this iteration.
    BREAK with manual intervention message.

END WHILE
```
</step>

<step name="5_final_report">
**Write final regression report.**

After fix loop (or report-only mode):

```bash
# Copy report to permanent location
cp "${PLANNING_DIR}/REGRESSION-REPORT.md" "${PLANNING_DIR}/REGRESSION-REPORT.md"
cp "${PLANNING_DIR}/regression-results.json" "${PLANNING_DIR}/regression-results.json"

# Clean tmp
rm -f "${VG_TMP}/vitest-results.json" "${VG_TMP}/e2e-results.json"
rm -f "${VG_TMP}/vitest-stdout.log" "${VG_TMP}/e2e-stdout.log"
rm -f "${VG_TMP}/regression-baselines.json"
```

**If clean (0 regressions):**
```
Regression sweep CLEAN ✓

Phases tested: {N}
Goals verified: {M} ({stable} stable, {fixed} fixed this run)
Test files: {T} (all pass)
Fix iterations: {ITERATION}
Report: ${PLANNING_DIR}/REGRESSION-REPORT.md

▶ Ready to ship milestone.
```

**If regressions remain (exhausted fix loop):**
```
Regression sweep INCOMPLETE — {REGRESSION_COUNT} regressions remain.

Remaining:
  {goal_id}: {title} — {error_summary}
  ...

Report: ${PLANNING_DIR}/REGRESSION-REPORT.md
Fix targets: ${PLANNING_DIR}/regression-results.json → "Fix targets" section

Options:
  [1] /vg:regression --fix  (retry fix loop)
  [2] Fix manually → /vg:regression --report-only  (verify after manual fix)
  [3] Accept known regressions → document in REGRESSION-REPORT.md, ship with caveats
```
</step>

</process>

<success_criteria>
- All vitest + E2E from repo executed (not just critical subset)
- Each goal classified: REGRESSION / FIXED / STABLE / STILL_FAILING / NEW_FAIL
- Regressions traced to causal commits via git log
- Fix loop: AI auto-fix per cluster → re-verify full suite → max 3 iterations
- Fixes that introduce NEW regressions are reverted
- REGRESSION-REPORT.md written with fix targets for manual follow-up
- Exit clean (0 regressions) = ship-ready
</success_criteria>
