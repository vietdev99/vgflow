"""v2.73.0 T8 — update.md fetch + merge section split."""
from pathlib import Path


def test_fetch_and_merge_subfile_exists():
    p = Path("commands/vg/_shared/update/fetch-and-merge.md")
    assert p.exists(), \
        "v2.73.0 T8 must create _shared/update/fetch-and-merge.md"


def test_fetch_and_merge_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/update/fetch-and-merge.md").read_text(encoding="utf-8")
    expected_steps = [
        "5_fetch_tarball",
        "6_three_way_merge_per_file",
        "6b_verify_gate_integrity",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, \
            f"fetch-and-merge.md missing step tag: {s}"


def test_update_md_routes_to_fetch_and_merge_subfile():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    assert "_shared/update/fetch-and-merge.md" in body, \
        "update.md must reference _shared/update/fetch-and-merge.md after T8"


def test_update_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="5_fetch_tarball">',
        '<step name="6_three_way_merge_per_file">',
        '<step name="6b_verify_gate_integrity">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"update.md still contains extracted step tag {tag}"


def test_fetch_and_merge_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/update/fetch-and-merge.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/update/fetch-and-merge.md").read_bytes()
    assert canonical == mirror, \
        "_shared/update/fetch-and-merge.md mirrors must be byte-identical"


def test_update_md_mirror_byte_identity():
    canonical = Path("commands/vg/update.md").read_bytes()
    mirror = Path(".claude/commands/vg/update.md").read_bytes()
    assert canonical == mirror, "commands/vg/update.md mirrors must be byte-identical"
