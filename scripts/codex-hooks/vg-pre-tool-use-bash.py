#!/usr/bin/env python3
"""Codex PreToolUse wrapper for VGFlow Bash gates."""
from __future__ import annotations

import sys

from vg_codex_hook_lib import forward_to_bash, forward_to_python, read_hook_input


def main() -> int:
    hook_input = read_hook_input()
    rc = forward_to_python(
        hook_input,
        (
            ".claude/scripts/codex-hooks/vg-codex-spawn-guard.py",
            "scripts/codex-hooks/vg-codex-spawn-guard.py",
        ),
        timeout=30,
    )
    if rc != 0:
        return rc
    return forward_to_bash(
        hook_input,
        (
            ".claude/scripts/hooks/vg-pre-tool-use-bash.sh",
            "scripts/hooks/vg-pre-tool-use-bash.sh",
        ),
        timeout=60,
    )


if __name__ == "__main__":
    sys.exit(main())
