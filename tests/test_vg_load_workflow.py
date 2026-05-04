"""Task 40 — verify vg-load.sh supports `--artifact workflow --workflow WF-NN`."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VG_LOAD = REPO / "scripts/vg-load.sh"


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    (phase_dir / "WORKFLOW-SPECS").mkdir(parents=True)
    (phase_dir / "WORKFLOW-SPECS" / "index.md").write_text("# WF index\n- WF-001\n", encoding="utf-8")
    (phase_dir / "WORKFLOW-SPECS" / "WF-001.md").write_text("# WF-001\nworkflow_id: WF-001\n", encoding="utf-8")
    return phase_dir


def _run(args: list[str], phase_root: Path) -> subprocess.CompletedProcess:
    # vg-load.sh reads PHASES_DIR (plural). PHASES_DIR points at the parent
    # of the phase dir — so `--phase N1` finds `<PHASES_DIR>/N1`. (Codex
    # round-3 B1 fix.)
    env = {**os.environ, "PHASES_DIR": str(phase_root.parent)}
    return subprocess.run(["bash", str(VG_LOAD), *args], capture_output=True, text=True, env=env)


def test_vg_load_workflow_by_id(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "workflow", "--workflow", "WF-001"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "workflow_id: WF-001" in result.stdout


def test_vg_load_workflow_index(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "workflow", "--index"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "WF-001" in result.stdout


def test_vg_load_workflow_unknown_id_errors(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "workflow", "--workflow", "WF-999"], synthetic_phase)
    assert result.returncode != 0
