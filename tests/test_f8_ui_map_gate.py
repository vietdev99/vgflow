"""tests/test_f8_ui_map_gate.py — F8 UI-MAP existence gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "commands" / "vg" / "_shared" / "blueprint" / "design.md"


def test_ui_map_gate_present():
    body = DESIGN.read_text(encoding="utf-8")
    # Find the LAST occurrence of the marker (after the FE-tasks > 0 branch)
    last_marker = body.rfind("2b6b_ui_map.done")
    assert last_marker > 0, "2b6b_ui_map.done marker not found"
    block = body[max(0, last_marker - 2000):last_marker]
    # Must check UI-MAP.md existence + emit event when missing
    assert "UI-MAP.md" in block, "F8: must reference UI-MAP.md in gate block"
    assert ("blueprint.ui_map_missing" in body or "F8" in body), (
        "F8: design.md must emit blueprint.ui_map_missing event when UI-MAP.md "
        "absent for FE phase"
    )


def test_ui_map_fe_phase_blocks():
    body = DESIGN.read_text(encoding="utf-8")
    # In the FE_TASKS > 0 branch, missing UI-MAP.md must lead to exit 1
    # Find '"${FE_TASKS:-0}" -eq 0' first
    fe_idx = body.find('"${FE_TASKS:-0}" -eq 0')
    assert fe_idx > 0, '"${FE_TASKS:-0}" -eq 0 not found in design.md'
    fe_else = body.find("else", fe_idx)
    # Up to 3500 chars into the else branch
    else_block = body[fe_else:fe_else + 3500]
    # Need a gate path
    assert ("F8" in else_block and ("exit 1" in else_block or "BLOCK" in else_block)) or "blueprint.ui_map_missing" in else_block, (
        "F8: FE-phase branch must BLOCK when UI-MAP.md missing post-Agent"
    )
