"""Task 37 — verify vg-load.sh supports new artifacts: crud-surfaces, lens-walk, rcrurd-invariant.

Pin: per-task / per-goal slicing for build envelope (Bug E).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VG_LOAD = REPO / "scripts/vg-load.sh"


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    """Create a synthetic .vg/phases/N1 with CRUD-SURFACES, LENS-WALK, RCRURD-INVARIANTS."""
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # CRUD-SURFACES split: per-resource files
    cs_dir = phase_dir / "CRUD-SURFACES"
    cs_dir.mkdir()
    (cs_dir / "index.md").write_text("# CRUD-SURFACES index\n- sites\n- users\n", encoding="utf-8")
    (cs_dir / "sites.md").write_text("# Resource: sites\n- create: POST /api/sites\n- read: GET /api/sites/{id}\n", encoding="utf-8")
    (cs_dir / "users.md").write_text("# Resource: users\n- create: POST /api/users\n", encoding="utf-8")
    (phase_dir / "CRUD-SURFACES.md").write_text("# CRUD-SURFACES (flat)\n", encoding="utf-8")

    # LENS-WALK: per-goal split (already exists in repo for blueprint output)
    lw_dir = phase_dir / "LENS-WALK"
    lw_dir.mkdir()
    (lw_dir / "index.md").write_text("# LENS-WALK index\n- G-04\n- G-12\n", encoding="utf-8")
    (lw_dir / "G-04.md").write_text("# G-04 lens-walk seeds\n## form-lifecycle\n- create_then_read\n", encoding="utf-8")
    (lw_dir / "G-12.md").write_text("# G-12 lens-walk seeds\n## modal-state\n- esc_dismiss\n", encoding="utf-8")

    # RCRURD-INVARIANTS: per-goal yaml files (Task 22 schema)
    ri_dir = phase_dir / "RCRURD-INVARIANTS"
    ri_dir.mkdir()
    (ri_dir / "index.md").write_text("# RCRURD index\n- G-04 (mutation)\n- G-12 (mutation)\n", encoding="utf-8")
    (ri_dir / "G-04.yaml").write_text("goal_id: G-04\nlifecycle: rcrurd\n", encoding="utf-8")
    (ri_dir / "G-12.yaml").write_text("goal_id: G-12\nlifecycle: rcrurdr\n", encoding="utf-8")

    return phase_dir


def _run(args: list[str], phase_root: Path) -> subprocess.CompletedProcess:
    """Invoke vg-load.sh with PHASES_DIR env override.

    `phase_root` is the per-phase directory (e.g. tmp/.vg/phases/N1).
    `vg-load.sh` reads `${PHASES_DIR:-.vg/phases}` and appends `/<phase>`
    — so PHASES_DIR must point at the *parent* (`tmp/.vg/phases`), not at
    the phase dir itself. (Codex round-3 B1 fix.)
    """
    env = {"PHASES_DIR": str(phase_root.parent)}
    return subprocess.run(
        ["bash", str(VG_LOAD), *args],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **env},
    )


def test_vg_load_crud_surfaces_by_resource(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--resource", "sites"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "Resource: sites" in result.stdout
    assert "POST /api/sites" in result.stdout


def test_vg_load_crud_surfaces_full(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--full"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "CRUD-SURFACES (flat)" in result.stdout


def test_vg_load_crud_surfaces_index(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "crud-surfaces", "--index"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "CRUD-SURFACES index" in result.stdout


def test_vg_load_lens_walk_by_goal(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "lens-walk", "--goal", "G-04"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "G-04 lens-walk seeds" in result.stdout
    assert "create_then_read" in result.stdout


def test_vg_load_rcrurd_invariant_by_goal(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "rcrurd-invariant", "--goal", "G-12"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "lifecycle: rcrurdr" in result.stdout


def test_vg_load_rcrurd_invariant_by_task_lists_paths(synthetic_phase: Path) -> None:
    """`--task NN` requires goals→task mapping. We test the listing form: use --list to enumerate
    available per-goal files, then orchestrator handles mapping. This test covers the --list filter."""
    result = _run(["--phase", "N1", "--artifact", "rcrurd-invariant", "--list"], synthetic_phase)
    assert result.returncode == 0, result.stderr
    assert "G-04.yaml" in result.stdout
    assert "G-12.yaml" in result.stdout


def test_vg_load_unknown_artifact_errors(synthetic_phase: Path) -> None:
    result = _run(["--phase", "N1", "--artifact", "totally-unknown"], synthetic_phase)
    assert result.returncode != 0
    assert "unknown artifact" in result.stderr.lower()
