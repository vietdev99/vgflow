"""tests/test_f8_lens_skip_override.py — F8 lens probe skip requires override."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LF = REPO / "commands" / "vg" / "_shared" / "review" / "lens-and-findings.md"


def test_skip_writes_override_event():
    body = LF.read_text(encoding="utf-8")
    # When .recursive-probe-skipped.yaml is written, must also emit
    # vg-orchestrator override --flag --reason event
    skip_idx = body.find(".recursive-probe-skipped.yaml")
    assert skip_idx > 0
    block = body[max(0, skip_idx - 1500):skip_idx + 2000]
    assert ("vg-orchestrator override" in block or "override.used" in block), (
        "F8: when lens probe skip writes .recursive-probe-skipped.yaml, must "
        "emit vg-orchestrator override event for override-debt tracking"
    )


def test_coverage_failure_blocks():
    body = LF.read_text(encoding="utf-8")
    # Lens coverage failure block must exit 1 unless explicit override
    cov_idx = body.lower().find("coverage")
    if cov_idx > 0:
        block = body[cov_idx:cov_idx + 2000]
        assert ("exit 1" in block or "BLOCK" in block.upper()), (
            "F8: lens coverage failure must BLOCK (exit 1), not prompt-only"
        )
