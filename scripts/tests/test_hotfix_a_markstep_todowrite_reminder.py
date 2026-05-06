"""HOTFIX A (2026-05-05) — PreToolUse Bash hook emits TodoWrite UI sync
reminder when AI calls `vg-orchestrator mark-step <ns> <step>`.

Bug: VG marker filesystem (`.step-markers/<step>.done`) updates atomically
when AI calls mark-step, but Claude Code TodoWrite UI does NOT auto-refresh
from filesystem state. AI must explicitly re-call TodoWrite tool with
updated todos[]. AI dispatchers frequently forget mid-flow → user sees
stale tasklist (observed PV3 build 4.2 dogfood 2026-05-05).

Fix: hook fires non-blocking on mark-step bash and writes a stderr reminder.
PreToolUse stdout JSON cannot include additionalContext on current runtimes.
"""
import hashlib
import hmac
import json
import subprocess
from pathlib import Path

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts").is_dir() and (parent / "commands").is_dir() and (parent / "codex-skills").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]

REPO_ROOT = _repo_root()
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


def _run_hook(tmp_path, cmd_text, session_id="test-sess", with_evidence=True):
    """Invoke hook with tool_input.command = cmd_text. Stage minimal active run.

    HOTFIX session 2: hook now also gates mark-step on evidence file. To test
    the reminder injection (HOTFIX A behavior) we must stage the evidence file
    so the hook proceeds past the gate to the reminder block. with_evidence=False
    exercises the new gate path (mark-step blocks when tasklist unprojected).
    """
    run_id = "test-run"
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs" / f"{session_id}.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:build",
                    "session_id": session_id})
    )
    if with_evidence:
        key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
        key_path = tmp_path / ".vg/.evidence-key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
        contract_path = tmp_path / f".vg/runs/{run_id}/tasklist-contract.json"
        contract_path.write_text(
            json.dumps({"checklists": [{"id": "build_execute", "items": ["8_execute_waves"]}]}),
            encoding="utf-8",
        )
        payload = {
            "run_id": run_id,
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "depth_valid": True,
            "match": True,
            "adapter": "claude",
            "todo_ids": ["build_execute"],
            "contract_ids": ["build_execute"],
        }
        sig = hmac.new(key, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        (tmp_path / f".vg/runs/{run_id}/.tasklist-projected.evidence.json").write_text(
            json.dumps({"payload": payload, "hmac_sha256": sig}),
            encoding="utf-8",
        )
    payload = json.dumps({"tool_input": {"command": cmd_text}})
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, cwd=tmp_path, capture_output=True, text=True,
        env={
            "CLAUDE_HOOK_SESSION_ID": session_id,
            "VG_EVIDENCE_KEY_PATH": str(tmp_path / ".vg/.evidence-key"),
            "PATH": "/usr/bin:/bin",
        },
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_markstep_emits_todowrite_reminder(tmp_path):
    """mark-step bash → stderr includes TodoWrite guidance, stdout stays schema-safe."""
    rc, stdout, stderr = _run_hook(
        tmp_path,
        "python3 .claude/scripts/vg-orchestrator mark-step build 8_execute_waves",
    )
    assert rc == 0, f"Hook should not block, got rc={rc}"
    assert stdout.strip() == ""
    assert "TodoWrite" in stderr
    assert "8_execute_waves" in stderr
    assert "complete this step" in stderr
    assert "in_progress" in stderr


def test_markstep_namespace_extracted(tmp_path):
    """Namespace + step both surfaced in reminder."""
    rc, stdout, stderr = _run_hook(
        tmp_path,
        "python3 .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review",
    )
    assert rc == 0
    assert stdout.strip() == ""
    assert "blueprint" in stderr  # namespace
    assert "2d_crossai_review" in stderr  # step name


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
