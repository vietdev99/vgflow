"""tests/test_h3_validator_output_surfaced.py — H3 validator output surfaced.

Verifies that fix-loop-and-verdict.md's validator loop surfaces diagnostic
output (tails last lines) and writes a summary JSON on PASS path.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILE = REPO / "commands" / "vg" / "_shared" / "test" / "fix-loop-and-verdict.md"


def test_validator_loop_emits_summary_json():
    body = FILE.read_text(encoding="utf-8")
    # Validator loop must produce a result-summary JSON for PASS path inspectability
    assert (
        "validator-summary" in body.lower()
        or "result.json" in body
        or "_summary.json" in body
        or "summary.json" in body
    ), (
        "H3: validator loop must produce a result-summary JSON alongside the "
        ".diag dump (so PASS path leaves inspectable evidence)"
    )


def test_validator_loop_tails_last_lines_on_pass():
    body = FILE.read_text(encoding="utf-8")
    # On PASS (or always), must tail/echo last few lines so user sees what was checked
    assert (
        "tail" in body.lower()
        or "head -" in body
        or "last 5 lines" in body.lower()
        or "last lines" in body.lower()
    ), (
        "H3: validator loop must tail-print last lines of diag so user "
        "sees what was checked on PASS path"
    )
