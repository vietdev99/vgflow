#!/usr/bin/env python3
"""Codex PostToolUse wrapper for VGFlow Bash step tracking."""
from __future__ import annotations

import sys

from vg_codex_hook_lib import forward_to_python, read_hook_input


def main() -> int:
    return forward_to_python(
        read_hook_input(),
        (
            ".claude/scripts/vg-step-tracker.py",
            "scripts/vg-step-tracker.py",
        ),
        timeout=60,
    )


if __name__ == "__main__":
    sys.exit(main())
