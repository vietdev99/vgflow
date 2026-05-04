# VG Test — Slim Surface + Codegen Subagent Refactor

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R2 (bundled with vg:build, after blueprint pilot R1)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/test.md` is **4,188 lines, 27 steps**, mapped to 6 checklist groups (test_preflight, test_deploy, test_runtime, test_codegen, test_regression_security, test_close).

### 1.1 Heavy steps (>300 lines)

| Step | Lines | Role | Refactor approach |
|---|---|---|---|
| `5d_codegen` | **645** | Codegen + binding gate + failure routes | Subagent: `vg-test-codegen` |
| `5c_goal_verification` | 303 | Goal replay loop + topological sort | Subagent: `vg-test-goal-verifier` |
| `complete` | 305 | Cleanup + verdict routing + interactive next-steps | Inline ref (split nested) |

Other large but manageable inline: `5c_fix` (251), `5c_auto_escalate` (217), `5f_security_audit` (206), `5g_performance_check` (189), `5b_runtime_contract_verify` (146).

### 1.2 Existing patterns to preserve

- **Deep-probe spawn (L2664)**: Sonnet primary + Codex/Gemini/Haiku adversarial cross-check. Consensus disagreement >30% → escalate Opus. **Already orchestrator-worker pattern. Preserve.**
- **Bootstrap reflection (L3796)**: Haiku isolated, vg-reflector skill invocation. **Preserve.**
- **L1/L2 binding gates** for codegen (L2285 5d_binding_gate): inline re-codegen → architect proposal escalation. **Preserve.**
- **Console monitoring (L938-945)**: mandatory per-step check after every action. **Preserve.**

### 1.3 Dogfood baseline (PrintwayV3)

| Metric | Value |
|---|---|
| `test.started` events | 17 |
| `test.completed` events | 11 (65%) |
| `test.tasklist_shown` | 14 |
| **`test.native_tasklist_projected`** | **0** (never fired) |

→ Worse than blueprint (3.5%) and build (1.1%). Tasklist projection is completely broken for test command.

### 1.4 Goals

- Reduce `commands/vg/test.md` from 4,188 → ≤500 lines
- Apply imperative + HARD-GATE + Red Flags
- 2 subagents for 2 heavy steps (codegen 645 + goal-verification 303)
- Strengthen: emit `test.native_tasklist_projected` (currently never fires)
- Dogfood metric target: `native_tasklist_projected ≥ 1`, completion rate ↑ from 65%

### 1.5 Non-goals

- Refactor of deep-probe spawn (already pattern-correct, preserve as-is)
- L1/L2 codegen binding gates (working, preserve)
- Mobile-specific paths (separate consideration if needed)
- Codex skill mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build spec §2. Hooks + diagnostic + meta-skill base inherited unchanged.

---

## 3. Audit findings (parallel + binding safety)

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | Deep-probe Sonnet+adversarial cross-check | PASS | Preserve as-is |
| 2 | L1/L2 codegen binding gates | PASS | Preserve as-is |
| 3 | Console monitoring per-step | PASS | Preserve as-is |
| 4 | Bootstrap reflection Haiku | PASS | Preserve as-is |
| 5 | TEST-GOALS.md surface dispatch (L249, 810-825) | PASS | Preserve as-is |
| 6 | API-CONTRACTS Block 4 idempotency check (5b L580-670) | PASS | Preserve as-is |
| 7 | Tier 3 contract-code verification (L3003-3050) | PASS | Preserve as-is |
| 8 | `test.native_tasklist_projected` emission | **FAIL** | **Strengthen** — see §5.1 |
| 9 | Profile filtering per step (L334+) | PASS | Preserve as-is |

**Summary:** 8/9 PASS, 1/9 FAIL. Test architecture is sound; only tasklist projection telemetry is broken.

---

## 4. File and directory layout

### 4.1 Canonical (vgflow-bugfix repo)

```
commands/vg/
  test.md                                   REFACTOR: 4,188 → ~500 lines
  _shared/test/                             NEW dir
    preflight.md                            ~250 lines (gate, session, parse, telemetry, task tracker, state update)
    deploy.md                               ~150 lines (5a_deploy + 5a_mobile_deploy)
    runtime.md                              ~250 lines (5b_runtime_contract_verify + 5c_smoke + 5c_flow + 5c_mobile_flow)
    goal-verification/                      nested for HEAVY 5c_goal_verification (303 lines)
      overview.md                           ~150 lines (entry, instructs spawn vg-test-goal-verifier)
      delegation.md                         ~200 lines (input/output contract)
    codegen/                                nested for HEAVY 5d_codegen (645 lines)
      overview.md                           ~150 lines (entry, instructs spawn vg-test-codegen)
      delegation.md                         ~250 lines (input/output, L1/L2 binding gate spec)
      deep-probe.md                         ~150 lines (5d_deep_probe — UNCHANGED, refers to existing impl)
      mobile-codegen.md                     ~150 lines (5d_mobile_codegen)
    fix-loop.md                             ~250 lines (5c_fix + 5c_auto_escalate)
    regression-security.md                  ~300 lines (5e_regression + 5f_security_audit + 5g_performance_check + 5h_security_dynamic + 5f_mobile_security_audit)
    close.md                                ~250 lines (write_report + bootstrap_reflection + complete)

