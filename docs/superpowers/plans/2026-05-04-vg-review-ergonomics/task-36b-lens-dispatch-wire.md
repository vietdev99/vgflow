<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 36b: Wire Task 26 lens dispatch into review.md Phase 2.5

**Files:**
- Modify: `scripts/spawn_recursive_probe.py` (~200-400 LOC change)
- Modify: `commands/vg/review.md` (Phase 2.5 wiring + frontmatter telemetry)
- Test: `tests/test_review_lens_dispatch_wiring.py`

**Why:** Task 26 (commit `ed4d148`) shipped LENS-DISPATCH-PLAN.json schema, emit-dispatch-plan.py, verify-lens-runs-coverage.py, lens_tier_dispatcher.py, lens-coverage-matrix.py — but explicitly deferred review.md wiring as "architectural — touches existing widely-used scripts." Task 36b does the wiring.

**Depends on**: Task 33 (wrapper used for coverage gate failure routing) + Task 36a (lens frontmatter populated).

- [ ] **Step 1: Write the failing test**

Create `tests/test_review_lens_dispatch_wiring.py`:

```python
"""Task 36b — verify review.md Phase 2.5 wires Task 26 dispatch chain."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_review_md_calls_emit_dispatch_plan() -> None:
    """review.md Phase 2.5 must call emit-dispatch-plan.py before spawn loop."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "emit-dispatch-plan.py" in text, (
        "review.md Phase 2.5 must call scripts/lens-dispatch/emit-dispatch-plan.py"
    )
    # emit must come BEFORE spawn_recursive_probe.py invocation
    emit_pos = text.find("emit-dispatch-plan.py")
    spawn_pos = text.find("spawn_recursive_probe.py")
    assert emit_pos != -1 and spawn_pos != -1
    assert emit_pos < spawn_pos, (
        f"emit-dispatch-plan.py at byte {emit_pos} must come before "
        f"spawn_recursive_probe.py at byte {spawn_pos}"
    )


def test_review_md_calls_verify_lens_runs_coverage() -> None:
    """review.md must call verify-lens-runs-coverage.py after spawn loop."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "verify-lens-runs-coverage.py" in text


def test_review_md_renders_coverage_matrix() -> None:
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "lens-coverage-matrix.py" in text or "LENS-COVERAGE-MATRIX.md" in text


def test_review_md_routes_coverage_block_through_wrapper() -> None:
    """Coverage gate failure must route through Task 33 wrapper, not exit 1."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # When verify-lens-runs-coverage exits non-zero, must call wrapper
    import re
    # Look for verify-lens-runs-coverage block followed by wrapper invocation within 30 lines
    pattern = re.compile(
        r'verify-lens-runs-coverage\.py.*?(?:\n[^\n]*){0,30}blocking_gate_prompt_emit',
        re.DOTALL,
    )
    assert pattern.search(text), (
        "lens coverage gate failure must invoke blocking_gate_prompt_emit "
        "(Task 33 wrapper), not exit 1 directly"
    )


def test_spawn_recursive_probe_uses_tier_dispatcher() -> None:
    """spawn_recursive_probe.py must import lens_tier_dispatcher.select_tier."""
    text = (REPO / "scripts/spawn_recursive_probe.py").read_text(encoding="utf-8")
    assert "lens_tier_dispatcher" in text or "select_tier" in text, (
        "spawn_recursive_probe.py must use Task 26's tier dispatcher"
    )


def test_spawn_recursive_probe_writes_plan_hash_in_artifacts() -> None:
    """Per-dispatch artifact must include plan_hash (anti-reuse)."""
    text = (REPO / "scripts/spawn_recursive_probe.py").read_text(encoding="utf-8")
    assert "plan_hash" in text, "spawn_recursive_probe.py must write plan_hash in artifacts"


def test_review_md_skip_mode_shortcuts_coverage() -> None:
    """When --probe-mode skip set, coverage gate skipped (legitimate user decision)."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Look for .recursive-probe-skipped.yaml check before coverage gate
    assert ".recursive-probe-skipped.yaml" in text


def test_telemetry_events_declared_in_frontmatter() -> None:
    """review.md must declare review.lens_dispatch_emitted + review.lens_coverage_blocked."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "review.lens_dispatch_emitted" in text
    assert "review.lens_coverage_blocked" in text
```

