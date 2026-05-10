"""v2.72.0 T2 — migrate.md enrich section split."""
from pathlib import Path


def test_enrich_subfile_exists():
    p = Path("commands/vg/_shared/migrate/enrich.md")
    assert p.exists(), "v2.72.0 T2 must create _shared/migrate/enrich.md"


def test_enrich_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/migrate/enrich.md").read_text(encoding="utf-8")
    expected_steps = [
        "4_enrich_context",
        "5_generate_contracts",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"enrich.md missing step tag: {s}"


def test_migrate_md_routes_to_enrich_subfile():
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    assert "_shared/migrate/enrich.md" in body, \
        "migrate.md must reference _shared/migrate/enrich.md after T2 split"


def test_migrate_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted enrich step <step name=...> tags are gone from migrate.md."""
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="4_enrich_context">',
        '<step name="5_generate_contracts">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"migrate.md still contains extracted step tag {tag} (should live in _shared/migrate/enrich.md)"


def test_enrich_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/migrate/enrich.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/migrate/enrich.md").read_bytes()
    assert canonical == mirror, "_shared/migrate/enrich.md mirrors must be byte-identical"


def test_migrate_md_mirror_byte_identity():
    canonical = Path("commands/vg/migrate.md").read_bytes()
    mirror = Path(".claude/commands/vg/migrate.md").read_bytes()
    assert canonical == mirror, "commands/vg/migrate.md mirrors must be byte-identical"
