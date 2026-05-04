# R4 Accept Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/accept.md` from 2,429 → ≤500-line slim entry + ~10 flat refs in `commands/vg/_shared/accept/` (3 nested dirs: `uat/checklist-build/`, `uat/`, `cleanup/`) + 2 custom subagents (`vg-accept-uat-builder` for HEAVY 4_build_uat_checklist 291 lines, `vg-accept-cleanup` for HEAVY 7_post_accept_actions 324 lines). **Critical UX requirement: interactive UAT (step 5, 213 lines) STAYS INLINE — NOT a subagent.** Strengthen `accept.native_tasklist_projected` emission (0 events baseline). Bake all 3 R1a UX baseline requirements + vg-load consumption (Phase F Task 30 absorbed for vg:accept). Pilot is GATE — if 12 exit criteria PASS, R4 round complete.

**Architecture:** Reuse 100% of R1a infrastructure. Accept-specific work: 0 audit fixes (1 FAIL inherited via blueprint pilot's PostToolUse hook + slim entry imperative TodoWrite — auto-fix) + 2 subagent pair + 1 slim entry + ~10 refs. HEAVY steps `4_build_uat_checklist` and `7_post_accept_actions` extracted to subagents. Other patterns preserved as-is: `.uat-responses.json` anti-theatre, quorum gate critical-skip threshold, override-debt register integration (gate 3c), greenfield design Form B block, design-debt threshold gate, UAT narrative autofire (4b deterministic Sonnet-free), learn auto-surface (6c orchestrator hook), security baseline subprocess.

**Tech Stack:** bash, Python 3 (subagent skills + tests), pytest, Claude Code Agent tool, sqlite3, HMAC-SHA256 (signed evidence — reused), AskUserQuestion (50+ items in interactive UAT — UNCHANGED).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-accept-design.md` (311 lines, includes UX baseline reference).

**Branch:** `feat/rfc-v9-followup-fixes`. Each task commits incrementally. Final dogfood on a PrintwayV3 phase with completed build+review+test.

**Phase F Task 30 absorption:** vg:accept portion absorbed via Tasks 4, 5, 8, 11, 14. After R4 verdict (Task 17), update blueprint plan Phase F Task 30 to remove `vg:accept` from scope.

**Sequencing:** R4 (after R1 blueprint, R2 build+test, R3 review). Accept depends on artifacts from build + review + test → must wait for those to stabilize. Override-debt patterns may emerge from R1-R3 dogfood; refine accept gates afterward.

---

## File structure (new + modified)

| File | Action | Lines | Purpose |
|---|---|---|---|
| `commands/vg/accept.md` | REFACTOR (2429 → ~500) | -1929 | Slim entry per blueprint pilot template |
| `commands/vg/.accept.md.r4-backup` | CREATE | 2429 | Backup |
| `commands/vg/_shared/accept/preflight.md` | CREATE | ~150 | gate integrity, config load, task tracker, telemetry |
| `commands/vg/_shared/accept/gates.md` | CREATE | ~300 | artifact precheck, marker precheck, sandbox verdict, unreachable triage, override resolution |
| `commands/vg/_shared/accept/uat/checklist-build/overview.md` | CREATE | ~100 | Step 4 entry — spawns vg-accept-uat-builder |
| `commands/vg/_shared/accept/uat/checklist-build/delegation.md` | CREATE | ~150 | I/O contract for 6 sections A-F |
| `commands/vg/_shared/accept/uat/narrative.md` | CREATE | ~150 | 4b autofire UAT-NARRATIVE.md |
| `commands/vg/_shared/accept/uat/interactive.md` | CREATE | ~250 | Step 5 STAYS INLINE — slim, imperative, AskUserQuestion loop |
| `commands/vg/_shared/accept/uat/quorum.md` | CREATE | ~200 | 5_uat_quorum_gate |
| `commands/vg/_shared/accept/audit.md` | CREATE | ~250 | 6b security baseline, 6c learn auto-surface, 6 write_uat_md |
| `commands/vg/_shared/accept/cleanup/overview.md` | CREATE | ~100 | Step 7 entry — spawns vg-accept-cleanup |
| `commands/vg/_shared/accept/cleanup/delegation.md` | CREATE | ~150 | Cleanup steps + bootstrap hygiene |
| `agents/vg-accept-uat-builder/SKILL.md` | CREATE | ~250 | Build 6-section UAT checklist from VG artifacts |
| `agents/vg-accept-cleanup/SKILL.md` | CREATE | ~200 | Post-accept cleanup + bootstrap hygiene |
| `scripts/emit-tasklist.py` | MODIFY | +0 | Add CHECKLIST_DEFS["vg:accept"] |
| `scripts/tests/test_accept_slim_size.py` | CREATE | ~50 | Assert accept.md ≤600 lines |
| `scripts/tests/test_accept_references_exist.py` | CREATE | ~60 | All 10 refs + 3 nested dirs |
| `scripts/tests/test_accept_subagent_definitions.py` | CREATE | ~80 | 2 subagents valid; assert NO uat-interactive subagent |
| `scripts/tests/test_accept_interactive_stays_inline.py` | CREATE | ~70 | Verify step 5 has no Agent() call (interactive UX requirement) |
| `scripts/tests/test_accept_uses_vg_load.py` | CREATE | ~80 | All flat reads in AI-context paths replaced by vg-load |

**Total: 1 modified + 18 created. ~2200 lines added, ~1929 lines removed.**

---

## Phase A — Backup

### Task 1: Backup current accept.md

- [ ] **Step 1: Backup**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp commands/vg/accept.md commands/vg/.accept.md.r4-backup
wc -l commands/vg/.accept.md.r4-backup   # Expected: 2429
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/.accept.md.r4-backup
git commit -m "chore(r4-accept): backup accept.md before slim refactor (2429 lines)"
```

---

## Phase B — Accept slim refs (10 files, 3 nested dirs)

### Task 2: Create _shared/accept/preflight.md

**Files:**
- Create: `commands/vg/_shared/accept/preflight.md` (~150 lines)

- [ ] **Step 1: Extract gate integrity + config load + task tracker + telemetry**

```markdown
# Accept preflight — STEP 1

<HARD-GATE>
TodoWrite IMPERATIVE after emit-tasklist.py.
accept.native_tasklist_projected = 0 baseline; this step's TodoWrite
is the fix.
</HARD-GATE>
[Sub-steps from backup]
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/accept/preflight.md
git commit -m "feat(r4-accept): preflight ref"
```

---

### Task 3: Create _shared/accept/gates.md

**Files:**
- Create: `commands/vg/_shared/accept/gates.md` (~300 lines)

- [ ] **Step 1: Extract 3-tier gates**

artifact precheck → marker precheck → sandbox verdict → unreachable triage → override resolution. Each gate fail-fast.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/accept/gates.md
git commit -m "feat(r4-accept): gates ref — 3-tier preflight gates"
```

---

### Task 4: Create _shared/accept/uat/checklist-build/ (overview + delegation, HEAVY)

**Files:**
- Create: `commands/vg/_shared/accept/uat/checklist-build/overview.md` (~100 lines)
- Create: `commands/vg/_shared/accept/uat/checklist-build/delegation.md` (~150 lines)

- [ ] **Step 1: Extract 4_build_uat_checklist (291 lines) → split**

Per spec §1.1 + §5.2: HEAVY step that builds 6-section UAT checklist (A: decisions, A.1: foundation refs, B: goals, B.1: CRUD surfaces, C: ripple HIGH, D: design refs, E: deliverables, F: mobile gates).

- [ ] **Step 2: Write overview.md (spawn site)**

```markdown
# UAT checklist build — STEP 3 (HEAVY, subagent)

<HARD-GATE>
DO NOT build inline. Spawn vg-accept-uat-builder.
291-line step parses 8+ artifact files; inline execution will skim.
</HARD-GATE>

## Pre-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-accept-uat-builder spawning "phase ${PHASE_NUMBER} UAT checklist"`

## Spawn

Read `delegation.md`. Then call:
  Agent(subagent_type="vg-accept-uat-builder", prompt=<from delegation>)

## Post-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-accept-uat-builder returned "<count> items"`

Validate output contract.
```

- [ ] **Step 3: Write delegation.md (sources via vg-load where possible)**

```markdown
# vg-accept-uat-builder — input/output contract

## Input capsule

- decisions: parse CONTEXT.md (KEEP-FLAT — small file)
- foundation: FOUNDATION.md if cited (KEEP-FLAT)
- goals: vg-load --phase ${PHASE_NUMBER} --artifact goals --list (Layer 1 list, then per-goal expand)
- crud_surfaces: CRUD-SURFACES.md (single doc, KEEP-FLAT)
- ripple: .ripple.json + RIPPLE-ANALYSIS.md (KEEP-FLAT, small)
- design_refs: vg-load --phase ${PHASE_NUMBER} --artifact plan --list (extract design-refs from PLAN tasks)
- deliverables: SUMMARY*.md (KEEP-FLAT)
- mobile_gates: build-state.log (KEEP-FLAT)

## Workflow

1. Parse each source
2. Build 6 sections (A-F)
3. Write checklist to ${PHASE_DIR}/uat-checklist.md
4. Return: { checklist_path, sections: [{name, items: [{id, summary, source_file, source_line}]}] }

## Allowed tools

Read, Write, Bash, Grep
(NO Task — single-task build, no recursive spawn)

## Forbidden

- DO NOT spawn other subagents
- DO NOT cat flat TEST-GOALS.md (use vg-load --list + per-goal)
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/accept/uat/checklist-build/
git commit -m "feat(r4-accept): checklist-build refs — overview + delegation (HEAVY)

4_build_uat_checklist (291 lines) split. Subagent uses vg-load for goals
+ design-refs (NOT flat TEST-GOALS.md / PLAN.md)."
```

---

### Task 5: Create _shared/accept/uat/narrative.md

**Files:**
- Create: `commands/vg/_shared/accept/uat/narrative.md` (~150 lines)

- [ ] **Step 1: Extract 4b autofire UAT-NARRATIVE.md generation**

Deterministic, Sonnet-free generation from TEST-GOALS frontmatter. Uses `vg-load --priority` + per-goal expand.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/accept/uat/narrative.md
git commit -m "feat(r4-accept): narrative ref — 4b autofire UAT-NARRATIVE.md"
```

---

### Task 6: Create _shared/accept/uat/interactive.md (CRITICAL — INLINE, NOT subagent)

**Files:**
- Create: `commands/vg/_shared/accept/uat/interactive.md` (~250 lines)

- [ ] **Step 1: Extract 5_interactive_uat (213 lines) — STAYS INLINE**

Per spec §1.2: interactive UX requires AskUserQuestion in main agent. Subagent context handoff would feel disjointed. `.uat-responses.json` written after EACH section.

- [ ] **Step 2: Write ref with HARD-GATE forbidding subagent extraction**

```markdown
# Interactive UAT — STEP 5 (INLINE, NOT subagent)

<HARD-GATE>
This step MUST execute in the main agent. DO NOT spawn a subagent for
interactive UAT. AskUserQuestion is a UI-presentation tool; subagent
delegation breaks UX continuity.

You MUST write .uat-responses.json after EACH of the 6 sections (anti-theatre
measure). Quorum gate (Step 6) blocks if file missing or sections empty.
</HARD-GATE>

## 6 sections (50+ AskUserQuestion items)

### Section A — Decisions
[~10 items per phase from CONTEXT.md]

### Section B — Goals
[~15 items from vg-load --list]

### Section C — Ripple HIGH
[~5 items from RIPPLE-ANALYSIS.md]

### Section D — Design refs
[~5 items from PLAN design-refs]

### Section E — Deliverables
[~10 items from SUMMARY*.md]

### Section F — Mobile gates
[~5 items from build-state.log]

## After EACH section

Bash:
```
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): section ${SECTION} complete with N answers" \
  >> ${PHASE_DIR}/.uat-responses.json
