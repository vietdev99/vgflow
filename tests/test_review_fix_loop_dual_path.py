"""v2.65.0 A6 — Fix-loop dual-path: Claude=Agent tool, Codex=codex-spawn.sh."""
import re
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent


def _review_md_full_text() -> str:
    """Concatenate review.md + all _shared/review/*.md sub-files (v2.70.0 split).

    v2.70.0 T8 moved phase3_fix_loop content to _shared/review/fix-loop-and-goals.md.
    Concatenation keeps these assertions independent of the split layout.
    """
    parts = [(REPO / "commands/vg/review.md").read_text(encoding="utf-8")]
    shared_review = REPO / "commands" / "vg" / "_shared" / "review"
    if shared_review.is_dir():
        for p in sorted(shared_review.glob("*.md")):
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.fixture
def review_md_text():
    return _review_md_full_text()


def test_fix_loop_branches_on_vg_runtime(review_md_text):
    """Phase 3 fix loop must branch on VG_RUNTIME for Codex vs Claude path."""
    # Find phase3 fix loop section
    fix_loop_match = re.search(
        r'<step name="phase3_fix_loop".*?</step>', review_md_text, re.DOTALL
    ) or re.search(r"phase3_fix_loop.*?(?=<step|## |\Z)", review_md_text, re.DOTALL)
    assert fix_loop_match, "Phase 3 fix loop section not found"
    section = fix_loop_match.group(0)

    # Codex branch: must reference codex-spawn.sh
    assert "codex-spawn.sh" in section, \
        "Fix loop must dual-path with codex-spawn.sh for VG_RUNTIME=codex"


def test_fix_loop_codex_uses_executor_tier(review_md_text):
    """Codex path must use --tier executor (not scanner — scanner is for read-only reviewers)."""
    fix_loop_match = re.search(
        r'<step name="phase3_fix_loop".*?</step>', review_md_text, re.DOTALL
    ) or re.search(r"phase3_fix_loop.*?(?=<step|## |\Z)", review_md_text, re.DOTALL)
    assert fix_loop_match
    section = fix_loop_match.group(0)
    assert re.search(r"codex-spawn\.sh\s+--tier\s+executor", section), \
        "Codex fix-agent must use --tier executor (write access for fixes)"


def test_fix_loop_claude_path_preserved(review_md_text):
    """Claude runtime path (Agent tool) must still be present."""
    fix_loop_match = re.search(
        r'<step name="phase3_fix_loop".*?</step>', review_md_text, re.DOTALL
    ) or re.search(r"phase3_fix_loop.*?(?=<step|## |\Z)", review_md_text, re.DOTALL)
    assert fix_loop_match
    section = fix_loop_match.group(0)
    # Either Agent( tool call or vg-narrate-spawn.sh narration must remain
    assert "Agent(" in section or "vg-narrate-spawn.sh" in section, \
        "Claude path (Agent tool / narrate-spawn) must be preserved"


def test_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror
