"""tests/test_batch21_prerun_existence_gate.py — Batch 21 pre-run gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_prerun_existence_check():
    body = RS.read_text(encoding="utf-8")
    # Must verify each manifest spec file exists before playwright runs.
    # Require either the telemetry event name or the MISSING_SPECS variable
    # pattern — these are specific to the existence gate, not generic text.
    assert ("test.manifest_spec_missing" in body or "MISSING_SPECS" in body), (
        "Batch 21: pre-run gate must check each manifest spec exists on disk; "
        "missing spec → BLOCK with test.manifest_spec_missing event or MISSING_SPECS variable"
    )
