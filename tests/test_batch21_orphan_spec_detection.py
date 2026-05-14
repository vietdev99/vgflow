"""tests/test_batch21_orphan_spec_detection.py — Batch 21 orphan spec detection."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_orphan_spec_event_emitted():
    body = RS.read_text(encoding="utf-8")
    # Must emit test.orphan_spec_executed event when specs ran that aren't in manifest
    assert ("test.orphan_spec" in body or "orphan_spec" in body), (
        "Batch 21: post-run gate must emit test.orphan_spec_executed when "
        "specs executed that aren't in CODEGEN-MANIFEST.json"
    )
