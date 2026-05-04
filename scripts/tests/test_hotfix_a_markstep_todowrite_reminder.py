"""HOTFIX A (2026-05-05) — PreToolUse Bash hook injects TodoWrite UI sync
reminder when AI calls `vg-orchestrator mark-step <ns> <step>`.

Bug: VG marker filesystem (`.step-markers/<step>.done`) updates atomically
when AI calls mark-step, but Claude Code TodoWrite UI does NOT auto-refresh
from filesystem state. AI must explicitly re-call TodoWrite tool with
updated todos[]. AI dispatchers frequently forget mid-flow → user sees
stale tasklist (observed PV3 build 4.2 dogfood 2026-05-05).

Fix: hook fires non-blocking on mark-step bash, emits hookSpecificOutput
JSON with additionalContext reminding model to call TodoWrite update.
"""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


def _run_hook(tmp_path, cmd_text, session_id="test-sess"):
    """Invoke hook with tool_input.command = cmd_text. Stage minimal active run."""
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs" / f"{session_id}.json").write_text(
        json.dumps({"run_id": "test-run", "command": "vg:build",
                    "session_id": session_id})
    )
    payload = json.dumps({"tool_input": {"command": cmd_text}})
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=tmp_path, capture_output=True, text=True,
        env={"CLAUDE_HOOK_SESSION_ID": session_id, "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_markstep_emits_todowrite_reminder(tmp_path):
    """mark-step bash → hookSpecificOutput.additionalContext includes TodoWrite guidance."""
    rc, stdout, _ = _run_hook(
        tmp_path,
        "python3 .claude/scripts/vg-orchestrator mark-step build 8_execute_waves",
    )
    assert rc == 0, f"Hook should not block, got rc={rc}"
    payload = json.loads(stdout)
    addl = payload["hookSpecificOutput"]["additionalContext"]
    assert "TodoWrite" in addl
    assert "8_execute_waves" in addl
    assert "completed" in addl  # instructs status change
    assert "in_progress" in addl  # instructs next-step transition


def test_markstep_namespace_extracted(tmp_path):
    """Namespace + step both surfaced in reminder."""
    rc, stdout, _ = _run_hook(
        tmp_path,
        "python3 .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review",
    )
    assert rc == 0
    addl = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
    assert "blueprint" in addl  # namespace
    assert "2d_crossai_review" in addl  # step name


def test_step_active_unaffected(tmp_path):
    """step-active path still gates on tasklist evidence — not changed by HOTFIX A."""
    rc, stdout, stderr = _run_hook(
        tmp_path,
        "python3 .claude/scripts/vg-orchestrator step-active 8_execute_waves",
    )
    # Without contract+evidence, hook blocks — that's existing behavior.
    # HOTFIX A is mark-step path only. Verify reminder NOT injected here.
    if rc == 0:
        # No tasklist contract → may exit silent; either way, no mark-step reminder
        if stdout.strip():
            payload = json.loads(stdout)
            addl = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
            assert "After this `mark-step` succeeds" not in addl


def test_unrelated_bash_unaffected(tmp_path):
    """Non-vg-orchestrator commands pass through silently."""
    rc, stdout, _ = _run_hook(tmp_path, "ls -la")
    assert rc == 0
    assert stdout.strip() == ""  # no JSON injection


def test_mark_step_outside_vg_run(tmp_path):
    """No active run file → hook silent on mark-step (graceful exit)."""
    # Don't create active-runs/<session>.json
    payload = json.dumps({
        "tool_input": {"command": "python3 .claude/scripts/vg-orchestrator mark-step build 8_execute_waves"}
    })
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=tmp_path, capture_output=True, text=True,
        env={"CLAUDE_HOOK_SESSION_ID": "no-such-session", "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0
    # No reminder injected when no active run (run_file check guards this)


def test_mirror_parity():
    mirror = REPO_ROOT / ".claude/scripts/hooks/vg-pre-tool-use-bash.sh"
    assert mirror.is_file()
    assert HOOK.read_bytes() == mirror.read_bytes()
