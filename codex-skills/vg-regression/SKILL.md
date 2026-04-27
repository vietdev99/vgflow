---
name: "vg-regression"
description: "Full regression sweep — re-run ALL tests from accepted phases, detect regressions, auto-fix loop"
metadata:
  short-description: "Full regression sweep — re-run ALL tests from accepted phases, detect regressions, auto-fix loop"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-regression`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



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
    2. Spawn Agent (gsd-debugger or inline) with context:
       # gsd-debugger is a generic Claude agent type for debugging — not a GSD workflow dependency
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
