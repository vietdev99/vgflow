"""tests/test_f4_b4_final_review_verdict_gate.py — F4 final review verdict gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "commands" / "vg" / "_shared" / "build" / "close.md"


def test_final_review_verdict_file_check_before_marker():
    body = CLOSE.read_text(encoding="utf-8")
    final_review_idx = body.find("7_1_5_final_review")
    assert final_review_idx > 0
    block = body[final_review_idx:final_review_idx + 2500]
    # Must reference verdict file
    assert ".final-review/verdict.md" in block or "final-review" in block, (
        "F4: B4 final review block must reference verdict file path"
    )
    # Must check existence
    assert ("[ -f" in block or "[ ! -f" in block or "test -f" in block or "is_file" in block), (
        "F4: must check verdict file exists before marker touch"
    )
    # Must parse PASS|PARTIAL|FAIL
    assert ("PASS" in block and "FAIL" in block), (
        "F4: must parse PASS|PARTIAL|FAIL verdict and block on FAIL"
    )
