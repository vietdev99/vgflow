#!/usr/bin/env python3
"""
PostToolUse hook — warn when Claude edits VG skill files.

Why: Claude Code loads skill MD content at session start. If Claude
edits `.claude/commands/vg/**` or `.claude/skills/vg-*/SKILL.md` during
a session, the CURRENT session keeps using the cached old content —
the edit only applies from next session onward. This silently causes
"I wired it but it doesn't fire" confusion (documented 3-round pattern
in audit).

This hook detects such edits and prints a visible warning back to Claude
so the AI knows (and can inform user) that reload is required.

Hook input (stdin, JSON):
    {
      "session_id": "...",
      "tool_name": "Edit" | "Write",
      "tool_input": { "file_path": "..." },
      "tool_response": {...},
      "cwd": "..."
    }

Hook output:
    - exit 0 with empty stdout: no warning (file not a skill)
    - exit 0 with warning JSON on stdout: Claude sees warning in next turn
      (per Claude Code hooks contract: `{"additionalContext": "..."}` or
      `{"hookSpecificOutput": {...}}`)

We use stderr for the warning text (appears in hook execution log),
plus stdout decision JSON so Claude Code routes back properly.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
LOG_FILE = REPO_ROOT / ".vg" / "hook-edit-warn.log"


# Paths that trigger warning when edited
WATCHED_PATTERNS = [
    ".claude/commands/vg/",
    ".claude/skills/vg-",
    ".claude/skills/api-contract/",
    ".claude/commands/vg/_shared/",
]


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


def is_watched(file_path: str) -> bool:
    """Check if the edited file is a VG skill/command that gets cached at
    session start. Path may be absolute or relative.
    """
    # Normalize to forward-slash relative form
    p = file_path.replace("\\", "/")
    try:
        abs_p = Path(file_path).resolve()
        rel = str(abs_p.relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception:
        rel = p

    return any(pat in rel or pat in p for pat in WATCHED_PATTERNS)


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # Can't parse → silently approve, don't block editing

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path") or ""

    # Only care about Edit / Write / MultiEdit / NotebookEdit
    if tool_name not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0

    if not file_path or not is_watched(file_path):
        return 0

    rel = file_path.replace(str(REPO_ROOT), "").lstrip("\\/").replace("\\", "/")
    log(f"[{tool_name}] {rel} — reload-required warning injected")

    # Emit warning via additionalContext per Claude Code hooks docs
    warning = (
        f"⚠ VG SKILL FILE EDITED: {rel}\n"
        f"   This file is cached at session start. Current session still uses "
        f"the PRE-EDIT content. Changes apply from NEXT session only.\n"
        f"   If the user asks 'why didn't my change take effect?' — explain this. "
        f"Either (a) warn user to restart Claude Code to pick up changes, or "
        f"(b) if the change is important NOW, ask them to start a new session."
    )

    # Claude Code PostToolUse hook contract supports hookSpecificOutput
    # to inject additional context into the conversation.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": warning,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Never block on error
        try:
            log(f"HOOK ERROR (soft-approving): {e}")
        except Exception:
            pass
        sys.exit(0)
