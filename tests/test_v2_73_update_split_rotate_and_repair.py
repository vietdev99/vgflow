"""v2.73.0 T9 — update.md rotate + repair section split."""
from pathlib import Path


def test_rotate_and_repair_subfile_exists():
    p = Path("commands/vg/_shared/update/rotate-and-repair.md")
    assert p.exists(), \
        "v2.73.0 T9 must create _shared/update/rotate-and-repair.md"


def test_rotate_and_repair_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/update/rotate-and-repair.md").read_text(encoding="utf-8")
    expected_steps = [
        "7_rotate_ancestor_and_version",
        "7b_repair_hooks",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, \
            f"rotate-and-repair.md missing step tag: {s}"


def test_update_md_routes_to_rotate_and_repair_subfile():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    assert "_shared/update/rotate-and-repair.md" in body, \
        "update.md must reference _shared/update/rotate-and-repair.md after T9"


def test_update_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="7_rotate_ancestor_and_version">',
        '<step name="7b_repair_hooks">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"update.md still contains extracted step tag {tag}"


def test_rotate_and_repair_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/update/rotate-and-repair.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/update/rotate-and-repair.md").read_bytes()
    assert canonical == mirror, \
        "_shared/update/rotate-and-repair.md mirrors must be byte-identical"


def test_update_md_mirror_byte_identity():
    canonical = Path("commands/vg/update.md").read_bytes()
    mirror = Path(".claude/commands/vg/update.md").read_bytes()
    assert canonical == mirror, "commands/vg/update.md mirrors must be byte-identical"