agents/                                     EXTEND
  vg-test-codegen/SKILL.md                  ~250 lines, codegen with L1/L2 binding gate
  vg-test-goal-verifier/SKILL.md            ~200 lines, goal replay + topological sort

scripts/
  emit-tasklist.py                          STRENGTHEN — ensure test.native_tasklist_projected emits (see §5.1)
```

---

## 5. Components

### 5.1 Strengthen `test.native_tasklist_projected` emission (the 1 audit FAIL)

Test currently fires `test.tasklist_shown` (14 events) but never `test.native_tasklist_projected` (0 events). This is the SAME bug blueprint pilot is fixing — tasklist contract is generated but Claude never projects.

Fix is already covered by inheriting blueprint pilot's:
- PostToolUse hook on TodoWrite (writes evidence file)
- vg-orchestrator tasklist-projected --adapter <claude|codex|fallback> bash command
- Slim entry SKILL.md with HARD-GATE imperative TodoWrite call

→ No test-specific code changes for this audit fail. Inheriting blueprint pilot's hook + slim template fixes it automatically.

Verification: after pilot, query events.db for `test.native_tasklist_projected` count. Target ≥ 1.

### 5.2 Slim `commands/vg/test.md` (~500 lines)

Same template as build spec §5.2. Test-specific outline:

```markdown
---
name: vg:test
description: Clean goal verification + smoke + codegen regression + security audit
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, AskUserQuestion]
runtime_contract: { ... }
---

<HARD-GATE>
You MUST follow steps in profile-filtered order. Codegen step MUST spawn
vg-test-codegen subagent (NOT inline). Goal verification MUST spawn
vg-test-goal-verifier subagent. Console monitoring MUST run after every
action — silent error skip will be detected by Stop hook.
</HARD-GATE>

## Red Flags (test-specific)

| Thought | Reality |
|---|---|
| "Codegen 1 spec.ts file, đơn giản, làm inline"      | 645-line step has L1/L2 binding gates that vg-test-codegen subagent enforces |
| "Goal verification toàn passing, skip step"          | 5c_goal_verification has topological sort + console check; skip = miss regression |
| "Console errors là noise, ignore"                    | L938-945 mandatory check; new errors = FAIL |
| "Regression không change gì, dùng cache"             | 5e_regression must execute, not just status check |
| "Security audit chạy lâu, skip lần này"              | 5f_security_audit emits event tracked by Stop hook |

## Steps

### STEP 1 — preflight
Read `_shared/test/preflight.md`. Follow exactly.

