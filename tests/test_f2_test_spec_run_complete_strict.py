"""tests/test_f2_test_spec_run_complete_strict.py — F2 test-spec run-complete strict."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
TS = REPO / "commands" / "vg" / "test-spec.md"


def test_test_spec_run_complete_no_swallow():
    body = TS.read_text(encoding="utf-8")
    # Find the LAST occurrence of test_spec.completed (the bash emit-event call),
    # not the YAML marker at the top of the file.
    idx = body.rfind('test_spec.completed')
    assert idx > 0
    block = body[idx:idx + 1000]
    # The run-complete line must NOT swallow failures via `|| true`
    rc_idx = block.find("run-complete")
    assert rc_idx > 0, (
        "run-complete not found within 1000 chars after test_spec.completed emit block"
    )
    rc_line_end = block.find("\n", rc_idx)
    rc_line = block[rc_idx:rc_line_end]
    assert "|| true" not in rc_line, (
        "F2: 'vg-orchestrator run-complete --outcome PASS' line must NOT end "
        "with '|| true' — that swallows contract failures. PASS verdict "
        "should only ship if run-complete returns 0."
    )


def test_test_spec_verdict_pass_conditional_on_run_complete():
    body = TS.read_text(encoding="utf-8")
    # The Python block that writes verdict=PASS must come AFTER run-complete
    # passes, OR there must be a guard. Easier check: there's an explicit exit
    # path on run-complete failure.
    idx = body.find('verdict": "PASS"')
    if idx < 0:
        idx = body.find("'verdict': 'PASS'")
    assert idx > 0
    # Within 2000 chars after, either an exit 1 / fail path OR run-complete
    # without `|| true`
    after = body[idx:idx + 2000]
    # Check: run-complete exists in after, and its line does NOT have || true
    if "run-complete" in after:
        line_after_rc = after.split("run-complete", 1)[1].split("\n", 1)[0]
        assert "|| true" not in line_after_rc, (
            "F2: run-complete called after verdict=PASS write must NOT have "
            "'|| true' — failures must surface to exit 1"
        )
    else:
        # If run-complete is not in the 2000-char window, there must be exit 1
        assert "exit 1" in after, (
            "F2: verdict=PASS write must be guarded — either explicit exit 1 on "
            "failure path OR run-complete called without `|| true`"
        )
