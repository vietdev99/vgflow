# VG Build — Slim Surface + Wave-Multi-Subagent Refactor

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R2 (after blueprint pilot R1 passes; bundled with `vg:test` in same round)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md` (template + shared infrastructure)

---

## 1. Background

### 1.1 Why build needs its own spec

Build (`commands/vg/build.md`, 4,571 lines, 18 steps) is the heaviest execution command in VG. While it inherits the slim+refs+hooks+diagnostic template from the blueprint pilot, it has unique structural concerns:

- Step `8_execute_waves` is **1,881 lines** — the largest single step in all of VG
- Step `9_post_execution` is **896 lines** — heavy verification with API truthcheck, gap closure, design fidelity gates (L1-L6)
- Wave execution requires **parallel subagents** (1 per task within a wave) — the blueprint pilot only had 2 sequential subagents
- Build already has 11 layers of binding enforcement (context capsules, L1-L6 design gates, agent spawn guard, commit-msg hook, R5 spawn-plan, scoped contract context). These must be PRESERVED, not duplicated.

### 1.2 Dogfood baseline (PrintwayV3 `.vg/events.db`)

| Metric | Value |
|---|---|
| `build.started` events | 95 |
| `build.completed` events | 24 (25%) |
| `build.native_tasklist_projected` events | **1 / 95 = 1.1%** |
| `wave.started` events | 202 |
| `wave.completed` events | 68 (34%) |
| `wave.blocked` events | **57 / 202 = 28%** wave block rate |
| `build.crossai_iteration_started` | 45 |
| `build.crossai_loop_complete` | 4 (88% loop fail) |
| `build.crossai_loop_user_override` | 18 (forced human intervention) |

Comparison vs blueprint baseline (3.5% projection): build is **3x worse** at native tasklist projection.

### 1.3 Audit findings (parallel-safety of existing 11-layer enforcement)

Pre-design audit run on 6 mechanisms (see §3 for verdicts):

- **5/6 PASS** — context capsule, prompt materialization, L1-L6 gates, commit-msg hook, R5 budget are all parallel-safe by current design
- **1/6 FAIL** — `vg-agent-spawn-guard.py` checks subagent_type but does NOT count spawned vs expected. If orchestrator spawns N-1 instead of N tasks, no detection.

→ Build refactor scope: **pure-surface (slim+refs+hooks+diagnostic, inherited from blueprint pilot) + 1 enhancement** (add spawn-count to spawn guard). No redesign of binding enforcement architecture.

### 1.4 Goals

- Reduce `commands/vg/build.md` from 4,571 → ≤500 lines (Anthropic ceiling)
- Apply imperative language + HARD-GATE tags + Red Flags (build-specific)
- Replace inline `8_execute_waves` heavy section with reference + Task spawn instruction
- Add 2 custom subagents: `vg-build-task-executor` + `vg-build-post-executor`
- Strengthen `vg-agent-spawn-guard.py` with spawn-count check (the 1 audit FAIL)
- Empirically prove on PrintwayV3: target `build.native_tasklist_projected ≥ 1`, wave block rate ↓
- Defer: CrossAI build verify loop refactor (88% fail rate — separate round)

### 1.5 Non-goals

- CrossAI build verify loop refactor (defer to separate round; 88% fail rate is architectural, needs dedicated design)
- New binding enforcement layers (existing 11 layers preserved as-is)
- Codex skill mirror (defer to round 2 after Claude path verified, same as blueprint pilot)

---

## 2. Inheritance from blueprint pilot

This spec inherits and does NOT redesign:

| Component | Source spec |
|---|---|
| 4 hook scripts (SessionStart, PreToolUse, PostToolUse, Stop) | blueprint pilot §4.4 |
| `vg-meta-skill.md` base content | blueprint pilot §4.6 |
| `install-hooks.sh` | blueprint pilot §3.1 |
| Slim-entry-SKILL.md template structure | blueprint pilot §4.1 |
| Reference file pattern (`_shared/<cmd>/...`) | blueprint pilot §3.1 |
| Custom subagent SKILL.md template | blueprint pilot §4.3 |
| 5-layer diagnostic flow (when blocked) | blueprint pilot §4.5 |
| Imperative language rules | blueprint pilot §4.1 |

This spec adds only:
- Build-specific slim entry + reference files
- 2 new custom subagents (build-specific)
- 1 enhancement to `vg-agent-spawn-guard.py` (spawn-count check)
- Build-specific Red Flags addendum to `vg-meta-skill.md`
- Build-specific exit criteria for round 2 dogfood

---

## 3. Audit findings (full evidence)

| # | Mechanism | File:line | Verdict | Action |
|---|---|---|---|---|
| 1 | `pre-executor-check.py` per-task capsule | `scripts/pre-executor-check.py:1010-1018` | PASS | Preserve as-is |
| 2 | 7 context blocks materialized per-spawn | `commands/vg/build.md:1370-1378, 1843-1911` | PASS | Preserve as-is |
| 3a | L1 design-pixel gate per-task | `commands/vg/build.md:1379-1412` | PASS | Preserve as-is |
| 3b | L2 fingerprint per-task | `commands/vg/build.md:3616-3684` | PASS | Preserve as-is |
| 3c | L3 SSIM per-task | `commands/vg/build.md:3686-3762` | PASS | Preserve as-is |
| 3d | L5 design-fidelity-guard per-task | `commands/vg/build.md:3764-3852` | PASS | Preserve as-is |
| 3e | L6 read-evidence per-task | `commands/vg/build.md:3854-3919` | PASS | Preserve as-is |
| 4 | `vg-agent-spawn-guard.py` count check | `scripts/vg-agent-spawn-guard.py:131-180` | **FAIL** | **Strengthen** — see §5.1 |
| 5 | commit-msg hook per-commit (parallel-safe via git) | `.claude/templates/vg/commit-msg:1-328` | PASS | Preserve as-is |
| 6 | R5 spawn-plan budget pre-allocate | `commands/vg/build.md:1271-1342` | PASS | Preserve as-is |

**Summary:** 5/6 PASS. Only spawn-guard needs the count enhancement.

---

## 4. File and directory layout

### 4.1 Canonical (vgflow-bugfix repo)

```
commands/vg/
  build.md                                  REFACTOR: 4,571 → ~500 lines
  _shared/build/                            NEW dir
    preflight.md                            ~250 lines (steps 0_gate, 0_session, 1_parse, 1a/1b, create_task_tracker)
    context/                                nested for medium-heavy step 4
      overview.md                           ~150 lines (entry, instructs running pre-executor-check.py)
      capsule-spec.md                       ~150 lines (capsule schema reference)
    validate-blueprint.md                   ~200 lines (step 3, 6, 7)
    waves/                                  nested for HEAVY step 8
      overview.md                           ~150 lines (entry, instructs spawning task subagents)
      task-delegation.md                    ~200 lines (input/output contract for vg-build-task-executor)
      wave-orchestration.md                 ~150 lines (R5 spawn-plan, budget gate, fail-fast)
    post-execution/                         nested for HEAVY step 9
      overview.md                           ~150 lines (entry, instructs spawning post-executor subagent)
      gates-l1-l6.md                        ~200 lines (design fidelity gate sequence)
      delegation.md                         ~150 lines (input/output for vg-build-post-executor)
    crossai-loop.md                         ~150 lines (step 11 — UNCHANGED, refers to existing impl, defer refactor)
    close.md                                ~150 lines (step 10 postmortem + step 12 run-complete)

