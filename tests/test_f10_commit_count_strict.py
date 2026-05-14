"""tests/test_f10_commit_count_strict.py — F10 commit count strict equality."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
WAVES = REPO / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"


def test_commit_count_blocks_both_directions():
    body = WAVES.read_text(encoding="utf-8")
    # Find the audit block
    idx = body.find("EXPECTED_COMMITS")
    assert idx > 0
    block = body[idx:idx + 2000]
    # Old behavior: `[ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]` (< only)
    # New behavior: != check OR both -lt + -gt
    has_strict_eq = (
        "ACTUAL_COMMITS\" != \"$EXPECTED_COMMITS" in block or
        "ACTUAL_COMMITS != EXPECTED_COMMITS" in block or
        ("-lt" in block and "-gt" in block) or
        "-ne" in block
    )
    assert has_strict_eq, (
        "F10: commit count audit must reject ACTUAL != EXPECTED (both "
        "directions). Old code blocked only ACTUAL < EXPECTED; extra "
        "commits passed audit silently."
    )


def test_extra_commits_message_present():
    body = WAVES.read_text(encoding="utf-8")
    # Should mention extra commit case
    assert ("extra" in body.lower() or "more than" in body.lower() or "exceed" in body.lower()) and "commit" in body.lower(), (
        "F10: error message must distinguish missing vs extra commits "
        "so operator knows which case fired"
    )
