"""debug.md Step 1 runtime_ui branch MUST spawn vg-debug-ui-discovery."""
import re

from .conftest import grep_count


def test_debug_step1_runtime_ui_spawns_ui_discovery(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    # Look for spawn within Step 1 section
    step1_match = re.search(
        r"^## Step 1(.*?)^## Step 2",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert step1_match, "Step 1 section not found in debug.md"
    step1_body = step1_match.group(1)
    spawn_refs = len(re.findall(
        r'subagent_type=["\']vg-debug-ui-discovery["\']',
        step1_body,
    ))
    assert spawn_refs >= 1, (
        "debug.md Step 1 does not spawn vg-debug-ui-discovery; "
        "the runtime_ui branch must call Agent(subagent_type='vg-debug-ui-discovery', ...)"
    )


def test_debug_step1_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("debug")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-debug-ui-discovery",
    )
    assert narrate_calls >= 2, (
        f"debug.md MUST wrap ui-discovery spawn with at least 2 vg-narrate-spawn.sh "
        f"calls (spawning + returned/failed); found {narrate_calls}"
    )


def test_ui_discovery_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-debug-ui-discovery")
    assert agent["frontmatter"].get("name") == "vg-debug-ui-discovery"
    tools = agent["frontmatter"].get("tools", "")
    tools_str = " ".join(tools) if isinstance(tools, list) else str(tools)
    assert "mcp__playwright1__browser_navigate" in tools_str
    # Crude: ensure Write isn't in tools list (allow it inside descriptions)
    tool_tokens = [t.strip() for t in tools_str.replace(",", " ").split()]
    assert "Write" not in tool_tokens, "ui-discovery must not have Write tool"
    assert "Agent" not in tool_tokens
