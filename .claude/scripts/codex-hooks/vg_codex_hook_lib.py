#!/usr/bin/env python3
"""Shared helpers for VGFlow Codex hook wrappers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_hook_input() -> dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _git_root(cwd: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def repo_root(hook_input: dict[str, Any]) -> Path:
    env_root = os.environ.get("VG_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    cwd = Path(str(hook_input.get("cwd") or os.getcwd())).resolve()
    git_root = _git_root(cwd)
    if git_root is not None:
        return git_root
    for parent in (cwd, *cwd.parents):
        if (parent / ".claude" / "scripts").is_dir() or (parent / "scripts").is_dir():
            return parent
    return cwd


def safe_session_filename(session_id: str | None) -> str:
    if not session_id:
        return "unknown"
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return safe or "unknown"


def compat_env(hook_input: dict[str, Any], root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    env.setdefault("VG_RUNTIME", "codex")
    session_id = str(hook_input.get("session_id") or "")
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
        env["CLAUDE_HOOK_SESSION_ID"] = safe_session_filename(session_id)
    return env


def first_existing(root: Path, relative_paths: tuple[str, ...]) -> Path | None:
    for rel in relative_paths:
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def forward_to_python(
    hook_input: dict[str, Any],
    relative_paths: tuple[str, ...],
    *,
    timeout: int = 60,
) -> int:
    root = repo_root(hook_input)
    script = first_existing(root, relative_paths)
    if script is None:
        return 0
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(root),
        env=compat_env(hook_input, root),
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def forward_to_stop_python(
    hook_input: dict[str, Any],
    relative_paths: tuple[str, ...],
    *,
    timeout: int = 60,
) -> int:
    """Forward to a Claude Stop hook and normalize stdout for Codex.

    Claude Stop hooks commonly return `{"decision": "approve"}` on stdout.
    Codex Stop accepts `continue` for approval and uses `decision: "block"`
    only as a continuation signal. Passing Claude's approval shape through
    makes Codex reject the hook output as invalid.
    """
    root = repo_root(hook_input)
    script = first_existing(root, relative_paths)
    if script is None:
        return 0
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(root),
        env=compat_env(hook_input, root),
    )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode == 0:
        if stdout:
            try:
                payload = json.loads(stdout.splitlines()[-1])
            except Exception:
                payload = {}
            if payload.get("decision") == "block":
                reason = str(payload.get("reason") or "Stop hook requested continuation.")
                print(json.dumps({"decision": "block", "reason": reason}))
                return 0
            if payload.get("continue") is False:
                reason = str(payload.get("stopReason") or payload.get("reason") or "Stop hook stopped.")
                print(json.dumps({"continue": False, "stopReason": reason}))
                return 0
        print(json.dumps({"continue": True}))
        return 0

    reason = stderr or stdout or f"Stop verifier failed with rc={proc.returncode}"
    print(reason, file=sys.stderr)
    return 2


def forward_to_bash(
    hook_input: dict[str, Any],
    relative_paths: tuple[str, ...],
    *,
    timeout: int = 60,
) -> int:
    root = repo_root(hook_input)
    script = first_existing(root, relative_paths)
    if script is None:
        return 0
    proc = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(root),
        env=compat_env(hook_input, root),
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode
