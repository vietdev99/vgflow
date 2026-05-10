"""v2.74.0 T1 — scope-review.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/scope-review/preflight.md")
    assert p.exists(), "v2.74.0 T1 must create _shared/scope-review/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/scope-review/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "0_parse_and_collect",
        "incremental_check",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"preflight.md missing step tag: {s}"


def test_scope_review_md_routes_to_preflight_subfile():
    body = Path("commands/vg/scope-review.md").read_text(encoding="utf-8")
    assert "_shared/scope-review/preflight.md" in body, \
        "scope-review.md must reference _shared/scope-review/preflight.md after T1 split"


def test_scope_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from scope-review.md."""
    body = Path("commands/vg/scope-review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="0_parse_and_collect">',
        '<step name="incremental_check">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"scope-review.md still contains extracted step tag {tag} (should live in _shared/scope-review/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/scope-review/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/scope-review/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/scope-review/preflight.md mirrors must be byte-identical"


def test_scope_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/scope-review.md").read_bytes()
    mirror = Path(".claude/commands/vg/scope-review.md").read_bytes()
    assert canonical == mirror, "commands/vg/scope-review.md mirrors must be byte-identical"