agents/                                     EXTEND from blueprint pilot
  vg-build-task-executor/SKILL.md           ~250 lines, parallel per-task executor
  vg-build-post-executor/SKILL.md           ~200 lines, single post-wave verifier

scripts/
  vg-agent-spawn-guard.py                   STRENGTHEN — add spawn-count check (§5.1)

scripts/hooks/                              SHARED with blueprint pilot — no new files
```

### 4.2 PrintwayV3 install (via sync.sh)

```
.claude/commands/vg/build.md
.claude/commands/vg/_shared/build/...
.claude/agents/vg-build-task-executor/...
.claude/agents/vg-build-post-executor/...
.claude/scripts/vg-agent-spawn-guard.py     (replace with strengthened version)
.claude/scripts/hooks/...                   (already installed by blueprint pilot)
```

---

## 5. Components

### 5.1 Strengthen `vg-agent-spawn-guard.py` (THE 1 audit FAIL fix)

**Current behavior** (`scripts/vg-agent-spawn-guard.py:131-180`):
- Hook input: `subagent_type` from PreToolUse on `Task` tool
- Logic: check subagent_type against allow-list (general-purpose, vg-*, gsd-debugger; deny gsd-* others)
- Output: ALLOW or DENY

**Strengthened behavior:**
- Read active wave's spawn plan from `.vg/runs/<run_id>/.wave-spawn-plan.json` (R5 output)
- Maintain spawn counter in `.vg/runs/<run_id>/.spawn-count.json`:
  ```json
  { "wave_id": 3, "expected": 5, "spawned": [task_id1, task_id2, ...], "remaining": [task_id4, task_id5] }
  ```
- On each Task tool spawn:
  1. Check subagent_type allow-list (existing logic)
  2. Parse subagent prompt for `task_id` (must be in `remaining[]`)
  3. If task_id missing or not in remaining → DENY with reason
  4. Move task_id from `remaining` to `spawned`
- On wave-complete: assert `len(spawned) == expected`. If not, emit `wave.spawn_shortfall` event + Stop hook will fail.

**Why this matters for parallel:**
Wave has N tasks expected. Without count check, AI can silently spawn N-1, claim wave done, advance. Spawn-count check catches silent shortfall — pairs naturally with R5 spawn-plan and wave-completed event.

### 5.2 Slim `commands/vg/build.md` (~500 lines)

Inherits structure from blueprint pilot §4.1 (HARD-GATE + Red Flags + 6 step blocks with reference load instructions):

```markdown
---
name: vg:build
description: Execute phase plans with contract-aware wave-based parallel execution
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion, BashOutput]
runtime_contract: { ... }  # unchanged from current build.md (Stop hook authority)
---

