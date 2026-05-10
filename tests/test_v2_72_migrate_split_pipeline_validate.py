"""v2.72.0 T4 — migrate.md pipeline-and-validate section split (final)."""
from pathlib import Path


def test_pipeline_validate_subfile_exists():
    p = Path("commands/vg/_shared/migrate/pipeline-and-validate.md")
    assert p.exists(), \
        "v2.72.0 T4 must create _shared/migrate/pipeline-and-validate.md"


def test_pipeline_validate_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/migrate/pipeline-and-validate.md").read_text(encoding="utf-8")
    expected_steps = [
        "8_write_pipeline_state",
        "8b_backfill_infra",
        "9_validate_and_report",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, \
            f"pipeline-and-validate.md missing step tag: {s}"


def test_migrate_md_routes_to_pipeline_validate_subfile():
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    assert "_shared/migrate/pipeline-and-validate.md" in body, \
        "migrate.md must reference _shared/migrate/pipeline-and-validate.md after T4 split"


def test_migrate_md_no_longer_contains_extracted_step_bodies():
    """Verify all 4 v2.72.0 extracted step <step name=...> tags are gone from migrate.md."""
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="8_write_pipeline_state">',
        '<step name="8b_backfill_infra">',
        '<step name="9_validate_and_report">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"migrate.md still contains extracted step tag {tag} (should live in _shared/migrate/pipeline-and-validate.md)"


def test_migrate_md_has_no_step_tags_after_full_split():
    """T4 is the last extraction — migrate.md should have no `<step name=` tags left."""
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    assert "<step name=" not in body, \
        "After v2.72.0 T1-T4, migrate.md must contain zero <step name= tags (all step bodies live in _shared/migrate/*.md)"


def test_pipeline_validate_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/migrate/pipeline-and-validate.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/migrate/pipeline-and-validate.md").read_bytes()
    assert canonical == mirror, \
        "_shared/migrate/pipeline-and-validate.md mirrors must be byte-identical"


def test_migrate_md_mirror_byte_identity():
    canonical = Path("commands/vg/migrate.md").read_bytes()
    mirror = Path(".claude/commands/vg/migrate.md").read_bytes()
    assert canonical == mirror, "commands/vg/migrate.md mirrors must be byte-identical"
