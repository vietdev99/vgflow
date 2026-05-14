"""tests/test_f7_ui_spec_gate.py — F7 UI-SPEC file existence gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "commands" / "vg" / "_shared" / "blueprint" / "design.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_ui_spec_gate_block_near_marker():
    """F7: The gate that checks UI-SPEC/index.md existence must appear
    within 2500 chars BEFORE the LAST 2b6_ui_spec.done marker touch line.
    (First occurrence is in the --skip-ui-spec escape branch; last is normal flow.)
    Without F7 fix, no gate exists there."""
    body = _read(DESIGN)
    # Use rfind to get the LAST marker (the normal-flow one, not the skip-branch one)
    last_marker = body.rfind("2b6_ui_spec.done")
    assert last_marker > 0, "2b6_ui_spec.done marker not found in design.md"
    # Look back 2500 chars before the last marker (normal-flow marker)
    block = body[max(0, last_marker - 2500):last_marker]
    # F7 gate must emit blueprint.ui_spec_missing event
    assert "blueprint.ui_spec_missing" in block, (
        "F7: blueprint.ui_spec_missing event must be emitted in the block "
        "BEFORE the last 2b6_ui_spec.done marker (normal flow) — gate is missing"
    )


def test_fe_phase_blocks_on_missing_ui_spec():
    """F7: gate must exit 1 for FE phases with missing UI-SPEC/index.md."""
    body = _read(DESIGN)
    # F7 gate block must have FE_TASKS_COUNT check + exit 1
    assert "FE_TASKS_COUNT" in body, (
        "F7: gate must use FE_TASKS_COUNT to be FE-profile-aware"
    )
    # Find FE_TASKS_COUNT usage near ui_spec_missing
    idx = body.find("FE_TASKS_COUNT")
    # Within 3000 chars of that block, must have exit 1
    block = body[max(0, idx - 100):idx + 3000]
    assert "exit 1" in block, (
        "F7: missing UI-SPEC for FE phase must exit 1"
    )
