from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "reset-review-state.py"


def test_reset_review_state_removes_review_outputs(tmp_path: Path):
    phase_dir = tmp_path / "phase"
    (phase_dir / ".step-markers" / "review").mkdir(parents=True)
    (phase_dir / "crossai").mkdir(parents=True)
    (phase_dir / "scans").mkdir()
    (phase_dir / "api-docs-check.txt").write_text("docs", encoding="utf-8")
    (phase_dir / "api-contract-precheck.txt").write_text("probe", encoding="utf-8")
    (phase_dir / "RUNTIME-MAP.json").write_text("{}", encoding="utf-8")
    (phase_dir / "GOAL-COVERAGE-MATRIX.md").write_text("# matrix", encoding="utf-8")
    (phase_dir / ".step-markers" / "review" / "phase2a_api_contract_probe.done").write_text("", encoding="utf-8")
    (phase_dir / "crossai" / "review-check.xml").write_text("<xml/>", encoding="utf-8")
    (phase_dir / "scans" / "stale.json").write_text("{}", encoding="utf-8")
    keep = phase_dir / "TEST-GOALS.md"
    keep.write_text("# keep", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(proc.stdout)

    assert result["removed_count"] >= 5
    assert not (phase_dir / "api-docs-check.txt").exists()
    assert not (phase_dir / "api-contract-precheck.txt").exists()
    assert not (phase_dir / "RUNTIME-MAP.json").exists()
    assert not (phase_dir / "GOAL-COVERAGE-MATRIX.md").exists()
    assert not (phase_dir / ".step-markers" / "review" / "phase2a_api_contract_probe.done").exists()
    assert not (phase_dir / "crossai" / "review-check.xml").exists()
    assert not (phase_dir / "scans").exists()
    assert keep.exists()


def test_reset_review_state_missing_phase_dir_returns_error(tmp_path: Path):
    missing = tmp_path / "missing-phase"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(missing)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["error"] == "phase_dir_missing"
