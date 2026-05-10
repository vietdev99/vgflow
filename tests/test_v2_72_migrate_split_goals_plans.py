"""v2.72.0 T3 — migrate.md goals-plans section split."""
from pathlib import Path


def test_goals_plans_subfile_exists():
    p = Path("commands/vg/_shared/migrate/goals-plans.md")
    assert p.exists(), "v2.72.0 T3 must create _shared/migrate/goals-plans.md"


def test_goals_plans_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/migrate/goals-plans.md").read_text(encoding="utf-8")
    expected_steps = [
        "6_generate_goals",
        "6_5_link_plan_goals",
        "7_attribute_plans",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"goals-plans.md missing step tag: {s}"


def test_migrate_md_routes_to_goals_plans_subfile():
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    assert "_shared/migrate/goals-plans.md" in body, \
        "migrate.md must reference _shared/migrate/goals-plans.md after T3 split"


def test_migrate_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted goals-plans step <step name=...> tags are gone from migrate.md."""
    body = Path("commands/vg/migrate.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="6_generate_goals">',
        '<step name="6_5_link_plan_goals">',
        '<step name="7_attribute_plans">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"migrate.md still contains extracted step tag {tag} (should live in _shared/migrate/goals-plans.md)"


def test_goals_plans_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/migrate/goals-plans.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/migrate/goals-plans.md").read_bytes()
    assert canonical == mirror, "_shared/migrate/goals-plans.md mirrors must be byte-identical"


def test_migrate_md_mirror_byte_identity():
    canonical = Path("commands/vg/migrate.md").read_bytes()
    mirror = Path(".claude/commands/vg/migrate.md").read_bytes()
    assert canonical == mirror, "commands/vg/migrate.md mirrors must be byte-identical"
