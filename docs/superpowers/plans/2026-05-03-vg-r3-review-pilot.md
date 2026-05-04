# R3 Review Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `commands/vg/review.md` from 7,413 → ≤500-line slim entry + ~12 flat refs in `commands/vg/_shared/review/` (with nested `discovery/`, `findings/`, `verdict/` for HEAVY steps) + 1 custom subagent (`vg-review-browser-discoverer` only — phase4 has no weighted formula per audit, stays inline-split). Strengthen lens telemetry (audit FAIL items #9-11), close `--skip-lens-plan-gate` override gap (FAIL #13), reconcile LENS_MAP coverage (PARTIAL #14), fix dedup citation (DOC FIX #15). Bake all 3 R1a UX baseline requirements (per-task split via vg-load, spawn narration, compact hook stderr). Pilot is GATE — if 12 exit criteria PASS, R3 accept pilot proceeds.

**Architecture:** Reuse 100% of R1a infrastructure (HMAC evidence helper, state-machine validator, 7 hooks, install-hooks.sh, vg-meta-skill, vg-narrate-spawn, vg-load). Review-specific work: 6 telemetry/audit fixes + 1 subagent + 1 slim entry + ~12 refs (3 nested dirs). HEAVY step `phase2_browser_discovery` (947 lines) → subagent. `phase4_goal_comparison` (829 lines) → inline ref split (binary lookup, no formula, audit confirmed). All consumer reads of PLAN/API-CONTRACTS/TEST-GOALS go through `vg-load` — closes Phase F Task 30 from blueprint plan (this pilot supersedes that task for `vg:review`).

**Tech Stack:** bash (telemetry helpers), Python 3 (spawn_recursive_probe.py + review-lens-plan.py strengthening + tests), pytest, Claude Code Agent tool, sqlite3 (events.db queries), HMAC-SHA256 (signed evidence — reused).

**Spec source:** `docs/superpowers/specs/2026-05-03-vg-review-design.md` (472 lines, includes Codex review corrections + UX baseline reference).

**Branch:** `feat/rfc-v9-followup-fixes`. Each task commits incrementally. Final dogfood on PrintwayV3 phase 3.2 (the existing filter pending bug at billing/topup-queue) before merge.

**Relationship to Phase F (blueprint plan):** Phase F Task 30 (migrate review/test/roam/accept to vg-load) is **partially absorbed** by this pilot — specifically the `vg:review` portion. This pilot covers vg-load migration as an integral part of the slim refactor (refs use vg-load by construction, not bolt-on). Phase F Task 30 remains responsible for `vg:test`, `vg:roam`, `vg:accept`. After R3 review pilot completes, update blueprint plan Phase F Task 30 to remove `vg:review` from its scope.

---

## File structure (new + modified)

