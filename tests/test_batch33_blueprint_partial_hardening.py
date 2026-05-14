"""tests/test_batch33_blueprint_partial_hardening.py — Batch 33.

Hardens 3 worst PARTIAL blueprint markers from audit:

- 2d_validation_gate (verify.md:489): threshold decision pseudocode, not
  real bash. Mark fires regardless of miss percentages.
- 2d_crossai_review (verify.md:597): marker can fire without
  crossai/result-*.xml.
- 3_complete (close.md:230): marker fires BEFORE traceability/BLOCK5/
  workflow/slice gates run.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "commands" / "vg" / "_shared" / "blueprint" / "verify.md"
CLOSE = REPO / "commands" / "vg" / "_shared" / "blueprint" / "close.md"


def test_2d_validation_gate_real_bash():
    """5.5.5 threshold decision must be real bash setting GATE_VERDICT,
    not pseudocode in plain ``` fence."""
    body = VERIFY.read_text(encoding="utf-8")
    gate_idx = body.find("### 5.5.5")
    assert gate_idx > 0
    block = body[gate_idx:gate_idx + 3500]
    assert "GATE_VERDICT" in block, (
        "Batch 33 gap #9: 5.5.5 must set GATE_VERDICT var from real bash "
        "comparing miss percentages vs thresholds. Currently pseudocode "
        "in plain fence (not executed)."
    )


def test_2d_crossai_review_xml_gate():
    """5.5.6 must check crossai/result-*.xml exists before non-skip
    mark-step. The non-skip branch is the SECOND mark-step occurrence."""
    body = VERIFY.read_text(encoding="utf-8")
    # Find LAST occurrence (non-skip branch with XML gate)
    mark_idx = body.rfind("mark-step blueprint 2d_crossai_review")
    assert mark_idx > 0
    pre = body[max(0, mark_idx - 2500):mark_idx]
    assert "CROSSAI_XML_FOUND" in pre, (
        "Batch 33 gap #10: non-skip 2d_crossai_review mark must check "
        "CROSSAI_XML_FOUND var (from ls crossai/result-*.xml). Currently "
        "fires after Agent spawn regardless of result XML."
    )


def test_3_complete_moved_after_gates():
    """close.md 6.2.4 marker write must be removed/deferred; new section
    after slice gate (6.2.5d) writes the marker."""
    body = CLOSE.read_text(encoding="utf-8")
    # Find both 6.2.4 and the new post-gates section
    sec_624_idx = body.find("### 6.2.4")
    sec_625e_idx = body.find("### 6.2.5e")
    sec_625d_idx = body.find("### 6.2.5d")
    assert sec_624_idx > 0
    assert sec_625e_idx > 0, (
        "Batch 33 gap #11: close.md must have 6.2.5e section that writes "
        "3_complete marker AFTER all gates (traceability/BLOCK5/workflow/slice)"
    )
    assert sec_625e_idx > sec_625d_idx, (
        "6.2.5e (marker write) must come AFTER 6.2.5d (slice gate)"
    )
    # 6.2.4 must NOT have the unconditional mark-step anymore
    sec_624_block = body[sec_624_idx:body.find("### 6.2.5", sec_624_idx)]
    assert "mark-step blueprint 3_complete" not in sec_624_block, (
        "Batch 33 gap #11: 6.2.4 must not mark 3_complete anymore — "
        "marker write moved to 6.2.5e after all gates pass"
    )
    # 6.2.5e MUST have the mark-step
    sec_625e_block = body[sec_625e_idx:sec_625e_idx + 2000]
    assert "mark-step blueprint 3_complete" in sec_625e_block


def test_mirrors_in_sync():
    for src in [VERIFY, CLOSE]:
        mirror = REPO / ".claude" / src.relative_to(REPO)
        assert src.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8"), (
            f"Mirror drift: {mirror.relative_to(REPO)}"
        )
