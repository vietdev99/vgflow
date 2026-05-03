"""debug.md MUST stay <= 600 lines after refactor.

Original R6b plan ceiling was 500; bumped to 600 after commit a8318aa
ported 3 features from gsd:debug (resume, checkpoint, isolate) adding
~119 lines of legitimate scope. R6b runtime_ui refactor adds ~30 lines
of spawn/narrate boilerplate that pushes us toward 550.
"""
SLIM_LIMIT = 600


def test_debug_within_500_lines(skill_loader):
    skill = skill_loader("debug")
    assert skill["lines"] <= SLIM_LIMIT, (
        f"commands/vg/debug.md is {skill['lines']} lines (limit {SLIM_LIMIT})"
    )
