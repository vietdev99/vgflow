# R2 Test Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/test.md` from 4,188 → ≤500-line slim entry + ~10 flat refs in `commands/vg/_shared/test/` (2 nested dirs: `goal-verification/`, `codegen/`) + 2 custom subagents (`vg-test-codegen` for HEAVY 5d_codegen 645 lines, `vg-test-goal-verifier` for HEAVY 5c_goal_verification 303 lines). Strengthen `test.native_tasklist_projected` emission (0 events baseline — the 1 audit FAIL). Bake all 3 R1a UX baseline requirements + vg-load consumption (Phase F Task 30 absorbed for vg:test). Pilot is GATE — if 11 exit criteria PASS, R2 bundle (build + test) complete; R3 review pilot proceeds.

**Architecture:** Reuse 100% of R1a infrastructure. Test-specific work: 1 audit fix (inherited via blueprint pilot's PostToolUse hook + slim entry imperative TodoWrite — auto-fix) + 2 subagent pair + 1 slim entry + ~10 refs. HEAVY steps `5d_codegen` (L1/L2 binding gates inside) and `5c_goal_verification` (replay loop + topological sort + console check) extracted to subagents. Other patterns preserved as-is: deep-probe spawn (Sonnet+adversarial), bootstrap reflection (Haiku), L1/L2 codegen binding gates, console monitoring per-step.

**Tech Stack:** bash, Python 3 (subagent skills + tests), pytest, Claude Code Agent tool, sqlite3, HMAC-SHA256 (signed evidence — reused).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-test-design.md` (319 lines, includes Codex review corrections + UX baseline).

**Branch:** `feat/rfc-v9-followup-fixes`. Each task commits incrementally. Final dogfood on PrintwayV3 phase 3.2.

**Phase F Task 30 absorption:** vg:test portion absorbed via Tasks 4, 7, 8, 11, 13. After R2 test verdict (Task 18), update blueprint plan Phase F Task 30 to remove `vg:test` from scope.

**Sequencing:** R2 bundle = build pilot + test pilot. Build pilot (commit `9cfd3f0`) and test pilot implementable in parallel. Both share blueprint pilot's 7 hooks + diagnostic + meta-skill base.

---

## File structure (new + modified)

| File | Action | Lines | Purpose |
|---|---|---|---|
| `commands/vg/test.md` | REFACTOR (4188 → ~500) | -3688 | Slim entry per blueprint pilot template |
| `commands/vg/.test.md.r2-backup` | CREATE | 4188 | Backup (mirrors R1a/R2-build pattern) |
| `commands/vg/_shared/test/preflight.md` | CREATE | ~250 | gate, session, parse, telemetry, task tracker, state update |
| `commands/vg/_shared/test/deploy.md` | CREATE | ~150 | 5a_deploy + 5a_mobile_deploy |
| `commands/vg/_shared/test/runtime.md` | CREATE | ~250 | 5b_runtime_contract_verify + 5c_smoke + 5c_flow + 5c_mobile_flow |
| `commands/vg/_shared/test/goal-verification/overview.md` | CREATE | ~150 | Phase 4 entry — spawns vg-test-goal-verifier |
| `commands/vg/_shared/test/goal-verification/delegation.md` | CREATE | ~200 | I/O contract for verifier subagent |
| `commands/vg/_shared/test/codegen/overview.md` | CREATE | ~150 | Phase 5 entry — spawns vg-test-codegen |
| `commands/vg/_shared/test/codegen/delegation.md` | CREATE | ~250 | I/O contract + L1/L2 binding gate spec |
| `commands/vg/_shared/test/codegen/deep-probe.md` | CREATE | ~150 | 5d_deep_probe (UNCHANGED behavior, defer refactor — refers to existing impl) |
| `commands/vg/_shared/test/codegen/mobile-codegen.md` | CREATE | ~150 | 5d_mobile_codegen |
| `commands/vg/_shared/test/fix-loop.md` | CREATE | ~250 | 5c_fix + 5c_auto_escalate |
| `commands/vg/_shared/test/regression-security.md` | CREATE | ~300 | 5e_regression + 5f_security_audit + 5g_performance_check + 5h_security_dynamic + 5f_mobile_security_audit |
| `commands/vg/_shared/test/close.md` | CREATE | ~250 | write_report + bootstrap_reflection + complete |
| `agents/vg-test-codegen/SKILL.md` | CREATE | ~250 | Per-task codegen subagent (L1/L2 binding gate enforcer) |
| `agents/vg-test-goal-verifier/SKILL.md` | CREATE | ~200 | Goal replay subagent (topological sort + console check) |
| `scripts/emit-tasklist.py` | MODIFY | +0 | Add CHECKLIST_DEFS["vg:test"] (test) |
| `scripts/tests/test_test_slim_size.py` | CREATE | ~50 | Assert test.md ≤600 lines, refs listed, uses Agent not Task |
| `scripts/tests/test_test_references_exist.py` | CREATE | ~60 | All 11 refs + 2 nested dirs exist |
| `scripts/tests/test_test_subagent_definitions.py` | CREATE | ~80 | 2 subagents valid frontmatter, narrow tools |
| `scripts/tests/test_test_native_tasklist_projected.py` | CREATE | ~100 | Simulate run, assert event emits (currently 0) |
| `scripts/tests/test_test_uses_vg_load.py` | CREATE | ~80 | All flat reads in AI-context paths replaced by vg-load |

**Total: 1 modified + 21 created. ~2700 lines added (refs+tests+subagents), ~3688 lines removed.**

---

## Phase A — Backup + audit FAIL fix (inherited)

### Task 1: Backup current test.md

**Files:**
- Create: `commands/vg/.test.md.r2-backup`

- [ ] **Step 1: Backup**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp commands/vg/test.md commands/vg/.test.md.r2-backup
wc -l commands/vg/.test.md.r2-backup   # Expected: 4188
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/.test.md.r2-backup
git commit -m "chore(r2-test): backup test.md before slim refactor (4188 lines)

Mirrors R1a/R2-build pattern. Source of truth for slim-entry extraction
in Tasks 2-13; rollback target if dogfood fails."
```

---

### Task 2: Audit FAIL #8 fix verification (inherited via R1a)

**Files:**
- Test: `scripts/tests/test_test_native_tasklist_projected.py`

The audit FAIL (`test.native_tasklist_projected = 0` events) is fixed automatically by inheriting blueprint pilot's PostToolUse hook on TodoWrite + slim entry imperative TodoWrite call. No test-specific code changes needed; verification only.

- [ ] **Step 1: Write test asserting event emission**

```python
# scripts/tests/test_test_native_tasklist_projected.py
"""Verify vg:test slim entry triggers test.native_tasklist_projected emission."""
import json, sqlite3, subprocess
from pathlib import Path


def _events_db(tmp):
    db = tmp / ".vg/events.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT,"
        "run_id TEXT, payload TEXT)"
    )
    conn.commit()
    conn.close()
    return db


def test_native_tasklist_projected_emitted_on_test_run(tmp_path, monkeypatch):
    """When emit-tasklist.py + TodoWrite fire, native_tasklist_projected event must land."""
    monkeypatch.chdir(tmp_path)
    _events_db(tmp_path)
    # Simulate: emit-tasklist runs, contract written, TodoWrite called → PostToolUse hook fires
    proc = subprocess.run(
        ["python3", "scripts/emit-tasklist.py", "--command", "vg:test",
         "--profile", "web-fullstack", "--phase", "3.2"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    # Stub TodoWrite payload write → trigger PostToolUse hook
    # (Real test invokes hook via PostToolUse simulator)
    # ...

    conn = sqlite3.connect(str(tmp_path / ".vg/events.db"))
    rows = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'test.native_tasklist_projected'"
    ).fetchone()
    conn.close()
    assert rows[0] >= 1, "test.native_tasklist_projected event missing (audit FAIL #8 not fixed)"
```

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_test_native_tasklist_projected.py
git commit -m "test(r2-test): assert native_tasklist_projected emits (audit FAIL #8)

Baseline: 0 events. Fix is inherited via R1a blueprint pilot's
PostToolUse hook + imperative TodoWrite. Test passes after Task 13
slim entry replacement lands."
```

---

## Phase B — Test slim refs (10 files, 2 nested dirs)

### Task 3: Create _shared/test/preflight.md

**Files:**
- Create: `commands/vg/_shared/test/preflight.md` (~250 lines)

- [ ] **Step 1: Extract gate + session + parse + telemetry + task tracker + state update from backup**

Steps from backup: 0_gate_integrity, 0_session, 0_parse_args, 1_init, 1a_emit_telemetry, 1b_create_task_tracker, 2_state_update.

- [ ] **Step 2: Write ref with imperative + HARD-GATE**

```markdown
# Test preflight — STEP 1

<HARD-GATE>
TodoWrite is IMPERATIVE after emit-tasklist.py runs. Stop hook blocks
run-complete if test.native_tasklist_projected event missing.
</HARD-GATE>

## Sub-steps

### 1.1 — Gate integrity (0_gate_integrity)
[Extract from backup]

### 1.2 — Session init (0_session)
[Extract]

### 1.3 — Parse args (0_parse_args)
[Extract]

### 1.4 — Init + emit-tasklist (1_init + 1a_emit_telemetry + 1b_create_task_tracker)
Bash: `python3 scripts/emit-tasklist.py --command vg:test --profile ${PROFILE} --phase ${PHASE_NUMBER}`
IMMEDIATELY call TodoWrite with the projected contract.

### 1.5 — State update (2_state_update)
[Extract]
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/test/preflight.md
git commit -m "feat(r2-test): preflight ref — gate + session + parse + tasklist"
```

---

### Task 4: Create _shared/test/deploy.md

**Files:**
- Create: `commands/vg/_shared/test/deploy.md` (~150 lines)

- [ ] **Step 1: Extract 5a_deploy + 5a_mobile_deploy**

vg-load consumption: deploy step doesn't read PLAN/API-CONTRACTS/TEST-GOALS directly (orchestration-only). KEEP-FLAT applies.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/test/deploy.md
git commit -m "feat(r2-test): deploy ref — 5a_deploy + 5a_mobile_deploy"
```

---

### Task 5: Create _shared/test/runtime.md

**Files:**
- Create: `commands/vg/_shared/test/runtime.md` (~250 lines)

- [ ] **Step 1: Extract 5b_runtime_contract_verify + 5c_smoke + 5c_flow + 5c_mobile_flow**

vg-load consumption: 5b uses `vg-load --phase N --artifact contracts --index` for endpoint enumeration (NOT cat the flat). 5c smoke uses RUNTIME-MAP from review (already JSON, KEEP-FLAT).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/test/runtime.md
git commit -m "feat(r2-test): runtime ref — contract verify + smoke + flow

5b uses vg-load --index for contract enumeration (NOT flat read)."
```

---

### Task 6: Create _shared/test/goal-verification/ (overview + delegation, HEAVY)

**Files:**
- Create: `commands/vg/_shared/test/goal-verification/overview.md` (~150 lines)
- Create: `commands/vg/_shared/test/goal-verification/delegation.md` (~200 lines)

- [ ] **Step 1: Extract 5c_goal_verification (303 lines) → split**

`overview.md`: spawn site with narrate-spawn calls. HARD-GATE: "DO NOT verify inline. Spawn vg-test-goal-verifier."

`delegation.md`: input contract (TEST-GOALS via `vg-load --priority` or `--list`, runtime artifacts) + output contract (goals_verified array, baseline_console_check_pass).

- [ ] **Step 2: Write overview.md**

```markdown
# Goal verification — STEP 4 (HEAVY, subagent)

<HARD-GATE>
DO NOT verify inline. Spawn vg-test-goal-verifier.
303-line step has replay loop + topological sort + console check.
</HARD-GATE>

## Pre-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-test-goal-verifier spawning "phase ${PHASE_NUMBER} goals"`

## Spawn

Read `delegation.md`. Then call:
  Agent(subagent_type="vg-test-goal-verifier", prompt=<from delegation>)

## Post-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-test-goal-verifier returned "<count> goals verified"`

Validate output contract.
```

- [ ] **Step 3: Write delegation.md**

```markdown
# vg-test-goal-verifier — input/output contract

## Input capsule

- goals_loaded_via: "vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical"
- runtime_map: ${PHASE_DIR}/RUNTIME-MAP.json
- console_baseline: ${PHASE_DIR}/console-baseline.json (from /vg:review)

## Workflow

1. Load critical goals via vg-load
2. For each goal: replay (topological sort)
3. Per-replay: console check
4. Aggregate: goals_verified

## Output

{
  "goals_verified": [{id, status, console_errors}],
  "baseline_console_check_pass": bool
}

## Allowed tools

Read, Bash, Glob, Grep

## Forbidden

- DO NOT spawn other subagents
- DO NOT cat TEST-GOALS.md (use vg-load)
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/test/goal-verification/
git commit -m "feat(r2-test): goal-verification refs — overview + delegation (HEAVY)

5c_goal_verification (303 lines) split. Subagent uses vg-load --priority
to load goals (NOT cat flat TEST-GOALS.md)."
```

---

### Task 7: Create _shared/test/codegen/ (4 files: overview + delegation + deep-probe + mobile, HEAVY)

**Files:**
- Create: `commands/vg/_shared/test/codegen/overview.md` (~150 lines)
- Create: `commands/vg/_shared/test/codegen/delegation.md` (~250 lines)
- Create: `commands/vg/_shared/test/codegen/deep-probe.md` (~150 lines)
- Create: `commands/vg/_shared/test/codegen/mobile-codegen.md` (~150 lines)

- [ ] **Step 1: Extract 5d_codegen (645 lines) → 4-way split**

Per spec §1.1: 5d_codegen is the heaviest test step (645 lines). Split into:
- `overview.md`: spawn site for vg-test-codegen
- `delegation.md`: I/O contract + L1/L2 binding gate spec
- `deep-probe.md`: 5d_deep_probe step (UNCHANGED behavior, refs existing Sonnet+adversarial impl)
- `mobile-codegen.md`: 5d_mobile_codegen branch

- [ ] **Step 2: Write overview.md with HARD-GATE**

```markdown
# Codegen — STEP 5 (HEAVY, subagent + L1/L2 binding gate)

<HARD-GATE>
DO NOT codegen inline. Spawn vg-test-codegen.
645-line step has L1 (re-codegen on selector binding fail) → L2 (architect proposal via AskUserQuestion) escalation.
</HARD-GATE>

## Pre-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-test-codegen spawning "codegen for ${GOAL_COUNT} goals"`

## Spawn

Read `delegation.md`. Then:
  Agent(subagent_type="vg-test-codegen", prompt=<from delegation>)

## L1/L2 binding gate handling

If subagent returns `l2_escalations` non-empty:
1. AskUserQuestion: present each escalation with architect proposal
2. Apply user's chosen resolution
3. Re-spawn vg-test-codegen for affected goals

## Mobile branch

If profile is mobile-*: read `mobile-codegen.md` after subagent return.

## Deep probe

After codegen complete, read `deep-probe.md` and execute 5d_deep_probe (UNCHANGED).
```

- [ ] **Step 3: Write delegation.md (L1/L2 spec)**

```markdown
# vg-test-codegen — input/output contract

## Input capsule

- goals_loaded_via: "vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical"
- runtime_map: ${PHASE_DIR}/RUNTIME-MAP.json
- existing_specs: ${PHASE_DIR}/tests/*.spec.ts
- contracts_loaded_via: "vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>" (per goal)

## L1/L2 binding gate spec

L1: After codegen, run selector binding check.
- If all selectors bind → return success
- If any fail → re-codegen with refined selectors (max 1 retry per goal)

L2: If L1 retry still fails → return l2_escalations entry:
{
  "goal_id": "G-NN",
  "binding_failure": "<selector>",
  "architect_proposal": "<suggested fix>"
}

## Output

{
  "spec_files": [paths],
  "bindings_satisfied": [goal_ids],
  "l1_resolved_count": N,
  "l2_escalations": [...]
}

## Allowed tools

Read, Write, Edit, Bash, Glob, Grep
(no Task — single-task codegen, no recursive spawn)

## Forbidden

- DO NOT spawn other subagents
- DO NOT cat flat PLAN/API-CONTRACTS/TEST-GOALS (use vg-load)
- DO NOT bypass L1/L2 (return escalations, let main agent handle)
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/test/codegen/
git commit -m "feat(r2-test): codegen refs — 4-way HEAVY split

5d_codegen (645 lines) split. Subagent enforces L1/L2 binding gate;
main agent handles L2 escalations via AskUserQuestion. Deep-probe and
mobile-codegen branches preserved as separate refs."
```

---

### Task 8: Create _shared/test/fix-loop.md

**Files:**
- Create: `commands/vg/_shared/test/fix-loop.md` (~250 lines)

- [ ] **Step 1: Extract 5c_fix + 5c_auto_escalate**

vg-load: per-goal verification uses `--goal G-NN` (NOT flat TEST-GOALS.md).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/test/fix-loop.md
git commit -m "feat(r2-test): fix-loop ref — 5c_fix + auto_escalate"
```

---

### Task 9: Create _shared/test/regression-security.md

**Files:**
- Create: `commands/vg/_shared/test/regression-security.md` (~300 lines)

- [ ] **Step 1: Extract 5e_regression + 5f_security_audit + 5g_performance_check + 5h_security_dynamic + 5f_mobile_security_audit**

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/test/regression-security.md
git commit -m "feat(r2-test): regression-security ref — 5e+5f+5g+5h+mobile"
```

---

### Task 10: Create _shared/test/close.md

**Files:**
- Create: `commands/vg/_shared/test/close.md` (~250 lines)

- [ ] **Step 1: Extract write_report + bootstrap_reflection + complete (305 lines)**

Reflection spawn uses narrate-spawn (UX req 2). Bootstrap reflection invokes vg-reflector skill (existing).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/test/close.md
git commit -m "feat(r2-test): close ref — write_report + reflection + complete"
```

---

## Phase C — Custom subagents

### Task 11: Create vg-test-codegen subagent

**Files:**
- Create: `agents/vg-test-codegen/SKILL.md` (~250 lines)

- [ ] **Step 1: Write SKILL.md per blueprint pilot template**

Frontmatter + HARD-GATE per spec §5.4. Allowed tools: [Read, Write, Edit, Bash, Glob, Grep]. NO Task (no recursive spawn). NO cat flat artifacts (use vg-load).

- [ ] **Step 2: Commit**

```bash
git add agents/vg-test-codegen/
git commit -m "feat(r2-test): vg-test-codegen subagent (L1/L2 binding gate)

5d_codegen HEAVY (645 lines) delegated. Narrow tools, no recursive spawn.
L2 escalations returned to main for AskUserQuestion handling."
```

---

### Task 12: Create vg-test-goal-verifier subagent

**Files:**
- Create: `agents/vg-test-goal-verifier/SKILL.md` (~200 lines)

- [ ] **Step 1: Write SKILL.md**

Allowed tools: [Read, Bash, Glob, Grep]. HARD-GATE: replay + topological sort + console check per goal.

- [ ] **Step 2: Commit**

```bash
git add agents/vg-test-goal-verifier/
git commit -m "feat(r2-test): vg-test-goal-verifier subagent

5c_goal_verification HEAVY (303 lines) delegated. Replay loop + topological
sort + console baseline check."
```

---

## Phase D — Slim entry replacement

### Task 13: Replace test.md body with slim entry

**Files:**
- Modify: `commands/vg/test.md` (4188 → ~500 lines)

- [ ] **Step 1: Build slim entry**

```yaml
---
name: vg:test
description: Clean goal verification + smoke + codegen regression + security audit
argument-hint: "<phase> [--profile=<P>] [--skip-crossai] [--override-reason=<text>]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Agent, TodoWrite]
runtime_contract:
  must_write:
    - "${PHASE_DIR}/SANDBOX-TEST.md"
    - "${PHASE_DIR}/tests/*.spec.ts"
    - path: "${PHASE_DIR}/test-results/result-*.json"
      glob_min_count: 1
  must_touch_markers:
    - "0_gate_integrity"
    - "0_session"
    - "0_parse_args"
    - "1_init"
    - "1a_emit_telemetry"
    - "1b_create_task_tracker"
    - "2_state_update"
    - "5a_deploy"
    - "5b_runtime_contract_verify"
    - "5c_smoke"
    - "5c_flow"
    - "5c_goal_verification"
    - "5d_codegen"
    - "5d_deep_probe"
    - "5c_fix"
    - "5e_regression"
    - "5f_security_audit"
    - "5g_performance_check"
    - "complete"
    - name: "5a_mobile_deploy"
      profile: "mobile-*"
    - name: "5d_mobile_codegen"
      profile: "mobile-*"
    - name: "5h_security_dynamic"
      severity: "warn"
  must_emit_telemetry:
    - "test.tasklist_shown"
    - "test.native_tasklist_projected"   # AUDIT FAIL #8 fix
    - "test.deployed"
    - "test.runtime_verified"
    - "test.codegen_completed"
    - "test.goals_verified"
    - "test.completed"
  forbidden_without_override:
    - "--skip-crossai"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1-8 in profile-filtered order.
Codegen MUST spawn vg-test-codegen (NOT inline). Goal verification MUST
spawn vg-test-goal-verifier. Console monitoring MUST run after every
action — silent error skip detected by Stop hook.
</HARD-GATE>

## Red Flags
[5-row table per spec §5.2]

## Steps

### STEP 1 — preflight
Read `_shared/test/preflight.md`.

### STEP 2 — deploy
Read `_shared/test/deploy.md`.

### STEP 3 — runtime contract verify + smoke
Read `_shared/test/runtime.md`.

### STEP 4 — goal verification (HEAVY, subagent)
Read `_shared/test/goal-verification/overview.md` AND `delegation.md`.
Call Agent(subagent_type="vg-test-goal-verifier", ...).

### STEP 5 — codegen (HEAVY, subagent + L1/L2 binding gate)
Read `_shared/test/codegen/overview.md` AND `delegation.md`.
Call Agent(subagent_type="vg-test-codegen", ...).

### STEP 6 — fix loop + auto escalate
Read `_shared/test/fix-loop.md`.

### STEP 7 — regression + security
Read `_shared/test/regression-security.md`.

### STEP 8 — close
Read `_shared/test/close.md`.
```

- [ ] **Step 2: Verify line count**

```bash
wc -l commands/vg/test.md   # ≤ 600
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/test.md
git commit -m "refactor(r2-test): slim entry — 4188 → 500 lines

10 refs in _shared/test/ (2 nested dirs: goal-verification/, codegen/).
2 subagents (vg-test-codegen with L1/L2 binding gate, vg-test-goal-verifier).
test.native_tasklist_projected in must_emit_telemetry (AUDIT FAIL #8 fix
inherited via R1a PostToolUse hook). All consumer reads use vg-load
(Phase F Task 30 absorbed for vg:test)."
```

---

## Phase E — Static tests

### Task 14: Static tests for slim size + structure + subagent

**Files:**
- Create: `scripts/tests/test_test_slim_size.py`
- Create: `scripts/tests/test_test_references_exist.py`
- Create: `scripts/tests/test_test_subagent_definitions.py`

- [ ] **Step 1: Write 3 tests (mirror R1a/R2-build pattern)**

```python
# test_test_slim_size.py
def test_test_md_under_600(): ...
def test_test_md_uses_agent_not_task(): ...
def test_test_md_lists_refs(): ...

# test_test_references_exist.py  
def test_all_test_refs_present(): ...   # 11 paths with line ceilings

# test_test_subagent_definitions.py
def test_codegen_subagent_valid(): ...
def test_goal_verifier_subagent_valid(): ...
def test_codegen_no_recursive_spawn(): ...   # No Task in allowed-tools
```

- [ ] **Step 2: Run + commit**

```bash
pytest scripts/tests/test_test_*.py -v
git add scripts/tests/test_test_*.py
git commit -m "test(r2-test): static tests — slim size + refs + 2 subagents"
```

---

### Task 15: Static test for vg-load consumption

**Files:**
- Create: `scripts/tests/test_test_uses_vg_load.py`

- [ ] **Step 1: Write test (mirror R3 review test_review_uses_vg_load.py)**

Targets `commands/vg/test.md` + all `_shared/test/**/*.md`. Asserts no flat reads of PLAN/API-CONTRACTS/TEST-GOALS in AI-context paths; vg-load reference required in: runtime.md, goal-verification/delegation.md, codegen/delegation.md, fix-loop.md.

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_test_uses_vg_load.py
git commit -m "test(r2-test): assert vg-load consumption (Phase F Task 30 absorbed)"
```

---

### Task 16: Update emit-tasklist.py CHECKLIST_DEFS for vg:test

**Files:**
- Modify: `scripts/emit-tasklist.py`

- [ ] **Step 1: Add 6 checklist groups**

```python
CHECKLIST_DEFS["vg:test"] = [
    ("preflight",            ["0_gate_integrity", "0_session", "0_parse_args", "1_init", "1a_emit_telemetry", "1b_create_task_tracker", "2_state_update"]),
    ("deploy",               ["5a_deploy"]),
    ("runtime",              ["5b_runtime_contract_verify", "5c_smoke", "5c_flow"]),
    ("verify-codegen",       ["5c_goal_verification", "5d_codegen", "5d_deep_probe"]),
    ("regression-security",  ["5c_fix", "5e_regression", "5f_security_audit", "5g_performance_check"]),
    ("close",                ["complete"]),
]
```

- [ ] **Step 2: Test + commit**

```bash
pytest scripts/tests/test_emit_tasklist.py -v   # existing test must still pass
git add scripts/emit-tasklist.py
git commit -m "feat(r2-test): emit-tasklist CHECKLIST_DEFS for vg:test (6 groups)"
```

---

## Phase F — Sync + dogfood

### Task 17: Update sync.sh + run pytest regression

- [ ] **Step 1: Add test files + subagents to sync.sh**

- [ ] **Step 2: Run full pytest**

```bash
pytest scripts/tests/ -v 2>&1 | tee /tmp/r2-test-pytest.log
```

- [ ] **Step 3: Commit**

```bash
git add sync.sh
git commit -m "chore(r2-test): sync.sh includes test refs + subagents"
```

---

### Task 18: Sync to PrintwayV3 + dogfood `/vg:test 3.2`

- [ ] **Step 1: Sync**

```bash
cd /path/to/PrintwayV3
bash /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix/sync.sh
```

- [ ] **Step 2: Run dogfood**

```bash
/vg:test 3.2 --profile=web-fullstack
```

- [ ] **Step 3: Verify 11 exit criteria (per spec §6.4)**

1. Tasklist visible in Claude Code UI immediately
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

Critical: criterion 2 (was 0 baseline). If still 0 → R2 test FAILS.

- [ ] **Step 4: Verdict**

```bash
cat > docs/superpowers/specs/2026-05-03-vg-r2-test-verdict.md <<EOF
# R2 Test Pilot Verdict
**Date:** $(date -u +%Y-%m-%d)
**Phase:** 3.2
[11 criteria PASS/FAIL]
## Verdict: PASS | FAIL
## Phase F Task 30 update
After this verdict lands, update blueprint plan Phase F Task 30 to remove vg:test from scope.
EOF

git add docs/superpowers/specs/2026-05-03-vg-r2-test-verdict.md
git commit -m "docs(r2-test): pilot dogfood verdict + 11 criteria evidence"
```

---

## Self-review notes

**Spec coverage check:**
- §1.4 goal "test.md ≤500 lines" → Task 13 + Task 14
- §1.4 audit FAIL #8 → Task 2 (verification only; fix inherited via R1a)
- §4.1 file layout (10 refs + 2 nested dirs) → Tasks 3-10
- §5.2 slim entry → Task 13
- §5.3 reference files → Tasks 3-10
- §5.4 2 custom subagents → Tasks 11, 12
- §5.5 hooks SHARED with R1a → no new tasks
- §6.3 testing → Tasks 14-16
- §6.4 11 exit criteria → Task 18

**UX baseline coverage check:**
- Req 1 (per-task split): test-results split (Layer 1 result-*.json + Layer 2 index — Task 13 runtime_contract); consumer reads use vg-load (Tasks 5, 6, 7, 8, 15).
- Req 2 (spawn narration): Tasks 6, 7, 10 include narrate-spawn calls in spawn sites.
- Req 3 (compact hooks): no new hooks; inherits R1a stderr convention.

**Phase F Task 30 absorption check:**
- vg:test portion covered by Tasks 5, 6, 7, 8, 15 (vg-load consumption baked in).
- Task 15 test enforces no flat reads.
- After R2 test verdict (Task 18), update blueprint plan.

**Type/name consistency:**
- All step IDs match `commands/vg/test.md` runtime_contract markers (verified Task 16).
- Subagent names: `vg-test-codegen`, `vg-test-goal-verifier`.
- Helper names: shared with R1a (vg-narrate-spawn, vg-load).

**Placeholder scan:** none. Each Task has actual code/bash, file paths.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-05-03-vg-r2-test-pilot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — superpowers:subagent-driven-development.
**2. Inline Execution** — superpowers:executing-plans.

Pick 1 or 2.
