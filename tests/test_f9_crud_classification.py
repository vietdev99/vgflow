"""tests/test_f9_crud_classification.py — F9 CRUD lane classification."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LF = REPO / "commands" / "vg" / "_shared" / "review" / "lens-and-findings.md"


def test_crud_classification_states():
    body = LF.read_text(encoding="utf-8")
    # CRUD lane must classify outcomes explicitly: SKIPPED|NO_SURFACE|FAILED|PASS
    crud_idx = body.find("CRUD")
    assert crud_idx > 0
    # Look for state names
    found = sum(1 for state in ["NO_SURFACE", "SKIPPED", "FAILED"] if state in body)
    assert found >= 2, (
        "F9: CRUD lane must distinguish at least SKIPPED / NO_SURFACE / FAILED "
        "(plus PASS) — currently all paths continue with marker written"
    )


def test_crud_skip_emits_event():
    body = LF.read_text(encoding="utf-8")
    # CRUD skip must emit telemetry, not silently mark done
    assert ("review.crud_skipped" in body or "crud.skip" in body or "crud_no_surface" in body), (
        "F9: CRUD skip must emit a specific event (not just marker touch)"
    )
