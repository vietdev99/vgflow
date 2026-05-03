from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "commands/vg/build.md"


def test_build_slim():
    text = ENTRY.read_text()
    lines = text.splitlines()
    assert len(lines) <= 600, f"build.md exceeds 600 lines (got {len(lines)})"


def test_build_imperative_language():
    text = ENTRY.read_text().lower()
    # Must use imperative (You MUST/DO NOT) per Anthropic SKILL.md guidance
    assert "you must" in text, "build.md missing 'You MUST' imperative phrasing"
    assert "do not" in text or "must not" in text, "build.md missing 'Do not'/'MUST NOT'"


def test_build_uses_agent_not_task():
    text = ENTRY.read_text()
    # Tool name is Agent, not Task (Codex correction baked into R1a)
    assert "Agent(subagent_type=" in text or "subagent_type=" in text, "build.md should reference Agent tool"


def test_build_refs_listed_directly():
    text = ENTRY.read_text()
    expected = [
        "_shared/build/preflight.md",
        "_shared/build/context.md",
        "_shared/build/validate-blueprint.md",
        "_shared/build/waves-overview.md",
        "_shared/build/post-execution-overview.md",
        "_shared/build/crossai-loop.md",
        "_shared/build/close.md",
    ]
    for ref in expected:
        assert ref in text, f"build.md missing reference to {ref}"