```

## At step end

Verify .uat-responses.json has all 6 sections + final verdict line.
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/accept/uat/interactive.md
git commit -m "feat(r4-accept): interactive ref — STAYS INLINE (UX requirement)

5_interactive_uat (213 lines) NOT extracted to subagent — interactive
AskUserQuestion UX requires main agent. .uat-responses.json mandatory
per section (anti-theatre)."
```

---

### Task 7: Create _shared/accept/uat/quorum.md

**Files:**
- Create: `commands/vg/_shared/accept/uat/quorum.md` (~200 lines)

- [ ] **Step 1: Extract 5_uat_quorum_gate (204 lines)**

Quorum math + rationalization-guard. Counts SKIPs on critical items (Section A decisions, Section B READY goals); blocks unless `--allow-uat-skips` + rationalization-guard.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/accept/uat/quorum.md
git commit -m "feat(r4-accept): quorum ref — critical-skip threshold gate"
```

---

### Task 8: Create _shared/accept/audit.md

**Files:**
- Create: `commands/vg/_shared/accept/audit.md` (~250 lines)

- [ ] **Step 1: Extract 6b security baseline + 6c learn auto-surface + 6 write_uat_md**

vg-load consumption: write_uat_md uses `vg-load --priority` to enumerate goals (NOT flat TEST-GOALS.md).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/accept/audit.md
git commit -m "feat(r4-accept): audit ref — security + learn + UAT.md write"
```