### STEP 2 — deploy
Read `_shared/test/deploy.md`. Follow exactly.

### STEP 3 — runtime contract verify + smoke
Read `_shared/test/runtime.md`. Follow exactly.

### STEP 4 — goal verification (HEAVY, subagent)
Read `_shared/test/goal-verification/overview.md`. Spawn vg-test-goal-verifier
subagent. DO NOT verify inline.

### STEP 5 — codegen (HEAVY, subagent + L1/L2 binding gate)
Read `_shared/test/codegen/overview.md`. Spawn vg-test-codegen subagent.
Subagent enforces L1 (re-codegen on selector binding fail) → L2 (architect
proposal via AskUserQuestion). DO NOT codegen inline.

### STEP 6 — fix loop + auto escalate
Read `_shared/test/fix-loop.md`. Follow exactly.

### STEP 7 — regression + security
Read `_shared/test/regression-security.md`. Follow profile-filtered branches.

### STEP 8 — close
Read `_shared/test/close.md`. Follow exactly.
```

### 5.3 Reference files

Each ref ≤500 lines. Heavy steps split into nested sub-refs (`goal-verification/`, `codegen/`).

### 5.4 Custom subagents

**`agents/vg-test-codegen/SKILL.md`** (~250 lines):
- Tools: [Read, Write, Edit, Bash, Glob, Grep]  (no Task — single-task codegen)
- HARD-GATE: "Generate Playwright .spec.ts files per TEST-GOALS slice. Apply L1 binding gate (re-codegen if selector binding fails). If L1 fails, return L2 escalation request to main. Return: { spec_files: [...], bindings_satisfied: [...], l1_resolved_count, l2_escalations: [] }"

**`agents/vg-test-goal-verifier/SKILL.md`** (~200 lines):
- Tools: [Read, Bash, Glob, Grep]
- HARD-GATE: "Verify each TEST-GOAL via replay loop with topological sort + console check. Return: { goals_verified: [{id, status, console_errors}], baseline_console_check_pass }"

### 5.5 Hooks (SHARED with blueprint pilot)

No new hooks.

### 5.6 Test-specific addendum to `vg-meta-skill.md`

```markdown
## Test-specific Red Flags

