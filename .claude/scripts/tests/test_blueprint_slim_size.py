from pathlib import Path

BLUEPRINT = Path(__file__).resolve().parents[1].parent / "commands/vg/blueprint.md"


def test_blueprint_slim():
    lines = BLUEPRINT.read_text().splitlines()
    assert len(lines) <= 600, f"blueprint.md exceeds 600 lines (got {len(lines)})"


def test_blueprint_imperative_language():
    body = BLUEPRINT.read_text()
    assert "<HARD-GATE>" in body
    assert "Red Flags" in body
    assert "MUST" in body
    assert "STEP 1" in body
    forbidden_in_imperative = [" should call ", " may call ", " will call "]
    for phrase in forbidden_in_imperative:
        assert phrase not in body.lower(), f"forbidden descriptive phrase: '{phrase}'"


def test_blueprint_refs_listed_directly():
    body = BLUEPRINT.read_text()
    expected_refs = [
        "_shared/blueprint/preflight.md",
        "_shared/blueprint/design.md",
        "_shared/blueprint/plan-overview.md",
        "_shared/blueprint/plan-delegation.md",
        "_shared/blueprint/contracts-overview.md",
        "_shared/blueprint/contracts-delegation.md",
        "_shared/blueprint/verify.md",
        "_shared/blueprint/close.md",
    ]
    for ref in expected_refs:
        assert ref in body, f"entry SKILL.md must directly list leaf ref: {ref}"


def test_blueprint_uses_agent_not_task():
    body = BLUEPRINT.read_text()
    # Tool name "Agent" must appear in allowed-tools and instructions
    assert "Agent" in body, "must use Agent tool name (Codex fix #3)"
    # Avoid "Task(" or "subagent_type=...)" with Task tool name in invocation context
    # (some Task references in description text are OK; what matters is the actual invocation pattern)
    # Check allowed-tools list does NOT have "- Task" (deprecated naming for VG context):
    assert "\n  - Task\n" not in body, "allowed-tools should use Agent, not Task"
