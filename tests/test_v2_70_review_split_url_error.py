"""v2.70.0 T7 — review.md url-and-error section split."""
from pathlib import Path


def test_url_error_subfile_exists():
    p = Path("commands/vg/_shared/review/url-and-error.md")
    assert p.exists(), "v2.70.0 T7 must create _shared/review/url-and-error.md"


def test_url_error_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/url-and-error.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase2_7_url_state_sync",
        "phase2_8_url_state_runtime",
        "phase2_9_error_message_runtime",
    ]
    for s in expected_steps:
        assert s in body, f"url-and-error.md missing step: {s}"


def test_review_md_routes_to_url_error_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/url-and-error.md" in body, \
        "review.md must reference _shared/review/url-and-error.md after T7 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted url-and-error step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase2_7_url_state_sync"',
        '<step name="phase2_8_url_state_runtime"',
        '<step name="phase2_9_error_message_runtime"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/url-and-error.md)"


def test_url_error_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/url-and-error.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/url-and-error.md").read_bytes()
    assert canonical == mirror, "_shared/review/url-and-error.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
