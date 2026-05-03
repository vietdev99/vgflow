"""amend.md Step 5 MUST spawn vg-amend-cascade-analyzer with narrate-spawn."""
import re

from .conftest import grep_count


def test_amend_step5_spawns_cascade_analyzer(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-amend-cascade-analyzer["\']',
    )
    assert spawn_refs >= 1, (
        "amend.md does not spawn vg-amend-cascade-analyzer; "
        "Step 5 must call Agent(subagent_type='vg-amend-cascade-analyzer', ...)"
    )


def test_amend_step5_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-amend-cascade-analyzer",
    )
    assert narrate_calls >= 2, (
        f"amend.md MUST wrap analyzer spawn with at least 2 vg-narrate-spawn.sh "
        f"calls (spawning + returned/failed); found {narrate_calls}"
    )


def test_amend_step5_section_exists(skill_loader):
    skill = skill_loader("amend")
    body = skill["body"]
    assert re.search(r"^## Step 5", body, flags=re.MULTILINE), (
        "Step 5 section header missing from amend.md body"
    )


def test_cascade_analyzer_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-amend-cascade-analyzer")
    assert agent["frontmatter"].get("name") == "vg-amend-cascade-analyzer"
    tools = agent["frontmatter"].get("tools", "")
    tools_str = " ".join(tools) if isinstance(tools, list) else str(tools)
    assert "Write" not in tools_str, "analyzer must be read-only"
    assert "Edit" not in tools_str
    assert "Agent" not in tools_str
