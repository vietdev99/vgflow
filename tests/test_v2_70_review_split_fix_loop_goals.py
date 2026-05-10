"""v2.70.0 T8 — review.md fix-loop-and-goals section split (largest extraction)."""
from pathlib import Path


def test_fix_loop_goals_subfile_exists():
    p = Path("commands/vg/_shared/review/fix-loop-and-goals.md")
    assert p.exists(), "v2.70.0 T8 must create _shared/review/fix-loop-and-goals.md"


def test_fix_loop_goals_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/fix-loop-and-goals.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase3_fix_loop",
        "phase4_goal_comparison",
    ]
    for s in expected_steps:
        assert s in body, f"fix-loop-and-goals.md missing step: {s}"


def test_review_md_routes_to_fix_loop_goals_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/fix-loop-and-goals.md" in body, \
        "review.md must reference _shared/review/fix-loop-and-goals.md after T8 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted fix-loop-and-goals step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase3_fix_loop"',
        '<step name="phase4_goal_comparison"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/fix-loop-and-goals.md)"


def test_fix_loop_goals_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/fix-loop-and-goals.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/fix-loop-and-goals.md").read_bytes()
    assert canonical == mirror, "_shared/review/fix-loop-and-goals.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
