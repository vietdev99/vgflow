#!/usr/bin/env python3
"""
PostToolUse hook — incremental typecheck after Edit/Write on .ts/.tsx files.

Opt-in via VG_TYPECHECK_ON_EDIT=1 env var. Default OFF (typecheck takes 10-30s
even incremental — would slow every edit). When enabled:

1. Reads hook input from stdin (Edit/Write tool result)
2. Extracts file_path from tool args
3. If .ts/.tsx + under apps/ or packages/ → run project typecheck scoped to
   that app via `pnpm turbo typecheck --filter={app}` (fast with cache)
4. On failure: exit 2 + print error → Claude Code shows error to user +
   AI can react in same turn
5. On success: exit 0 silently

Config (via env):
- VG_TYPECHECK_ON_EDIT=1           — enable (default 0, opt-in)
- VG_TYPECHECK_CMD="pnpm turbo typecheck --filter=%s"
                                    — format string, %s = app/package name
- VG_TYPECHECK_TIMEOUT_SEC=60      — max wait (default 60s)

Fail-open: hook crashes or times out → exit 0 (don't block user work).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
LOG = REPO_ROOT / ".vg" / "hook-typecheck.log"


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now(timezone.utc).isoformat()}Z] {msg}\n")
    except Exception:
        pass


def approve() -> None:
    print(json.dumps({"decision": "approve"}))
    sys.exit(0)


def main() -> int:
    # Opt-in guard
    if os.environ.get("VG_TYPECHECK_ON_EDIT", "0") != "1":
        approve()

    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        approve()

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        approve()

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        approve()

    # Only .ts / .tsx under apps/** or packages/**
    if not re.search(r"\.(ts|tsx)$", file_path):
        approve()
    m = re.search(r"(?:apps|packages)[/\\]([^/\\]+)", file_path)
    if not m:
        approve()
    target = m.group(1)

    cmd_template = os.environ.get(
        "VG_TYPECHECK_CMD",
        "pnpm turbo typecheck --filter=%s")
    timeout = int(os.environ.get("VG_TYPECHECK_TIMEOUT_SEC", "60"))
    cmd = cmd_template % target
    log(f"typechecking target={target} cmd={cmd}")

    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log(f"timeout after {timeout}s — approve to not block user")
        approve()
    except Exception as e:
        log(f"typecheck invoke error: {e}")
        approve()

    if r.returncode == 0:
        log(f"✓ typecheck passed {target}")
        approve()

    # BLOCK — inject error into Claude's view
    err_lines = (r.stdout + r.stderr).splitlines()
    # Trim to last 30 lines (most relevant)
    err_tail = "\n".join(err_lines[-30:])
    log(f"\033[38;5;208mtypecheck FAIL {target}:\033[0m\n{err_tail}")
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"Typecheck failed for {target} after Edit/Write on "
            f"{file_path}. Fix type errors before continuing.\n\n"
            f"{err_tail}"
        )
    }))
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"hook crash (soft-approve): {e}")
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)
