"""tests/test_rule2_complexity_gate.py — Rule 2 simplicity gate."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-task-complexity.py"


def test_validator_exists():
    assert VAL.is_file(), "Rule 2: verify-task-complexity.py must ship"


def test_no_budget_in_plan_skips_check(tmp_path):
    """When PLAN.md has no complexity_budget, validator must skip cleanly (advisory)."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PLAN.md").write_text("# Plan\nNo budget here.\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"Rule 2: missing budget should skip cleanly. stderr={r.stderr}"


def test_budget_overrun_warns_or_blocks(tmp_path):
    """When task delta exceeds declared budget, validator must surface OVERRUN."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    plan_text = """# Plan

## Task T-01
**complexity_budget:** max_loc_delta=10

Implementation
"""
    (phase_dir / "PLAN.md").write_text(plan_text, encoding="utf-8")
    # Inject a fake diff stats file so validator can compute overrun
    (phase_dir / ".task-diff-stats.json").write_text(
        '{"T-01": {"loc_delta": 200, "files_changed": 5}}', encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01"],
        capture_output=True, text=True,
    )
    # Advisory: prints OVERRUN; exit 0 unless --strict
    combined = r.stdout + r.stderr
    assert "overrun" in combined.lower() or "exceed" in combined.lower() or "200" in combined, (
        f"Rule 2: 200 loc delta vs max_loc_delta=10 must surface OVERRUN. Got: {combined[:300]}"
    )


def test_strict_mode_blocks_on_overrun(tmp_path):
    """--strict promotes overrun to non-zero exit."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PLAN.md").write_text(
        "## Task T-01\n**complexity_budget:** max_loc_delta=5\n", encoding="utf-8"
    )
    (phase_dir / ".task-diff-stats.json").write_text(
        '{"T-01": {"loc_delta": 500, "files_changed": 3}}', encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01", "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "Rule 2: --strict must escalate overrun to non-zero exit"
