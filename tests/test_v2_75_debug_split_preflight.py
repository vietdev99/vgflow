"""v2.75.0 T6 — debug.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/debug/preflight.md")
    assert p.exists(), "v2.75.0 T6 must create _shared/debug/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/debug/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "0_parse_and_classify",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"preflight.md missing step tag: {s}"


def test_debug_md_routes_to_preflight_subfile():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    assert "_shared/debug/preflight.md" in body, \
        "debug.md must reference _shared/debug/preflight.md after T6 split"


def test_debug_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="0_parse_and_classify">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"debug.md still contains extracted step tag {tag} (should live in _shared/debug/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/debug/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/debug/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/debug/preflight.md mirrors must be byte-identical"


def test_debug_md_mirror_byte_identity():
    canonical = Path("commands/vg/debug.md").read_bytes()
    mirror = Path(".claude/commands/vg/debug.md").read_bytes()
    assert canonical == mirror, "commands/vg/debug.md mirrors must be byte-identical"
