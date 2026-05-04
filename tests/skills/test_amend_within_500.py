"""amend.md MUST stay <= 500 lines after refactor."""
SLIM_LIMIT = 500


def test_amend_within_500_lines(skill_loader):
    skill = skill_loader("amend")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/amend.md is {skill['lines']} lines (limit {SLIM_LIMIT})"
    )
