"""v2.73.0 T10 — update.md sync + report section split (final extraction)."""
from pathlib import Path


def test_sync_and_report_subfile_exists():
    p = Path("commands/vg/_shared/update/sync-and-report.md")
    assert p.exists(), \
        "v2.73.0 T10 must create _shared/update/sync-and-report.md"


def test_sync_and_report_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/update/sync-and-report.md").read_text(encoding="utf-8")
    expected_steps = [
        "8_sync_codex",
        "8b_repair_playwright_mcp",
        "8c_ensure_graphify",
        "9_report",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, \
            f"sync-and-report.md missing step tag: {s}"


def test_update_md_routes_to_sync_and_report_subfile():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    assert "_shared/update/sync-and-report.md" in body, \
        "update.md must reference _shared/update/sync-and-report.md after T10"


def test_update_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="8_sync_codex">',
        '<step name="8b_repair_playwright_mcp">',
        '<step name="8c_ensure_graphify">',
        '<step name="9_report">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"update.md still contains extracted step tag {tag}"


def test_update_md_has_no_inline_step_tags_after_t10():
    """T10 is the final extraction — update.md should contain ZERO <step name=> tags."""
    body = Path("commands/vg/update.md").read_text(encoding="utf-8")
    assert '<step name="' not in body, \
        "update.md should have no inline step blocks after T10 (all extracted to _shared/update/*.md)"


def test_sync_and_report_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/update/sync-and-report.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/update/sync-and-report.md").read_bytes()
    assert canonical == mirror, \
        "_shared/update/sync-and-report.md mirrors must be byte-identical"


def test_update_md_mirror_byte_identity():
    canonical = Path("commands/vg/update.md").read_bytes()
    mirror = Path(".claude/commands/vg/update.md").read_bytes()
    assert canonical == mirror, "commands/vg/update.md mirrors must be byte-identical"