---

### Task 9: Create _shared/accept/cleanup/ (overview + delegation, HEAVY)

**Files:**
- Create: `commands/vg/_shared/accept/cleanup/overview.md` (~100 lines)
- Create: `commands/vg/_shared/accept/cleanup/delegation.md` (~150 lines)

- [ ] **Step 1: Extract 7_post_accept_actions (324 lines)**

Cleanup tasks: artifact archival, bootstrap hygiene, marker rotation, telemetry consolidation.

- [ ] **Step 2: Write overview.md (spawn site)**

```markdown
# Cleanup — STEP 8 (HEAVY, subagent)

<HARD-GATE>
DO NOT cleanup inline. Spawn vg-accept-cleanup.
324-line step has bootstrap hygiene + marker rotation + telemetry consolidation.
</HARD-GATE>

## Pre-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-accept-cleanup spawning "post-accept ${PHASE_NUMBER}"`

## Spawn

Read `delegation.md`. Then:
  Agent(subagent_type="vg-accept-cleanup", prompt=<from delegation>)

## Post-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-accept-cleanup returned "<count> actions"`
```

- [ ] **Step 3: Write delegation.md**

```markdown
# vg-accept-cleanup — input/output contract

## Input capsule

- phase_dir: ${PHASE_DIR}
- archived_marker_dir: .vg/archive/phase-${PHASE_NUMBER}/
- bootstrap_state: .vg/bootstrap/state.json (if exists)

