"""v2.73.0 T7 — update.md version + changelog section split."""
from pathlib import Path


def test_version_and_changelog_subfile_exists():
    p = Path("commands/vg/_shared/update/version-and-changelog.md")
    assert p.exists(), \
        "v2.73.0 T7 must create _shared/update/version-and-changelog.md"


def test_version_and_changelog_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/update/version-and-changelog.md").read_text(encoding="utf-8")
    expected_steps = [
        "2_version_compare",
        "3_changelog_preview",
        "4_breaking_gate",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, \
            f"version-and-changelog.md missing step tag: {s}"


def test_update_md_routes_to_version_and_changelog_subfile():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    assert "_shared/update/version-and-changelog.md" in body, \
        "update.md must reference _shared/update/version-and-changelog.md after T7"


def test_update_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="2_version_compare">',
        '<step name="3_changelog_preview">',
        '<step name="4_breaking_gate">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"update.md still contains extracted step tag {tag}"


def test_version_and_changelog_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/update/version-and-changelog.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/update/version-and-changelog.md").read_bytes()
    assert canonical == mirror, \
        "_shared/update/version-and-changelog.md mirrors must be byte-identical"


def test_update_md_mirror_byte_identity():
    canonical = Path("commands/vg/update.md").read_bytes()
    mirror = Path(".claude/commands/vg/update.md").read_bytes()
    assert canonical == mirror, "commands/vg/update.md mirrors must be byte-identical"