- [ ] **Step 2: Run failing tests**

Expected: 8 failures (review.md not yet wired; spawn_recursive_probe.py not refactored).

- [ ] **Step 3: Update spawn_recursive_probe.py to use Task 26 chain**

Read current spawn_recursive_probe.py structure:

```bash
grep -nE "^def |spawn|Agent\(" scripts/spawn_recursive_probe.py | head -30
```

Modifications (per Codex round-2 finding #67, ~200-400 LOC):

1. **Pre-loop** — call `emit-dispatch-plan.py`:
```python
import subprocess
from pathlib import Path

def emit_dispatch_plan(phase_dir: Path, phase: str, profile: str, review_run_id: str) -> Path:
    """Call Task 26 emitter; returns path to LENS-DISPATCH-PLAN.json."""
    output = phase_dir / "LENS-DISPATCH-PLAN.json"
    subprocess.run([
        "python3", ".claude/scripts/lens-dispatch/emit-dispatch-plan.py",
        "--phase-dir", str(phase_dir),
        "--phase", phase,
        "--profile", profile,
        "--review-run-id", review_run_id,
        "--output", str(output),
    ], check=True, timeout=60)
    return output
```

2. **Spawn loop** — iterate dispatches, use tier_dispatcher per dispatch:
```python
import sys
sys.path.insert(0, '.claude/scripts/lib')
from lens_tier_dispatcher import select_tier

def spawn_per_dispatch(plan_path: Path, project_cost_caps: dict):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_hash = plan["plan_hash"]
    for dispatch in plan["dispatches"]:
        if dispatch["applicability_status"] != "APPLICABLE":
            continue
        # Read lens frontmatter for tier dispatch
        lens_path = LENS_DIR / f"{dispatch['lens']}.md"
        lens_fm = read_frontmatter(lens_path)
        tier = select_tier(lens_fm, project_cost_caps)
        if tier.override_required and lens_fm.get("worker_complexity_score", 1) >= 4:
            # Cost cap exceeded for high-complexity lens — log debt + skip
            log_override_debt("lens-cost-cap-exceeded", phase, dispatch["dispatch_id"])
            continue
        # Spawn worker per dispatch (existing pattern)
        artifact = spawn_worker(dispatch, tier, plan_hash)
        # Write plan_hash into artifact for coverage gate verification
        artifact["plan_hash"] = plan_hash
        write_artifact(dispatch["expected_artifact_path"], artifact)
```

3. **Post-loop** — coverage gate:
```bash
# In review.md slim entry (Step 4 below), AFTER spawn_recursive_probe.py returns
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-lens-runs-coverage.py \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
  --runs-dir "${PHASE_DIR}/runs" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${PHASE_DIR}/.lens-coverage-evidence.json"
COVERAGE_RC=$?
```

- [ ] **Step 4: Wire into review.md Phase 2.5**

Edit `commands/vg/review.md` Phase 2.5 (search `recursive_lens_probe`). Add at start:

```bash
# Task 36b — Lens dispatch enforcement (wires Task 26 infrastructure).

# Skip-mode escape (existing user decision)
if [ -f "${PHASE_DIR}/.recursive-probe-skipped.yaml" ]; then
  echo "▸ Phase 2.5 skipped per --probe-mode skip"
  return 0
fi

# 1. Emit dispatch plan FIRST (trust anchor)
"${PYTHON_BIN:-python3}" .claude/scripts/lens-dispatch/emit-dispatch-plan.py \
  --phase-dir "${PHASE_DIR}" \
  --phase "${PHASE_NUMBER}" \
  --profile "$(vg_config_get profile web-fullstack)" \
  --review-run-id "${REVIEW_RUN_ID}" \
  --output "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" || {
  echo "⛔ Phase 2.5: emit-dispatch-plan failed" >&2
  exit 1
}

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.lens_dispatch_emitted" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"plan_path\":\"${PHASE_DIR}/LENS-DISPATCH-PLAN.json\"}" \
  >/dev/null 2>&1 || true

# 2. Spawn workers per dispatch (existing spawn_recursive_probe.py, now Task 26-aware)
"${PYTHON_BIN:-python3}" .claude/scripts/spawn_recursive_probe.py \
  --phase-dir "${PHASE_DIR}" \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"

# 3. Coverage gate
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-lens-runs-coverage.py \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
  --runs-dir "${PHASE_DIR}/runs" \
  --phase "${PHASE_NUMBER}" \
  --evidence-out "${PHASE_DIR}/.lens-coverage-evidence.json"
COVERAGE_RC=$?

# 4. Render matrix (always, even on coverage fail — gives user the picture)
"${PYTHON_BIN:-python3}" .claude/scripts/aggregators/lens-coverage-matrix.py \
  --dispatch-plan "${PHASE_DIR}/LENS-DISPATCH-PLAN.json" \
  --runs-dir "${PHASE_DIR}/runs" \
  --output "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md" || true

# 5. Coverage failure → Task 33 wrapper (NOT exit 1 — user gets 4 options)
if [ "$COVERAGE_RC" -ne 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.lens_coverage_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence\":\"${PHASE_DIR}/.lens-coverage-evidence.json\"}" \
    >/dev/null 2>&1 || true

  # Task 33 wrapper: present 4 options (auto-fix-spawn-missing-lenses / skip-with-override / amend / abort)
  source scripts/lib/blocking-gate-prompt.sh
  blocking_gate_prompt_emit "lens_coverage_blocked" \
    "${PHASE_DIR}/.lens-coverage-evidence.json" \
    "error" \
    "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
  # AI controller calls AskUserQuestion → re-invokes Leg 2
  # Branch on Leg 2 exit code per blocking-gate-prompt-contract.md
fi
```

Add to `commands/vg/review.md` `must_emit_telemetry`:

```yaml
    - event_type: "review.lens_dispatch_emitted"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.lens_coverage_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

Add to `must_write`:

```yaml
    - path: "${PHASE_DIR}/LENS-DISPATCH-PLAN.json"
      content_min_bytes: 200
      required_unless_flag: "--probe-mode-skip"
    - path: "${PHASE_DIR}/LENS-COVERAGE-MATRIX.md"
      content_min_bytes: 100
      required_unless_flag: "--probe-mode-skip"
```

- [ ] **Step 5: Run tests + sync + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_review_lens_dispatch_wiring.py -v
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
python3 scripts/vg_sync_codex.py --apply 2>&1 | tail -2
git add scripts/spawn_recursive_probe.py \
        commands/vg/review.md \
        tests/test_review_lens_dispatch_wiring.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(review): wire Task 26 lens dispatch into Phase 2.5 (Task 36b, Bug D part 2)

Task 26 ed4d148 shipped LENS-DISPATCH-PLAN.json + verify-lens-runs-coverage
+ M1 tier dispatcher + matrix renderer but explicitly deferred
review.md wiring (architectural cost). Task 36b does the wiring.

Phase 2.5 chain:
1. emit-dispatch-plan.py → LENS-DISPATCH-PLAN.json (trust anchor)
2. spawn_recursive_probe.py iterates per dispatch w/ lens_tier_dispatcher
   (per-lens model selection per Task 36a frontmatter)
3. verify-lens-runs-coverage.py — BLOCK on MISSING APPLICABLE artifacts
4. Coverage failure → Task 33 wrapper (NOT exit 1) → user picks
   [a] auto-fix (spawn missing lenses), [s] skip+override, [r] amend, [x] abort

PV3 dogfood validation: phase 4.1 review previously hand-waved
'Phase 2.5/2.7/2.9 Lens probes ⏸ DEFERRED' to /vg:test. After Task 36b,
DEFERRED is impossible — coverage gate enforces APPLICABLE dispatches
have artifacts. Closes Bug D.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