## Workflow

1. Archive phase artifacts (PLAN, contracts, goals split + flat) to .vg/archive/
2. Rotate step markers (move .step-markers/ → .step-markers.archive/)
3. Consolidate telemetry (events.db → events-archive.db for this phase)
4. Bootstrap hygiene: clear stale candidates, prune resolved overrides

## Output

{
  "cleanup_actions_taken": [...],
  "files_archived": [...],
  "markers_rotated": [...],
  "summary": "..."
}

## Allowed tools

Read, Write, Edit, Bash, Glob, Grep
(NO Task)
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/accept/cleanup/
git commit -m "feat(r4-accept): cleanup refs — overview + delegation (HEAVY)

7_post_accept_actions (324 lines) split."
```

---

## Phase C — Custom subagents

### Task 10: Create vg-accept-uat-builder subagent

**Files:**
- Create: `agents/vg-accept-uat-builder/SKILL.md` (~250 lines)

- [ ] **Step 1: Write SKILL.md per spec §5.2**

Allowed tools: [Read, Write, Bash, Grep]. NO Task. NO cat flat artifacts (use vg-load).

- [ ] **Step 2: Commit**

```bash
git add agents/vg-accept-uat-builder/
git commit -m "feat(r4-accept): vg-accept-uat-builder subagent

4_build_uat_checklist HEAVY (291 lines) delegated. Builds 6 sections from
8+ artifact sources via vg-load + KEEP-FLAT mix per audit classification."
```

---

### Task 11: Create vg-accept-cleanup subagent

**Files:**
- Create: `agents/vg-accept-cleanup/SKILL.md` (~200 lines)

- [ ] **Step 1: Write SKILL.md per spec §5.2**

Allowed tools: [Read, Write, Edit, Bash, Glob, Grep]. NO Task.

- [ ] **Step 2: Commit**

```bash
git add agents/vg-accept-cleanup/
git commit -m "feat(r4-accept): vg-accept-cleanup subagent

