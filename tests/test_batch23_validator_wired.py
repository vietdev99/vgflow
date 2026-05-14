"""tests/test_batch23_validator_wired.py — Batch 23 wiring."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_test_spec_invokes_stage_coverage():
    body = (REPO / "commands/vg/test-spec.md").read_text(encoding="utf-8")
    assert "verify-spec-stage-coverage" in body, (
        "Batch 23: test-spec.md must invoke verify-spec-stage-coverage.py "
        "after codegen (post-F1-gate, pre-run-complete)"
    )


def test_test_preflight_invokes_stage_coverage():
    body = (REPO / "commands/vg/_shared/test/preflight.md").read_text(encoding="utf-8")
    assert "verify-spec-stage-coverage" in body, (
        "Batch 23: test/preflight.md must invoke verify-spec-stage-coverage.py "
        "before playwright runtime"
    )
