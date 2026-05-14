"""tests/test_batch27_regression_rc_check.py — G2 regression rc capture."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_playwright_rc_captured():
    body = RS.read_text(encoding="utf-8")
    pw_idx = body.find("npx playwright test")
    assert pw_idx > 0
    block = body[pw_idx:pw_idx + 2500]
    # After playwright invocation must capture rc
    assert ("PLAYWRIGHT_RC=$?" in block or "PIPESTATUS" in block), (
        "G2 Batch 27: regression-security.md must capture playwright exit "
        "code after invocation. Currently REGRESSION_STATUS defaults to PASS "
        "even when tests fail."
    )


def test_regression_status_set_from_rc():
    body = RS.read_text(encoding="utf-8")
    # REGRESSION_STATUS must be set to FAIL when rc != 0
    assert ('REGRESSION_STATUS="FAIL"' in body or 'REGRESSION_STATUS=FAIL' in body or
            'REGRESSION_STATUS = "FAIL"' in body), (
        "G2: REGRESSION_STATUS must be set to FAIL on non-zero playwright rc"
    )


def test_emit_event_on_regression_fail():
    body = RS.read_text(encoding="utf-8")
    assert "test.regression_failed" in body or "regression.failed" in body, (
        "G2: must emit test.regression_failed event when playwright rc != 0"
    )