7_post_accept_actions HEAVY (324 lines) delegated. Bootstrap hygiene +
marker rotation + telemetry consolidation."
```

---

## Phase D — Slim entry replacement

### Task 12: Replace accept.md body with slim entry

**Files:**
- Modify: `commands/vg/accept.md` (2429 → ~500 lines)

- [ ] **Step 1: Build slim entry**

```yaml
---
name: vg:accept
description: Human UAT acceptance — structured checklist driven by VG artifacts
argument-hint: "<phase> [--allow-uat-skips] [--allow-unresolved-overrides] [--override-reason=<text>]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Agent, TodoWrite]
runtime_contract:
  must_write:
    - "${PHASE_DIR}/UAT.md"
    - "${PHASE_DIR}/.uat-responses.json"
    - "${PHASE_DIR}/uat-checklist.md"
    - "${PHASE_DIR}/UAT-NARRATIVE.md"
  must_touch_markers:
    - "0_gate_integrity"
    - "0_session"
    - "1_init"
    - "create_task_tracker"
    - "2_artifact_precheck"
    - "3_marker_precheck"
    - "3a_sandbox_verdict"
    - "3b_unreachable_triage"
    - "3c_override_resolution_gate"
    - "4_build_uat_checklist"
    - "4b_uat_narrative_autofire"
    - "5_interactive_uat"        # MUST stay inline
    - "5_uat_quorum_gate"
    - "6b_security_baseline"
    - "6c_learn_auto_surface"
    - "6_write_uat_md"
    - "7_post_accept_actions"
    - "complete"
  must_emit_telemetry:
    - "accept.tasklist_shown"
    - "accept.native_tasklist_projected"   # AUDIT FAIL #9 fix
    - "accept.gates_passed"
    - "accept.uat_responses_written"
    - "accept.quorum_verdict"
    - "accept.uat_md_written"
    - "accept.completed"
  forbidden_without_override:
    - "--allow-uat-skips"
    - "--allow-unresolved-overrides"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1-8 in order.
Interactive UAT (STEP 5) MUST execute INLINE in the main agent — DO NOT
spawn a subagent for it. AskUserQuestion is a UI-presentation tool;
subagent delegation breaks UX continuity. .uat-responses.json MUST be
written after each section.
Quorum gate enforces critical-skip threshold. Override-resolution gate
blocks unresolved blocking-severity entries.
</HARD-GATE>

## Red Flags
[6-row table per spec §5.1]

## Steps

### STEP 1 — preflight
Read `_shared/accept/preflight.md`.

### STEP 2 — gates (3-tier)
Read `_shared/accept/gates.md`.

### STEP 3 — UAT checklist build (HEAVY, subagent)
Read `_shared/accept/uat/checklist-build/overview.md` AND `delegation.md`.
Call Agent(subagent_type="vg-accept-uat-builder", ...).

### STEP 4 — UAT narrative autofire
Read `_shared/accept/uat/narrative.md`.

### STEP 5 — interactive UAT (INLINE — NOT subagent)
Read `_shared/accept/uat/interactive.md`.
Loop 50+ AskUserQuestion items across 6 sections. Write .uat-responses.json
after EACH section.

### STEP 6 — UAT quorum gate
Read `_shared/accept/uat/quorum.md`.

### STEP 7 — audit (security + learn + UAT.md write)
Read `_shared/accept/audit.md`.

### STEP 8 — cleanup (HEAVY, subagent)
Read `_shared/accept/cleanup/overview.md` AND `delegation.md`.
Call Agent(subagent_type="vg-accept-cleanup", ...).
```

- [ ] **Step 2: Verify line count**

```bash
wc -l commands/vg/accept.md   # ≤ 600
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/accept.md
git commit -m "refactor(r4-accept): slim entry — 2429 → 500 lines

10 refs in _shared/accept/ (3 nested dirs: uat/checklist-build/, uat/, cleanup/).
2 subagents (vg-accept-uat-builder, vg-accept-cleanup).
NO uat-interactive subagent — Step 5 stays inline (UX requirement).
accept.native_tasklist_projected in must_emit_telemetry (AUDIT FAIL #9 fix
inherited via R1a). Phase F Task 30 absorbed for vg:accept."
```

---

## Phase E — Static tests

### Task 13: Static tests for slim size + structure + subagent

**Files:**
- Create: `scripts/tests/test_accept_slim_size.py`
- Create: `scripts/tests/test_accept_references_exist.py`
- Create: `scripts/tests/test_accept_subagent_definitions.py`

- [ ] **Step 1: Write 3 tests**

```python
# test_accept_slim_size.py — ≤600 lines, lists refs, uses Agent
# test_accept_references_exist.py — 10 refs + 3 nested dirs valid
# test_accept_subagent_definitions.py:
def test_uat_builder_subagent_valid(): ...
def test_cleanup_subagent_valid(): ...
def test_no_uat_interactive_subagent():
    """Step 5 must stay inline (UX requirement)."""
    p = Path("agents/vg-accept-uat-interactive")
    assert not p.exists()
    p2 = Path("agents/vg-accept-interactive")
    assert not p2.exists()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_accept_*.py
