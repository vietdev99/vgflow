"""Task 37 — verify pre-executor-check.py orchestrator resolves per-task slices.

Pin: capsule build resolves crud_surfaces_slice_path + lens_walk_slice_path +
rcrurd_invariants_paths from goals→task mapping. Stale capsules degrade
gracefully (warning, not fail).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_pre_executor_check():
    """Load scripts/pre-executor-check.py (hyphen in name prevents direct import)."""
    spec = importlib.util.spec_from_file_location(
        "pre_executor_check",
        REPO / "scripts" / "pre-executor-check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_executor_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # CRUD-SURFACES per-resource
    (phase_dir / "CRUD-SURFACES").mkdir()
    (phase_dir / "CRUD-SURFACES" / "sites.md").write_text("# Resource: sites\n", encoding="utf-8")
    (phase_dir / "CRUD-SURFACES.md").write_text("flat\n", encoding="utf-8")

    # LENS-WALK per-goal
    (phase_dir / "LENS-WALK").mkdir()
    (phase_dir / "LENS-WALK" / "G-04.md").write_text("# G-04\n", encoding="utf-8")

    # RCRURD-INVARIANTS per-goal
    (phase_dir / "RCRURD-INVARIANTS").mkdir()
    (phase_dir / "RCRURD-INVARIANTS" / "G-04.yaml").write_text("goal_id: G-04\n", encoding="utf-8")

    # Task capsule cache dir
    (tmp_path / ".task-capsules").mkdir()
    return phase_dir


def test_build_per_task_slices_resolves_resource_and_goals(synthetic_phase: Path) -> None:
    mod = _load_pre_executor_check()
    build_per_task_slices = mod.build_per_task_slices

    slices = build_per_task_slices(
        phase_dir=synthetic_phase,
        task_num=4,
        endpoints=["POST /api/sites", "GET /api/sites/{id}"],
        goals=["G-04"],
        cache_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    assert slices["crud_surfaces_slice_path"] is not None
    assert "sites" in slices["crud_surfaces_slice_path"]
    assert slices["lens_walk_slice_path"] is not None
    assert "G-04" in slices["lens_walk_slice_path"]
    assert isinstance(slices["rcrurd_invariants_paths"], list)
    assert len(slices["rcrurd_invariants_paths"]) == 1
    assert "G-04" in slices["rcrurd_invariants_paths"][0]


def test_build_per_task_slices_handles_missing_artifact(tmp_path: Path) -> None:
    """Phase without CRUD-SURFACES gets None for slice path; no exception."""
    mod = _load_pre_executor_check()
    build_per_task_slices = mod.build_per_task_slices

    empty_phase = tmp_path / ".vg" / "phases" / "N2"
    empty_phase.mkdir(parents=True)
    (tmp_path / ".task-capsules").mkdir()

    slices = build_per_task_slices(
        phase_dir=empty_phase,
        task_num=1,
        endpoints=[],
        goals=[],
        cache_dir=tmp_path / ".task-capsules",
    )
    assert slices["crud_surfaces_slice_path"] is None
    assert slices["lens_walk_slice_path"] is None
    assert slices["rcrurd_invariants_paths"] == []


def test_capsule_includes_slice_paths(synthetic_phase: Path) -> None:
    mod = _load_pre_executor_check()
    build_task_context_capsule = mod.build_task_context_capsule

    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=4,
        task_context="## Task 04: Add POST /api/sites handler\n<file-path>apps/api/src/sites/routes.ts</file-path>\n<goal>G-04</goal>\n",
        contract_context="POST /api/sites\n",
        goals_context="G-04",
        crud_surface_context="sites",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    # New fields (Task 37) — present even if null
    assert "crud_surfaces_slice_path" in capsule
    assert "lens_walk_slice_path" in capsule
    assert "rcrurd_invariants_paths" in capsule
    assert isinstance(capsule["rcrurd_invariants_paths"], list)


def test_telemetry_emits_envelope_slice_resolved(synthetic_phase: Path, tmp_path: Path) -> None:
    """`build.envelope_slice_resolved` event must be declared in build.md must_emit_telemetry."""
    build_md = REPO / "commands/vg/build.md"
    text = build_md.read_text(encoding="utf-8")
    assert "build.envelope_slice_resolved" in text, \
        "Task 37 telemetry event must be declared in build.md must_emit_telemetry"
