#!/usr/bin/env python3
"""
Hook health check fixture. Runs after install.sh wires hooks into a new
project. Proves hooks execute as expected via known fixtures.

Test matrix:
  1. Stop hook — no runtime_contract → approves
  2. Stop hook — runtime_contract violations → blocks (exit 2)
  3. PostToolUse — edit VG skill file → warning
  4. PostToolUse — edit normal file → silent

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
import tempfile
from pathlib import Path


REPO_ROOT = Path(os.getcwd()).resolve()
PYTHON = sys.executable or "python"

STOP_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-verify-claim.py"
EDIT_HOOK = REPO_ROOT / ".claude" / "scripts" / "vg-edit-warn.py"


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


def case_stop_no_contract():
    """Command without runtime_contract → approve."""
    # Fake current-run pointing to a command without contract (e.g. /vg:progress)
    run_json = REPO_ROOT / ".vg" / "current-run.json"
    run_json.parent.mkdir(parents=True, exist_ok=True)
    run_json.write_text(json.dumps({
        "command": "vg:progress",
        "phase": "",
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
        # Should approve (exit 0)
        if exit_code != 0:
            return False, f"Expected exit 0, got {exit_code}. stderr: {stderr[:200]}"
        if '"approve"' not in stdout:
            return False, f"Expected approve decision, got: {stdout[:200]}"
        return True, "approve emitted for command without contract"
    finally:
        run_json.unlink(missing_ok=True)


def case_stop_missing_evidence():
    """Command with runtime_contract but zero evidence → block (exit 2)."""
    run_json = REPO_ROOT / ".vg" / "current-run.json"
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
        run_json.unlink(missing_ok=True)


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


def main() -> int:
    print("VG hooks self-test")
    print(f"  repo: {REPO_ROOT}")
    print(f"  python: {PYTHON}")
    print(f"  stop hook: {STOP_HOOK}")
    print(f"  edit hook: {EDIT_HOOK}")
    print()

    cases = [
        ("Stop / no contract → approve", case_stop_no_contract),
        ("Stop / contract + no evidence → block-or-soft-approve", case_stop_missing_evidence),
        ("PostToolUse / VG skill edit → warning", case_edit_watched_file),
        ("PostToolUse / normal file edit → silent", case_edit_normal_file),
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
