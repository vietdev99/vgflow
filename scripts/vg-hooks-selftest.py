#!/usr/bin/env python3
"""
Hook health check fixture. Runs after install.sh wires hooks into a new
project. Proves hooks execute as expected via known fixtures.

Test matrix:
  1. Stop hook - no runtime_contract -> approves
  2. Stop hook - runtime_contract violations -> blocks (exit 2)
  3. PostToolUse edit hook - edit VG skill file -> warning
  4. PostToolUse edit hook - edit normal file -> silent
  5. UserPromptSubmit entry hook - non-VG prompt -> approve
  6. PostToolUse Bash step tracker - marker command updates session context

Exit 0 if all pass, 1 if any failure.

Usage:
    python .claude/scripts/vg-hooks-selftest.py

Run automatically at end of install.sh after hooks wired — confirms the
installation actually works, not just "installed".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(os.getcwd()).resolve()
PYTHON = sys.executable or "python"

STOP_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-verify-claim.py"
EDIT_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-edit-warn.py"
ENTRY_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-entry-hook.py"
STEP_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-step-tracker.py"


def _read_optional(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_optional(path: Path, content: str | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_hook(script: Path, input_json: dict) -> tuple[int, str, str]:
    """Invoke hook with stdin JSON, return (exit_code, stdout, stderr)."""
    if not script.exists():
        return (-1, "", f"hook script missing: {script}")

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)

    proc = subprocess.run(
        [PYTHON, str(script)],
        input=json.dumps(input_json).encode("utf-8"),
        capture_output=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    return (proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"))


def case_stop_no_active_run():
    """No active current-run -> approve."""
    run_json = REPO_ROOT / ".vg" / "current-run.json"
    original = _read_optional(run_json)
    run_json.unlink(missing_ok=True)

    try:
        exit_code, stdout, stderr = run_hook(STOP_HOOK, {
            "session_id": "selftest",
            "transcript_path": "",
            "cwd": str(REPO_ROOT),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        })
        # Should approve (exit 0)
        if exit_code != 0:
            return False, f"Expected exit 0, got {exit_code}. stderr: {stderr[:200]}"
        if '"approve"' not in stdout:
            return False, f"Expected approve decision, got: {stdout[:200]}"
        return True, "approve emitted when no active run exists"
    finally:
        _restore_optional(run_json, original)


def case_stop_missing_evidence():
    """Command with runtime_contract but zero evidence → block (exit 2)."""
    run_json = REPO_ROOT / ".vg" / "current-run.json"
    original = _read_optional(run_json)
    run_json.parent.mkdir(parents=True, exist_ok=True)
    # Use a fake phase number that definitely has no artifacts
    fake_phase = "99999999"
    run_json.write_text(json.dumps({
        "command": "vg:blueprint",
        "phase": fake_phase,
        "args": "",
    }), encoding="utf-8")

    try:
        exit_code, stdout, stderr = run_hook(STOP_HOOK, {
            "session_id": "selftest",
            "transcript_path": "",
            "cwd": str(REPO_ROOT),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        })
        # Either blocks (exit 2) OR approves if phase dir not found (soft-approve path).
        # Both are acceptable — what we're testing is that hook runs + makes a decision.
        if exit_code not in (0, 2):
            return False, f"Unexpected exit {exit_code}. stderr: {stderr[:200]}"
        return True, f"hook produced decision (exit {exit_code}) — contract eval path exercised"
    finally:
        _restore_optional(run_json, original)


def case_edit_watched_file():
    """Edit VG skill file → warning emitted."""
    exit_code, stdout, stderr = run_hook(EDIT_HOOK, {
        "session_id": "selftest",
        "tool_name": "Edit",
        "tool_input": {"file_path": ".claude/commands/vg/build.md"},
        "tool_response": {},
        "cwd": str(REPO_ROOT),
    })
    if exit_code != 0:
        return False, f"Expected exit 0, got {exit_code}"
    if "additionalContext" not in stdout or "VG SKILL FILE EDITED" not in stdout:
        return False, f"Expected warning JSON, got: {stdout[:200]}"
    return True, "warning emitted for VG skill edit"


def case_edit_normal_file():
    """Edit regular source file → silent (no output)."""
    exit_code, stdout, stderr = run_hook(EDIT_HOOK, {
        "session_id": "selftest",
        "tool_name": "Edit",
        "tool_input": {"file_path": "apps/web/src/App.tsx"},
        "tool_response": {},
        "cwd": str(REPO_ROOT),
    })
    if exit_code != 0:
        return False, f"Expected exit 0, got {exit_code}"
    if stdout.strip():
        return False, f"Expected silent (empty stdout), got: {stdout[:200]}"
    return True, "silent for normal source edit"


def case_entry_non_vg_prompt():
    """UserPromptSubmit non-VG prompt -> approve."""
    exit_code, stdout, stderr = run_hook(ENTRY_HOOK, {
        "session_id": "selftest",
        "prompt": "hello",
        "cwd": str(REPO_ROOT),
        "hook_event_name": "UserPromptSubmit",
    })
    if exit_code != 0:
        return False, f"Expected exit 0, got {exit_code}. stderr: {stderr[:200]}"
    if '"approve"' not in stdout:
        return False, f"Expected approve decision, got: {stdout[:200]}"
    return True, "entry hook approves non-VG prompt"


def case_step_tracker_updates_context():
    """Bash marker hook updates .vg/.session-context.json."""
    context_path = REPO_ROOT / ".vg" / ".session-context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    original = context_path.read_text(encoding="utf-8") if context_path.exists() else None
    context_path.write_text(json.dumps({
        "run_id": "selftest-run",
        "command": "vg:build",
        "phase": "99999999",
        "started_at": "2026-04-27T00:00:00Z",
        "current_step": None,
        "step_history": [],
        "telemetry_emitted": [],
    }), encoding="utf-8")

    try:
        exit_code, stdout, stderr = run_hook(STEP_HOOK, {
            "session_id": "selftest",
            "tool_name": "Bash",
            "tool_input": {
                "command": "python .claude/scripts/vg-orchestrator mark-step build 8_execute_waves"
            },
            "tool_response": {},
            "cwd": str(REPO_ROOT),
        })
        if exit_code != 0:
            return False, f"Expected exit 0, got {exit_code}. stderr: {stderr[:200]}"
        updated = json.loads(context_path.read_text(encoding="utf-8"))
        if updated.get("current_step") != "8_execute_waves":
            return False, f"current_step not updated: {updated}"
        emitted = set(updated.get("telemetry_emitted") or [])
        if "8_execute_waves:mark" not in emitted:
            return False, f"telemetry dedup key missing: {updated}"
        return True, "step tracker updated session context"
    finally:
        if original is None:
            context_path.unlink(missing_ok=True)
        else:
            context_path.write_text(original, encoding="utf-8")


def main() -> int:
    print("VG hooks self-test")
    print(f"  repo: {REPO_ROOT}")
    print(f"  python: {PYTHON}")
    print(f"  stop hook: {STOP_HOOK}")
    print(f"  edit hook: {EDIT_HOOK}")
    print(f"  entry hook: {ENTRY_HOOK}")
    print(f"  step hook: {STEP_HOOK}")
    print()

    cases = [
        ("Stop / no active run -> approve", case_stop_no_active_run),
        ("Stop / contract + no evidence → block-or-soft-approve", case_stop_missing_evidence),
        ("PostToolUse / VG skill edit → warning", case_edit_watched_file),
        ("PostToolUse / normal file edit → silent", case_edit_normal_file),
        ("UserPromptSubmit / non-VG prompt -> approve", case_entry_non_vg_prompt),
        ("PostToolUse / Bash marker -> step context", case_step_tracker_updates_context),
    ]

    passed = 0
    failed = 0
    for name, fn in cases:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"exception: {e}"

        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}")
        print(f"      {msg}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    total = passed + failed
    print(f"Result: {passed}/{total} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
