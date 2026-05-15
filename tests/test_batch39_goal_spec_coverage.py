"""tests/test_batch39_goal_spec_coverage.py — Batch 39.

Verifies:
- New validator: verify-goal-to-spec-coverage.py asserts every TEST-GOAL
  has >=1 manifest entry.
- Orphan check in regression-security.md flipped from WARN to BLOCK
  (with --allow-orphan-specs escape).
- Goal coverage gate wired in test pipeline.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-goal-to-spec-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-goal-to-spec-coverage.py"
REG_SEC = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"
REG_SEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_validator_exists():
    assert VAL.exists()
    assert VAL_MIRROR.exists()
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")


def test_validator_blocks_uncovered_goal(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    # 3 goals declared
    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-01: list sites\n\n## Goal G-02: create site\n\n## Goal G-03: delete site\n",
        encoding="utf-8",
    )
    # Manifest covers only G-01 and G-02
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [
            {"path": "tests/G-01.spec.ts", "goal_id": "G-01"},
            {"path": "tests/G-02.spec.ts", "goal_id": "G-02"},
        ]}),
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must FAIL strict mode with uncovered G-03"
    assert "G-03" in r.stderr or "G-03" in r.stdout


def test_validator_passes_when_all_covered(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-01: x\n\n## Goal G-02: y\n", encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [
            {"path": "tests/G-01.spec.ts", "goal_id": "G-01"},
            {"path": "tests/G-02.spec.ts", "goal_id": "G-02"},
        ]}),
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"expected PASS, got {r.returncode}: {r.stderr}"


def test_validator_path_heuristic(tmp_path):
    """Manifest entry without explicit goal_id but path contains G-NN."""
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text("## Goal G-01: x\n", encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [
            {"path": "tests/G-01-foo.spec.ts"},  # no goal_id, but G-01 in path
        ]}),
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, "path heuristic must detect G-01 in filename"


def test_orphan_check_blocks_by_default():
    """regression-security.md orphan check must exit 1 unless escape."""
    body = REG_SEC.read_text(encoding="utf-8")
    orphan_idx = body.find("orphan specs executed")
    assert orphan_idx > 0
    block = body[orphan_idx:orphan_idx + 2000]
    # Must have exit 1 path
    assert "exit 1" in block, (
        "Batch 39: orphan specs must trigger exit 1 by default"
    )
    assert "--allow-orphan-specs" in body, "must support escape hatch"


def test_goal_coverage_gate_wired():
    body = REG_SEC.read_text(encoding="utf-8")
    assert "verify-goal-to-spec-coverage.py" in body, (
        "Batch 39: regression-security.md must invoke goal coverage validator"
    )
    assert "--allow-goal-shortfall" in body


def test_mirror_in_sync():
    assert REG_SEC.read_text(encoding="utf-8") == REG_SEC_MIRROR.read_text(encoding="utf-8")