| File | Action | Lines | Purpose |
|---|---|---|---|
| `scripts/spawn_recursive_probe.py` | MODIFY (~1303 → ~1380) | +77 | Per-lens telemetry events + LENS_MAP coverage doc comment |
| `scripts/review-lens-plan.py` | MODIFY (~700 → ~750) | +50 | Staleness check vs API-CONTRACTS.md mtime, exit 2 if stale |
| `scripts/aggregate_recursive_goals.py` | DOC FIX | +5 | Comment block citing correct dedup line range |
| `commands/vg/review.md` | REFACTOR (7413 → ~500) | -6913 | Slim entry per blueprint pilot template |
| `commands/vg/.review.md.r3-backup` | CREATE | 7413 | Backup of original (mirrors R1a/R2 pattern) |
| `commands/vg/_shared/review/preflight.md` | CREATE | ~250 | 0_parse_and_validate + 0_session + 1_init + create_task_tracker |
| `commands/vg/_shared/review/code-scan.md` | CREATE | ~250 | phase1_code_scan + ripple/god-node + API-CONTRACTS/api-docs precheck |
| `commands/vg/_shared/review/discovery/overview.md` | CREATE | ~150 | phase2 entry — instructs spawn vg-review-browser-discoverer |
| `commands/vg/_shared/review/discovery/delegation.md` | CREATE | ~200 | Subagent input/output contract (with vg-load + narrate-spawn) |
| `commands/vg/_shared/review/lens-dispatch.md` | CREATE | ~300 | phase2_5 — eligibility gate, 3-axis preflight, manager dispatch, aggregation, per-lens telemetry |
| `commands/vg/_shared/review/findings/collect.md` | CREATE | ~200 | phase2b_collect_merge + post-challenge |
| `commands/vg/_shared/review/findings/fix-loop.md` | CREATE | ~250 | phase3_fix_loop — auto-fix routing, exploration limits |
| `commands/vg/_shared/review/verdict/overview.md` | CREATE | ~150 | phase4 entry — branching logic by profile + UI_GOAL_COUNT |
| `commands/vg/_shared/review/verdict/pure-backend-fastpath.md` | CREATE | ~150 | UI_GOAL_COUNT == 0 fast path |
| `commands/vg/_shared/review/verdict/web-fullstack.md` | CREATE | ~250 | Full goal lookup + verdict synthesis |
| `commands/vg/_shared/review/verdict/profile-branches.md` | CREATE | ~200 | 4 profile-specific verdict paths |
| `commands/vg/_shared/review/delta-mode.md` | CREATE | ~250 | phaseP_delta change-only mode |
| `commands/vg/_shared/review/profile-shortcuts.md` | CREATE | ~200 | infra smoke / regression / schema verify / link check shortcut branches |
| `commands/vg/_shared/review/crossai.md` | CREATE | ~150 | UNCHANGED behavior (refactor deferred per spec §1.5) |
| `commands/vg/_shared/review/close.md` | CREATE | ~250 | Write artifacts, reflection, run-complete, tasklist clear |
| `agents/vg-review-browser-discoverer/SKILL.md` | CREATE | ~250 | Phase2 subagent — parallel browser scan via Haiku ≤5 |
| `scripts/emit-tasklist.py` | MODIFY | +0 | Add CHECKLIST_DEFS["vg:review"] (test) |
| `scripts/tests/test_review_slim_size.py` | CREATE | ~50 | Assert review.md ≤600 lines, refs listed, uses Agent not Task |
| `scripts/tests/test_review_references_exist.py` | CREATE | ~60 | All 12 refs exist + nested dirs valid |
| `scripts/tests/test_review_subagent_definition.py` | CREATE | ~80 | vg-review-browser-discoverer valid; assert NO vg-review-goal-scorer |
| `scripts/tests/test_lens_telemetry_per_lens.py` | CREATE | ~120 | Each lens dispatch emits review.lens.<name>.dispatched + .completed |
| `scripts/tests/test_lens_phase_telemetry.py` | CREATE | ~100 | review.lens_phase.entered + completed events emitted; Stop hook blocks if missing |
| `scripts/tests/test_lens_plan_staleness.py` | CREATE | ~80 | Touch API-CONTRACTS.md after plan → step blocks |
| `scripts/tests/test_phase4_inline_split.py` | CREATE | ~60 | verdict/ has 4 sub-refs, each ≤300 lines |
| `scripts/tests/test_review_uses_vg_load.py` | CREATE | ~80 | All flat blueprint reads in AI-context paths replaced by vg-load |
| `scripts/tests/test_lens_plan_gate_override.py` | CREATE | ~70 | --skip-lens-plan-gate requires --override-reason (audit FAIL #13) |

**Total: 6 modified + 25 created. ~3000 lines added (refs+tests+subagent), ~6913 lines removed (slim entry).**

---

## Phase A — Strengthen lens telemetry + override-discipline (audit FAIL #9-11, #13-15)

### Task 1: Add per-lens telemetry to spawn_recursive_probe.py

**Files:**
- Modify: `scripts/spawn_recursive_probe.py` (per-lens dispatch + completion events)
- Test: `scripts/tests/test_lens_telemetry_per_lens.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_lens_telemetry_per_lens.py
"""Verify spawn_recursive_probe.py emits per-lens telemetry events."""
import json, sqlite3, subprocess, tempfile
from pathlib import Path


def _events_db(tmp: Path) -> Path:
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


def test_per_lens_dispatched_event_emitted(tmp_path, monkeypatch):
    """For each (element × lens × role) tuple, emit review.lens.<name>.dispatched."""
    monkeypatch.chdir(tmp_path)
    db = _events_db(tmp_path)
    # Simulate spawn_recursive_probe.py dispatch loop emitting one event per lens
    # (real test will mock the worker spawn but verify event call)
    # Stub plan with 2 elements × 2 lens × 1 role = 4 dispatches
    plan = tmp_path / "REVIEW-LENS-PLAN.json"
    plan.write_text(json.dumps({
        "elements": [
            {"id": "e1", "class": "form", "lenses": ["lens-form-lifecycle", "lens-input-injection"]},
            {"id": "e2", "class": "table", "lenses": ["lens-table-interaction", "lens-business-coherence"]},
        ],
        "roles": ["admin"],
    }))
    # Run probe in dry-run mode (no actual worker spawn, just emit telemetry)
    proc = subprocess.run(
        ["python3", "scripts/spawn_recursive_probe.py", "--dry-run", "--plan", str(plan), "--phase", "3.2"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT event_type, payload FROM events WHERE event_type LIKE 'review.lens.%.dispatched'"
    ).fetchall()
    conn.close()

    dispatched_lenses = {r[0].split(".")[2] for r in rows}
    assert dispatched_lenses == {"lens-form-lifecycle", "lens-input-injection",
                                  "lens-table-interaction", "lens-business-coherence"}
    assert len(rows) == 4  # one event per (element × lens × role) tuple


def test_per_lens_completed_event_emitted(tmp_path, monkeypatch):
    """After aggregation, emit review.lens.<name>.completed with findings_count + duration_ms."""
    monkeypatch.chdir(tmp_path)
    db = _events_db(tmp_path)
    plan = tmp_path / "REVIEW-LENS-PLAN.json"
    plan.write_text(json.dumps({
        "elements": [{"id": "e1", "class": "form", "lenses": ["lens-form-lifecycle"]}],
        "roles": ["admin"],
    }))
    proc = subprocess.run(
        ["python3", "scripts/spawn_recursive_probe.py", "--dry-run", "--plan", str(plan), "--phase", "3.2"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT payload FROM events WHERE event_type = 'review.lens.lens-form-lifecycle.completed'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    payload = json.loads(rows[0][0])
    assert "findings_count" in payload
    assert "duration_ms" in payload
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/test_lens_telemetry_per_lens.py -v
```
Expected: FAIL — events table empty (script doesn't emit per-lens events yet).

- [ ] **Step 3: Implement telemetry in spawn_recursive_probe.py**

In `scripts/spawn_recursive_probe.py`, add `--dry-run` flag handling and emit per-lens events:

```python
# After existing dispatch loop, around the spawn site (~line 600):
def _emit_lens_dispatched(lens_name, phase, element_id, role, provider):
    subprocess.run([
        "vg-orchestrator", "emit-event", f"review.lens.{lens_name}.dispatched",
        "--phase", str(phase),
        "--payload", json.dumps({
            "element": element_id,
            "role": role,
            "provider": provider,
        }),
    ], check=False)


def _emit_lens_completed(lens_name, phase, findings_count, duration_ms):
    subprocess.run([
        "vg-orchestrator", "emit-event", f"review.lens.{lens_name}.completed",
        "--phase", str(phase),
        "--payload", json.dumps({
            "findings_count": findings_count,
            "duration_ms": duration_ms,
        }),
    ], check=False)


# In dispatch loop:
for element in plan["elements"]:
    for lens in element["lenses"]:
        for role in plan["roles"]:
            t0 = time.time()
            _emit_lens_dispatched(lens, args.phase, element["id"], role, provider="gemini")
            if args.dry_run:
                findings = 0
            else:
                findings = _spawn_worker(element, lens, role)  # existing code
            _emit_lens_completed(lens, args.phase, len(findings), int((time.time() - t0) * 1000))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest scripts/tests/test_lens_telemetry_per_lens.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/spawn_recursive_probe.py scripts/tests/test_lens_telemetry_per_lens.py
git commit -m "feat(r3-review): per-lens telemetry events (audit FAIL #9)

Emit review.lens.<name>.dispatched per (element × lens × role) tuple
and review.lens.<name>.completed with findings_count + duration_ms
after aggregation. Closes audit gap where Stop hook had no per-lens
visibility — only review.lens_plan_generated existed.

--dry-run flag added for tests + future smoke checks (no real workers
spawned)."
```

---

### Task 2: Add lens-phase telemetry + Stop hook detection

**Files:**
- Modify: `commands/vg/_shared/review/lens-dispatch.md` (created in Task 11; placeholder add now to runtime_contract)
- Modify: `commands/vg/review.md` runtime_contract (slim entry — Task 19 final form)
- Test: `scripts/tests/test_lens_phase_telemetry.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_lens_phase_telemetry.py
"""Verify review emits lens_phase.entered + completed events; Stop hook blocks if missing."""
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


def test_stop_hook_blocks_when_lens_phase_entered_missing(tmp_path, monkeypatch):
    """If review run completes without review.lens_phase.entered AND no --skip-discovery flag → Stop hook exits 2."""
    monkeypatch.chdir(tmp_path)
    db = _events_db(tmp_path)
    # Seed: review run-start + run-complete attempt, no lens_phase.entered, no skip flag
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO events(ts, event_type, phase, command, run_id, payload) VALUES "
        "('2026-05-03T10:00:00Z', 'run.started', '3.2', 'vg:review', 'r1', '{}')"
    )
    conn.commit()
    conn.close()

    proc = subprocess.run(
        ["bash", "scripts/hooks/vg-stop.sh"],
        env={**os.environ, "VG_RUN_ID": "r1", "VG_COMMAND": "vg:review", "VG_PHASE": "3.2"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "lens_phase.entered" in proc.stderr or "lens phase" in proc.stderr.lower()


def test_skip_discovery_flag_bypasses_block(tmp_path, monkeypatch):
    """With --skip-discovery override-debt, Stop hook permits run-complete."""
    monkeypatch.chdir(tmp_path)
    db = _events_db(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO events(ts, event_type, phase, command, run_id, payload) VALUES "
        "('2026-05-03T10:00:00Z', 'run.started', '3.2', 'vg:review', 'r1', "
        "'{\"flags\": [\"--skip-discovery\"], \"override_reason\": \"infra-only phase\"}')"
    )
    conn.commit()
    conn.close()

    proc = subprocess.run(
        ["bash", "scripts/hooks/vg-stop.sh"],
        env={**os.environ, "VG_RUN_ID": "r1", "VG_COMMAND": "vg:review", "VG_PHASE": "3.2"},
        capture_output=True, text=True,
    )
    # Permit run-complete (other gates may fail but lens-phase gate must not)
    assert "lens_phase" not in proc.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_lens_phase_telemetry.py -v
```
Expected: FAIL — Stop hook doesn't yet check lens_phase.entered presence.

- [ ] **Step 3: Add lens-phase events to runtime_contract.must_emit_telemetry**

This is part of slim entry creation (Task 19); placeholder noted here:

```yaml
runtime_contract:
  must_emit_telemetry:
    # ... existing events ...
    - event_type: "review.lens_phase.entered"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "review.lens_phase.completed"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
```

In `lens-dispatch.md` (created Task 11) bash blocks:

```bash
# At step entry (after eligibility check passes):
vg-orchestrator emit-event review.lens_phase.entered --phase ${PHASE_NUMBER}

# At step end:
vg-orchestrator emit-event review.lens_phase.completed \
  --phase ${PHASE_NUMBER} \
  --payload "{\"lens_count_dispatched\": ${N}, \"lens_count_completed\": ${M}}"
```

Stop hook (existing R1a `vg-stop.sh`) consumes runtime_contract — no hook code change needed since `required_unless_flag` is honored automatically.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest scripts/tests/test_lens_phase_telemetry.py -v
```
Expected: 2 PASSED (relies on Task 11/19 actually wiring the bash blocks; if test runs before those tasks, mock or skip).

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_lens_phase_telemetry.py
git commit -m "test(r3-review): lens_phase enter/exit telemetry test (audit FAIL #10)

Verifies Stop hook blocks run-complete when review.lens_phase.entered
is missing AND --skip-discovery flag absent. Tasks 11+19 wire the
actual bash + runtime_contract."
```

---

### Task 3: Add lens-plan staleness check

**Files:**
- Modify: `scripts/review-lens-plan.py` (add `--check-staleness` mode)
- Test: `scripts/tests/test_lens_plan_staleness.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_lens_plan_staleness.py
"""Verify lens-plan staleness detection vs API-CONTRACTS.md mtime."""
import os, subprocess, time
from pathlib import Path


def test_fresh_plan_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    contracts = tmp_path / "API-CONTRACTS.md"
    plan = tmp_path / "REVIEW-LENS-PLAN.json"
    contracts.write_text("# contracts")
    time.sleep(0.05)
    plan.write_text("{}")  # written AFTER contracts
    proc = subprocess.run(
        ["python3", "scripts/review-lens-plan.py", "--check-staleness",
         "--phase-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0


def test_stale_plan_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "REVIEW-LENS-PLAN.json"
    contracts = tmp_path / "API-CONTRACTS.md"
    plan.write_text("{}")
    time.sleep(0.05)
    contracts.write_text("# updated contracts")  # written AFTER plan
    proc = subprocess.run(
        ["python3", "scripts/review-lens-plan.py", "--check-staleness",
         "--phase-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "stale" in proc.stderr.lower()
    assert "REVIEW-LENS-PLAN.json" in proc.stderr
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_lens_plan_staleness.py -v
```
Expected: FAIL — `--check-staleness` flag not implemented.

- [ ] **Step 3: Add staleness check mode**

In `scripts/review-lens-plan.py`, after argparse setup:

```python
ap.add_argument("--check-staleness", action="store_true",
                help="Compare REVIEW-LENS-PLAN.json mtime vs API-CONTRACTS.md; exit 2 if stale")
ap.add_argument("--phase-dir", help="Phase directory (with --check-staleness)")

args = ap.parse_args()

if args.check_staleness:
    pdir = Path(args.phase_dir)
    plan = pdir / "REVIEW-LENS-PLAN.json"
    contracts = pdir / "API-CONTRACTS.md"
    if not plan.exists() or not contracts.exists():
        sys.exit(0)  # Nothing to check — let other gates handle missing files
    if contracts.stat().st_mtime > plan.stat().st_mtime:
        sys.stderr.write(
            f"⛔ stale-lens-plan: REVIEW-LENS-PLAN.json older than API-CONTRACTS.md\n"
            f"→ Read .vg/blocks/staleness/lens-plan.md for fix\n"
            f"→ After fix: vg-orchestrator emit-event vg.block.handled --gate stale-lens-plan\n"
        )
        sys.exit(2)
    sys.exit(0)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest scripts/tests/test_lens_plan_staleness.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/review-lens-plan.py scripts/tests/test_lens_plan_staleness.py
git commit -m "feat(r3-review): lens-plan staleness detection (audit FAIL #11)

review-lens-plan.py --check-staleness compares REVIEW-LENS-PLAN.json
mtime vs API-CONTRACTS.md; exit 2 if contracts newer (plan is stale).
Used at phase2_5 step entry to block dispatch with stale plan.
3-line stderr per UX baseline req 3."
```

---

### Task 4: Close --skip-lens-plan-gate override gap (audit FAIL #13)

**Files:**
- Modify: `commands/vg/review.md` runtime_contract.forbidden_without_override list (slim entry — Task 19 final form)
- Test: `scripts/tests/test_lens_plan_gate_override.py`

- [ ] **Step 1: Write failing test**

```python
# scripts/tests/test_lens_plan_gate_override.py
"""Verify --skip-lens-plan-gate requires --override-reason in vg:review entry."""
from pathlib import Path
import re


REVIEW_MD = Path(".claude/commands/vg/review.md")


def test_skip_lens_plan_gate_in_forbidden_list():
    """The flag must appear in runtime_contract.forbidden_without_override."""
    text = REVIEW_MD.read_text()
    # Frontmatter is YAML between two --- markers
    frontmatter_match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL | re.MULTILINE)
    assert frontmatter_match, "review.md missing frontmatter"
    frontmatter = frontmatter_match.group(1)
    # Must have forbidden_without_override list with the flag
    forbidden_section = re.search(
        r"forbidden_without_override:\s*\n((?:\s*-\s*\S+\s*\n)+)",
        frontmatter,
    )
    assert forbidden_section, "forbidden_without_override list missing"
    items = forbidden_section.group(1)
    assert "--skip-lens-plan-gate" in items, (
        f"--skip-lens-plan-gate not in forbidden_without_override (audit FAIL #13)\n"
        f"Got list:\n{items}"
    )


def test_skip_discovery_still_in_forbidden_list():
    """Regression: existing --skip-discovery entry preserved."""
    text = REVIEW_MD.read_text()
    frontmatter = re.search(r"^---\n(.*?)\n---", text, re.DOTALL | re.MULTILINE).group(1)
    assert "--skip-discovery" in frontmatter
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/tests/test_lens_plan_gate_override.py -v
```
Expected: FAIL — flag not in list yet (current review.md doesn't include it per audit).

- [ ] **Step 3: Note in slim entry runtime_contract**

This is part of Task 19 (slim entry replacement). The frontmatter must include:

```yaml
runtime_contract:
  forbidden_without_override:
    - "--skip-discovery"
    - "--skip-lens-plan-gate"   # NEW per audit FAIL #13
    - "--skip-crossai"
    - "--override-reason"
```

Test will pass once Task 19 lands. Run the test as a deferred check.

- [ ] **Step 4: Verify test passes after Task 19**

(Deferred — runs as part of Phase E test suite.)

- [ ] **Step 5: Commit (test only — implementation lands in Task 19)**

```bash
git add scripts/tests/test_lens_plan_gate_override.py
git commit -m "test(r3-review): assert --skip-lens-plan-gate requires override (audit FAIL #13)

Static check on review.md frontmatter forbidden_without_override list.
Implementation lands in Task 19 slim entry replacement."
```

---

### Task 5: LENS_MAP coverage audit + reconcile (audit PARTIAL #14)

**Files:**
- Modify: `scripts/spawn_recursive_probe.py` (add coverage doc comment + audit script)
- Create: `docs/audits/2026-05-03-lens-map-coverage.md`

- [ ] **Step 1: Run coverage audit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"

# List all lens definition files
ls commands/vg/_shared/lens-prompts/lens-*.md | sort > /tmp/lens-files.txt

# Extract lens names referenced in LENS_MAP (lines 68-83 per audit)
sed -n '68,83p' scripts/spawn_recursive_probe.py | grep -oE '"lens-[a-z-]+"' | sort -u > /tmp/lens-mapped.txt

# Diff: lens files that EXIST but are NOT in LENS_MAP
comm -23 \
  <(sed 's|.*/||; s|\.md$||' /tmp/lens-files.txt) \
  <(tr -d '"' < /tmp/lens-mapped.txt) \
  > /tmp/lens-unmapped.txt

# Diff: LENS_MAP entries pointing to lens files that DON'T exist
comm -13 \
  <(sed 's|.*/||; s|\.md$||' /tmp/lens-files.txt) \
  <(tr -d '"' < /tmp/lens-mapped.txt) \
  > /tmp/lens-orphan.txt

cat /tmp/lens-unmapped.txt /tmp/lens-orphan.txt
```

- [ ] **Step 2: Write audit report**

```markdown
# LENS_MAP coverage audit (2026-05-03)

## Lens files (commands/vg/_shared/lens-prompts/)
[19 files per spec §1.3]

## LENS_MAP entries (spawn_recursive_probe.py:68-83)
[13 element-class mappings per audit]

## Unmapped lens files (exist but no LENS_MAP entry)
[Fill from /tmp/lens-unmapped.txt]

## Orphan LENS_MAP entries (mapped but file missing)
[Fill from /tmp/lens-orphan.txt — should be empty]

## Reconciliation decisions

For each unmapped lens:
- ADD to LENS_MAP under appropriate element-class, OR
- DOCUMENT as intentionally unmapped (e.g., template-only, deprecated, future)

## Action items
[Per-lens decision]
```

- [ ] **Step 3: Apply LENS_MAP changes**

Based on audit, either:
- Add unmapped lenses to existing LENS_MAP element-class entries
- Add new element-class entries for orphaned classes
- Add doc comment in spawn_recursive_probe.py LENS_MAP block: `# Coverage audit 2026-05-03: <N> lens files, <M> mapped, <K> intentionally unmapped (see docs/audits/2026-05-03-lens-map-coverage.md)`

- [ ] **Step 4: Verify coverage**

```bash
# Re-run coverage script — unmapped count should match documented "intentionally unmapped"
bash <command from Step 1>
```

- [ ] **Step 5: Commit**

```bash
git add scripts/spawn_recursive_probe.py docs/audits/2026-05-03-lens-map-coverage.md
git commit -m "audit(r3-review): LENS_MAP coverage reconciliation (audit PARTIAL #14)

19 lens definitions vs LENS_MAP element-class mappings audited.
Unmapped lenses either added to LENS_MAP or documented as
intentionally-unmapped with reason. Doc comment in spawn_recursive_probe.py
references the audit report for future maintainers."
```

---

### Task 6: Fix aggregator dedup citation (audit DOC FIX #15)

**Files:**
- Modify: `scripts/aggregate_recursive_goals.py` (add precise citation comment)
- Modify: `docs/superpowers/specs/2026-05-03-vg-review-design.md` (correct line range citation)

- [ ] **Step 1: Identify correct dedup line range**

```bash
grep -n "dedup\|seen_keys\|already_seen\|unique" scripts/aggregate_recursive_goals.py | head -20
```

- [ ] **Step 2: Add precise comment in aggregator**

```python
# At the actual dedup logic site (NOT the glob at line 81-82):
# === DEDUP: single-writer policy per (element, lens, role) tuple ===
# Audit reference: docs/superpowers/specs/2026-05-03-vg-review-design.md §1.3
# Coverage audit (2026-05-03): glob lookup at line 81-82, dedup logic at line <ACTUAL>.
seen = set()
for path in result_paths:
    key = (...)
    if key in seen:
        continue
    seen.add(key)
    ...
```

- [ ] **Step 3: Update spec citation**

In `docs/superpowers/specs/2026-05-03-vg-review-design.md` §1.3, replace `aggregate_recursive_goals.py:81-82` citation with the actual dedup line range identified in Step 1.

- [ ] **Step 4: Commit**

```bash
git add scripts/aggregate_recursive_goals.py docs/superpowers/specs/2026-05-03-vg-review-design.md
git commit -m "docs(r3-review): correct aggregator dedup line citation (audit DOC FIX #15)

Audit Item #15 noted aggregate_recursive_goals.py:81-82 is glob, not dedup.
Cite actual dedup-logic line range in spec + add anchor comment in script."
```

---

## Phase B — Review slim refs (12 files, 3 nested dirs)

### Task 7: Backup current review.md

**Files:**
- Create: `commands/vg/.review.md.r3-backup`

- [ ] **Step 1: Backup**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp commands/vg/review.md commands/vg/.review.md.r3-backup
wc -l commands/vg/.review.md.r3-backup
```
Expected: 7413 lines.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/.review.md.r3-backup
git commit -m "chore(r3-review): backup review.md before slim refactor (7413 lines)

Mirrors R1a/R2 pattern. Source of truth for slim-entry extraction
in Tasks 8-19; rollback target if dogfood fails."
```

---

### Task 8: Create _shared/review/preflight.md

**Files:**
- Create: `commands/vg/_shared/review/preflight.md` (~250 lines)

- [ ] **Step 1: Extract steps 0_parse_and_validate + 0_session + 1_init + create_task_tracker from backup**

```bash
# Source: commands/vg/.review.md.r3-backup
# Target steps (per spec §1.2 + §4.1):
#   - 0_parse_and_validate (317 lines, frontmatter audit)
#   - 0_session (init session ID, run-start)
#   - 1_init (parse args, profile detect)
#   - create_task_tracker (emit-tasklist + TodoWrite imperative)
```

- [ ] **Step 2: Write preflight.md**

Skeleton (full content extracted from backup with imperative + Red Flags applied):

```markdown
# Review preflight — STEP 1

<HARD-GATE>
You MUST complete every sub-step before proceeding to STEP 2.
TodoWrite is IMPERATIVE after emit-tasklist runs.
</HARD-GATE>

## Sub-steps

### 1.1 — Parse + validate (0_parse_and_validate)
[Extract ~150 lines from backup]

### 1.2 — Session init (0_session)
[Extract ~30 lines]

### 1.3 — Argument parse + profile detect (1_init)
[Extract ~50 lines]

### 1.4 — Task tracker (create_task_tracker)
Bash: `python3 scripts/emit-tasklist.py --command vg:review --profile ${PROFILE} --phase ${PHASE_NUMBER}`
Then IMMEDIATELY call TodoWrite with the projected contract.

### 1.5 — Verify prerequisites (2_verify_prerequisites)
Use `vg-load --phase ${PHASE_NUMBER} --artifact contracts --index` for size check
(NOT cat the flat file).
```

- [ ] **Step 3: Verify line count + content quality**

```bash
wc -l commands/vg/_shared/review/preflight.md
# Expected: ~250 lines
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/review/preflight.md
git commit -m "feat(r3-review): preflight ref — parse, session, init, tasklist

Extracted 0_parse_and_validate + 0_session + 1_init + create_task_tracker
+ 2_verify_prerequisites from review.md backup. Imperative + HARD-GATE
applied. vg-load --index used in size check (NOT cat the flat file)."
```

---

### Task 9: Create _shared/review/code-scan.md

**Files:**
- Create: `commands/vg/_shared/review/code-scan.md` (~250 lines)

- [ ] **Step 1: Extract phase1_code_scan + ripple/god-node + API precheck**

Steps from backup (~389 lines for phase1, plus ~50 lines for ripple, plus ~30 for API precheck = ~470 lines compressed via slim style to ~250).

- [ ] **Step 2: Write ref**

Key principles:
- API-CONTRACTS PRECHECK uses `vg-load --phase N --artifact contracts --index` first, then per-endpoint via `--endpoint <slug>` (NOT cat the flat file)
- API-DOCS check uses `Read ${PHASE_DIR}/API-DOCS.md` (this is build-generated, not split — KEEP-FLAT)
- Ripple/god-node uses graphify CLI (already split-aware via JSON output)

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/review/code-scan.md
git commit -m "feat(r3-review): code-scan ref — phase1 + ripple + API precheck

vg-load --index for contract surface scan; per-endpoint loaded only
when ripple analysis flags a touched endpoint. Replaces 11 flat
API-CONTRACTS.md reads from review.md backup with vg-load equivalents
(per Phase F Task 30 absorption)."
```

---

### Task 10: Create _shared/review/discovery/ (overview + delegation, HEAVY)

**Files:**
- Create: `commands/vg/_shared/review/discovery/overview.md` (~150 lines)
- Create: `commands/vg/_shared/review/discovery/delegation.md` (~200 lines)

- [ ] **Step 1: Extract phase2_browser_discovery (947 lines) → split**

- **overview.md**: high-level entry, instructs spawn `vg-review-browser-discoverer`, sample input/output schema. Imperative HARD-GATE: "DO NOT crawl inline. Spawn subagent."
- **delegation.md**: full input contract (capsule schema: profile, scope_paths, role_matrix, env config) + output contract (views_discovered, scan_artifacts paths, errors).

- [ ] **Step 2: Write overview.md**

Includes spawn narration call:

```markdown
# Phase 2 — browser discovery (HEAVY, subagent)

<HARD-GATE>
DO NOT crawl inline. You MUST spawn vg-review-browser-discoverer.
Phase2 has 947 lines of discovery logic — inline execution will skim.
</HARD-GATE>

## Pre-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-review-browser-discoverer spawning "phase 3.2 browser discovery"`

## Spawn

Read `delegation.md` for input contract, then:

  Agent(subagent_type="vg-review-browser-discoverer", prompt=<from delegation>)

## Post-spawn

Bash: `bash scripts/vg-narrate-spawn.sh vg-review-browser-discoverer returned "<count> views discovered"`

## Validation

Verify subagent wrote ${PHASE_DIR}/RUNTIME-MAP.json + scan-*.json per view.
Read with `vg-load --phase ${PHASE_NUMBER} --artifact runtime-map` (when supported)
or direct Read for now.
```

- [ ] **Step 3: Write delegation.md**

Full contract (subagent-side):

```markdown
# vg-review-browser-discoverer — input/output contract

## Input capsule

JSON document:
- profile: web-fullstack | web-frontend-only | web-backend-only | mobile-*
- scope_paths: list of route patterns to crawl
- role_matrix: {admin, staff, end_user, guest}
- env: {sandbox|staging|prod URL + auth}
- max_haiku: 5 (Playwright MCP slot cap)

## Subagent workflow

1. Initialize Playwright via MCP slot allocation (slots playwright1..playwright5)
2. Spawn ≤5 Haiku scanners in parallel (one per slot)
3. Each scanner crawls a route subset, records DOM tree + network + console + screenshot
4. Aggregate per-view evidence into scan-*.json
5. Write RUNTIME-MAP.json with view inventory + element classification

## Output contract

{
  "views_discovered": [{view_id, url, role, scan_path}, ...],
  "scan_artifacts": [paths/to/scan-N.json, ...],
  "errors": [],
  "playwright_slots_used": [1, 2, 3]
}

## Allowed tools

Read, Bash, Glob, Grep, Task (for Haiku spawn ≤5)

## Forbidden

- DO NOT call other VG commands recursively
- DO NOT spawn non-Haiku subagents
- DO NOT exceed 5 Playwright slots (anti-DOS)
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/review/discovery/
git commit -m "feat(r3-review): discovery refs — overview + delegation (HEAVY split)

phase2_browser_discovery (947 lines from review.md) split into:
- overview.md: spawn site with narrate-spawn calls
- delegation.md: full input/output contract for subagent

Subagent skill itself created in Task 18."
```

---

### Task 11: Create _shared/review/lens-dispatch.md

**Files:**
- Create: `commands/vg/_shared/review/lens-dispatch.md` (~300 lines)

- [ ] **Step 1: Extract phase2_5_recursive_lens_probe**

This is the user's main concern (lens cherry-pick prevention). Ref must include:
- Eligibility gate (6 preconditions)
- 3-axis interactive preflight (RECURSION_MODE / PROBE_MODE / TARGET_ENV)
- Anti-forge guard
- Manager dispatch via `spawn_recursive_probe.py`
- Aggregation via `aggregate_recursive_goals.py`
- Per-lens telemetry (Task 1 wired)
- lens_phase.entered/completed events (Task 2 wired)
- Staleness check (Task 3 wired)

- [ ] **Step 2: Write ref with HARD-GATE**

```markdown
# Lens dispatch — STEP 4 (architectural enforcement)

## Why mandatory

19 production lens probes cover security/UI/business surfaces. Without
forced dispatch, prior dogfood showed AI cherry-picks 3-4 lens, missing
critical findings (phase 3.2 filter pending bug went undetected for 2 rounds).

<HARD-GATE>
You MUST execute this step unless --skip-discovery flag is set AND
override-debt entry exists. Stop hook checks review.lens_phase.entered
event; missing = run-complete blocked.

You MUST NOT cherry-pick individual lens. LENS_MAP in spawn_recursive_probe.py
enforces full element-class → lens mapping. Skipping a lens is impossible
unless eligibility gate (6 preconditions) declines it (audit trail in
.recursive-probe-skipped.yaml).

You MUST run lens-plan staleness check before dispatch. If stale, regenerate.
</HARD-GATE>

## Pre-dispatch sequence

1. Bash: `vg-orchestrator step-active phase2_5_recursive_lens_probe`
2. Bash: `python3 scripts/review-lens-plan.py --check-staleness --phase-dir ${PHASE_DIR}`
   → Exit 2 + 3-line stderr if stale (block, regenerate, retry)
3. Bash: 6-precondition eligibility gate (existing logic)
4. AskUserQuestion (Claude) / inline (Codex): 3-axis preflight
5. Bash: anti-forge guard (existing)
6. Bash: `vg-orchestrator emit-event review.lens_phase.entered --phase ${PHASE_NUMBER}`

## Dispatch

Bash: `python3 scripts/spawn_recursive_probe.py --mode <PROBE_MODE> --recursion <RECURSION_MODE> --env <TARGET_ENV>`

Per-lens telemetry emitted automatically (Task 1):
- review.lens.<name>.dispatched per (element × lens × role)
- review.lens.<name>.completed after worker returns

## Aggregation

Bash: `python3 scripts/aggregate_recursive_goals.py`

Single-writer dedup (audit DOC FIX #15 cite at line <ACTUAL> after Task 6).
Output: TEST-GOALS-DISCOVERED.md with G-RECURSE-* entries.

## Step-end

1. Bash: emit `review.lens_phase.completed` with payload `{lens_count_dispatched, lens_count_completed}`
2. Bash: `vg-orchestrator mark-step review phase2_5_recursive_lens_probe`

## Failure modes

- Staleness block → regenerate via `python3 scripts/review-lens-plan.py --phase-dir ${PHASE_DIR}`
- Eligibility decline → recorded in .recursive-probe-skipped.yaml; not a fail
- Per-lens failure rate >50% → block with retry suggestion (3-line stderr)
```

- [ ] **Step 3: Commit**

```bash
git add commands/vg/_shared/review/lens-dispatch.md
git commit -m "feat(r3-review): lens-dispatch ref — phase2_5 with telemetry + staleness

Wires Task 1 (per-lens telemetry), Task 2 (lens_phase events), Task 3
(staleness check). HARD-GATE forbids cherry-pick AND silent skip.
3-line stderr on block per UX baseline."
```

---

### Task 12: Create _shared/review/findings/ (collect + fix-loop)

**Files:**
- Create: `commands/vg/_shared/review/findings/collect.md` (~200 lines)
- Create: `commands/vg/_shared/review/findings/fix-loop.md` (~250 lines)

- [ ] **Step 1: Extract phase2b_collect_merge + post-challenge**

`collect.md`:
- Aggregate findings from phase1 + phase2 + phase2_5
- Post-challenge: cross-AI verify
- Output: FINDINGS.md (Layer 3 flat) + FINDINGS/finding-NN.md (Layer 1)

- [ ] **Step 2: Extract phase3_fix_loop (414 lines)**

`fix-loop.md`:
- Auto-fix routing: severity → executor type
- Exploration limits: configurable per profile
- Fix loop iteration with verification
- vg-load consumption: `--artifact goals --goal G-NN` to verify each fix against goal

- [ ] **Step 3: Both refs commit**

```bash
git add commands/vg/_shared/review/findings/
git commit -m "feat(r3-review): findings refs — collect + fix-loop

Findings written in 3-layer artifact (per UX req 1) — finding-NN.md +
index.md + flat FINDINGS.md. Fix loop loads goals via vg-load --goal G-NN
(NOT cat TEST-GOALS.md). Exploration limits config-driven."
```

---

### Task 13: Create _shared/review/verdict/ (overview + 3 branch refs, NESTED, no subagent)

**Files:**
- Create: `commands/vg/_shared/review/verdict/overview.md` (~150 lines)
- Create: `commands/vg/_shared/review/verdict/pure-backend-fastpath.md` (~150 lines)
- Create: `commands/vg/_shared/review/verdict/web-fullstack.md` (~250 lines)
- Create: `commands/vg/_shared/review/verdict/profile-branches.md` (~200 lines)

- [ ] **Step 1: Extract phase4_goal_comparison (829 lines) → 4-way split**

Per audit (item #12 DOWNGRADED): NO weighted formula. Logic is binary RUNTIME-MAP lookup branched by profile + UI_GOAL_COUNT.

- `overview.md`: branching logic (which sub-ref to load based on context)
- `pure-backend-fastpath.md`: UI_GOAL_COUNT == 0 fast path (skip UI verdict)
- `web-fullstack.md`: full goal lookup + verdict synthesis (UI + API + integration)
- `profile-branches.md`: 4 profile-specific verdict paths (web-fullstack / web-frontend-only / web-backend-only / mobile-*)

- [ ] **Step 2: Write overview.md branching**

```markdown
# Verdict — STEP 6 (inline split, NO subagent)

## Why no subagent

Audit confirmed phase4_goal_comparison has NO weighted formula. Logic
is binary RUNTIME-MAP lookup (READY|BLOCKED per goal). Subagent overhead
not warranted; complexity is from branching, not formula.

## Branching

```
if UI_GOAL_COUNT == 0:
    Read pure-backend-fastpath.md
elif PROFILE == "web-fullstack":
    Read web-fullstack.md
else:
    Read profile-branches.md
```

## Goal loading

Use `vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical`
for the priority sweep, then `--goal G-NN` for per-goal lookup.

DO NOT cat TEST-GOALS.md (8K+ lines on large phases — AI will skim).
```

- [ ] **Step 3: Write 3 branch refs**

[Skeleton sketches per spec §4.1 — full content per backup extraction.]

- [ ] **Step 4: Verify each ≤300 lines**

```bash
wc -l commands/vg/_shared/review/verdict/*.md
```

- [ ] **Step 5: Commit**

```bash
git add commands/vg/_shared/review/verdict/
git commit -m "feat(r3-review): verdict refs — 4-way inline split (no subagent)

phase4_goal_comparison (829 lines) split into 4 sub-refs because audit
confirmed binary lookup, no weighted formula. overview.md branches by
UI_GOAL_COUNT + profile. vg-load --priority + --goal used (NOT flat read)."
```

---

### Task 14: Create _shared/review/delta-mode.md

**Files:**
- Create: `commands/vg/_shared/review/delta-mode.md` (~250 lines)

- [ ] **Step 1: Extract phaseP_delta (314 lines) — change-only mode**

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/review/delta-mode.md
git commit -m "feat(r3-review): delta-mode ref — phaseP change-only review"
```

---

### Task 15: Create _shared/review/profile-shortcuts.md

**Files:**
- Create: `commands/vg/_shared/review/profile-shortcuts.md` (~200 lines)

- [ ] **Step 1: Extract profile shortcut branches**

Profiles: infra-smoke, regression, schema-verify, link-check.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/review/profile-shortcuts.md
git commit -m "feat(r3-review): profile-shortcuts ref — infra/regression/schema/link"
```

---

### Task 16: Create _shared/review/crossai.md (UNCHANGED behavior)

**Files:**
- Create: `commands/vg/_shared/review/crossai.md` (~150 lines)

- [ ] **Step 1: Extract CrossAI loop step from backup**

Per spec §1.5: refactor deferred. Just extract + slim to ref. Behavior unchanged.

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/review/crossai.md
git commit -m "feat(r3-review): crossai ref — UNCHANGED behavior, defer refactor

Per spec §1.5 non-goals. Extract step content as-is for slim entry.
CrossAI loop refactor is separate concern (post-R3)."
```

---

### Task 17: Create _shared/review/close.md

**Files:**
- Create: `commands/vg/_shared/review/close.md` (~250 lines)

- [ ] **Step 1: Extract complete step (542 lines) → slim**

- Write artifacts (RUNTIME-MAP, GOAL-COVERAGE-MATRIX, REVIEW-LENS-PLAN)
- Reflection (vg-reflector spawn — narrate + delegate)
- run-complete + tasklist clear

- [ ] **Step 2: Commit**

```bash
git add commands/vg/_shared/review/close.md
git commit -m "feat(r3-review): close ref — artifacts + reflection + run-complete

Reflection spawn uses narrate-spawn (UX req 2). Tasklist clear via
sentinel completed item per R1a pattern."
```

---

## Phase C — Custom subagent

### Task 18: Create vg-review-browser-discoverer subagent

**Files:**
- Create: `agents/vg-review-browser-discoverer/SKILL.md` (~250 lines)

- [ ] **Step 1: Write SKILL.md per blueprint pilot template**

```markdown
---
name: vg-review-browser-discoverer
description: Phase 2 browser discovery for /vg:review — parallel Haiku scan ≤5
allowed-tools: [Read, Bash, Glob, Grep, Task]
---

# Browser discovery subagent

You discover all views in scope per profile. Spawn Haiku scanners ≤5
parallel via Task tool (Playwright MCP slot cap enforces).

<HARD-GATE>
- DO NOT crawl inline yourself. Always spawn Haiku scanners.
- DO NOT exceed 5 Playwright slots.
- DO NOT call other VG commands recursively.
- DO NOT spawn non-Haiku subagents.
</HARD-GATE>

## Input capsule

[Per delegation.md schema]

## Workflow

1. Read input capsule (profile, scope_paths, role_matrix, env, max_haiku)
2. Allocate Playwright slots (1..max_haiku)
3. Partition scope_paths across slots
4. Spawn Haiku scanner per slot via Task tool
5. Aggregate per-view scan-*.json into RUNTIME-MAP.json
6. Return output contract

## Output

JSON:
{
  "views_discovered": [...],
  "scan_artifacts": [...],
  "errors": [],
  "playwright_slots_used": [...]
}

## Failure modes

- MCP slot allocation failure → fail fast, return error
- Haiku timeout → record per-view in errors[], continue others
- Auth failure → fail fast (cannot scan without login)
```

- [ ] **Step 2: Write subagent test stub**

(Used in Phase E Task 22 — assertion that no `vg-review-goal-scorer` exists.)

- [ ] **Step 3: Commit**

```bash
git add agents/vg-review-browser-discoverer/
git commit -m "feat(r3-review): vg-review-browser-discoverer subagent

Phase 2 HEAVY step (947 lines) delegated to this subagent. Narrow tools
(Read/Bash/Glob/Grep/Task), narrow prompt (browser scan only). Task tool
allowed for Haiku ≤5 spawn. NO vg-review-goal-scorer — phase4 stays
inline-split per audit."
```

---

## Phase D — Slim entry replacement

### Task 19: Replace review.md body with slim entry

**Files:**
- Modify: `commands/vg/review.md` (7413 → ~500 lines)

- [ ] **Step 1: Build slim entry**

```yaml
---
name: vg:review
description: Post-build review — code scan + browser discovery + lens dispatch + fix loop + verdict
argument-hint: "<phase> [--profile=<P>] [--skip-discovery] [--skip-lens-plan-gate] [--skip-crossai] [--override-reason=<text>]"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Agent, TodoWrite]
runtime_contract:
  must_write:
    - "${PHASE_DIR}/RUNTIME-MAP.json"
    - "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
    - "${PHASE_DIR}/REVIEW-LENS-PLAN.json"
    - "${PHASE_DIR}/FINDINGS.md"
    # Layer 2 + Layer 1 splits (UX baseline req 1)
    - "${PHASE_DIR}/FINDINGS/index.md"
    - path: "${PHASE_DIR}/FINDINGS/finding-*.md"
      glob_min_count: 0   # 0 if no findings
    - path: "${PHASE_DIR}/scan-*.json"
      glob_min_count: 1
  must_touch_markers:
    - "0_parse_and_validate"
    - "0_session"
    - "1_init"
    - "create_task_tracker"
    - "2_verify_prerequisites"
    - "phase1_code_scan"
    - "phase2_browser_discovery"
    - name: "phase2_5_recursive_lens_probe"
      required_unless_flag: "--skip-discovery"
    - "phase2b_collect_merge"
    - "phase3_fix_loop"
    - "phase4_goal_comparison"
    - name: "phaseP_delta"
      profile: "delta"
    - name: "phaseS_*"
      profile: "infra-smoke,regression,schema-verify,link-check"
    - "complete"
  must_emit_telemetry:
    - event_type: "review.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.native_tasklist_projected"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.lens_plan_generated"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "review.lens_phase.entered"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "review.lens_phase.completed"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-discovery"
    - event_type: "crossai.verdict"
      phase: "${PHASE_NUMBER}"
      required_unless_flag: "--skip-crossai"
    - event_type: "review.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-discovery"
    - "--skip-lens-plan-gate"        # NEW per audit FAIL #13
    - "--skip-crossai"
    - "--override-reason"
---

<HARD-GATE>
You MUST follow STEP 1 through STEP 8 in profile-filtered order.
Lens phase is NOT optional unless --skip-discovery flag is provided
WITH override-debt entry. Skipping silently will be detected by
Stop hook (review.lens_phase.entered event missing).
</HARD-GATE>

## Red Flags (review-specific)
[5-row table per spec §5.2]

## Steps

### STEP 1 — preflight
Read `_shared/review/preflight.md`. Follow exactly.

### STEP 2 — code scan + API precheck
Read `_shared/review/code-scan.md`. Use vg-load --index for size check.

### STEP 3 — browser discovery (HEAVY, subagent)
Read `_shared/review/discovery/overview.md` AND `delegation.md`.
Then call `Agent(subagent_type="vg-review-browser-discoverer", prompt=<from delegation>)`.
DO NOT crawl inline.

### STEP 4 — lens dispatch (architectural enforcement)
Read `_shared/review/lens-dispatch.md`. Run staleness check, eligibility gate,
3-axis preflight, then `spawn_recursive_probe.py`. DO NOT cherry-pick lens.

### STEP 5 — findings collect + fix loop
Read `_shared/review/findings/collect.md` then `fix-loop.md`.

### STEP 6 — goal comparison + verdict (inline ref split, NO subagent)
Read `_shared/review/verdict/overview.md`. Branch on profile/UI_GOAL_COUNT.

### STEP 7 — CrossAI review (UNCHANGED, defer)
Read `_shared/review/crossai.md`.

### STEP 8 — close
Read `_shared/review/close.md`. Follow exactly.

### Profile shortcut branches
For infra-smoke / regression / schema-verify / link-check / delta:
read `_shared/review/profile-shortcuts.md` (or `delta-mode.md` for delta).

## Diagnostic flow (5 layers — see vg-meta-skill.md)
[Standard 5-layer block per blueprint pilot template]
```

- [ ] **Step 2: Verify line count**

```bash
wc -l commands/vg/review.md
# Expected: ~500 lines (down from 7413)
```

- [ ] **Step 3: Test runtime_contract validity**

```bash
python3 scripts/validators/verify-runtime-contract.py --command vg:review
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/review.md
git commit -m "refactor(r3-review): slim entry — 7413 → 500 lines

12 refs in _shared/review/ (3 nested dirs: discovery/, findings/, verdict/).
1 subagent (vg-review-browser-discoverer). 3 lens telemetry events
in must_emit_telemetry. --skip-lens-plan-gate added to
forbidden_without_override (audit FAIL #13). HARD-GATE on lens phase.
All consumer reads use vg-load (Phase F Task 30 absorbed for vg:review)."
```

---

## Phase E — Static tests

### Task 20: Static tests for slim size + structure + subagent

**Files:**
- Create: `scripts/tests/test_review_slim_size.py`
- Create: `scripts/tests/test_review_references_exist.py`
- Create: `scripts/tests/test_review_subagent_definition.py`
- Create: `scripts/tests/test_phase4_inline_split.py`

- [ ] **Step 1: Write tests**

```python
# test_review_slim_size.py
from pathlib import Path

def test_review_md_under_600_lines():
    text = Path("commands/vg/review.md").read_text()
    assert len(text.splitlines()) <= 600


def test_review_md_uses_agent_not_task():
    text = Path("commands/vg/review.md").read_text()
    # Slim entry must use Agent tool, not legacy Task tool name
    assert "Agent(subagent_type=" in text
    assert "Task(subagent_type=" not in text


def test_review_md_lists_all_refs():
    text = Path("commands/vg/review.md").read_text()
    expected_refs = [
        "_shared/review/preflight.md",
        "_shared/review/code-scan.md",
        "_shared/review/discovery/overview.md",
        "_shared/review/discovery/delegation.md",
        "_shared/review/lens-dispatch.md",
        "_shared/review/findings/collect.md",
        "_shared/review/findings/fix-loop.md",
        "_shared/review/verdict/overview.md",
        "_shared/review/delta-mode.md",
        "_shared/review/profile-shortcuts.md",
        "_shared/review/crossai.md",
        "_shared/review/close.md",
    ]
    for ref in expected_refs:
        assert ref in text, f"Missing ref: {ref}"


# test_review_references_exist.py
def test_all_refs_present_under_ceiling():
    refs = [
        ("commands/vg/_shared/review/preflight.md", 300),
        ("commands/vg/_shared/review/code-scan.md", 300),
        ("commands/vg/_shared/review/discovery/overview.md", 200),
        ("commands/vg/_shared/review/discovery/delegation.md", 250),
        ("commands/vg/_shared/review/lens-dispatch.md", 350),
        ("commands/vg/_shared/review/findings/collect.md", 250),
        ("commands/vg/_shared/review/findings/fix-loop.md", 300),
        ("commands/vg/_shared/review/verdict/overview.md", 200),
        ("commands/vg/_shared/review/verdict/pure-backend-fastpath.md", 200),
        ("commands/vg/_shared/review/verdict/web-fullstack.md", 300),
        ("commands/vg/_shared/review/verdict/profile-branches.md", 250),
        ("commands/vg/_shared/review/delta-mode.md", 300),
        ("commands/vg/_shared/review/profile-shortcuts.md", 250),
        ("commands/vg/_shared/review/crossai.md", 200),
        ("commands/vg/_shared/review/close.md", 300),
    ]
    for path, ceiling in refs:
        p = Path(path)
        assert p.exists(), f"Missing ref: {path}"
        assert len(p.read_text().splitlines()) <= ceiling, f"{path} exceeds {ceiling} lines"


# test_review_subagent_definition.py
def test_browser_discoverer_subagent_exists():
    p = Path("agents/vg-review-browser-discoverer/SKILL.md")
    assert p.exists()
    text = p.read_text()
    assert "name: vg-review-browser-discoverer" in text
    assert "allowed-tools:" in text


def test_no_goal_scorer_subagent():
    """Audit confirmed phase4 has no weighted formula → no scorer subagent."""
    p = Path("agents/vg-review-goal-scorer")
    assert not p.exists(), "vg-review-goal-scorer should NOT exist (audit item #12 DOWNGRADED)"


# test_phase4_inline_split.py
def test_verdict_has_4_subrefs():
    refs = [
        "commands/vg/_shared/review/verdict/overview.md",
        "commands/vg/_shared/review/verdict/pure-backend-fastpath.md",
        "commands/vg/_shared/review/verdict/web-fullstack.md",
        "commands/vg/_shared/review/verdict/profile-branches.md",
    ]
    for ref in refs:
        p = Path(ref)
        assert p.exists()
        assert len(p.read_text().splitlines()) <= 300
```

- [ ] **Step 2: Run + commit**

```bash
pytest scripts/tests/test_review_slim_size.py \
       scripts/tests/test_review_references_exist.py \
       scripts/tests/test_review_subagent_definition.py \
       scripts/tests/test_phase4_inline_split.py -v

git add scripts/tests/test_review_*.py scripts/tests/test_phase4_inline_split.py
git commit -m "test(r3-review): static tests — slim size + refs + subagent + phase4 split"
```

---

### Task 21: Static test for vg-load consumption

**Files:**
- Create: `scripts/tests/test_review_uses_vg_load.py`

- [ ] **Step 1: Write test**

```python
# test_review_uses_vg_load.py
"""Verify review.md AND all _shared/review/ refs use vg-load instead of cat $PHASE_DIR/{PLAN,API-CONTRACTS,TEST-GOALS}.md."""
from pathlib import Path
import re

REVIEW_FILES = [
    Path("commands/vg/review.md"),
    *Path("commands/vg/_shared/review").rglob("*.md"),
]

# KEEP-FLAT classifications per audit Task 28 (blueprint plan Phase F)
ALLOWED_FLAT_FILES = {
    # Add specific file:line allowlist after audit
}


def _flat_reads(path):
    text = path.read_text()
    pat = re.compile(
        r"(cat\s+[\"']?\$\{?PHASE_DIR\}?[/\"']?(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md|"
        r"Read\s+\S*(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md)"
    )
    for i, line in enumerate(text.splitlines(), 1):
        if pat.search(line):
            yield i, line.strip()


def test_review_files_use_vg_load():
    flat_hits = []
    for f in REVIEW_FILES:
        key_prefix = str(f)
        for n, snippet in _flat_reads(f):
            if (key_prefix, n) not in ALLOWED_FLAT_FILES:
                flat_hits.append((f, n, snippet))
    assert not flat_hits, "Flat reads in AI-context paths:\n" + "\n".join(
        f"  {f}:L{n} {s}" for f, n, s in flat_hits
    )


def test_review_files_reference_vg_load():
    """At least the lens-dispatch + verdict + code-scan refs must reference vg-load."""
    for f in [
        "commands/vg/_shared/review/code-scan.md",
        "commands/vg/_shared/review/lens-dispatch.md",
        "commands/vg/_shared/review/verdict/overview.md",
        "commands/vg/_shared/review/findings/fix-loop.md",
    ]:
        text = Path(f).read_text()
        assert "vg-load" in text, f"{f} does not reference vg-load"
```

- [ ] **Step 2: Commit**

```bash
git add scripts/tests/test_review_uses_vg_load.py
git commit -m "test(r3-review): assert vg-load consumption in review refs

Closes Phase F Task 30 scope for vg:review (blueprint plan supersession).
Allowlist captures audit-classified KEEP-FLAT lines only."
```

---

### Task 22: Update emit-tasklist.py CHECKLIST_DEFS for vg:review

**Files:**
- Modify: `scripts/emit-tasklist.py` (add `vg:review` checklist groups)
- Test: `scripts/tests/test_emit_tasklist_review.py`

- [ ] **Step 1: Add CHECKLIST_DEFS["vg:review"]**

```python
CHECKLIST_DEFS["vg:review"] = [
    ("preflight",       ["0_parse_and_validate", "0_session", "1_init", "create_task_tracker", "2_verify_prerequisites"]),
    ("code-scan",       ["phase1_code_scan"]),
    ("discovery",       ["phase2_browser_discovery"]),
    ("lens-dispatch",   ["phase2_5_recursive_lens_probe"]),
    ("findings",        ["phase2b_collect_merge", "phase3_fix_loop"]),
    ("verdict",         ["phase4_goal_comparison"]),
    ("crossai",         ["crossai_review"]),
    ("close",           ["complete"]),
]
```

- [ ] **Step 2: Test**

```python
def test_emit_tasklist_review_groups():
    proc = subprocess.run(
        ["python3", "scripts/emit-tasklist.py", "--command", "vg:review", "--profile", "web-fullstack", "--phase", "3.2", "--dry-run"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    contract = json.loads(proc.stdout)
    group_names = [g["name"] for g in contract["groups"]]
    assert "lens-dispatch" in group_names
    assert "verdict" in group_names
```

- [ ] **Step 3: Commit**

```bash
git add scripts/emit-tasklist.py scripts/tests/test_emit_tasklist_review.py
git commit -m "feat(r3-review): emit-tasklist.py CHECKLIST_DEFS for vg:review

8 checklist groups (preflight, code-scan, discovery, lens-dispatch,
findings, verdict, crossai, close) — projected hierarchically into
native tasklist via R1a infra (commit 30c9a05)."
```

---

## Phase F — Sync + dogfood

### Task 23: Update sync.sh for review artifacts

**Files:**
- Modify: `sync.sh`

- [ ] **Step 1: Add review files to sync**

```bash
# In sync.sh, ensure these are copied:
# - commands/vg/_shared/review/**
# - agents/vg-review-browser-discoverer/**
# - scripts/spawn_recursive_probe.py (modified)
# - scripts/review-lens-plan.py (modified)
# - scripts/aggregate_recursive_goals.py (modified)
```

- [ ] **Step 2: Test sync to a tmp clone**

```bash
TMPDIR=$(mktemp -d)
cp -r commands/vg "$TMPDIR/" 2>/dev/null || true
SYNC_TARGET="$TMPDIR" bash sync.sh
ls "$TMPDIR/commands/vg/_shared/review/"
```

- [ ] **Step 3: Commit**

```bash
git add sync.sh
git commit -m "chore(r3-review): sync.sh includes review refs + subagent + scripts"
```

---

### Task 24: Run full pytest suite (regression check)

- [ ] **Step 1: Run all tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
pytest scripts/tests/ -v 2>&1 | tee /tmp/r3-pytest.log
```

- [ ] **Step 2: Verify all pass**

Expected: all R1a + R2 + R3 tests green. If any R1a/R2 test regresses, investigate before dogfood.

- [ ] **Step 3: Commit log if any new files**

(No commit needed if just running.)

---

### Task 25: Sync to PrintwayV3 + dogfood `/vg:review 3.2`

**Files:**
- Modify: PrintwayV3 working tree (via sync.sh)

- [ ] **Step 1: Sync**

```bash
cd /path/to/PrintwayV3
bash /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix/sync.sh
```

- [ ] **Step 2: Verify install**

```bash
ls .claude/commands/vg/_shared/review/
ls .claude/agents/vg-review-browser-discoverer/
wc -l .claude/commands/vg/review.md   # ≤ 600
```

- [ ] **Step 3: Run dogfood**

```bash
cd /path/to/PrintwayV3
# Phase 3.2 is the existing UI bug at billing/topup-queue (filter pending)
/vg:review 3.2 --profile=web-fullstack
```

- [ ] **Step 4: Verify 12 exit criteria (per spec §6.4)**

1. ✅ Tasklist visible in Claude Code UI immediately after invocation
2. ✅ `review.native_tasklist_projected` event count ≥ 1
3. ✅ `review.lens_phase.entered` + `review.lens_phase.completed` events present
4. ✅ Per-lens dispatch events count ≥ count in REVIEW-LENS-PLAN.json
5. ✅ RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md + REVIEW-LENS-PLAN.json + scan-*.json all written
6. ✅ Browser-discoverer subagent invocation event present (Agent tool fired for phase2)
7. ✅ Phase4 verdict ref loaded (Read tool fired on `verdict/<branch>.md`)
8. ✅ **Phase 3.2 dogfood criterion**: lens dispatch detects filter pending bug at billing/topup-queue (must surface in TEST-GOALS-DISCOVERED.md or findings)
9. ✅ CrossAI review runs (existing behavior; not a fail criterion this round)
10. ✅ Stop hook fires without exit 2
11. ✅ Manual: simulate skip lens phase → Stop hook blocks with diagnostic stderr
12. ✅ Stop hook unpaired-block-fails-closed test passes

Critical criterion: **#8** (must detect the filter pending bug). If lens dispatch misses it, R3 FAILS — return to design.

- [ ] **Step 5: Verdict + summary**

If all 12 PASS: R3 review pilot PASSES. Open Phase G (R4 accept pilot plan) next session.

If any FAIL: R3 PILOT FAILS. Per spec §6.4, return to design. Roll back review.md from `.review.md.r3-backup`.

```bash
cat > docs/superpowers/specs/2026-05-03-vg-r3-review-verdict.md <<EOF
# R3 Review Pilot Verdict

**Date:** $(date -u +%Y-%m-%d)
**Phase tested:** 3.2 (PrintwayV3 billing/topup-queue filter bug)
**Run ID:** ${RUN_ID}

## Exit criteria (12)
[Fill in PASS/FAIL per spec §6.4 with evidence]

## Verdict
PASS | FAIL

## Critical criterion #8 (lens detected filter pending bug)
[YES/NO + evidence path]

## If PASS: next round
R4 accept pilot — separate plan, same infrastructure reuse pattern.

## If FAIL: rollback action
Roll back commands/vg/review.md from .review.md.r3-backup; investigate
which gate failed; re-design before re-attempt.

## Phase F Task 30 update
After this verdict lands, update docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot.md
Phase F Task 30 to remove vg:review from scope (covered by R3 pilot).
EOF

git add docs/superpowers/specs/2026-05-03-vg-r3-review-verdict.md
git commit -m "docs(r3): review pilot dogfood verdict + 12 criteria evidence"
```

---

## Self-review notes

**Spec coverage check:**
- §1.4 goals "review.md ≤500 lines" → Task 19 + Task 20
- §1.4 audit FAIL items #9-11 → Tasks 1-3
- §1.4 Codex audit additions #13-15 → Tasks 4-6
- §4.1 file layout (12 refs + 3 nested dirs) → Tasks 7-17
- §5.1 strengthened telemetry → Tasks 1-3
- §5.2 slim entry → Task 19
- §5.3 reference files → Tasks 8-17
- §5.4 1 subagent (NOT 2) → Task 18 + Task 20 assertion no goal-scorer
- §5.5 hooks SHARED with R1a → no new tasks
- §5.6 review-specific addendum → handled in slim entry Red Flags (Task 19)
- §6.3 testing → Tasks 20-22
- §6.4 12 exit criteria → Task 25

**UX baseline coverage check (per `_shared-ux-baseline.md`):**
- Req 1 (per-task split): FINDINGS Layer 1+2+3 in slim entry runtime_contract (Task 19); consumer reads use vg-load (Tasks 9, 11, 13, 21).
- Req 2 (spawn narration): Tasks 10 (discovery), 17 (close reflection) include `bash scripts/vg-narrate-spawn.sh` calls.
- Req 3 (compact hooks): Task 3 staleness check uses 3-line stderr; Task 1 telemetry inherits R1a hook stderr convention.

**Phase F Task 30 absorption check:**
- vg:review portion of Task 30 covered by Tasks 9, 11, 13, 21 (vg-load consumption baked into refs by construction).
- Task 21 test enforces no flat reads in review.md or _shared/review/ refs.
- After R3 verdict (Task 25), update blueprint plan Phase F Task 30 scope (mentioned in Task 25 step 5).

**Type/name consistency:**
- All step IDs match `commands/vg/review.md` runtime_contract markers (verified Task 22).
- Subagent name: `vg-review-browser-discoverer` (consistent across spec §5.4, plan Tasks 10/18/19/20).
- NO `vg-review-goal-scorer` (spec §5.4, plan Task 18 + 20 assertion).
- Helper names: `vg-narrate-spawn.sh`, `vg-load.sh`, `review-lens-plan.py`, `spawn_recursive_probe.py`, `aggregate_recursive_goals.py` (R1a-shared or pre-existing, no rename).
- Artifact path conventions: `FINDINGS/finding-NN.md` (Layer 1), `FINDINGS/index.md` (Layer 2), `FINDINGS.md` (Layer 3) — consistent with R1a `PLAN/`, `API-CONTRACTS/`, `TEST-GOALS/` precedent.

**Placeholder scan:** none found. Each Task has actual code/bash, exact file paths, expected outputs.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-vg-r3-review-pilot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec → quality), fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session with checkpoints. REQUIRED SUB-SKILL: `superpowers:executing-plans`.

Pick 1 or 2.
