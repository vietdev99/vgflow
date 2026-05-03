"""
Static tests for the two subagents spawned by vg:test:
  - agents/vg-test-codegen/SKILL.md
  - agents/vg-test-goal-verifier/SKILL.md

Uses stdlib only (no PyYAML required); falls back to a manual frontmatter
parser that reads the --- delimited block and processes simple key: value
and key: [list] lines.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBAGENTS_DIR = REPO_ROOT / "agents"


# ---------------------------------------------------------------------------
# Frontmatter parser (stdlib, no PyYAML)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
    """
    Extract and parse YAML frontmatter between the first pair of '---' fences.
    Handles:
      name: value
      tools: [Read, Write, Edit]
      model: sonnet
    Returns a dict; raises ValueError if frontmatter block not found.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("No opening '---' frontmatter fence found")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("No closing '---' frontmatter fence found")

    fm_lines = lines[1:end_idx]
    result = {}
    for line in fm_lines:
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()
        # Inline list: [Read, Write, Edit]
        if raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1]
            result[key] = [item.strip() for item in inner.split(",") if item.strip()]
        else:
            result[key] = raw_val
    return result


def _body_after_frontmatter(text: str) -> str:
    """Return the body text after the closing '---' frontmatter fence."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1:])
    return text


# ---------------------------------------------------------------------------
# Shared assertions helper
# ---------------------------------------------------------------------------

def _assert_subagent(skill_path: Path, expected_name: str):
    assert skill_path.exists(), f"SKILL.md not found: {skill_path}"
    text = skill_path.read_text()

    # 1. Frontmatter parses
    fm = _parse_frontmatter(text)

    # 2. name field matches
    assert fm.get("name") == expected_name, (
        f"Expected name={expected_name!r}, got {fm.get('name')!r}"
    )

    # 3. tools is a non-empty list
    tools = fm.get("tools")
    assert isinstance(tools, list) and len(tools) > 0, (
        f"tools field must be a non-empty list, got: {tools!r}"
    )

    # 4. Task is NOT in tools — no recursive spawn
    assert "Task" not in tools, (
        f"'Task' found in tools for {expected_name} — recursive spawn forbidden. "
        f"tools={tools}"
    )

    # 5. model field is set
    model = fm.get("model", "")
    assert model, f"model field not set in {skill_path}"
    assert "sonnet" in model.lower(), (
        f"Expected sonnet model, got {model!r} in {skill_path}"
    )

    # 6. HARD-GATE block present in body
    body = _body_after_frontmatter(text)
    assert "<HARD-GATE>" in body, f"<HARD-GATE> block missing in {skill_path}"

    # 7. Body mentions vg-load (mandatory consumer pattern)
    assert "vg-load" in body, (
        f"'vg-load' not found in body of {skill_path} — mandatory consumer pattern required"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_codegen_subagent_valid():
    """vg-test-codegen SKILL.md must be structurally valid."""
    _assert_subagent(
        SUBAGENTS_DIR / "vg-test-codegen" / "SKILL.md",
        expected_name="vg-test-codegen",
    )


def test_goal_verifier_subagent_valid():
    """vg-test-goal-verifier SKILL.md must be structurally valid."""
    _assert_subagent(
        SUBAGENTS_DIR / "vg-test-goal-verifier" / "SKILL.md",
        expected_name="vg-test-goal-verifier",
    )


def test_codegen_no_recursive_spawn():
    """
    vg-test-codegen must NOT have 'Task' in its allowed-tools list.
    This is the critical no-recursive-spawn assertion: the codegen subagent
    must not be able to spawn further subagents via the Task tool.
    """
    skill_path = SUBAGENTS_DIR / "vg-test-codegen" / "SKILL.md"
    assert skill_path.exists(), f"SKILL.md not found: {skill_path}"
    fm = _parse_frontmatter(skill_path.read_text())
    tools = fm.get("tools", [])
    assert isinstance(tools, list), f"tools field is not a list: {tools!r}"
    assert "Task" not in tools, (
        f"'Task' in allowed-tools for vg-test-codegen — recursive spawn is forbidden. "
        f"Current tools: {tools}"
    )
