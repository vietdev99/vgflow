#!/usr/bin/env python3
"""Shared helpers for VGFlow Codex hook wrappers."""
from __future__ import annotations

import json
import os
import shutil
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
    roots = [root]
    for raw in (os.environ.get("VG_HOME"), str(Path.home() / ".vgflow")):
        if not raw:
            continue
        candidate_root = Path(raw).expanduser().resolve()
        if candidate_root not in roots:
            roots.append(candidate_root)

    # Hook wrappers live under <VG_HOME>/scripts/codex-hooks. When VG_HOME is
    # not exported, infer the package root from this file so global hooks still
    # work after project-local .claude/.codex files are pruned.
    try:
        wrapper_root = Path(__file__).resolve().parents[2]
        if wrapper_root not in roots:
            roots.append(wrapper_root)
    except Exception:
        pass

    for base in roots:
        for rel in relative_paths:
            candidate = base / rel
            if candidate.exists():
                return candidate
    return None

def _is_wsl_launcher(path: str) -> bool:
    p = path.replace("/", "\\").lower()
    return (
        "\\windows\\system32\\bash.exe" in p
        or "\\appdata\\local\\microsoft\\windowsapps\\bash.exe" in p
    )

def _existing_commands(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        if not raw:
            continue
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
        key = os.path.normcase(path)
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        out.append(path)
    return out

def candidate_bashes() -> list[str]:
    env_bash = os.environ.get("VG_BASH", "")
    path_bash = shutil.which("bash") or shutil.which("bash.exe") or ""
    if os.name != "nt":
        return _existing_commands([env_bash, path_bash, "/usr/bin/bash", "/bin/bash"])

    program_files = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LocalAppData", ""),
    ]
    git_candidates: list[str] = []
    for root in program_files:
        if not root:
            continue
        git_candidates.extend(
            [
                str(Path(root) / "Git" / "bin" / "bash.exe"),
                str(Path(root) / "Git" / "usr" / "bin" / "bash.exe"),
                str(Path(root) / "Programs" / "Git" / "bin" / "bash.exe"),
                str(Path(root) / "Programs" / "Git" / "usr" / "bin" / "bash.exe"),
            ]
        )

    candidates = [env_bash, *git_candidates]
    if path_bash and not _is_wsl_launcher(path_bash):
        candidates.append(path_bash)
    candidates.append(path_bash)
    return _existing_commands(candidates)

def script_arg_for_bash(script: Path, bash: str) -> str:
    script_str = str(script)
    if os.name != "nt" or _is_wsl_launcher(bash):
        return script_str
    return str(script.resolve()).replace("\\", "/")


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


def _last_json_object(stdout: str) -> dict[str, Any]:
    if not stdout.strip():
        return {}
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}

def _extract_user_prompt_context(payload: dict[str, Any]) -> str | None:
    for key in ("systemMessage", "additionalContext"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    hook_specific = payload.get("hookSpecificOutput")
    if isinstance(hook_specific, dict):
        value = hook_specific.get("additionalContext")
        if isinstance(value, str) and value.strip():
            return value
    return None

def forward_to_user_prompt_submit_python(
    hook_input: dict[str, Any],
    relative_paths: tuple[str, ...],
    *,
    timeout: int = 60,
) -> int:
    """Forward Claude UserPromptSubmit and normalize stdout for Codex."""
    root = repo_root(hook_input)
    script = first_existing(root, relative_paths)
    if script is None:
        print(json.dumps({"continue": True}))
        return 0

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(root),
            env=compat_env(hook_input, root),
        )
    except Exception as exc:
        print(f"UserPromptSubmit adapter failed open: {exc}", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stderr:
        sys.stderr.write(stderr + "\n")

    payload = _last_json_object(stdout)
    if proc.returncode != 0:
        if stdout and not payload:
            print(stdout, file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    if payload.get("continue") is False:
        reason = str(payload.get("stopReason") or payload.get("reason") or "User prompt blocked.")
        print(json.dumps({"continue": False, "stopReason": reason}))
        return 0

    if payload.get("decision") == "block":
        reason = str(payload.get("reason") or "User prompt blocked.")
        print(json.dumps({"continue": False, "stopReason": reason}))
        return 0

    response: dict[str, Any] = {"continue": True}
    context = _extract_user_prompt_context(payload)
    if context:
        response["systemMessage"] = context
    if isinstance(payload.get("suppressOutput"), bool):
        response["suppressOutput"] = payload["suppressOutput"]
    print(json.dumps(response))
    return 0

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
    bashes = candidate_bashes()
    if not bashes:
        print("VG Codex hook: no bash found. Install Git Bash or set VG_BASH.", file=sys.stderr)
        return 127
    bash = bashes[0]
    proc = subprocess.run(
        [bash, script_arg_for_bash(script, bash)],
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