<HARD-GATE>
You MUST follow steps in exact order. Wave execution MUST spawn parallel
subagents per task (NOT inline implementation). Skipping ANY step will be
blocked by hooks. Spawning fewer subagents than the wave plan declares
will be blocked by vg-agent-spawn-guard.
</HARD-GATE>

## Red Flags (build-specific)

| Thought | Reality |
|---|---|
| "Implement task inline, faster than spawning subagent"     | Spawn-guard counts spawn vs plan; shortfall blocks wave |
| "Skip pre-executor-check, capsule isn't needed"            | Hook blocks spawn without capsule (HARD BLOCK line 1414) |
| "L5 design-fidelity-guard is opt-in, skip it"              | This is wrong since R2 — guard is required for tasks with design-ref |
| "CrossAI verify loop too slow, skip"                       | Hook blocks `--skip-truthcheck` without override-debt entry |
| "1 commit per task is excessive, batch them"               | R5 + commit count check enforces 1:1 task→commit |

## Steps

### STEP 1 — preflight
Read `_shared/build/preflight.md`. Follow exactly.

### STEP 2 — load contracts and context
Read `_shared/build/context/overview.md`. It instructs running `pre-executor-check.py`
to assemble per-task capsules. DO NOT skip context loading.

### STEP 3 — validate blueprint
Read `_shared/build/validate-blueprint.md`. Follow exactly.

### STEP 4 — execute waves (HEAVY, multi-subagent)
Read `_shared/build/waves/overview.md`. It instructs spawning N parallel
`vg-build-task-executor` subagents per wave (N = wave's task count from
spawn-plan). DO NOT execute tasks inline. Spawn-guard will block any
shortfall.

### STEP 5 — post-execution verification (HEAVY, single subagent)
Read `_shared/build/post-execution/overview.md`. It instructs spawning the
`vg-build-post-executor` subagent for L1-L6 design gates + API truthcheck +
gap closure + summary writing. DO NOT verify inline.

### STEP 6 — CrossAI build verify loop
Read `_shared/build/crossai-loop.md`. (UNCHANGED behavior — refactor deferred.)

