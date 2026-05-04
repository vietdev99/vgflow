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


# R6 Task 1 follow-up (C-1, C-2): each skip-flag handler must enforce
# --override-reason pairing AND emit override.used + log_override_debt
# so run-complete validation accepts the skip per
# `commands/vg/blueprint.md::forbidden_without_override`.
@pytest.mark.parametrize("ref_basename,skip_flag,gate_id", [
    ("fe-contracts-overview", "--skip-fe-contracts", "blueprint-fe-contracts-skipped"),
    ("rcrurdr-overview", "--skip-rcrurdr", "blueprint-rcrurdr-skipped"),
    ("workflows-overview", "--skip-workflows", "blueprint-workflows-skipped"),
])
def test_blueprint_skip_flag_handler_emits_override_and_guards_reason(
    ref_basename, skip_flag, gate_id,
):
    """Each skip-flag branch must:
    1. Guard --override-reason pairing (exit 1 if missing)
    2. Emit canonical `vg-orchestrator override --flag <skip_flag>`
    3. Call log_override_debt with the gate-id
    """
    ref = REPO_ROOT / "commands/vg/_shared/blueprint" / f"{ref_basename}.md"
    assert ref.exists(), f"Ref missing: {ref.relative_to(REPO_ROOT)}"
    text = ref.read_text(encoding="utf-8")

    # 1. --override-reason guard regex check
    guard_pattern = re.compile(
        r'if\s*\[\[\s*!\s*"\$ARGUMENTS"\s*=~\s*--override-reason\s*\]\];\s*then'
    )
    assert guard_pattern.search(text), (
        f"{ref.name}: skip-flag branch must guard --override-reason pairing "
        f"(regex `if [[ ! \"$ARGUMENTS\" =~ --override-reason ]]`)"
    )

    # 2. Canonical vg-orchestrator override --flag invocation
    override_pattern = re.compile(
        r'vg-orchestrator\s+override\s*\\\s*\n\s*--flag\s+"' + re.escape(skip_flag) + r'"'
    )
    assert override_pattern.search(text), (
        f"{ref.name}: skip-flag branch must call "
        f"`vg-orchestrator override --flag \"{skip_flag}\"` "
        f"(canonical pattern from contracts-overview.md::--skip-codex-test-goal-lane)"
    )

    # 3. log_override_debt invocation with gate-id
    debt_pattern = re.compile(
        r'log_override_debt\s+"' + re.escape(gate_id) + r'"'
    )
    assert debt_pattern.search(text), (
        f"{ref.name}: skip-flag branch must call "
        f"`log_override_debt \"{gate_id}\" ...`"
    )


# R6 Task 1 follow-up (I-1): blueprint.md must_emit_telemetry must declare
# the 3 events emitted by skip/blocked branches that were missing.
@pytest.mark.parametrize("event_type", [
    "blueprint.fe_contracts_pass_skipped",
    "blueprint.rcrurdr_invariant_skipped",
    "blueprint.workflows_pass_blocked",
])
def test_blueprint_must_emit_telemetry_declares_skip_events(event_type):
    """blueprint.md must_emit_telemetry must declare every event the bash emits."""
    blueprint_md = (REPO_ROOT / "commands/vg/blueprint.md").read_text(encoding="utf-8")
    assert f'event_type: "{event_type}"' in blueprint_md, (
        f"blueprint.md must_emit_telemetry must declare `{event_type}` "
        f"(emitted by skip-flag/blocked branch but currently undeclared)"
    )
