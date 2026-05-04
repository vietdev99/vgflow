"""R6 Task 1 — assert 3 blueprint markers have full lifecycle wiring.

Audit finding (codex 2026-05-04): markers declared in must_touch_markers
contract but no step-active / mark-step bash + no STEP 4 routing.
"""
from __future__ import annotations
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("marker,ref_basename", [
    ("2b6d_fe_contracts", "fe-contracts-overview"),
    ("2b8_rcrurdr_invariants", "rcrurdr-overview"),
    ("2b9_workflows", "workflows-overview"),
])
def test_blueprint_marker_has_lifecycle_bash(marker, ref_basename):
    """Each declared marker must have step-active + mark-step bash in its ref."""
    ref = REPO_ROOT / "commands/vg/_shared/blueprint" / f"{ref_basename}.md"
    assert ref.exists(), f"Ref missing: {ref.relative_to(REPO_ROOT)}"
    text = ref.read_text(encoding="utf-8")
    assert f"step-active {marker}" in text, (
        f"{ref.name} must have `vg-orchestrator step-active {marker}` bash call"
    )
    assert f"mark-step blueprint {marker}" in text, (
        f"{ref.name} must have `vg-orchestrator mark-step blueprint {marker}` bash call"
    )


def test_blueprint_step4_routes_three_subrefs():
    """blueprint.md STEP 4 must route to all 3 sub-step refs."""
    blueprint_md = (REPO_ROOT / "commands/vg/blueprint.md").read_text(encoding="utf-8")
    assert "fe-contracts-overview.md" in blueprint_md, "STEP 4 must route fe-contracts ref"
    assert "rcrurdr-overview.md" in blueprint_md, "STEP 4 must route rcrurdr ref"
    assert "workflows-overview.md" in blueprint_md, "STEP 4 must route workflows ref"


def test_rcrurdr_overview_ref_exists_and_uses_parser():
    """rcrurdr-overview.md must exist and reference the existing parser."""
    ref = REPO_ROOT / "commands/vg/_shared/blueprint/rcrurdr-overview.md"
    assert ref.exists(), "rcrurdr-overview.md must be created (currently missing)"
    text = ref.read_text(encoding="utf-8")
    # Must reference the existing parser (don't reinvent)
    assert "rcrurd_invariant" in text or "extract_from_test_goal_md" in text, (
        "rcrurdr-overview must reference scripts/lib/rcrurd_invariant.py "
        "(parser already exists from Task 39 commit 9923bad)"
    )
