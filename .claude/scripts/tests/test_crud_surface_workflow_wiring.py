"""Wiring checks for the CRUD-SURFACES contract across VG pipeline steps."""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_blueprint_build_review_test_accept_reference_crud_surfaces() -> None:
    assert "CRUD-SURFACES.md" in _read("commands/vg/blueprint.md")
    assert "verify-crud-surface-contract.py" in _read("commands/vg/blueprint.md")
    assert "crud_surface_context" in _read("commands/vg/build.md")
    assert "verify-crud-surface-contract.py" in _read("commands/vg/review.md")
    assert "verify-crud-surface-contract" in _read("commands/vg/test.md")
    assert "CRUD-SURFACES.md" in _read("commands/vg/accept.md")
    assert "uat-crud-surfaces.txt" in _read("commands/vg/accept.md")


def test_validator_registered_and_unquarantinable() -> None:
    orchestrator = _read("scripts/vg-orchestrator/__main__.py")
    registry = _read("scripts/validators/registry.yaml")
    assert "verify-crud-surface-contract" in orchestrator
    assert '"vg:blueprint"' in orchestrator
    assert '"vg:build"' in orchestrator
    assert '"vg:review"' in orchestrator
    assert '"vg:test"' in orchestrator
    assert '"vg:accept"' in orchestrator
    assert "crud-surface-contract" in registry
    assert "phases_active: [blueprint, build, review, test, accept]" in registry


def test_runtime_map_crud_depth_blocks_shallow_review_and_test() -> None:
    orchestrator = _read("scripts/vg-orchestrator/__main__.py")
    registry = _read("scripts/validators/registry.yaml")
    matrix_merger = _read("commands/vg/_shared/lib/matrix-merger.sh")
    test_command = _read("commands/vg/test.md")

    assert "verify-runtime-map-crud-depth.py" in _read("commands/vg/review.md")
    assert "verify-runtime-map-crud-depth.py" in test_command
    assert "--allow-structural-fallback" in test_command
    assert "STRUCTURAL_FROM_CRUD_SURFACES" in test_command
    assert "verify-runtime-map-crud-depth" in orchestrator
    assert "runtime-map-crud-depth" in registry
    assert "phases_active: [review, test]" in registry
    assert "shallow CRUD evidence" in matrix_merger
    assert "_has_mutation_step" in matrix_merger
