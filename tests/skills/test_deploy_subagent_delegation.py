"""Step 1 of deploy.md MUST spawn vg-deploy-executor with narrate-spawn wrap."""
import re

from .conftest import grep_count


def test_step1_spawns_executor(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    spawn_refs = grep_count(
        body,
        r'subagent_type=["\']vg-deploy-executor["\']',
    )
    assert spawn_refs >= 1, (
        "deploy.md does not spawn vg-deploy-executor anywhere; "
        "Step 1 must call Agent(subagent_type='vg-deploy-executor', ...) per env"
    )


def test_step1_wraps_spawn_with_narration(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    narrate_calls = grep_count(
        body,
        r"vg-narrate-spawn\.sh\s+vg-deploy-executor",
    )
    assert narrate_calls >= 2, (
        "deploy.md MUST wrap vg-deploy-executor spawn with at least 2 "
        "vg-narrate-spawn.sh calls (spawning + returned/failed); "
        f"found {narrate_calls}"
    )


def test_step1_section_exists(skill_loader):
    skill = skill_loader("deploy")
    body = skill["body"]
    assert re.search(r"^## Step 1", body, flags=re.MULTILINE), (
        "Step 1 section header missing from deploy.md body"
    )


def test_executor_agent_definition_exists(agent_loader):
    agent = agent_loader("vg-deploy-executor")
    assert agent["frontmatter"].get("name") == "vg-deploy-executor"
    tools = agent["frontmatter"].get("tools", "")
    if isinstance(tools, list):
        tools_str = " ".join(tools)
    else:
        tools_str = str(tools)
    assert "Agent" not in tools_str, (
        "executor must NOT have Agent tool (no nested spawns)"
    )
