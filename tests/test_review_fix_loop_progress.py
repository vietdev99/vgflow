"""v2.65.0 A4 — Review fix-loop iteration cap + per-iteration telemetry."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def review_md_text():
    return (REPO / "commands/vg/review.md").read_text(encoding="utf-8")


def _phase3_section(text):
    """Extract the Phase 3 fix loop step block.

    Spec example used `phase3_fix_loop.*?(?=phase\\d|## |\\Z)` but `## ` appears
    inside the step block (e.g. `## Phase 3:` heading), making the lookahead
    terminate inside the manifest entry on line 148. We target the canonical
    `<step name="phase3_fix_loop">...</step>` boundary instead — same intent,
    correct scope.
    """
    m = re.search(
        r'<step name="phase3_fix_loop".*?</step>',
        text,
        re.DOTALL,
    )
    return m.group(0) if m else None


def test_fix_loop_max_iterations_5(review_md_text):
    """Max iter bumped from 3 to 5 (multi-class violations need ~5 passes)."""
    section = _phase3_section(review_md_text)
    assert section, "phase3_fix_loop step block not found"

    m = re.search(
        r"max[\s_-]?iter(?:ations)?[\s:=]+(\d+)",
        section,
        re.IGNORECASE,
    )
    assert m, "max_iterations declaration not found in fix loop section"
    assert int(m.group(1)) == 5, f"expected max=5, found {m.group(1)}"


def test_fix_loop_emits_iteration_event(review_md_text):
    """Each fix loop iteration must emit review.fix_iteration_started event."""
    section = _phase3_section(review_md_text)
    assert section, "phase3_fix_loop step block not found"
    assert "review.fix_iteration_started" in section, (
        "Missing per-iteration telemetry event review.fix_iteration_started"
    )


def test_mirror_byte_identity():
    canonical = (REPO / "commands/vg/review.md").read_bytes()
    mirror = (REPO / ".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror
