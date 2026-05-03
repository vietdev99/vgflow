# R4 Scope Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/scope.md` from 1,380 → ≤500-line slim entry + 13 FLAT refs in `commands/vg/_shared/scope/`. NO new subagents (existing challenger/expander Task subagents preserved as-is — they are interactive UX, not extractable). Strengthen `scope.native_tasklist_projected` emission (1 audit FAIL — no scope events in dogfood baseline). Bake all 3 R1a UX baseline requirements (per-decision split for CONTEXT.md, subagent-spawn narration, compact hook stderr). Pilot is GATE — if 8 exit criteria PASS (spec §5.4), R4 round of replication advances.

**Architecture:** Reuse 100% of R1a infrastructure (HMAC evidence helper, vg-load.sh, narrate-spawn, 5 hooks, state-machine validator, vg-meta-skill). Apply Codex correction #4 — FLAT references only (no nested `discussion/<round>.md` from spec §3 — flatten to `discussion-round-N-*.md`). Scope-specific work: 1 audit fix (native_tasklist_projected emission via emit-tasklist.py wiring) + 0 new subagents + 1 slim entry + 13 refs + per-decision split for CONTEXT.md (UX baseline R3).

**Tech Stack:** bash (extract content from current scope.md to refs), Python 3 (pytest for static gates + emit-tasklist.py CHECKLIST_DEFS update), Claude Code Agent tool (existing challenger/expander unchanged), sqlite3 (events.db query for dogfood verification), AskUserQuestion (5 rounds × N answers — UNCHANGED).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-scope-design.md` (276 lines, includes Codex appendix corrections + UX baseline reference).

**Branch:** `feat/rfc-v9-followup-fixes` (continuing R4 batch with project + accept). Each task commits incrementally. Final dogfood on a fresh PrintwayV3 phase before claiming pilot PASS.

**Sequencing:** R4 (after R1 blueprint pilot, R2 build+test, R3 review). Scope is LAST in R4 to leverage learnings from accept pilot (which lands first per existing plans). Scope artifact (CONTEXT.md) feeds blueprint, so changes here have downstream impact — empirical dogfood mandatory before merge.

---

## File structure (new + modified)

| File | Action | Lines (target) | Purpose |
|---|---|---|---|
| `commands/vg/scope.md` | REFACTOR (1380 → ≤500) | -880 | Slim entry per blueprint pilot template (frontmatter + Red Flags + 7 STEP entries) |
| `commands/vg/.scope.md.r4-backup` | CREATE | 1380 | Backup of current scope.md (safety net for rollback) |
| `commands/vg/_shared/scope/preflight.md` | CREATE | ~150 | STEP 1 — parse args, validate phase context, SPECS.md gate, codebase-map injection, PIPELINE-STATE init, emit `scope.tasklist_shown` |
| `commands/vg/_shared/scope/discussion-overview.md` | CREATE | ~120 | STEP 2 entry — 5-round loop summary, sourced wrappers (challenger + expander), bug-detection-guide load, bootstrap-inject pattern |
| `commands/vg/_shared/scope/discussion-round-1-domain.md` | CREATE | ~150 | R1 Domain & Business — preamble, AskUserQuestion template, lock D-XX (business), per-answer challenger, per-round expander |
| `commands/vg/_shared/scope/discussion-round-2-technical.md` | CREATE | ~180 | R2 Technical Approach + multi-surface gate (lock `P{phase}.D-surfaces` if `config.surfaces` declared) |
| `commands/vg/_shared/scope/discussion-round-3-api.md` | CREATE | ~150 | R3 API Design — endpoints/auth/data per decision |
| `commands/vg/_shared/scope/discussion-round-4-ui.md` | CREATE | ~150 | R4 UI/UX with profile-aware skip (web-backend-only / cli-tool / library → skip with telemetry) |
| `commands/vg/_shared/scope/discussion-round-5-tests.md` | CREATE | ~150 | R5 Test Scenarios — TS-XX per decision |
| `commands/vg/_shared/scope/discussion-deep-probe.md` | CREATE | ~120 | Deep Probe Loop — mandatory minimum 5 probes after R5 |
| `commands/vg/_shared/scope/env-preference.md` | CREATE | ~100 | STEP 3 (`1b_env_preference`) — capture sandbox/staging/prod preference for downstream commands |
| `commands/vg/_shared/scope/artifact-write.md` | CREATE | ~180 | STEP 4 (`2_artifact_generation`) — write CONTEXT.md (legacy flat) + CONTEXT/D-NN.md per decision (Layer 1) + CONTEXT/index.md (Layer 2) + DISCUSSION-LOG.md (append). Atomic group commit. |
| `commands/vg/_shared/scope/completeness-validation.md` | CREATE | ~150 | STEP 5 (`3_completeness_validation`) — 4 checks (decision count, endpoint coverage, UI components, test scenarios) |
| `commands/vg/_shared/scope/crossai.md` | CREATE | ~150 | STEP 6 — `4_crossai_review` async dispatch + `4_5_bootstrap_reflection` + `4_6_test_strategy` (TEST-STRATEGY.md draft via tester-pro-cli) |
| `commands/vg/_shared/scope/close.md` | CREATE | ~120 | STEP 7 (`5_commit_and_next`) — contract pin write, decisions-trace gate, mark-step + emit `scope.completed`, run-complete |
| `scripts/hooks/vg-meta-skill.md` | MODIFY | +20 | Append "Scope-specific Red Flags" section (spec §4.4) |
| `scripts/emit-tasklist.py` | MODIFY | +30 | Add `CHECKLIST_DEFS["vg:scope"]` so `scope.native_tasklist_projected` emits (audit fix #9) |
| `scripts/tests/test_scope_slim_size.py` | CREATE | ~30 | Assert `commands/vg/scope.md` ≤ 600 lines |
| `scripts/tests/test_scope_references_exist.py` | CREATE | ~50 | Assert all 13 `_shared/scope/*.md` refs exist + listed in slim entry |
| `scripts/tests/test_scope_no_new_subagents.py` | CREATE | ~40 | Assert NO new agent SKILL.md added under `agents/vg-scope*` (challenger/expander reuse existing) |
| `scripts/tests/test_scope_runtime_contract.py` | CREATE | ~60 | Parse slim scope.md frontmatter, assert `must_write` includes 4 paths (CONTEXT.md, CONTEXT/index.md, CONTEXT/D-*.md glob, DISCUSSION-LOG.md) + `must_emit_telemetry` includes `scope.native_tasklist_projected` |

**Total: 2 modified + 17 created. ~1700 lines added, ~880 lines removed.**

---

## Phase A — Prerequisites verification (sanity check, no code changes)

### Task 1: Verify R1a shared infra prerequisites shipped

**Files:**
- Read-only check: `scripts/vg-orchestrator-emit-evidence-signed.py`, `scripts/vg-state-machine-validator.py`, `scripts/vg-narrate-spawn.sh`, `scripts/vg-load.sh`, all 5 hooks under `scripts/hooks/`, `scripts/hooks/vg-meta-skill.md`, wrappers `commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh` + `vg-expand-round-wrapper.sh` + `bootstrap-inject.sh`

- [ ] **Step 1: Confirm shared infra files exist**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
for f in \
  scripts/vg-orchestrator-emit-evidence-signed.py \
  scripts/vg-state-machine-validator.py \
  scripts/vg-narrate-spawn.sh \
  scripts/vg-load.sh \
  scripts/hooks/vg-pre-tool-use-bash.sh \
  scripts/hooks/vg-pre-tool-use-write.sh \
  scripts/hooks/vg-pre-tool-use-agent.sh \
  scripts/hooks/vg-stop.sh \
  scripts/hooks/vg-session-start.sh \
  scripts/hooks/vg-user-prompt-submit.sh \
  scripts/hooks/vg-meta-skill.md \
  commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
  commands/vg/_shared/lib/vg-expand-round-wrapper.sh \
  commands/vg/_shared/lib/bootstrap-inject.sh; do
  test -f "$f" && echo "✓ $f" || { echo "✗ MISSING $f"; exit 1; }
done
```
Expected: All 13 lines start with `✓`. Exit 0.

- [ ] **Step 2: Confirm hooks wired in settings.json**

```bash
python3 -c "
import json
s = json.load(open('.claude/settings.json'))
hooks = s.get('hooks', {})
required = ['SessionStart','UserPromptSubmit','Stop','PreToolUse','PostToolUse']
missing = [h for h in required if h not in hooks]
assert not missing, f'Missing hook events: {missing}'
print('✓ All 5 hook events wired')
"
```
Expected: `✓ All 5 hook events wired`.

- [ ] **Step 3: STOP if any prerequisite missing**

If Step 1 or 2 fails, STOP this plan. R1a blueprint pilot must complete first. Inform partner.

- [ ] **Step 4: Commit prerequisite log**

No code change, no commit. Just log success in conversation: "R4 scope prerequisites verified — proceeding."

---

## Phase B — Test scaffolding (TDD red — write all 4 tests before any refactor)

### Task 2: Test for slim scope.md size (≤600 lines)

**Files:**
- Create: `scripts/tests/test_scope_slim_size.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_scope_slim_size.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_scope_slim_at_or_below_600_lines():
    """Spec §1.5 goal: ≤500 target, ≤600 hard ceiling (buffer for STEP entries + Red Flags table)."""
    p = REPO / "commands" / "vg" / "scope.md"
    assert p.exists(), f"{p} missing"
    lines = p.read_text().splitlines()
    assert len(lines) <= 600, f"scope.md has {len(lines)} lines, exceeds 600 ceiling"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/test_scope_slim_size.py -v
```
Expected: FAIL with `AssertionError: scope.md has 1380 lines, exceeds 600 ceiling`.

- [ ] **Step 3: Commit failing test**

```bash
git add scripts/tests/test_scope_slim_size.py
git commit -m "test(r4-scope): slim size gate (≤600 lines) — RED" --no-verify
```
(`--no-verify` here: pre-commit hooks may also flag the still-large scope.md; this commit deliberately commits the failing test first per TDD discipline.)

---

### Task 3: Test for 13 reference files exist + listed in slim entry

**Files:**
- Create: `scripts/tests/test_scope_references_exist.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_scope_references_exist.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "commands" / "vg" / "_shared" / "scope"
SLIM = REPO / "commands" / "vg" / "scope.md"

REFS = [
    "preflight.md",
    "discussion-overview.md",
    "discussion-round-1-domain.md",
    "discussion-round-2-technical.md",
    "discussion-round-3-api.md",
    "discussion-round-4-ui.md",
    "discussion-round-5-tests.md",
    "discussion-deep-probe.md",
    "env-preference.md",
    "artifact-write.md",
    "completeness-validation.md",
    "crossai.md",
    "close.md",
]


def test_all_13_refs_exist():
    missing = [r for r in REFS if not (SHARED / r).exists()]
    assert not missing, f"Missing refs in {SHARED}: {missing}"


def test_refs_are_flat_one_level_only():
    """Codex correction #4: refs must be FLAT under _shared/scope/, no nested subdirs."""
    if not SHARED.exists():
        return  # Task 4 will create it
    nested = [p for p in SHARED.iterdir() if p.is_dir()]
    assert not nested, f"Found nested dirs (violates Codex #4): {nested}"


def test_slim_entry_lists_each_ref():
    """Slim scope.md MUST mention each ref by basename so AI knows to Read it."""
    if not SLIM.exists():
        return
    body = SLIM.read_text()
    missing = [r for r in REFS if r not in body]
    assert not missing, f"Slim entry missing ref mentions: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_scope_references_exist.py -v
```
Expected: `test_all_13_refs_exist` FAILs (refs not yet created), other 2 pass trivially.

- [ ] **Step 3: Commit failing test**

```bash
git add scripts/tests/test_scope_references_exist.py
git commit -m "test(r4-scope): 13 refs exist + flat layout + entry mentions — RED" --no-verify
```

---

### Task 4: Test for no new subagents added under `agents/vg-scope*`

**Files:**
- Create: `scripts/tests/test_scope_no_new_subagents.py`

- [ ] **Step 1: Write the test**

```python
# scripts/tests/test_scope_no_new_subagents.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_vg_scope_subagent_added():
    """Spec §1.2: scope refactor MUST NOT add new subagents.
    Existing challenger/expander reused via wrappers under _shared/lib/."""
    agents_dir = REPO / "agents"
    if not agents_dir.exists():
        return
    forbidden = sorted(p.name for p in agents_dir.iterdir() if p.name.startswith("vg-scope"))
    assert not forbidden, f"Forbidden new subagents: {forbidden}"


def test_existing_wrappers_still_present():
    """Sanity: the wrappers slim refs depend on must still exist after refactor."""
    lib = REPO / "commands" / "vg" / "_shared" / "lib"
    for w in ("vg-challenge-answer-wrapper.sh", "vg-expand-round-wrapper.sh", "bootstrap-inject.sh"):
        assert (lib / w).exists(), f"Wrapper missing: {w}"
```

- [ ] **Step 2: Run test (passes already — green from start)**

```bash
pytest scripts/tests/test_scope_no_new_subagents.py -v
```
Expected: PASS (no `agents/vg-scope*` dirs, wrappers exist).

- [ ] **Step 3: Commit (regression gate)**

```bash
git add scripts/tests/test_scope_no_new_subagents.py
git commit -m "test(r4-scope): no-new-subagents regression gate — GREEN" --no-verify
```

---

### Task 5: Test for runtime_contract structure

**Files:**
- Create: `scripts/tests/test_scope_runtime_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_scope_runtime_contract.py
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SLIM = REPO / "commands" / "vg" / "scope.md"


def _load_frontmatter():
    body = SLIM.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    assert m, "scope.md has no YAML frontmatter"
    return yaml.safe_load(m.group(1))


def test_must_write_includes_3_layers_for_context():
    """UX baseline R1: scope MUST write CONTEXT.md (L3 flat) + CONTEXT/index.md (L2) + CONTEXT/D-*.md (L1) + DISCUSSION-LOG.md."""
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    paths = []
    for entry in rc.get("must_write", []):
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict):
            paths.append(entry.get("path", ""))
    flat = " ".join(paths)
    assert "CONTEXT.md" in flat, "missing layer-3 CONTEXT.md"
    assert "CONTEXT/index.md" in flat, "missing layer-2 CONTEXT/index.md"
    assert "CONTEXT/D-" in flat, "missing layer-1 CONTEXT/D-*.md glob"
    assert "DISCUSSION-LOG.md" in flat, "missing DISCUSSION-LOG.md"


def test_must_emit_telemetry_includes_native_tasklist_projected():
    """Audit fix #9: scope.native_tasklist_projected MUST be required (was 0 events in baseline)."""
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    events = []
    for entry in rc.get("must_emit_telemetry", []):
        if isinstance(entry, str):
            events.append(entry)
        elif isinstance(entry, dict):
            events.append(entry.get("event_type", ""))
    assert "scope.native_tasklist_projected" in events, f"missing native_tasklist_projected in {events}"


def test_must_touch_markers_includes_3_required():
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    markers = []
    for entry in rc.get("must_touch_markers", []):
        if isinstance(entry, str):
            markers.append(entry)
        elif isinstance(entry, dict):
            markers.append(entry.get("name", ""))
    for required in ("0_parse_and_validate", "1_deep_discussion", "2_artifact_generation"):
        assert required in markers, f"missing marker {required}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_scope_runtime_contract.py -v
```
Expected: FAIL — `test_must_write_includes_3_layers_for_context` (current scope.md has only CONTEXT.md flat) AND `test_must_emit_telemetry_includes_native_tasklist_projected` (current has only `scope.tasklist_shown`/`started`/`completed`).

- [ ] **Step 3: Commit failing test**

```bash
git add scripts/tests/test_scope_runtime_contract.py
git commit -m "test(r4-scope): runtime_contract 3-layer + native_tasklist event — RED" --no-verify
```

---

## Phase C — Backup + slim entry skeleton

### Task 6: Backup current scope.md

**Files:**
- Create: `commands/vg/.scope.md.r4-backup` (copy of current `commands/vg/scope.md`)

- [ ] **Step 1: Copy current scope.md to backup**

```bash
cp "commands/vg/scope.md" "commands/vg/.scope.md.r4-backup"
wc -l "commands/vg/.scope.md.r4-backup"
```
Expected: `1380 commands/vg/.scope.md.r4-backup`.

- [ ] **Step 2: Commit backup**

```bash
git add commands/vg/.scope.md.r4-backup
git commit -m "chore(r4-scope): backup scope.md (1380 lines) before refactor" --no-verify
```

---

### Task 7: Create empty `_shared/scope/` directory + 13 placeholder refs

**Files:**
- Create dir: `commands/vg/_shared/scope/`
- Create 13 placeholder files: `preflight.md`, `discussion-overview.md`, `discussion-round-1-domain.md`, `discussion-round-2-technical.md`, `discussion-round-3-api.md`, `discussion-round-4-ui.md`, `discussion-round-5-tests.md`, `discussion-deep-probe.md`, `env-preference.md`, `artifact-write.md`, `completeness-validation.md`, `crossai.md`, `close.md`

- [ ] **Step 1: Create directory + placeholders**

```bash
mkdir -p commands/vg/_shared/scope
for f in preflight discussion-overview discussion-round-1-domain discussion-round-2-technical \
         discussion-round-3-api discussion-round-4-ui discussion-round-5-tests discussion-deep-probe \
         env-preference artifact-write completeness-validation crossai close; do
  printf "# %s (placeholder — content lands in subsequent task)\n" "$f" > "commands/vg/_shared/scope/${f}.md"
done
ls commands/vg/_shared/scope/ | wc -l
```
Expected: `13`.

- [ ] **Step 2: Verify Task 3 partial pass**

```bash
pytest scripts/tests/test_scope_references_exist.py::test_all_13_refs_exist -v
pytest scripts/tests/test_scope_references_exist.py::test_refs_are_flat_one_level_only -v
```
Expected: Both PASS now (refs exist + flat layout).

- [ ] **Step 3: Commit placeholder skeleton**

```bash
git add commands/vg/_shared/scope/
git commit -m "feat(r4-scope): scaffold 13 flat ref placeholders" --no-verify
```

---

### Task 8: Write slim `commands/vg/scope.md` (frontmatter + Red Flags + 7 STEP entries)

**Files:**
- Modify: `commands/vg/scope.md` (replace entire body — keep file path)

- [ ] **Step 1: Replace scope.md body with slim entry**

Write `commands/vg/scope.md` containing exactly the following content (target ≤500 lines, hard ceiling 600):

```markdown
---
name: vg:scope
description: Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md
argument-hint: "<phase> [--skip-crossai] [--auto] [--update] [--deepen=D-XX] [--override-reason=<text>]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
  - TodoWrite
runtime_contract:
  must_write:
    # Layer 3: flat concat (legacy compat for grep validators + blueprint consumer)
    - path: "${PHASE_DIR}/CONTEXT.md"
      content_min_bytes: 500
      content_required_sections: ["D-"]
    # Layer 2: index TOC of decisions
    - "${PHASE_DIR}/CONTEXT/index.md"
    # Layer 1: per-decision split (small files for partial vg-load)
    - path: "${PHASE_DIR}/CONTEXT/D-*.md"
      glob_min_count: 1
    # Append-only Q&A trail (single file, no split)
    - "${PHASE_DIR}/DISCUSSION-LOG.md"
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_deep_discussion"
    - "2_artifact_generation"
    - "3_completeness_validation"
    - "5_commit_and_next"
    # Flag-gated marker (skip via override flag with debt entry)
    - name: "4_crossai_review"
      required_unless_flag: "--skip-crossai"
  must_emit_telemetry:
    - event_type: "scope.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1 through STEP 7 in exact order. Each step is gated
by hooks. Skipping ANY step will be blocked by PreToolUse + Stop hooks.
You CANNOT rationalize past these gates.

You MUST call TodoWrite IMMEDIATELY after STEP 1 runs emit-tasklist.py.
The PreToolUse Bash hook will block all subsequent step-active calls
until signed evidence (HMAC) exists at `.vg/runs/<run>/tasklist-evidence.json`.

For each of the 5 discussion rounds (inside STEP 2), you MUST invoke:
  (a) per-answer adversarial challenger via the Agent tool
      (subagent_type=general-purpose, model=Opus default), AND
  (b) per-round dimension expander via the Agent tool
      (subagent_type=general-purpose, model=Opus default).
The wrappers `vg-challenge-answer-wrapper.sh` + `vg-expand-round-wrapper.sh`
build the prompts. DO NOT skip rounds, DO NOT skip challenger/expander —
hooks will not catch this, but Codex consensus blocked omission as
adversarial-suppression risk.

Tool name is `Agent`, NOT `Task` (Codex correction #1).
</HARD-GATE>

## Red Flags (do not rationalize)

| Thought | Reality |
|---|---|
| "User answered clearly, skip challenger this round" | Challenger is per-answer trigger; skipping = miss adversarial check |
| "All 5 rounds done, skip expander on R5" | Expander runs once per round end; missing = miss critical_missing detection |
| "R4 UI seems irrelevant for backend phase" | R4 has profile-aware skip — let the profile branch decide, don't manually skip |
| "Fast mode: write CONTEXT.md after R1 only" | Steps 2-5 build incremental decisions; partial = downstream phases ungrounded |
| "CrossAI review takes time, --skip-crossai" | --skip-crossai requires --override-reason; gate enforces override-debt entry |
| "Tasklist không quan trọng, để sau" | PreToolUse Bash hook BLOCKS step-active without signed evidence |
| "Step này đơn giản, bỏ qua" | Marker thiếu = Stop hook fail = run cannot complete |
| "Tôi đã hiểu, không cần đọc reference" | Reference contains step-specific bash commands not in entry |
| "Spawn Task() như cũ" | Tool name is `Agent`, not `Task` (Codex correction #1) |
| "Per-decision split overkill" | UX baseline R1 — blueprint already consumes via vg-load.sh; missing = build context overflow |

## Steps (7 checklist groups — wired into native tasklist via emit-tasklist.py CHECKLIST_DEFS["vg:scope"])

### STEP 1 — preflight
Read `_shared/scope/preflight.md` and follow it exactly.
This step parses args, validates SPECS.md exists, runs emit-tasklist.py,
and includes the IMPERATIVE TodoWrite call after evidence is signed.

### STEP 2 — deep discussion (HEAVY, INLINE — interactive UX)
Read `_shared/scope/discussion-overview.md` first (sources wrappers,
loads bug-detection-guide). Then loop through 5 rounds:
- R1: Read `_shared/scope/discussion-round-1-domain.md`
- R2: Read `_shared/scope/discussion-round-2-technical.md` (multi-surface gate)
- R3: Read `_shared/scope/discussion-round-3-api.md`
- R4: Read `_shared/scope/discussion-round-4-ui.md` (profile-aware skip)
- R5: Read `_shared/scope/discussion-round-5-tests.md`
- After R5: Read `_shared/scope/discussion-deep-probe.md` (mandatory min 5 probes)

For EACH user answer in EACH round:
1. Build challenger prompt:
   ```bash
   PROMPT=$(bash commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
            "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft")
   ```
2. Spawn challenger:
   ```bash
   bash scripts/vg-narrate-spawn.sh scope-challenger spawning "round-$ROUND answer #$N"
   ```
   Then `Agent(subagent_type="general-purpose", prompt=<PROMPT>)`.
   On return: `bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"`.

For EACH round end (after all answers + challengers):
1. Build expander prompt via `vg-expand-round-wrapper.sh`.
2. Spawn expander (same Agent + narrate pattern).

DO NOT skip rounds. DO NOT skip challenger or expander.

### STEP 3 — env preference
Read `_shared/scope/env-preference.md` and follow it exactly.
Captures sandbox/staging/prod target for downstream commands.

### STEP 4 — artifact generation
Read `_shared/scope/artifact-write.md` and follow it exactly.
Atomic group commit: writes CONTEXT.md (Layer 3 flat) + CONTEXT/D-NN.md
per decision (Layer 1) + CONTEXT/index.md (Layer 2) + DISCUSSION-LOG.md
(append-only). MUST emit `2_artifact_generation` step marker.

### STEP 5 — completeness validation
Read `_shared/scope/completeness-validation.md` and follow it exactly.
Runs 4 checks (decision count, endpoint coverage, UI components,
test scenarios) and surfaces warnings.

### STEP 6 — CrossAI review (skippable with --skip-crossai + --override-reason)
Read `_shared/scope/crossai.md` and follow it exactly.
Async dispatch via crossai-invoke.sh + bootstrap reflection (4_5) +
TEST-STRATEGY draft (4_6). Skipping requires override-debt entry.

### STEP 7 — close
Read `_shared/scope/close.md` and follow it exactly.
Writes contract pin, runs decisions-trace gate, marks `5_commit_and_next`,
emits `scope.completed`, calls run-complete.

## Diagnostic flow (5 layers — see vg-meta-skill.md)

If any tool call is blocked by a hook:
1. Read the stderr DIAGNOSTIC REQUIRED prompt (Layer 1 format).
2. Tell the user using the narrative template inside the message (Layer 5).
3. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`.
4. Apply the REQUIRED FIX described in the prompt.
5. Retry the original tool call.

After ≥3 blocks on the same gate, you MUST call AskUserQuestion (Layer 3 escalation).
After context compaction, SessionStart hook re-injects open diagnostics (Layer 4).

## UX baseline (R1a inheritance — mandatory cross-flow)

This flow honors the 3 UX requirements baked into R1a blueprint pilot:
- **Per-decision artifact split** — STEP 4 writes CONTEXT/D-NN.md
  (Layer 1) + CONTEXT/index.md (Layer 2) + CONTEXT.md flat concat
  (Layer 3). Blueprint consumes via `scripts/vg-load.sh --phase N --artifact context --decision D-NN`.
- **Subagent spawn narration** — every Agent() call (challenger, expander,
  reflector, vg-crossai inside crossai.md) wrapped with
  `bash scripts/vg-narrate-spawn.sh <name> {spawning|returned|failed}`.
- **Compact hook stderr** — success silent, block 3 lines + file pointer.
  Full diagnostic in `.vg/blocks/{run_id}/{gate_id}.md`.
```

- [ ] **Step 2: Run slim-size + runtime-contract tests**

```bash
pytest scripts/tests/test_scope_slim_size.py \
       scripts/tests/test_scope_runtime_contract.py \
       scripts/tests/test_scope_references_exist.py -v
```
Expected: ALL PASS now (slim ≤600, frontmatter has 3-layer + native_tasklist_projected, 13 refs exist, slim mentions each ref).

- [ ] **Step 3: Commit slim entry**

```bash
git add commands/vg/scope.md
git commit -m "feat(r4-scope): slim scope.md entry (1380→~250 lines) — frontmatter + 7 STEPs"
```

---

## Phase D — Reference content extraction (12 tasks, content from `.scope.md.r4-backup`)

> Each task in this phase reads the corresponding section from `commands/vg/.scope.md.r4-backup` and writes it to a focused ref file. Pattern is consistent: open backup, locate `<step name="N_xxx">` block, port bash + IMPERATIVE prose into the ref, prune dead code, ensure each ref ends with the corresponding `mark-step` call.

### Task 9: Write `_shared/scope/preflight.md`

**Files:**
- Modify: `commands/vg/_shared/scope/preflight.md` (replace placeholder)

- [ ] **Step 1: Extract `0_parse_and_validate` content**

Open `commands/vg/.scope.md.r4-backup`. Locate `<step name="0_parse_and_validate">` (around lines 220-310). Port to `_shared/scope/preflight.md` with this structure:

```markdown
# Scope preflight (STEP 1)

> Imperative ref — follow each section in order. DO NOT skip any.

## 1. Parse args + load config

```bash
PHASE_NUMBER="<from $ARGUMENTS>"
PHASE_DIR=".vg/phases/${PHASE_NUMBER}"
[ -d "$PHASE_DIR" ] || { echo "⛔ Phase dir missing: $PHASE_DIR" >&2; exit 1; }
source commands/vg/_shared/config-loader.md  # exports PLANNING_DIR, PROFILE
```

## 2. SPECS.md gate

```bash
[ -f "${PHASE_DIR}/SPECS.md" ] || {
  echo "⛔ SPECS.md missing — run /vg:specs ${PHASE_NUMBER} first" >&2
  exit 1
}
```

## 3. Existing CONTEXT.md handling (AskUserQuestion: Update / View / Skip)

[port the AskUserQuestion block from backup lines ~290-305]

## 4. Inject codebase-map (silent)

```bash
[ -f "${PLANNING_DIR}/codebase-map.md" ] && \
  echo "✓ codebase-map.md available — god nodes/communities ready for discussion"
```

## 5. PIPELINE-STATE update

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/pipeline-state-update.py \
  --phase "${PHASE_NUMBER}" --step scope --status in_progress
```

## 6. Emit tasklist + sign evidence + TodoWrite (HARD-GATE)

```bash
SESSION="$(cat .vg/active-runs/$(ls .vg/active-runs/ | head -1) 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SESSION:0:8}"

python3 scripts/emit-tasklist.py \
  --command vg:scope \
  --profile "${PROFILE}" \
  --phase "${PHASE_NUMBER}" \
  --out ".vg/runs/${RUN_ID}/tasklist-contract.json"

CONTRACT_SHA=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
  ".vg/runs/${RUN_ID}/tasklist-contract.json")

python3 scripts/vg-orchestrator-emit-evidence-signed.py \
  --out ".vg/runs/${RUN_ID}/tasklist-evidence.json" \
  --payload "{\"contract_sha256\":\"${CONTRACT_SHA}\",\"todowrite_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"

vg-orchestrator emit-event scope.tasklist_shown --phase "${PHASE_NUMBER}"
```

**THEN IMMEDIATELY** call `TodoWrite` with one todo per checklist group from
`tasklist-contract.json` (the PreToolUse Bash hook BLOCKS subsequent
step-active calls until TodoWrite has been called and PostToolUse hook
has captured matching evidence).

After TodoWrite returns:
```bash
vg-orchestrator emit-event scope.native_tasklist_projected --phase "${PHASE_NUMBER}"
```

## 7. Mark step

```bash
vg-orchestrator mark-step scope 0_parse_and_validate
vg-orchestrator emit-event scope.started --phase "${PHASE_NUMBER}"
```
```

- [ ] **Step 2: Verify file > placeholder size**

```bash
wc -l commands/vg/_shared/scope/preflight.md
```
Expected: ≥ 80 lines (substantive content).

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/scope/preflight.md
git commit -m "feat(r4-scope): preflight ref (STEP 1)"
```

---

### Task 10: Write `_shared/scope/discussion-overview.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-overview.md`

- [ ] **Step 1: Write discussion entry + sourced wrappers**

Replace placeholder with:

```markdown
# Scope deep discussion overview (STEP 2 entry)

> 5 structured rounds + Deep Probe Loop. Each round: AI presents
> recommendation, user confirms/edits/expands; per-answer challenger;
> per-round expander. Then advance.

## Sources (load once at top of STEP 2)

```bash
source commands/vg/_shared/lib/answer-challenger.sh        # exports challenge_answer, challenger_dispatch, challenger_count_for_phase
source commands/vg/_shared/lib/dimension-expander.sh       # exports expand_dimensions, expander_dispatch
source commands/vg/_shared/lib/bootstrap-inject.sh         # exports vg_bootstrap_render_block, vg_bootstrap_emit_fired
```

Read `commands/vg/_shared/bug-detection-guide.md` once (apply 6 detection
patterns throughout: schema_violation, helper_error, user_pushback,
ai_inconsistency, gate_loop, self_discovery).

## Round loop (5 fixed + Deep Probe)

For ROUND in 1..5:
1. Read `_shared/scope/discussion-round-${ROUND}-<topic>.md` and follow it.
2. After EACH user answer, invoke per-answer challenger (see pattern below).
3. After ALL answers in the round, invoke per-round expander.
4. Advance to next round.

After R5 completes: read `_shared/scope/discussion-deep-probe.md` and
run mandatory minimum 5 probes.

## Per-answer challenger pattern (re-used in EVERY round)

```bash
PROMPT=$(bash commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
         "$user_answer" "round-${ROUND}" "phase-scope" "$accumulated_draft")
wrapper_rc=$?
case $wrapper_rc in
  0)  ;;  # success — PROMPT contains content
  2)  echo "↷ Trivial answer — skip challenger"; PROMPT="" ;;
  *)  echo "⚠ challenger wrapper failed rc=$wrapper_rc" >&2; PROMPT="" ;;
esac

if [ -n "$PROMPT" ]; then
  # Inject bootstrap rules (promoted L-IDs) before dispatch
  BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope")
  vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope" "${PHASE_NUMBER}"
  PROMPT="${PROMPT}

<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>"

  bash scripts/vg-narrate-spawn.sh scope-challenger spawning "round-${ROUND} answer-${ANSWER_N}"
fi
```

Then in the AI runtime:

`Agent(subagent_type="general-purpose", model="opus", prompt=<PROMPT>)`

On return:

```bash
bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"
challenger_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
```

If `has_issue=true` → AskUserQuestion (3 options: Address / Acknowledge / Defer).
Then `challenger_record_user_choice "${PHASE_NUMBER}" "round-${ROUND}" "phase-scope" "$choice"`.
Loop guard: if `challenger_count_for_phase` ≥ `${config.scope.adversarial_max_rounds:-3}`,
helper auto-skips (no manual gate).

## Per-round expander pattern (re-used in EVERY round end)

```bash
PROMPT=$(bash commands/vg/_shared/lib/vg-expand-round-wrapper.sh \
         "${ROUND}" "${ROUND_TOPIC}" "${round_qa_accumulated}" "${PLANNING_DIR}/FOUNDATION.md")
bash scripts/vg-narrate-spawn.sh scope-expander spawning "round-${ROUND}"
```

`Agent(subagent_type="general-purpose", model="opus", prompt=<PROMPT>)`

```bash
bash scripts/vg-narrate-spawn.sh scope-expander returned "<critical:N nice:M>"
expander_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
```

If `critical_missing[]` non-empty → AskUserQuestion (Address critical / Acknowledge / Defer).

## Mark deep_discussion at end of STEP 2

After R5 + Deep Probe completes (no manual gate — Deep Probe ref handles
its own min-5 enforcement):

```bash
vg-orchestrator mark-step scope 1_deep_discussion
```
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-overview.md
git commit -m "feat(r4-scope): discussion-overview ref (STEP 2 entry + challenger/expander pattern)"
```

---

### Task 11: Write `_shared/scope/discussion-round-1-domain.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-round-1-domain.md`

- [ ] **Step 1: Port R1 from backup**

Open `commands/vg/.scope.md.r4-backup`, locate `### Round 1 — Domain & Business`
(around line 320 in backup), port to ref file. Include:
- Conversational preamble (R9 rule — Vietnamese)
- AskUserQuestion block (header, question template with US-1/US-2 placeholders + role + business rule examples)
- `--auto` mode branch
- Decision lock pattern: `P${PHASE_NUMBER}.D-XX` (category: business)
- Cross-reference to challenger pattern in `discussion-overview.md` (do NOT duplicate the bash)
- Cross-reference to expander pattern in `discussion-overview.md` (run ONCE at end of round)

End ref with:
```markdown
After R1 challenger + expander complete, advance to R2
(Read `_shared/scope/discussion-round-2-technical.md`).
```

DO NOT call `mark-step 1_deep_discussion` here — that happens at end of
STEP 2 in `discussion-overview.md` (after R5 + Deep Probe).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-round-1-domain.md
git commit -m "feat(r4-scope): R1 Domain & Business ref"
```

---

### Task 12: Write `_shared/scope/discussion-round-2-technical.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-round-2-technical.md`

- [ ] **Step 1: Port R2 + multi-surface gate from backup**

Locate `### Round 2 — Technical Approach` (around line 374 in backup) +
multi-surface gate block (lines 376-490). Port to ref. Include:
- Multi-surface detection (`grep -qE "^surfaces:" .claude/vg.config.md`)
- AskUserQuestion multi-select for surfaces touched
- Lock `SURFACE_LIST` + `SURFACE_ROLE` to `P${PHASE_NUMBER}.D-surfaces`
- Conversational preamble (R9 rule — Vietnamese)
- AskUserQuestion for tech approach (architecture style, DB, framework)
- Decision lock: `P${PHASE_NUMBER}.D-XX` (category: technical)
- Cross-reference challenger + expander patterns in `discussion-overview.md`

End: `Read _shared/scope/discussion-round-3-api.md`.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-round-2-technical.md
git commit -m "feat(r4-scope): R2 Technical Approach + multi-surface gate ref"
```

---

### Task 13: Write `_shared/scope/discussion-round-3-api.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-round-3-api.md`

- [ ] **Step 1: Port R3 from backup**

Locate `### Round 3 — API Design` (around line 493). Port preamble +
AskUserQuestion for endpoints/auth/data/error format. Lock D-XX (category: api).
Cross-reference challenger + expander patterns. End → R4.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-round-3-api.md
git commit -m "feat(r4-scope): R3 API Design ref"
```

---

### Task 14: Write `_shared/scope/discussion-round-4-ui.md` (with profile-aware skip)

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-round-4-ui.md`

- [ ] **Step 1: Port R4 + profile skip from backup**

Locate `### Round 4 — UI/UX` (around line 536). Port preamble +
AskUserQuestion for screens/states/empty/error UX. Lock D-XX (category: ui).

ADD profile gate at top of ref:
```bash
case "${PROFILE}" in
  web-backend-only|cli-tool|library)
    echo "↷ R4 UI/UX skipped — profile=${PROFILE} has no UI surface"
    vg-orchestrator emit-event scope.r4_skipped --payload "{\"profile\":\"${PROFILE}\"}"
    return 0
    ;;
esac
```

Cross-reference challenger + expander. End → R5 (or skip directly to R5 if profile-skipped).

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-round-4-ui.md
git commit -m "feat(r4-scope): R4 UI/UX ref + profile-aware skip"
```

---

### Task 15: Write `_shared/scope/discussion-round-5-tests.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-round-5-tests.md`

- [ ] **Step 1: Port R5 from backup**

Locate `### Round 5 — Test Scenarios` (around line 608). Port preamble +
AskUserQuestion for happy/sad/edge scenarios. Lock TS-XX per decision.
Cross-reference challenger + expander. End → Deep Probe Loop.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-round-5-tests.md
git commit -m "feat(r4-scope): R5 Test Scenarios ref"
```

---

### Task 16: Write `_shared/scope/discussion-deep-probe.md`

**Files:**
- Modify: `commands/vg/_shared/scope/discussion-deep-probe.md`

- [ ] **Step 1: Port Deep Probe Loop from backup**

Locate `### Deep Probe Loop (mandatory — minimum 5 probes after Round 5)`
(around line 675). Port loop control:
- Counter `PROBE_COUNT=0`
- Loop until `PROBE_COUNT >= 5` AND user signals "no more"
- Each probe: AskUserQuestion (open-ended, free-form follow-up question
  AI generates from accumulated context)
- After each user answer: same per-answer challenger pattern
- Increment counter; if `PROBE_COUNT < 5`, loop unconditionally
- Hard min: 5 probes (cannot exit before)
- Soft max: 10 probes (after 10, AI must offer "advance to artifact gen?" option)

Cross-reference challenger pattern in `discussion-overview.md`.

End ref with:
```bash
vg-orchestrator mark-step scope 1_deep_discussion
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/discussion-deep-probe.md
git commit -m "feat(r4-scope): Deep Probe Loop ref + 1_deep_discussion marker"
```

---

### Task 17: Write `_shared/scope/env-preference.md`

**Files:**
- Modify: `commands/vg/_shared/scope/env-preference.md`

- [ ] **Step 1: Port `1b_env_preference` from backup**

Locate `<step name="1b_env_preference">` block. Port:
- Read `.vg/phases/${PHASE_NUMBER}/DEPLOY-STATE.json` if exists (auto-detect prior env)
- AskUserQuestion: target env for downstream commands (sandbox / staging / prod)
- Persist choice to `${PHASE_DIR}/CONTEXT.md.env-pref` (one-line file: `target_env=<choice>`)
- Cross-reference: blueprint/build/test/review/accept consumers read this

End ref with:
```bash
vg-orchestrator mark-step scope 1b_env_preference 2>/dev/null || true
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/env-preference.md
git commit -m "feat(r4-scope): env-preference ref (STEP 3)"
```

---

### Task 18: Write `_shared/scope/artifact-write.md` (per-decision split)

**Files:**
- Modify: `commands/vg/_shared/scope/artifact-write.md`

- [ ] **Step 1: Port `2_artifact_generation` + add per-decision split**

Locate `<step name="2_artifact_generation">` (around line 800-940). Port atomic
write of CONTEXT.md (Layer 3 flat) and DISCUSSION-LOG.md (append-only).

ADD per-decision split (UX baseline R1):

```bash
mkdir -p "${PHASE_DIR}/CONTEXT"

# Parse CONTEXT.md, split each `### P{phase}.D-XX:` (or legacy `### D-XX:`) section
# into its own file under CONTEXT/D-NN.md
"${PYTHON_BIN:-python3}" - "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/CONTEXT" <<'PY'
import re, sys, pathlib

flat = pathlib.Path(sys.argv[1]).read_text()
out_dir = pathlib.Path(sys.argv[2])
out_dir.mkdir(exist_ok=True)

# Match `### P{phase}.D-NN: title` OR `### D-NN: title` headings
pattern = re.compile(r'^### (?:P[0-9.]+\.)?(D-\d+)(:?\s.*)?$', re.M)
matches = list(pattern.finditer(flat))

if not matches:
    print("⚠ no D-XX headings found in CONTEXT.md — split skipped", file=sys.stderr)
    sys.exit(0)

# Header (everything before first D- section)
header = flat[:matches[0].start()].rstrip() + "\n"

# Build index
index_lines = ["# CONTEXT decisions index\n", ""]
for i, m in enumerate(matches):
    decision_id = m.group(1)
    end = matches[i+1].start() if i+1 < len(matches) else len(flat)
    body = flat[m.start():end]
    out_file = out_dir / f"{decision_id}.md"
    out_file.write_text(body)
    title = (m.group(2) or "").lstrip(": ").strip().splitlines()[0] if m.group(2) else ""
    index_lines.append(f"- [{decision_id}]({decision_id}.md){' — ' + title if title else ''}")

(out_dir / "index.md").write_text("\n".join(index_lines) + "\n")
print(f"✓ split {len(matches)} decisions into CONTEXT/D-*.md + index.md")
PY
```

After split, mark step:
```bash
vg-orchestrator mark-step scope 2_artifact_generation
vg-orchestrator emit-event scope.artifact_written \
  --payload "{\"decisions\":$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")}"
```

- [ ] **Step 2: Quick smoke test the splitter inline**

```bash
mkdir -p /tmp/vg-scope-split-test/CONTEXT
cat > /tmp/vg-scope-split-test/CONTEXT.md <<'EOF'
# Phase X CONTEXT

Some intro text.

### P3.2.D-01: First decision
Decision body 1.

### P3.2.D-02: Second decision
Decision body 2.
EOF

python3 - /tmp/vg-scope-split-test/CONTEXT.md /tmp/vg-scope-split-test/CONTEXT <<'PY'
# (paste the splitter from above)
import re, sys, pathlib
flat = pathlib.Path(sys.argv[1]).read_text()
out_dir = pathlib.Path(sys.argv[2])
out_dir.mkdir(exist_ok=True)
pattern = re.compile(r'^### (?:P[0-9.]+\.)?(D-\d+)(:?\s.*)?$', re.M)
matches = list(pattern.finditer(flat))
header = flat[:matches[0].start()].rstrip() + "\n"
index_lines = ["# CONTEXT decisions index\n", ""]
for i, m in enumerate(matches):
    decision_id = m.group(1)
    end = matches[i+1].start() if i+1 < len(matches) else len(flat)
    body = flat[m.start():end]
    (out_dir / f"{decision_id}.md").write_text(body)
    title = (m.group(2) or "").lstrip(": ").strip().splitlines()[0] if m.group(2) else ""
    index_lines.append(f"- [{decision_id}]({decision_id}.md){' — ' + title if title else ''}")
(out_dir / "index.md").write_text("\n".join(index_lines) + "\n")
print(f"split {len(matches)}")
PY

ls /tmp/vg-scope-split-test/CONTEXT/
rm -rf /tmp/vg-scope-split-test
```
Expected: `D-01.md  D-02.md  index.md` listed; output `split 2`.

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/scope/artifact-write.md
git commit -m "feat(r4-scope): artifact-write ref + per-decision split (Layer 1/2/3)"
```

---

### Task 19: Write `_shared/scope/completeness-validation.md`

**Files:**
- Modify: `commands/vg/_shared/scope/completeness-validation.md`

- [ ] **Step 1: Port `3_completeness_validation` from backup**

Locate `<step name="3_completeness_validation">` (around line 1100). Port 4 checks:
1. Decision count vs SPECS.md in-scope items (warn if < count)
2. Endpoint coverage (warn if any decision lacks `endpoints:` sub-section)
3. UI components coverage (skip if profile-skipped R4)
4. Test scenarios coverage (warn if any decision lacks `test_scenarios:` sub-section)

Each warning emits `scope.completeness_warning` event. End:
```bash
vg-orchestrator mark-step scope 3_completeness_validation
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/completeness-validation.md
git commit -m "feat(r4-scope): completeness-validation ref (STEP 5, 4 checks)"
```

---

### Task 20: Write `_shared/scope/crossai.md`

**Files:**
- Modify: `commands/vg/_shared/scope/crossai.md`

- [ ] **Step 1: Port `4_crossai_review` + `4_5_bootstrap_reflection` + `4_6_test_strategy`**

Locate `<step name="4_crossai_review">` (around line 1180). Port:
- Skip path: if `--skip-crossai` in args, log override-debt entry, mark step, return
  ```bash
  if [[ "${ARGUMENTS}" =~ --skip-crossai ]]; then
    [[ "${ARGUMENTS}" =~ --override-reason= ]] || {
      echo "⛔ --skip-crossai requires --override-reason=<text>" >&2
      exit 1
    }
    bash commands/vg/_shared/override-debt.md  # logs to register
    vg-orchestrator mark-step scope 4_crossai_review
    return 0
  fi
  ```
- Async dispatch via `commands/vg/_shared/crossai-invoke.md`
- crossai-output validator (P16 verify-crossai-output.py) — preserve exit gate
- mark-step `4_crossai_review`

Then `4_5_bootstrap_reflection` (lines 1240-1265):
- Skip silently if `.vg/bootstrap/` absent
- Spawn vg-reflector via Agent (with narrate-spawn wrap)
- Show interactive y/n/e/s prompt for candidates

Then `4_6_test_strategy` (lines 1267-1294):
- Run tester-pro-cli `strategy generate` if executable exists
- Write TEST-STRATEGY.md draft (preserve existing on re-run unless `--force`)
- mark-step `4_6_test_strategy`

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/crossai.md
git commit -m "feat(r4-scope): crossai ref (STEP 6 — review + reflection + test-strategy)"
```

---

### Task 21: Write `_shared/scope/close.md`

**Files:**
- Modify: `commands/vg/_shared/scope/close.md`

- [ ] **Step 1: Port `5_commit_and_next` from backup**

Locate `<step name="5_commit_and_next">` (around line 1297). Port:
- Decision count + endpoint count + test scenario count grep
- contract-pin write (`vg-contract-pins.py write ${PHASE_NUMBER}`)
- git add CONTEXT.md, CONTEXT/, DISCUSSION-LOG.md, PIPELINE-STATE.json, .contract-pins.json
- git commit with summary
- decisions-trace gate (`verify-decisions-trace.py` — block mode default)
- mark-step `5_commit_and_next`
- emit `scope.completed`
- run-complete (`vg-orchestrator run-complete` — exit non-zero on block)
- Display summary + `Next: /vg:blueprint {phase}`

ADD: ensure `git add` includes per-decision split files:
```bash
git add "${PHASE_DIR}/CONTEXT.md" \
        "${PHASE_DIR}/CONTEXT/" \
        "${PHASE_DIR}/DISCUSSION-LOG.md" \
        "${PHASE_DIR}/PIPELINE-STATE.json"
[ -f "${PHASE_DIR}/.contract-pins.json" ] && git add "${PHASE_DIR}/.contract-pins.json"
```

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/scope/close.md
git commit -m "feat(r4-scope): close ref (STEP 7 — commit + decisions-trace + run-complete)"
```

---

## Phase E — Wire scope into emit-tasklist + meta-skill

### Task 22: Add `CHECKLIST_DEFS["vg:scope"]` to `scripts/emit-tasklist.py`

**Files:**
- Modify: `scripts/emit-tasklist.py` (locate `CHECKLIST_DEFS = {` dict, add `"vg:scope"` entry)

- [ ] **Step 1: Read current CHECKLIST_DEFS**

```bash
grep -n 'CHECKLIST_DEFS\|"vg:blueprint"' scripts/emit-tasklist.py | head -20
```

- [ ] **Step 2: Add scope entry mirroring blueprint shape**

In `scripts/emit-tasklist.py`, inside `CHECKLIST_DEFS = {` dict, add (alphabetically near `vg:blueprint`):

```python
    "vg:scope": [
        {"id": "preflight", "label": "Preflight (parse args, SPECS gate, tasklist)"},
        {"id": "deep_discussion", "label": "Deep discussion (5 rounds + Deep Probe)"},
        {"id": "env_preference", "label": "Env preference (sandbox/staging/prod)"},
        {"id": "artifact_generation", "label": "Artifact generation (CONTEXT + DISCUSSION-LOG + per-decision split)"},
        {"id": "completeness_validation", "label": "Completeness validation (4 checks)"},
        {"id": "crossai_review", "label": "CrossAI review (skippable with --skip-crossai)"},
        {"id": "close", "label": "Close (contract pin, decisions-trace, commit, run-complete)"},
    ],
```

- [ ] **Step 3: Smoke-emit a tasklist for scope**

```bash
mkdir -p /tmp/vg-scope-tasklist-test
python3 scripts/emit-tasklist.py \
  --command vg:scope \
  --profile web-fullstack \
  --phase 99.0 \
  --out /tmp/vg-scope-tasklist-test/contract.json
python3 -c "import json; c = json.load(open('/tmp/vg-scope-tasklist-test/contract.json')); assert len(c['groups']) == 7; print('✓ 7 checklist groups for vg:scope')"
rm -rf /tmp/vg-scope-tasklist-test
```
Expected: `✓ 7 checklist groups for vg:scope`.

- [ ] **Step 4: Commit**

```bash
git add scripts/emit-tasklist.py
git commit -m "feat(r4-scope): wire CHECKLIST_DEFS[\"vg:scope\"] (audit fix #9)"
```

---

### Task 23: Append "Scope-specific Red Flags" addendum to `vg-meta-skill.md`

**Files:**
- Modify: `scripts/hooks/vg-meta-skill.md` (append section)

- [ ] **Step 1: Append addendum**

Add at end of `scripts/hooks/vg-meta-skill.md`:

```markdown

---

## Scope-specific Red Flags (R4 pilot, 2026-05-03)

| Thought | Reality |
|---|---|
| "Skip challenger to speed up round" | Per-answer trigger; skipping = blind spot risk (Codex review confirmed) |
| "Skip expander on small round" | Per-round end gate; missing = critical_missing undetected |
| "Auto-accept all challenger findings" | User must choose Address / Acknowledge / Defer per finding (not blanket) |
| "Profile branch is suggestion" | Profile branch enforces R4 skip for backend-only — don't override |
| "Per-decision split optional" | UX baseline R1 — blueprint depends on `vg-load.sh --decision D-NN` |
| "Spawn Task() for challenger" | Tool name is `Agent` (Codex correction #1) |
```

- [ ] **Step 2: Commit**

```bash
git add scripts/hooks/vg-meta-skill.md
git commit -m "feat(r4-scope): scope-specific Red Flags addendum"
```

---

## Phase F — Verification + dogfood

### Task 24: Run full pytest suite — all 4 scope tests + R1a regression

**Files:**
- Run: existing test suite

- [ ] **Step 1: Run all scope tests**

```bash
pytest scripts/tests/test_scope_*.py -v
```
Expected: ALL PASS — 4 tests green.

- [ ] **Step 2: Run R1a blueprint regression to ensure no shared-infra breakage**

```bash
pytest scripts/tests/test_blueprint_*.py scripts/tests/test_evidence_helper_*.py -v
```
Expected: ALL PASS (scope refactor MUST NOT regress R1a).

- [ ] **Step 3: If any test fails, STOP and fix before dogfood**

Do NOT proceed to dogfood with red tests. Revisit Tasks 8-23.

---

### Task 25: Empirical dogfood — `/vg:scope` on PrintwayV3 phase

**Files:**
- Read-only on PrintwayV3 repo: `/Users/dzungnguyen/Vibe Code/Code/PrintwayV3` (per context.md)

- [ ] **Step 1: Sync vgflow scope refactor into PrintwayV3 .claude/**

```bash
# Inside PrintwayV3 repo (separate clone — or symlink for dogfood)
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
# Copy slim entry + 13 refs + emit-tasklist.py + meta-skill update
rsync -av --delete \
  "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/commands/vg/scope.md" \
  ".claude/commands/vg/scope.md"
rsync -av --delete \
  "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/commands/vg/_shared/scope/" \
  ".claude/commands/vg/_shared/scope/"
cp "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/scripts/emit-tasklist.py" \
   ".claude/scripts/emit-tasklist.py"
cp "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix/scripts/hooks/vg-meta-skill.md" \
   ".claude/scripts/hooks/vg-meta-skill.md"
```

(Adjust paths if PrintwayV3 uses different sync mechanism — check repo's existing
`/vg:sync` skill or `.claude/scripts` install pattern.)

- [ ] **Step 2: Pick a fresh phase for dogfood (NOT 3.2 which was the buggy baseline)**

```bash
# Pick phase 3.3 (or next available) — must have SPECS.md present
ls .vg/phases/ | sort -V | head -10
```

If no fresh phase exists, ask user to confirm a phase number with SPECS.md
ready (e.g. via `/vg:specs <phase>` first if needed).

- [ ] **Step 3: Run `/vg:scope <phase>` and complete all 5 rounds**

User runs (in PrintwayV3 Claude Code session):
```
/vg:scope 3.3
```

Engineer (this plan executor) supervises but does NOT touch PrintwayV3 from
the vgflow session — observe via events.db query (see Step 4).

- [ ] **Step 4: Verify all 8 exit criteria (spec §5.4)**

After scope run completes, query events.db:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/PrintwayV3"
PHASE=3.3   # or whichever phase user chose

# 1. Tasklist visible immediately — check first event
sqlite3 .vg/events.db "SELECT event_type FROM events WHERE phase='${PHASE}' ORDER BY ts ASC LIMIT 1;"
# Expected: scope.tasklist_shown

# 2. scope.native_tasklist_projected event ≥ 1
sqlite3 .vg/events.db "SELECT COUNT(*) FROM events WHERE event_type='scope.native_tasklist_projected' AND phase='${PHASE}';"
# Expected: >= 1

# 3. 3 step markers touched
ls .vg/phases/${PHASE}/.step-markers/scope/ 2>/dev/null
# Expected: 0_parse_and_validate.done, 1_deep_discussion.done, 2_artifact_generation.done (at minimum)

# 4. CONTEXT.md (>=500B with D-) + DISCUSSION-LOG.md written
wc -c .vg/phases/${PHASE}/CONTEXT.md
grep -c '^### .*D-' .vg/phases/${PHASE}/CONTEXT.md
test -f .vg/phases/${PHASE}/DISCUSSION-LOG.md && echo "✓ DISCUSSION-LOG.md exists"
# Expected: bytes >= 500, decision count >= 1, "✓ DISCUSSION-LOG.md exists"

# 4b. Per-decision split exists (NEW R4 requirement)
ls .vg/phases/${PHASE}/CONTEXT/ | grep -c '^D-'
test -f .vg/phases/${PHASE}/CONTEXT/index.md && echo "✓ CONTEXT/index.md exists"
# Expected: count >= 1, "✓ CONTEXT/index.md exists"

# 5. Per-round challenger Task events (one per user answer in each round)
sqlite3 .vg/events.db "SELECT COUNT(*) FROM events WHERE event_type='scope.challenger_dispatched' AND phase='${PHASE}';"
# Expected: >= 5 (at least 1 per round across R1-R5; typically 10-20)

# 6. Per-round expander Task events (one per round end, R1-R5)
sqlite3 .vg/events.db "SELECT COUNT(*) FROM events WHERE event_type='scope.expander_dispatched' AND phase='${PHASE}';"
# Expected: >= 5 (one per round)

# 7. CrossAI review event present (or --skip-crossai with override-debt)
sqlite3 .vg/events.db "SELECT event_type FROM events WHERE event_type IN ('crossai.verdict','scope.crossai_skipped') AND phase='${PHASE}';"
# Expected: at least one row

# 8. Stop hook fired without exit 2 (run-complete success)
sqlite3 .vg/events.db "SELECT event_type FROM events WHERE event_type IN ('scope.completed','run.completed') AND phase='${PHASE}';"
# Expected: both present
```

If ALL 8 criteria pass → R4 scope pilot PASS. Document evidence in conversation.

If ANY criterion fails → diagnose. Common causes:
- (1) tasklist_shown missing → preflight.md emit-tasklist call failed; check `.vg/runs/<run>/`
- (2) native_tasklist_projected missing → TodoWrite was not called after preflight
- (5/6) challenger/expander missing → check Agent calls were made in discussion rounds
- (8) run-complete blocked → read `.vg/blocks/<run>/` for diagnostic

- [ ] **Step 5: Commit dogfood evidence as plan retrospective**

After PASS, write a short retrospective to vgflow repo:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
mkdir -p docs/superpowers/retros
cat > docs/superpowers/retros/2026-05-03-vg-r4-scope-pilot-retro.md <<'EOF'
# R4 Scope Pilot Retro

**Date:** $(date -u +%Y-%m-%d)
**Dogfood phase:** PrintwayV3 phase 3.3
**Outcome:** PASS (all 8 exit criteria met)

## Evidence
- (paste sqlite3 query outputs here)
- (paste ls .step-markers/ output here)
- (paste wc / grep CONTEXT.md output here)

## Open follow-ups
- (any quirks observed)
EOF
git add docs/superpowers/retros/2026-05-03-vg-r4-scope-pilot-retro.md
git commit -m "docs(r4-scope): pilot retro — 8/8 exit criteria PASS"
```

---

### Task 26: Final cleanup — remove backup file

**Files:**
- Delete: `commands/vg/.scope.md.r4-backup`

- [ ] **Step 1: Confirm dogfood PASSED (Task 25 Step 4 all green)**

DO NOT delete backup if dogfood failed or partial.

- [ ] **Step 2: Delete backup**

```bash
git rm commands/vg/.scope.md.r4-backup
git commit -m "chore(r4-scope): remove .scope.md.r4-backup after dogfood PASS"
```

- [ ] **Step 3: Sanity — run full test suite one final time**

```bash
pytest scripts/tests/ -v
```
Expected: ALL PASS.

---

## Deviations from spec (apply during execution)

The spec at `docs/superpowers/specs/2026-05-03-vg-scope-design.md` has 2 places where this plan deviates intentionally — note them in commit messages or PR description:

1. **§3 file layout (nested `_shared/scope/discussion/<round>.md`)** → flattened to
   `_shared/scope/discussion-round-N-<topic>.md` per Codex correction #4 (spec §6 appendix).
   This plan's File Structure table reflects the flat layout.

2. **§4.1 must_write (CONTEXT.md + DISCUSSION-LOG.md only)** → expanded to 4 paths
   (CONTEXT.md + CONTEXT/index.md + CONTEXT/D-*.md glob + DISCUSSION-LOG.md) per
   UX baseline R1 (spec §line 264 mandates honoring R1 = per-decision split).
   Layer 3 flat concat preserves backward compat for blueprint consumer.

---

## Rollback procedure

If R4 scope pilot fails after merge (regression observed in PrintwayV3 dogfood):

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git revert <merge-commit-sha>  # reverts entire R4 scope pilot atomically
# OR partial:
git checkout HEAD~N -- commands/vg/scope.md  # restore prior slim entry
git checkout HEAD~N -- commands/vg/_shared/scope/  # restore prior refs
git commit -m "revert(r4-scope): rollback per dogfood regression"
```

The backup `.scope.md.r4-backup` is removed in Task 26 ONLY after PASS — before
that, it serves as the safety-net rollback target.

---

## Self-review notes

- Spec §1.1 heavy steps mapped → Tasks 9-21 (one ref per step block from backup).
- Spec §1.2 "no new subagents" → enforced by Task 4 regression test.
- Spec §1.3 patterns preserved → discussion-overview.md sources existing wrappers + bootstrap-inject; no rewrite of challenger/expander logic.
- Spec §1.4 audit fix #9 → Task 22 (CHECKLIST_DEFS) wires native_tasklist_projected emission via emit-tasklist + Task 9 (preflight ref) emits the event after TodoWrite.
- Spec §1.5 ≤500 line goal → Task 8 slim body targets ~250 lines; Task 2 test enforces ≤600 hard ceiling.
- Spec §4.4 meta-skill addendum → Task 23.
- Spec §5.3 testing → Tasks 2-5 (4 pytest tests, exceeds spec's 3).
- Spec §5.4 8 exit criteria → Task 25 Step 4 verifies each.
- Spec §6 Codex appendix corrections → all 5 applied: (1) Agent tool name in slim entry HARD-GATE + ref examples; (2) UserPromptSubmit hook already wired (Task 1 verify); (3) PreToolUse Write hook already wired (Task 1 verify); (4) FLAT layout (Task 7 + Task 3 test enforces); (5) state-machine validator already shipped (Task 1 verify).
- UX baseline R1 (per-decision split) → Task 18.
- UX baseline R2 (narrate-spawn) → Task 8 slim entry HARD-GATE + Task 10 discussion-overview pattern.
- UX baseline R3 (compact hook stderr) → inherited from R1a, no work in this plan.
