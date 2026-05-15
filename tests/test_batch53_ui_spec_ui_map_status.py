"""tests/test_batch53_ui_spec_ui_map_status.py — Batch 53 (final B33 deferral).

design.md 2b6_ui_spec + 2b6b_ui_map have multi-branch mark sites; some
branches silent. Add STATUS observability + skip events.

2b6_ui_spec branches:
  - --skip-ui-spec → mark + override but no SKIPPED event
  - Main → has ui_spec_missing event on F7 fail

2b6b_ui_map branches:
  - ui_map.enabled=false → mark, no SKIPPED event
  - FE_TASKS=0 → mark, no SKIPPED event
  - Main → has ui_map_missing on F8 fail

Fix: UI_SPEC_STATUS / UI_MAP_STATUS per branch + ui_spec_skipped /
ui_map_skipped_disabled / ui_map_skipped_no_fe events.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
DESIGN_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "design.md"


def test_2b6_ui_spec_status_var():
    body = DESIGN.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2b6_ui_spec")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 5000]
    assert "UI_SPEC_STATUS" in block, (
        "Batch 53: 2b6_ui_spec must set UI_SPEC_STATUS per branch"
    )


def test_2b6_ui_spec_skip_emits_event():
    body = DESIGN.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2b6_ui_spec")
    block = body[sec_idx:sec_idx + 5000]
    assert "ui_spec_skipped" in block or "blueprint.ui_spec_skipped" in block, (
        "Batch 53: 2b6_ui_spec --skip-ui-spec branch must emit blueprint.ui_spec_skipped"
    )


def test_2b6b_ui_map_status_var():
    body = DESIGN.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2b6b_ui_map")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 5000]
    assert "UI_MAP_STATUS" in block, (
        "Batch 53: 2b6b_ui_map must set UI_MAP_STATUS per branch"
    )


def test_2b6b_ui_map_skip_disabled_emits_event():
    body = DESIGN.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2b6b_ui_map")
    block = body[sec_idx:sec_idx + 5000]
    assert "ui_map_skipped_disabled" in block or "ui_map_skipped_config" in block, (
        "Batch 53: ui_map.enabled=false branch must emit event"
    )


def test_2b6b_ui_map_skip_no_fe_emits_event():
    body = DESIGN.read_text(encoding="utf-8")
    sec_idx = body.find("step-active 2b6b_ui_map")
    block = body[sec_idx:sec_idx + 5000]
    assert "ui_map_skipped_no_fe" in block, (
        "Batch 53: FE_TASKS=0 branch must emit blueprint.ui_map_skipped_no_fe"
    )


def test_mirror_in_sync():
    assert DESIGN.read_text(encoding="utf-8") == DESIGN_MIRROR.read_text(encoding="utf-8")