### STEP 7 — close
Read `_shared/build/close.md`. Follow exactly.
```

### 5.3 Reference files

Each ref ≤500 lines. Imperative throughout. Heavy steps split into nested sub-refs (waves/, post-execution/, context/) per the hybrid pattern locked in blueprint pilot.

For `waves/overview.md` (entry of HEAVY step 4):

```markdown
# Wave execution — STEP 4

## Why parallel subagent per task

Empirical data: build dogfood shows 1% native_tasklist_projected, 28% wave
block rate when wave executes inline. The 1,881-line inline implementation
is too large for AI to follow without skipping. Therefore:

<HARD-GATE>
You MUST spawn N parallel `vg-build-task-executor` subagents for each
wave, where N = task count from `.wave-spawn-plan.json`.
You MUST NOT implement tasks inline.
You MUST NOT spawn fewer than N — vg-agent-spawn-guard will block.
</HARD-GATE>

## Pre-spawn checklist (from existing build.md, preserved)

1. Bash: `vg-orchestrator step-active 8_execute_waves`
2. Bash: read `.wave-spawn-plan.json` to get N tasks for current wave
3. For each task in plan:
   a. Verify capsule exists at `.task-capsules/task-${N}.capsule.json`
      (else block — HARD line 1414 of legacy build.md)
   b. Run L1 design-pixel gate (if task has design-ref)
4. Spawn ALL N subagents in ONE assistant message (parallel)
5. Wait for all returns, validate each artifact
6. Bash: `vg-orchestrator mark-step build 8_execute_waves`

## How to spawn (loop body)

```python
for task in wave_plan["parallel"]:
    Task(
        subagent_type="vg-build-task-executor",
        prompt=read("task-delegation.md").format(
            task_id=task["id"],
            capsule_path=f".task-capsules/task-{task['id']}.capsule.json",
            ...
        )
    )
```

See `task-delegation.md` for exact input/output contract.

## After all returns

- Aggregate: count successful returns, sum commits
- Validate: spawn-count == expected (R5 budget assertion)
- L2-L6 gates run in step 5 (post-execution), not here
- Emit event: `wave.completed { wave_id, task_count, commit_count }`
```

### 5.4 Custom subagents

**`agents/vg-build-task-executor/SKILL.md`:**

```markdown
---
name: vg-build-task-executor
description: Execute one build task with full binding context (capsule). Output: artifacts written + commit_sha + bindings_satisfied. ONLY this task.
tools: [Read, Write, Edit, Bash, Glob, Grep]   # narrow; no Task (no nested spawn), no AskUserQuestion
model: opus
---

<HARD-GATE>
You execute ONE task. Your inputs include a fully-materialized context
capsule. You MUST:

1. Read the capsule fully (it contains contract slice, design ref, callers,
   siblings, interface standards — all materialized inline)
2. Implement the task per PLAN.md slice in the capsule
3. Write `// vg-binding: <id>` comment at top of each modified file citing
   which contract/design clause your code satisfies
4. Make EXACTLY ONE commit (R5 + commit count check expects 1:1 task→commit)
5. Write `.fingerprints/task-${TASK_ID}.fingerprint.md` (L2 gate input)
6. Write `.read-evidence/task-${TASK_ID}.json` with PNG sha256 if design-ref
   present (L6 anti-fabrication)
7. Return JSON: { task_id, artifacts_written: [...], commit_sha,
   bindings_satisfied: [...], fingerprint_path, read_evidence_path }

You MUST NOT:
- Skip capsule read (capsule is your contract — skipping = lazy-read drift)
- Make multiple commits (R5 violation)
- Skip fingerprint write (L2 gate will block wave)
- Modify files outside your task slice
- Spawn nested subagents (your tools list excludes Task)
- Ask user questions (your input is the contract)
</HARD-GATE>

## Step-by-step (continues with imperative procedure)

