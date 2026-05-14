### Finding 1: documented build skip flags rejected by preflight
**Q**: 5
**File:line**: `commands/vg/build.md:4`, `commands/vg/build.md:193`, `commands/vg/build.md:203`, `commands/vg/_shared/build/preflight.md:151`
**Purpose**: `--skip-pre-test` and `--skip-contract-runtime` are documented override paths.
**Actual**: allowlist omits both flags, so preflight treats them as unknown.
**Gap**: advertised hard-gate escapes cannot run.
**Severity**: high
**Fix**: add both flags to `VALID_FLAGS_PATTERN` and help text; keep `forbidden_without_override` enforcement.

### Finding 2: pre-test override path calls non-existent command
**Q**: 5
**File:line**: `commands/vg/_shared/build/pre-test-gate.md:42`, `commands/vg/_shared/build/pre-test-gate.md:50`, `.claude/scripts/vg-orchestrator/__main__.py:5106`
**Purpose**: skip pre-test only with `override.used` audit trail.
**Actual**: code calls `vg-orchestrator override-use`; CLI only defines `override`. It also passes undefined `OVERRIDE_REASON`.
**Gap**: even if allowlist fixed, override evidence is not emitted.
**Severity**: high
**Fix**: parse `--override-reason=...`; call `vg-orchestrator override --flag=... --reason=...`; fail if emit fails.

### Finding 3: B1 spec compliance review is scaffold only
**Q**: 2
**File:line**: `commands/vg/_shared/build/post-execution-overview.md:1074`, `commands/vg/_shared/build/post-execution-overview.md:1098`, `commands/vg/_shared/build/post-execution-overview.md:1117`
**Purpose**: spawn one `vg-build-spec-reviewer` per committed task and block on FAIL.
**Actual**: Agent call is comment-only, return is narrated, marker is always touched.
**Gap**: build can satisfy `5_1_spec_compliance_review` without review evidence.
**Severity**: critical
**Fix**: execute real Agent/Codex spawn, capture verdict, parse `PASS|FAIL`, block before marker on missing/FAIL.

### Finding 4: B4 final review marks done without verdict
**Q**: 2
**File:line**: `commands/vg/_shared/build/close.md:133`, `commands/vg/_shared/build/close.md:165`, `commands/vg/_shared/build/close.md:173`
**Purpose**: cumulative reviewer emits `PASS | PARTIAL | FAIL`; FAIL blocks build.
**Actual**: dispatch is comment-only; no verdict parse; marker touched unconditionally.
**Gap**: cross-task integration review can be skipped while contract passes.
**Severity**: critical
**Fix**: spawn reviewer, capture stdout or verdict file, parse verdict, block on FAIL, define PARTIAL policy.

### Finding 5: final reviewer output contract contradicts close step
**Q**: 5
**File:line**: `commands/vg/_shared/build/close.md:170`, `.claude/agents/vg-build-final-reviewer/SKILL.md:100`, `.claude/agents/vg-build-final-reviewer/SKILL.md:105`
**Purpose**: close expects `${PHASE_DIR}/.final-review/verdict.md`.
**Actual**: agent is read-only and returns verdict to stdout/final response.
**Gap**: downstream file expectation cannot be trusted.
**Severity**: high
**Fix**: choose one contract: stdout parsed by orchestrator, or allow/write required verdict file.

### Finding 6: UI runtime contract not enforced by blueprint contract
**Q**: 4
**File:line**: `commands/vg/_shared/blueprint/design.md:573`, `commands/vg/_shared/blueprint/design.md:603`, `commands/vg/_shared/blueprint/design.md:639`, `commands/vg/blueprint.md:138`, `scripts/validators/verify-ui-runtime-contract.py:240`
**Purpose**: emit `UI-RUNTIME-CONTRACT.md/json`; build consumes tokens/routes/spec count.
**Actual**: marker/artifacts absent from `blueprint.md` contract; emitter failure continues; build validator returns 0 when contract missing.
**Gap**: FE runtime invariants can vanish as “legacy phase.”
**Severity**: high
**Fix**: add profile-aware must-write + marker; block emitter failure for FE phases; make missing contract block for non-legacy phases.

