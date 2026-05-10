"""v2.75.0 T1 — specs.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/specs/preflight.md")
    assert p.exists(), "v2.75.0 T1 must create _shared/specs/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/specs/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "create_task_tracker",
        "parse_args",
        "check_existing",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"preflight.md missing step tag: {s}"


def test_specs_md_routes_to_preflight_subfile():
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    assert "_shared/specs/preflight.md" in body, \
        "specs.md must reference _shared/specs/preflight.md after T1 split"


def test_specs_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from specs.md."""
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="create_task_tracker">',
        '<step name="parse_args">',
        '<step name="check_existing">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"specs.md still contains extracted step tag {tag} (should live in _shared/specs/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/specs/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/specs/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/specs/preflight.md mirrors must be byte-identical"


def test_specs_md_mirror_byte_identity():
    canonical = Path("commands/vg/specs.md").read_bytes()
    mirror = Path(".claude/commands/vg/specs.md").read_bytes()
    assert canonical == mirror, "commands/vg/specs.md mirrors must be byte-identical"