1. Read all paths in capsule (capsule fields: contract_slice, design_ref_path, callers, siblings, interface_standards_excerpt, plan_task_slice)
2. If any required field empty → return error JSON, do NOT proceed
3. Pre-coding: write `.fingerprints/task-${TASK_ID}.fingerprint.md` with planned change summary + bindings to satisfy
4. Read existing files to be modified
5. If task has design-ref: write `.read-evidence/task-${TASK_ID}.json` with PNG sha256 (anti-fabrication L6 input)
6. Implement task per capsule's contract_slice + plan_task_slice
7. Add `// vg-binding: <id>` comment at top of EACH modified file
8. Run typecheck (Bash: `<typecheck-command-from-capsule>`) — must pass before commit
9. Make ONE commit with message format:
   ```
   <type>(<scope>): <task summary>
   
   vg-task: <task_id>
   vg-bindings: <binding_id1>, <binding_id2>, ...
   <other commit-msg hook required fields>
   ```
10. Return JSON described in HARD-GATE block above

## Failure modes

- Capsule missing field → return error JSON, no partial commit
- Typecheck fail → return error JSON with stderr, no commit
- Multiple commits attempted → R5 catches at wave-end, mark task incomplete
- Binding citation missing → output validator catches, mark task incomplete
- Cannot satisfy contract slice → return error JSON specifying which clause

The orchestrator will retry the task up to 2 times. After that, AskUserQuestion escalation per Layer 3 of diagnostic flow.
```

**`agents/vg-build-post-executor/SKILL.md`:**

Single subagent for step 9 (post-execution). Performs:
- L2 fingerprint validation (per-task loop)
- L3 SSIM diff (per-task loop)
- L5 design-fidelity-guard invocation (per-task loop, spawns Haiku subagents — these are not part of this subagent's tools, called via Bash to existing script)
- L6 read-evidence re-hash (per-task loop)
- API truthcheck loop entry (delegates to step 11 crossai loop, defer)
- Gap closure logic
- SUMMARY.md write

Output: `{ gates_passed: [L2, L3, L5, L6], gaps_closed: [...], summary_path, summary_sha256 }`

### 5.5 Hooks (SHARED with blueprint pilot, no new hooks)

All 4 hooks (SessionStart, PreToolUse, PostToolUse, Stop) inherited from blueprint pilot §4.4. The PreToolUse hook already matches `Bash` with `vg-orchestrator step-active` regex — works for build's step-active calls without modification.

The strengthened `vg-agent-spawn-guard.py` (§5.1) is a SEPARATE hook (PreToolUse on `Task` tool) — already installed in current VG, only enhanced here.

### 5.6 Build-specific addendum to `vg-meta-skill.md`

Append to existing `vg-meta-skill.md`:

```markdown
## Build-specific Red Flags

