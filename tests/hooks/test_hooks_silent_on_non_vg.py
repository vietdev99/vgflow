"""Regression — every hook silently exits when no VG run is active.

Locked by R5.5 design §3.1. Exception: vg-pre-tool-use-write.sh is
filesystem-scoped (test_write_protection_unconditional.py covers it).
"""
import json

import pytest

from .conftest import run_hook


def _agent_input(subagent_type: str) -> str:
    return json.dumps({"tool_input": {"subagent_type": subagent_type}})


def test_agent_hook_silent_when_no_active_run_and_non_allowlist_subagent(
    tmp_workspace,
):
    """Spawn from non-VG context with non-allow-list subagent must NOT block.

    Pre-R5.5 behavior: hook checked allow-list unconditionally and
    blocked any subagent outside {general-purpose|Explore|Plan|gsd-debugger|vg-*}.
    Post-R5.5: hook MUST exit 0 silently because there is no active VG run.
    """
    result = run_hook(
        "agent",
        stdin=_agent_input("statusline-setup"),  # not in allow-list
    )
    assert result.returncode == 0, (
        f"hook blocked non-VG spawn: stderr={result.stderr!r}"
    )
    assert result.stderr == "", (
        f"hook printed stderr on silent path: {result.stderr!r}"
    )


def test_agent_hook_still_enforces_allowlist_when_run_active(vg_active_run):
    """When VG run IS active, allow-list enforcement MUST still fire."""
    result = run_hook(
        "agent",
        stdin=_agent_input("statusline-setup"),  # not in allow-list
    )
    assert result.returncode == 2, (
        f"hook should have blocked non-allow-list spawn during VG run; "
        f"got rc={result.returncode}, stderr={result.stderr!r}"
    )
    assert "PreToolUse-Agent-allowlist" in result.stderr, (
        "expected gate_id in stderr"
    )


def test_agent_hook_allows_vg_subagent_when_run_active(vg_active_run):
    """vg-* subagents allowed during active VG run."""
    result = run_hook(
        "agent",
        stdin=_agent_input("vg-deploy-executor"),
    )
    assert result.returncode == 0
    assert result.stderr == ""


# ── Parametrized regression for hooks that already had correct guards ──
#
# These hooks were already correct pre-R5.5; the parametrized tests lock
# them so future edits cannot regress.
#
# We feed each hook a stdin payload its matcher would normally see;
# all must exit 0 silently when no .vg/active-runs/ file exists.

@pytest.mark.parametrize("hook_name,stdin_payload", [
    (
        "bash",
        json.dumps({"tool_input": {
            "command": "vg-orchestrator step-active --step blueprint-design"
        }}),
    ),
    (
        "post-todowrite",
        json.dumps({"tool_input": {"todos": [
            {"content": "x", "status": "pending", "activeForm": "doing x"}
        ]}}),
    ),
    (
        "stop",
        "",  # stop hook reads no meaningful stdin
    ),
    (
        "user-prompt-submit",
        json.dumps({"prompt": "/superpowers:brainstorming"}),
    ),
])
def test_existing_hooks_silent_when_no_active_run(
    tmp_workspace, hook_name, stdin_payload
):
    result = run_hook(hook_name, stdin=stdin_payload)
    assert result.returncode == 0, (
        f"{hook_name} broke silent-on-non-VG contract; "
        f"rc={result.returncode}, stderr={result.stderr!r}"
    )
    assert result.stderr == "", (
        f"{hook_name} leaked stderr: {result.stderr!r}"
    )
