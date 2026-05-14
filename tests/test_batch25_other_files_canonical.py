"""tests/test_batch25_other_files_canonical.py — Batch 25 misc files canonical."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_phase_md_canonical():
    body = (REPO / "commands/vg/phase.md").read_text(encoding="utf-8")
    # Must have review BEFORE test-spec in pipeline string
    assert re.search(r"build\s*→\s*review\s*→\s*test-spec\s*→\s*test\s*→\s*accept", body), (
        "phase.md must use v4.0 order: build → review → test-spec → test → accept"
    )
    # Old wrong order must be gone (test-spec → review)
    assert not re.search(r"test-spec\s*→\s*review", body), (
        "old wrong order 'test-spec → review' must be removed from phase.md"
    )


def test_next_md_canonical():
    body = (REPO / "commands/vg/next.md").read_text(encoding="utf-8")
    # Each occurrence of ordered step list must follow v4.0
    for m in re.finditer(r"\[['\"]specs['\"][^\]]+\]", body):
        steps_str = m.group(0)
        review_pos = steps_str.find("review")
        ts_pos = steps_str.find("test-spec")
        test_match = re.search(r"['\"]test['\"](?!-)", steps_str)
        test_pos = test_match.start() if test_match else -1
        if review_pos > 0 and ts_pos > 0 and test_pos > 0:
            assert review_pos < ts_pos < test_pos, (
                f"next.md step list wrong order: {steps_str[:200]}"
            )
    # Pipeline order line must also be canonical
    assert re.search(r"build\s*→\s*test-spec\s*→\s*review", body) is None, (
        "next.md must not have test-spec → review order"
    )
