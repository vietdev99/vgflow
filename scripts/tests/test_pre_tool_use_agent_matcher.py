import json, os, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-pre-tool-use-agent.sh"


def test_agent_hook_passes_for_known_subagent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "vg-blueprint-planner", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_agent_hook_blocks_gsd_subagent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "gsd-executor", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "gsd" in result.stderr.lower() or "not allowed" in result.stderr.lower()


def test_agent_hook_passes_for_general_purpose():
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "general-purpose", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_agent_hook_passes_for_explore_and_plan():
    for sa in ("Explore", "Plan"):
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": sa, "prompt": "..."},
        })
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=payload, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{sa} should pass"


def test_agent_hook_passes_for_gsd_debugger_exception():
    payload = json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "gsd-debugger", "prompt": "..."},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0  # explicit exception