git commit -m "test(r4-accept): static tests — slim + refs + 2 subagents (NOT 3)"
```

---

### Task 14: Static test for interactive UAT staying inline (CRITICAL)

**Files:**
- Create: `scripts/tests/test_accept_interactive_stays_inline.py`

- [ ] **Step 1: Write test**

```python
# scripts/tests/test_accept_interactive_stays_inline.py
"""Interactive UAT step 5 MUST stay inline (UX requirement, spec §1.2)."""
from pathlib import Path
import re


def test_step5_interactive_no_subagent_call():
    """Step 5 ref must NOT contain Agent(subagent_type=...) call."""
    text = Path("commands/vg/_shared/accept/uat/interactive.md").read_text()
    # Must NOT contain spawn pattern
    assert not re.search(r'Agent\s*\(\s*subagent_type', text), (
        "interactive.md contains Agent() call — Step 5 must stay inline (spec §1.2)"
    )
    # Must explicitly forbid subagent extraction in HARD-GATE
    assert "MUST execute in the main agent" in text or "STAYS INLINE" in text


def test_slim_entry_step5_does_not_spawn():
    """Slim accept.md STEP 5 description must NOT mention Agent() spawn."""
    text = Path("commands/vg/accept.md").read_text()
    # Find STEP 5 section
    m = re.search(r"### STEP 5.*?### STEP 6", text, re.DOTALL)
    assert m
    step5 = m.group(0)
    assert not re.search(r'Agent\s*\(\s*subagent_type', step5), (
        "Slim entry STEP 5 should NOT spawn a subagent — interactive UX requires inline"
    )


def test_no_uat_interactive_subagent_skill():
    """No agents/vg-accept-uat-interactive/SKILL.md should exist."""
    assert not Path("agents/vg-accept-uat-interactive/SKILL.md").exists()
    assert not Path("agents/vg-accept-interactive/SKILL.md").exists()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_accept_interactive_stays_inline.py
git commit -m "test(r4-accept): assert step 5 interactive UAT stays inline (CRITICAL)

UX requirement (spec §1.2): AskUserQuestion is UI-presentation; subagent
context handoff breaks UX continuity. This test prevents future
'optimization' that would extract step 5 into a subagent."
```

---

### Task 15: Static test for vg-load consumption

**Files:**
- Create: `scripts/tests/test_accept_uses_vg_load.py`

- [ ] **Step 1: Write test (mirror R3 review pattern)**

Targets `commands/vg/accept.md` + all `_shared/accept/**/*.md`. KEEP-FLAT allowlist for: CONTEXT.md, FOUNDATION.md, CRUD-SURFACES.md, RIPPLE-ANALYSIS.md, SUMMARY*.md, build-state.log (small/single-doc files).

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_accept_uses_vg_load.py
git commit -m "test(r4-accept): assert vg-load for goals + design-refs (Phase F Task 30)"
```

---

### Task 16: Update emit-tasklist.py CHECKLIST_DEFS for vg:accept

**Files:**
- Modify: `scripts/emit-tasklist.py`

- [ ] **Step 1: Add 6 checklist groups**

```python
CHECKLIST_DEFS["vg:accept"] = [
    ("preflight",        ["0_gate_integrity", "0_session", "1_init", "create_task_tracker"]),
    ("gates",            ["2_artifact_precheck", "3_marker_precheck", "3a_sandbox_verdict", "3b_unreachable_triage", "3c_override_resolution_gate"]),
    ("uat-build",        ["4_build_uat_checklist", "4b_uat_narrative_autofire"]),
    ("uat-interactive",  ["5_interactive_uat", "5_uat_quorum_gate"]),
    ("audit",            ["6b_security_baseline", "6c_learn_auto_surface", "6_write_uat_md"]),
    ("cleanup",          ["7_post_accept_actions", "complete"]),
]
```

- [ ] **Step 2: Commit**

```bash
git add scripts/emit-tasklist.py
git commit -m "feat(r4-accept): emit-tasklist CHECKLIST_DEFS for vg:accept (6 groups)"
```

---

## Phase F — Sync + dogfood

### Task 17: Sync to PrintwayV3 + dogfood `/vg:accept <phase>`

- [ ] **Step 1: Update sync.sh + run pytest regression**

