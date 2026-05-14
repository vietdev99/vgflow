"""tests/test_batch25_phase_recon_order.py — Batch 25 phase-recon canonical order."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RECON = REPO / ".claude" / "scripts" / "phase-recon.py"


def test_pipeline_steps_canonical():
    body = RECON.read_text(encoding="utf-8")
    # PIPELINE_STEPS line — canonical v4.0 order: review → test-spec → test
    import re
    m = re.search(r"PIPELINE_STEPS\s*=\s*\[([^\]]+)\]", body)
    assert m, "PIPELINE_STEPS list missing"
    steps_str = m.group(1)
    # Find positions of 'review' and 'test-spec'
    review_pos = steps_str.find('"review"')
    test_spec_pos = steps_str.find('"test-spec"')
    test_pos = re.search(r'"test"(?!-)', steps_str).start()  # 'test' not 'test-spec'
    assert review_pos > 0 and test_spec_pos > 0 and test_pos > 0
    assert review_pos < test_spec_pos < test_pos, (
        f"Canonical v4.0: review → test-spec → test. "
        f"Got review@{review_pos}, test-spec@{test_spec_pos}, test@{test_pos}"
    )