| Thought | Reality |
|---|---|
| "Implementing task inline is faster than spawning subagent" | Spawn-guard counts spawn vs plan; shortfall blocks wave |
| "Capsule has too much detail, I can skip parts" | Capsule is materialized contract — skipping = lazy-read drift, L1-L6 gates will catch divergence |
| "Multiple commits per task to keep them small" | R5 + commit count check enforces 1:1 task→commit |
| "L5 design-fidelity-guard sometimes fails on minor diffs" | Guard is Haiku zero-context, separate model — disagreement is signal, not noise |
| "CrossAI loop is slow, skip with --skip-truthcheck" | --skip-truthcheck requires override-debt entry; Stop hook checks |
```

---

## 6. Error handling, migration, testing, exit criteria

### 6.1 Error handling

All blocks follow §4.5 of blueprint pilot spec (5-layer diagnostic flow). Build-specific additions:

- **Wave spawn shortfall** (spawn-count check fails) — strengthened guard exit 2 with: "Wave 3 expected 5 spawns, only 4 received. Missing: task_id_5. Spawn the missing task or update wave-plan with override-reason."
- **Capsule missing** (existing HARD BLOCK line 1414) — already produces clear stderr; format aligned with diagnostic Layer 1
- **L1-L6 gate failure** (existing) — gate-specific stderr already exists; align format with diagnostic Layer 1 in pilot impl
- **Subagent task-executor returns invalid JSON** — main retries 2× then escalates AskUserQuestion (Layer 3)
- **R5 budget overflow** — existing block; align stderr format

### 6.2 Migration / backward compat

- **Existing PrintwayV3 build runs (24 completed, 35 aborted, 36 in-flight):** No migration. They stand as-is.
- **138 existing tests:** Must continue to pass. New tests added (see §6.3).
- **CrossAI loop refactor:** DEFERRED to separate round. No changes here.
- **Codex skill mirror:** DEFERRED (consistent with blueprint pilot).

### 6.3 Testing

**Static (pytest), new for build:**
- `test_build_slim_size.py` — assert `commands/vg/build.md` ≤ 600 lines
- `test_build_references_exist.py` — assert all `_shared/build/*.md` and nested sub-refs exist with min content size
- `test_build_imperative_language.py` — same imperative grep rules as blueprint pilot test
- `test_build_subagent_definitions.py` — assert 2 agent SKILL.md valid frontmatter
- `test_spawn_guard_count_check.py` — simulate spawn shortfall (4 spawns vs plan of 5), assert hook denies + emits `wave.spawn_shortfall` event
- `test_spawn_guard_preserves_type_check.py` — simulate gsd-* spawn, assert still denied (regression for existing logic)

**Tests inherited from blueprint pilot (no duplication):**
- All hook script tests (PreToolUse blocks, PostToolUse evidence, etc.)
- Diagnostic flow tests (block events paired with handled events)
- SessionStart re-injection on compact

**Empirical dogfood (manual run + automated metric query):**
- Sync to PrintwayV3 via `DEV_ROOT=".../PrintwayV3" ./sync.sh --no-global`
- Open fresh Claude Code session in PrintwayV3
- Invoke `/vg:build <phase>` (recommend phase 4 or fresh phase, NOT phase 1/3.2 which already have artifacts)
- After completion, run `scripts/query-pilot-metrics.py --command build --run-id <latest>` and assert exit criteria below

### 6.4 Exit criteria — build pilot PASS requires ALL of:

1. Tasklist visible in Claude Code UI immediately after invocation (target: same as blueprint pilot)
2. `build.native_tasklist_projected` event count ≥ 1 in this run (baseline 1/95 = 1.1%)
3. All 13 hard-gate step markers touched without override flag (current must_touch_markers)
4. SUMMARY.md, INTERFACE-STANDARDS.{md,json}, API-DOCS.md, .build-progress.json all exist with content_min_bytes met
5. Wave subagent invocations: count of `wave.started` events × N tasks each = total Task tool invocations (spawn-count check passes)
6. `wave.completed` events match `wave.started` count (no silent abort)
7. L1-L6 gates emit per-task verdict events (existing telemetry, verify still works under parallel)
8. CrossAI loop runs (deferred refactor — accept whatever current behavior produces; not a fail criterion this round)
9. Manual test: simulate spawn shortfall (skip 1 task in spawn loop) → strengthened spawn-guard blocks with diagnostic stderr
10. User reads workflow narration end-to-end and reports understanding (qualitative)
11. Stop hook fires without exit 2 (run-complete contract satisfied)
12. Stop hook fails closed if `vg.block.fired` events are not paired with `vg.block.handled` (manual induce-and-skip test)

Build pilot FAILS if any criterion missed. Failure path: return to design phase. Do not advance to test pilot.

---

## 7. Round 2 sequencing reminder

Per blueprint pilot spec §6.3, round 2 bundles `vg:build` + `vg:test`. This spec covers build only. Test will have its own sub-spec (`2026-05-XX-vg-test-design.md`) created after blueprint pilot R1 passes. Build and test specs implementable in parallel since they share infrastructure (hooks, diagnostic).

---

## 8. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md` (template + shared infrastructure + 5-layer diagnostic)
- Audit findings file:lines: see §3 table
- Existing build.md: `commands/vg/build.md` (4,571 lines pre-refactor)
- Existing spawn guard: `scripts/vg-agent-spawn-guard.py:131-180`
- Anthropic multi-agent research pattern: https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Verification debt (Medium 2026): https://fazy.medium.com/agentic-coding-ais-adolescence-b0d13452f981
