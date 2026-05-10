"""v2.75.0 T3 — specs.md write-and-commit section split."""
from pathlib import Path


def test_write_and_commit_subfile_exists():
    p = Path("commands/vg/_shared/specs/write-and-commit.md")
    assert p.exists(), "v2.75.0 T3 must create _shared/specs/write-and-commit.md"


def test_write_and_commit_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/specs/write-and-commit.md").read_text(encoding="utf-8")
    expected_steps = [
        "write_specs",
        "write_interface_standards",
        "commit_and_next",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"write-and-commit.md missing step tag: {s}"


def test_specs_md_routes_to_write_and_commit_subfile():
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    assert "_shared/specs/write-and-commit.md" in body, \
        "specs.md must reference _shared/specs/write-and-commit.md after T3 split"


def test_specs_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="write_specs">',
        '<step name="write_interface_standards">',
        '<step name="commit_and_next">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"specs.md still contains extracted step tag {tag} (should live in _shared/specs/write-and-commit.md)"


def test_write_and_commit_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/specs/write-and-commit.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/specs/write-and-commit.md").read_bytes()
    assert canonical == mirror, "_shared/specs/write-and-commit.md mirrors must be byte-identical"


def test_specs_md_mirror_byte_identity():
    canonical = Path("commands/vg/specs.md").read_bytes()
    mirror = Path(".claude/commands/vg/specs.md").read_bytes()
    assert canonical == mirror, "commands/vg/specs.md mirrors must be byte-identical"