| Thought | Reality |
|---|---|
| "Codegen inline faster than spawning subagent"          | L1/L2 binding gate enforced in vg-test-codegen — bypass = miss selector drift |
| "Goal verification looks done, skip topological sort"  | Replay loop + console check are independent; skip = miss async errors |
| "Console errors are environmental, ignore"             | Mandatory check L938-945; new errors → fail-fast |
| "Regression skip if no source change"                  | 5e_regression event must emit; --skip needs override-debt |
```

---

## 6. Error handling, migration, testing, exit criteria

### 6.1 Error handling

All blocks follow blueprint pilot §4.5 (5-layer diagnostic). Test-specific:

- **Codegen L1 fail → L2** — handled by subagent return + main agent escalation; no diagnostic block needed
- **Console error detected** — fail-fast, not block (test fails legitimately)
- **TEST-GOAL surface mismatch** — block + diagnostic prompt to update goal surface or skip with override

### 6.2 Migration

- Existing 11 PrintwayV3 test runs: stand as-is.
- Existing tests: pass.
- Defer: mobile path refactor, Codex mirror.

### 6.3 Testing

**Static (pytest), new for test:**
- `test_test_slim_size.py` — assert `commands/vg/test.md` ≤ 600 lines
- `test_test_references_exist.py` — all `_shared/test/*.md` + nested
- `test_test_subagent_definitions.py` — 2 new subagents valid
- `test_test_native_tasklist_projected.py` — simulate full test run, assert event emits (currently 0)

**Inherited:** all hook tests, diagnostic tests, SessionStart re-injection, console monitoring tests (existing).

**Empirical dogfood:**
- Sync to PrintwayV3
- Run `/vg:test 3.2` (use existing dogfood phase)
- Assert: `test.native_tasklist_projected ≥ 1`, completion rate ↑

### 6.4 Exit criteria — test pilot PASS requires ALL of:

1. Tasklist visible in Claude Code UI immediately after invocation
2. **`test.native_tasklist_projected` event count ≥ 1** (baseline 0 — critical fix)
3. All 13 hard-gate step markers touched without override
4. SANDBOX-TEST.md written with explicit pass/fail verdict per goal
5. Codegen subagent invocation event present (spec.ts files written)
6. Goal-verifier subagent invocation event present
7. Deep-probe spawn (existing pattern) still fires correctly
8. Console monitoring fires after every action (existing log)
9. Stop hook fires without exit 2
10. Manual: simulate skip TodoWrite → PreToolUse hook blocks
11. Stop hook unpaired-block-fails-closed test passes

---

## 7. Round 2 sequencing

Test is bundled with build in R2. Both inherit from blueprint pilot R1. Both share the same 4 hooks + diagnostic flow. Build and test specs implementable in parallel.

Test pilot dogfood may use the SAME PrintwayV3 phase as build pilot (e.g., phase 3.2) — they exercise the same downstream artifacts but different commands.

---

## 8. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Sibling: `2026-05-03-vg-build-design.md` (R2 bundle)
- Existing test.md: `commands/vg/test.md` (4,188 lines pre-refactor)
- Deep-probe pattern: existing L2664-2732 (Sonnet + adversarial)
- Bootstrap reflection: existing L3796-3845

---

## Appendix — Codex review corrections (2026-05-03)

External review by Codex (gpt-5.5) flagged 5 spec-wide issues:

1. **Tool name `Agent`, not `Task`** — Claude Code current docs use tool name `Agent` for subagent invocations (verified via [hooks reference](https://code.claude.com/docs/en/hooks)). Any reference in this spec to `Task(...)` invocation or PreToolUse matcher `Task` MUST be implemented as `Agent`. Both `SubagentStart`/`SubagentStop` events available for additional observability.

2. **UserPromptSubmit hook needed** — Per blueprint pilot spec amendment §4.4. This spec inherits the start-of-run gate that creates `.vg/active-runs/<session>.json` BEFORE model executes. Otherwise Stop hook no-ops bypass entire enforcement.

3. **PreToolUse on Write/Edit for protected paths** — Per blueprint pilot spec amendment §4.4. AI cannot directly Write to `.vg/runs/*evidence*`, `.step-markers/*`, `events.db` etc. Must use signed orchestrator helper.

4. **Flat references (1-level)** — Anthropic guidance: keep refs ONE level from SKILL.md. Any nested `_shared/<cmd>/<group>/overview.md + delegation.md` chain in this spec should be flattened to `_shared/<cmd>/<group>-overview.md + <group>-delegation.md`.

5. **State-machine validator** — Per blueprint pilot spec amendment §4.4c. Stop hook invokes `vg-state-machine-validator.py` to verify event ORDER matches expected sequence per command — beyond mere event count.

Implementation plans for this command MUST incorporate all 5 corrections.

---

## UX baseline (mandatory cross-flow)

This flow MUST honor the 3 UX requirements baked into R1a blueprint pilot:
- **Per-task artifact split** — large artifacts (PLAN, contracts, goals,
  results) write Layer 1 per-unit + Layer 2 index + Layer 3 flat concat.
  Consumers use `scripts/vg-load.sh` for partial loads.
- **Subagent spawn narration** — every `Agent()` call wrapped with
  `bash scripts/vg-narrate-spawn.sh <name> {spawning|returned|failed}` for
  GSD-style green/cyan/red chip UX.
- **Compact hook stderr** — success silent, block 3-line + file pointer.
  Full diagnostic to `.vg/blocks/{run_id}/{gate_id}.md`.

Source: `docs/superpowers/specs/_shared-ux-baseline.md` (full pattern + code).
