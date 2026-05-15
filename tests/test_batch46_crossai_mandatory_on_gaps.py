"""tests/test_batch46_crossai_mandatory_on_gaps.py — Batch 46.

Codex F5 + F12.

F5 HIGH: critical negative/failure variants previously deep-probe only.
Batch 37 closed F5 by making negative_specs[] first-class in
LIFECYCLE-SPECS. This batch verifies F5 closure + adds reminder note.

F12 MEDIUM: CrossAI semantic sweep skippable when no qualifying goal_type.
Missing negative/edge/failure coverage passes deterministic gates without
adversarial review.

Fix: extend test-spec.md CrossAI trigger rules — auto-fire when
verify-manifest-spec-kinds.py reports any goal lacking edge/negative
spec_kind. Closes F12.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"
LIFECYCLE_GEN = REPO / "scripts" / "generate-lifecycle-specs.py"


def test_f5_negative_specs_first_class():
    """F5 closure verification: LIFECYCLE-SPECS schema includes
    negative_specs[] per goal (Batch 37). Critical variants no longer
    deep-probe only."""
    body = LIFECYCLE_GEN.read_text(encoding="utf-8")
    assert "negative_specs" in body
    assert "_derive_negative_specs" in body
    # Must contain critical kinds (401/403/422)
    assert "unauthorized_401" in body
    assert "validation_422" in body or "forbidden_403" in body


def test_f12_crossai_auto_fires_on_manifest_kind_gap():
    """CrossAI trigger rules must auto-fire when manifest spec_kinds
    tally has gaps (no edge OR no negative for any goal)."""
    body = TEST_SPEC.read_text(encoding="utf-8")
    # New trigger condition mentions manifest spec_kind gap
    has_gap_trigger = (
        "manifest_spec_kind_gap" in body
        or "spec_kind shortfall" in body.lower()
        or "verify-manifest-spec-kinds" in body
        or "Batch 46" in body
    )
    assert has_gap_trigger, (
        "Batch 46 F12: CrossAI must auto-fire when manifest spec_kind "
        "tally has edge/negative gaps"
    )


def test_f12_crossai_trigger_documented():
    """Trigger rules section must list the new condition."""
    body = TEST_SPEC.read_text(encoding="utf-8")
    trigger_idx = body.find("Auto-trigger condition")
    if trigger_idx < 0:
        trigger_idx = body.find("CROSSAI_SHOULD_RUN")
    assert trigger_idx > 0
    block = body[trigger_idx:trigger_idx + 3000]
    # Must mention manifest or spec_kind gap as new condition
    assert "spec_kind" in block or "manifest_kind" in block or "Batch 46" in block, (
        "Batch 46 F12: trigger rules section must declare manifest gap trigger"
    )


def test_mirror_in_sync():
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
