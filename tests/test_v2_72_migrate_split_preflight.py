"""v2.72.0 T1 — migrate.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/migrate/preflight.md")
    assert p.exists(), "v2.72.0 T1 must create _shared/migrate/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/migrate/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "1_parse_args",
        "2_detect_artifacts",
        "3_backup_originals",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"preflight.md missing step tag: {s}"


def test_migrate_md_routes_to_preflight_subfile():
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    assert "_shared/migrate/preflight.md" in body, \
        "migrate.md must reference _shared/migrate/preflight.md after T1 split"


def test_migrate_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from migrate.md."""
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="1_parse_args">',
        '<step name="2_detect_artifacts">',
        '<step name="3_backup_originals">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"migrate.md still contains extracted step tag {tag} (should live in _shared/migrate/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/migrate/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/migrate/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/migrate/preflight.md mirrors must be byte-identical"


def test_migrate_md_mirror_byte_identity():
    canonical = Path("commands/vg/migrate.md").read_bytes()
    mirror = Path(".claude/commands/vg/migrate.md").read_bytes()
    assert canonical == mirror, "commands/vg/migrate.md mirrors must be byte-identical"
