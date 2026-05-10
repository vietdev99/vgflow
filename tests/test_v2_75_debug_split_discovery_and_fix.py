"""v2.75.0 T7 — debug.md discovery-and-fix section split."""
from pathlib import Path


def test_discovery_and_fix_subfile_exists():
    p = Path("commands/vg/_shared/debug/discovery-and-fix.md")
    assert p.exists(), "v2.75.0 T7 must create _shared/debug/discovery-and-fix.md"


def test_discovery_and_fix_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/debug/discovery-and-fix.md").read_text(encoding="utf-8")
    expected_steps = [
        "1_discovery",
        "2_hypothesize_and_fix",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"discovery-and-fix.md missing step tag: {s}"


def test_debug_md_routes_to_discovery_and_fix_subfile():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    assert "_shared/debug/discovery-and-fix.md" in body, \
        "debug.md must reference _shared/debug/discovery-and-fix.md after T7 split"


def test_debug_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="1_discovery">',
        '<step name="2_hypothesize_and_fix">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"debug.md still contains extracted step tag {tag} (should live in _shared/debug/discovery-and-fix.md)"


def test_discovery_and_fix_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/debug/discovery-and-fix.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/debug/discovery-and-fix.md").read_bytes()
    assert canonical == mirror, "_shared/debug/discovery-and-fix.md mirrors must be byte-identical"


def test_debug_md_mirror_byte_identity():
    canonical = Path("commands/vg/debug.md").read_bytes()
    mirror = Path(".claude/commands/vg/debug.md").read_bytes()
    assert canonical == mirror, "commands/vg/debug.md mirrors must be byte-identical"