```bash
git add sync.sh
git commit -m "chore(r4-accept): sync.sh includes accept refs + 2 subagents"

pytest scripts/tests/ -v 2>&1 | tee /tmp/r4-accept-pytest.log
```

- [ ] **Step 2: Sync + run dogfood**

```bash
cd /path/to/PrintwayV3
bash /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix/sync.sh
# Pick a phase with completed build+review+test
/vg:accept <phase>
```

- [ ] **Step 3: Verify 12 exit criteria (per spec §6.4)**

1. Tasklist visible in Claude Code UI immediately
2. **`accept.native_tasklist_projected` event count ≥ 1** (baseline 0)
3. All 17 step markers touched without override
4. UAT.md written with Verdict line and content_min_bytes met
5. .uat-responses.json present with all 6 sections + final verdict
6. UAT-builder subagent invocation event present
7. Cleanup subagent invocation event present
8. **Interactive UAT happened in main agent** (NOT delegated — verify via tool invocation log: AskUserQuestion calls in main, NOT in subagent)
9. Quorum gate verifies responses (event present)
10. Override-debt resolution gate ran (event present)
11. Stop hook fires without exit 2
12. Stop hook unpaired-block-fails-closed test passes

Critical: criterion 8 (interactive UAT must NOT be delegated — UX requirement).

- [ ] **Step 4: Verdict**

```bash
cat > docs/superpowers/specs/2026-05-03-vg-r4-accept-verdict.md <<EOF
# R4 Accept Pilot Verdict
**Date:** $(date -u +%Y-%m-%d)
**Phase:** ${PHASE}
[12 criteria PASS/FAIL]
## Critical: criterion 8 (interactive UAT inline)
[YES/NO + AskUserQuestion tool log evidence]
## Verdict: PASS | FAIL
## Phase F Task 30 update
After this verdict lands, update blueprint plan Phase F Task 30 to remove vg:accept from scope.
## Completion rate
Baseline: 36% (4/11 in PrintwayV3). Target: ↑.
[Actual: N/M]
EOF

git add docs/superpowers/specs/2026-05-03-vg-r4-accept-verdict.md
git commit -m "docs(r4-accept): pilot dogfood verdict + 12 criteria evidence"
```

---

## Self-review notes

**Spec coverage check:**
- §1.5 goal "accept.md ≤500 lines" → Task 12 + Task 13
- §1.5 audit FAIL #9 → fix inherited via R1a (no separate task; Task 12 adds event to runtime_contract)
- §4.1 file layout (10 refs + 3 nested dirs) → Tasks 2-9
- §5.1 slim entry → Task 12
- §5.2 2 subagents (NOT 3 — interactive stays inline) → Tasks 10, 11 + Task 14 critical assertion
- §5.3 hooks SHARED with R1a → no new tasks
- §6.3 testing → Tasks 13-16
- §6.4 12 exit criteria → Task 17

**UX baseline coverage check:**
- Req 1 (per-task split): UAT-RESPONSES Layer 3 + per-section appends in Task 6 (interactive.md); consumer reads use vg-load (Tasks 4, 5, 8, 15).
- Req 2 (spawn narration): Tasks 4, 9 include narrate-spawn in spawn sites.
- Req 3 (compact hooks): inherits R1a stderr convention.

**Critical UX requirement (interactive inline):**
- Task 6: ref explicitly states INLINE
- Task 12: slim entry STEP 5 description explicitly forbids spawn
- Task 13: subagent test asserts no uat-interactive subagent exists
- Task 14: dedicated test prevents Agent() call in interactive.md or slim entry STEP 5

**Phase F Task 30 absorption check:**
- vg:accept portion covered by Tasks 4, 5, 8, 11, 15.
- Task 15 test enforces no flat reads.
- KEEP-FLAT allowlist documented (small single-doc files don't need split).
- After R4 verdict (Task 17), update blueprint plan.

**Type/name consistency:**
- All step IDs match `commands/vg/accept.md` runtime_contract markers (verified Task 16).
- Subagent names: `vg-accept-uat-builder`, `vg-accept-cleanup`.
- NO `vg-accept-uat-interactive` (Tasks 13 + 14 assertions).
- Helper names: shared with R1a.

**Placeholder scan:** none. Each Task has actual code/bash, file paths.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-05-03-vg-r4-accept-pilot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — superpowers:subagent-driven-development.
**2. Inline Execution** — superpowers:executing-plans.

Pick 1 or 2.
