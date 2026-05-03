"""Schema smoke tests for every VGFlow Codex hook event."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_HOOKS = REPO_ROOT / "scripts" / "codex-hooks"


def _run_hook(hook: Path, root: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    env["VG_RUNTIME"] = "codex"
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def _assert_codex_pass_stdout(stdout: str) -> None:
    if not stdout:
        return
    payload = json.loads(stdout)
    assert payload.get("continue") is True
    assert payload.get("decision") != "approve"


def _copy_file(src: Path, dst: Path, *, executable: bool = False) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    if executable:
        dst.chmod(0o755)


def _install_forwarded_hook_targets(root: Path) -> None:
    _copy_file(
        REPO_ROOT / "scripts" / "codex-hooks" / "vg-codex-spawn-guard.py",
        root / ".claude" / "scripts" / "codex-hooks" / "vg-codex-spawn-guard.py",
    )
    _copy_file(
        REPO_ROOT / "scripts" / "codex-hooks" / "vg_codex_hook_lib.py",
        root / ".claude" / "scripts" / "codex-hooks" / "vg_codex_hook_lib.py",
    )
    _copy_file(
        REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh",
        root / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh",
        executable=True,
    )
    _copy_file(
        REPO_ROOT / "scripts" / "vg-step-tracker.py",
        root / ".claude" / "scripts" / "vg-step-tracker.py",
    )


def test_codex_user_prompt_submit_pass_schema(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    result = _run_hook(
        REPO_ROOT / "scripts" / "vg-entry-hook.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "hello",
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"continue": True}


def test_codex_pre_tool_use_bash_noop_has_empty_stdout(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _install_forwarded_hook_targets(root)
    result = _run_hook(
        CODEX_HOOKS / "vg-pre-tool-use-bash.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo ok"},
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_codex_pre_tool_use_bash_block_has_empty_stdout(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _install_forwarded_hook_targets(root)
    active = root / ".vg" / "active-runs" / "schema-sess.json"
    active.parent.mkdir(parents=True)
    active.write_text(
        json.dumps({"run_id": "run-1", "command": "vg:build", "phase": "1"}),
        encoding="utf-8",
    )
    result = _run_hook(
        CODEX_HOOKS / "vg-pre-tool-use-bash.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "vg-orchestrator step-active build 1"},
        },
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "PreToolUse-tasklist" in result.stderr


def test_codex_pre_tool_use_apply_patch_block_has_empty_stdout(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    result = _run_hook(
        CODEX_HOOKS / "vg-pre-tool-use-apply-patch.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n"
                "*** Add File: .vg/phases/1/.step-markers/9_post_execution.done\n"
                "+done\n"
                "*** End Patch\n"
            },
        },
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "PreToolUse-ApplyPatch-protected" in result.stderr


def test_codex_post_tool_use_bash_noop_has_empty_stdout(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _install_forwarded_hook_targets(root)
    result = _run_hook(
        CODEX_HOOKS / "vg-post-tool-use-bash.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo ok"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_codex_stop_pass_schema(tmp_path):
    root = tmp_path / "project"
    verifier = root / ".claude" / "scripts" / "vg-verify-claim.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        "import json\nprint(json.dumps({'decision': 'approve'}))\n",
        encoding="utf-8",
    )
    result = _run_hook(
        CODEX_HOOKS / "vg-stop.py",
        root,
        {
            "session_id": "schema-sess",
            "cwd": str(root),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        },
    )
    assert result.returncode == 0, result.stderr
    _assert_codex_pass_stdout(result.stdout)
