"""v2.70.0 T6 — review.md limits-and-mobile section split."""
from pathlib import Path


def test_limits_mobile_subfile_exists():
    p = Path("commands/vg/_shared/review/limits-and-mobile.md")
    assert p.exists(), "v2.70.0 T6 must create _shared/review/limits-and-mobile.md"


def test_limits_mobile_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/limits-and-mobile.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase2_exploration_limits",
        "phase2_mobile_discovery",
        "phase2_5_visual_checks",
        "phase2_5_mobile_visual_checks",
    ]
    for s in expected_steps:
        assert s in body, f"limits-and-mobile.md missing step: {s}"


def test_review_md_routes_to_limits_mobile_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/limits-and-mobile.md" in body, \
        "review.md must reference _shared/review/limits-and-mobile.md after T6 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted limits-and-mobile step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase2_exploration_limits"',
        '<step name="phase2_mobile_discovery"',
        '<step name="phase2_5_visual_checks"',
        '<step name="phase2_5_mobile_visual_checks"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/limits-and-mobile.md)"


def test_limits_mobile_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/limits-and-mobile.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/limits-and-mobile.md").read_bytes()
    assert canonical == mirror, "_shared/review/limits-and-mobile.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
