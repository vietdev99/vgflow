"""tests/test_lifecycle_generator_decisions.py — G9 D-XX propagation."""
from __future__ import annotations
import json
import subprocess
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


def _seed(tmp_path: Path, goals_md: str, context_md: str = "") -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    if context_md:
        (phase_dir / "CONTEXT.md").write_text(context_md, encoding="utf-8")
    return phase_dir


def _gen(tmp_path: Path, goals_md: str, context_md: str = "") -> dict:
    phase_dir = _seed(tmp_path, goals_md, context_md)
    out_path = phase_dir / "LIFECYCLE-SPECS.json"
    r = subprocess.run(
        [sys.executable, str(GENERATOR), "--phase", "99", "--phase-dir", str(phase_dir),
         "--out", str(out_path)],
        capture_output=True, text=True, env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_decision_refs_present_when_goal_mentions_d_xx(tmp_path):
    """v5.0 G9: goal mentioning 'D-7' in dependencies → decision_refs: ['D-7']."""
    goals = """## Goal G-01: Retry transient errors

**goal_type:** mutation
**Surface:** api
**dependencies:** D-7 max-retry policy
"""
    context = """## D-7: Max retry policy

**Decision:** Max 3 retry attempts. Return 429 on 4th attempt.

**expected_assertion:** HTTP 429 with Retry-After header on 4th retry.
"""
    spec = _gen(tmp_path, goals, context)
    goal_spec = spec["goals"]["G-01"]
    assert "decision_refs" in goal_spec, "v5.0 G9: goal_spec must have decision_refs key"
    assert "D-7" in goal_spec["decision_refs"]


def test_decision_assertion_propagated_to_step(tmp_path):
    """v5.0 G9: D-XX expected_assertion appears in relevant step's assertions array."""
    goals = """## Goal G-01: Retry on transient errors

**goal_type:** mutation
**dependencies:** D-7 retry policy
**mutation_evidence:** POST /api/transfers
"""
    context = """## D-7: Max retry policy

**Decision:** 3 retries max.

**expected_assertion:** status_code == 429 on 4th attempt
"""
    spec = _gen(tmp_path, goals, context)
    goal_spec = spec["goals"]["G-01"]
    # The create step should carry an assertion sourced from D-7
    create_step = next((s for s in goal_spec["steps"] if s["name"] == "create"), None)
    assert create_step is not None
    assert "assertions" in create_step, "v5.0 G9: steps must have assertions array"
    d7_assertions = [a for a in create_step["assertions"] if a.get("source") == "D-7"]
    assert len(d7_assertions) >= 1, (
        f"D-7 assertion must propagate to create step; got assertions={create_step['assertions']}"
    )


def test_no_context_file_falls_back_gracefully(tmp_path):
    """v5.0 G9: missing CONTEXT.md doesn't crash. decision_refs = []."""
    goals = "## Goal G-01: Test\n\n**goal_type:** mutation\n"
    spec = _gen(tmp_path, goals)
    goal_spec = spec["goals"]["G-01"]
    assert "decision_refs" in goal_spec
    assert goal_spec["decision_refs"] == []
