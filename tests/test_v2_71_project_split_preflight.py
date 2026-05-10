"""v2.71.0 T1 — project.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/project/preflight.md")
    assert p.exists(), "v2.71.0 T1 must create _shared/project/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/project/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "0_parse_args",
        "0b_print_state_summary",
        "0c_scan_existing_docs",
    ]
    for s in expected_steps:
        assert s in body, f"preflight.md missing step: {s}"


def test_project_md_routes_to_preflight_subfile():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    assert "_shared/project/preflight.md" in body, \
        "project.md must reference _shared/project/preflight.md after T1 split"


def test_project_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from project.md."""
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="0_parse_args">',
        '<step name="0b_print_state_summary">',
        '<step name="0c_scan_existing_docs">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"project.md still contains extracted step tag {tag} (should live in _shared/project/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/project/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/project/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/project/preflight.md mirrors must be byte-identical"


def test_project_md_mirror_byte_identity():
    canonical = Path("commands/vg/project.md").read_bytes()
    mirror = Path(".claude/commands/vg/project.md").read_bytes()
    assert canonical == mirror, "commands/vg/project.md mirrors must be byte-identical"