### Finding 7: UI-SPEC generation has no output gate
**Q**: 2
**File:line**: `commands/vg/_shared/blueprint/design.md:288`, `commands/vg/_shared/blueprint/design.md:447`, `commands/vg/_shared/blueprint/design.md:462`, `commands/vg/_shared/blueprint/design.md:475`
**Purpose**: generate per-slug UI specs for every `<design-ref>`.
**Actual**: Agent spawn is comment-only; concat loops over whatever exists; marker always touched.
**Gap**: empty or partial `UI-SPEC.md` can pass.
**Severity**: high
**Fix**: real spawn; assert `UI-SPEC/index.md` and per-slug count; run scan coverage; block for FE profiles.

### Finding 8: UI-MAP generation echoes work instead of doing work
**Q**: 2
**File:line**: `commands/vg/_shared/blueprint/design.md:533`, `commands/vg/_shared/blueprint/design.md:542`, `commands/vg/_shared/blueprint/design.md:562`, `commands/vg/_shared/blueprint/design.md:568`
**Purpose**: create `UI-MAP.md` target component tree.
**Actual**: missing file branch prints “spawn planner agent” but never spawns or validates missing output.
**Gap**: build UI subtree injection can lose source map while blueprint marker passes.
**Severity**: high
**Fix**: invoke planner/generator, require `UI-MAP.md` for FE phases, run schema validator even on missing file.

### Finding 9: blueprint escape hatches bypass canonical override gate
**Q**: 4
**File:line**: `commands/vg/blueprint.md:80`, `commands/vg/blueprint.md:93`, `commands/vg/blueprint.md:222`, `commands/vg/_shared/blueprint/plan-overview.md:420`, `.claude/scripts/vg-orchestrator/__main__.py:4875`
**Purpose**: every gate skip should leave enforceable `override.used`.
**Actual**: `--skip-form-api-map`, `--skip-ui-spec`, and allow flags log debt or waive artifacts but are absent from `forbidden_without_override`.
**Gap**: run-complete cannot enforce reasoned skip evidence.
**Severity**: high
**Fix**: list all skip/allow flags in frontmatter and emit `vg-orchestrator override`.

### Finding 10: “exactly 1 commit per task” only checks too few commits
**Q**: 4
**File:line**: `commands/vg/_shared/build/waves-overview.md:686`, `commands/vg/_shared/build/waves-overview.md:693`, `commands/vg/_shared/build/waves-overview.md:714`, `agents/vg-build-task-executor/SKILL.md:13`
**Purpose**: each task must produce exactly one commit.
**Actual**: orchestrator blocks only `ACTUAL_COMMITS < EXPECTED_COMMITS`.
**Gap**: extra commits pass count audit.
**Severity**: medium
**Fix**: block `ACTUAL_COMMITS != EXPECTED_COMMITS`; map commits per task; fail task with more than one commit.

### Finding 11: `--reset-queue` bypasses merge-conflict hard block
**Q**: 5
**File:line**: `commands/vg/_shared/lib/build-queue-preflight.sh:4`, `commands/vg/_shared/lib/build-queue-preflight.sh:43`, `commands/vg/_shared/lib/build-queue-preflight.sh:55`, `commands/vg/_shared/lib/build-queue-preflight.sh:102`
**Purpose**: unresolved merge conflicts always block build.
**Actual**: `--reset-queue` returns 0 before conflict check.
**Gap**: build can start on conflicted working tree.
**Severity**: high
**Fix**: run conflict check before reset short-circuit, or repeat after reset and refuse if `diff-filter=U` remains.

## Summary table

| # | Lane | Q | Severity |
|---|---|---:|---|
| 1 | build | 5 | high |
| 2 | build | 5 | high |
| 3 | build | 2 | critical |
| 4 | build | 2 | critical |
| 5 | build | 5 | high |
| 6 | blueprint/build | 4 | high |
| 7 | blueprint | 2 | high |
| 8 | blueprint | 2 | high |
| 9 | blueprint | 4 | high |
| 10 | build | 4 | medium |
| 11 | build | 5 | high |

## Top 5 priority

1. Fix B1 spec review real spawn + verdict gate.
2. Fix B4 final review real spawn + verdict gate.
3. Add UI runtime contract to blueprint contract and non-legacy build block.
4. Fix build skip flag allowlist plus `override` emission.
5. Gate UI-SPEC/UI-MAP outputs before markers.

## Smoothness verdict

| Lane | Verdict | Reason |
|---|---|---|
| blueprint | NEEDS-WORK | UI artifacts/runtime contracts can mark done without required artifacts. |
| build | NEEDS-WORK | hard review/pre-test gates exist in docs, but spawn, override, and safety plumbing leak. |