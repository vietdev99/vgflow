#!/usr/bin/env python3
"""Codex UserPromptSubmit wrapper for VGFlow run-start seeding."""
from __future__ import annotations

import sys

from vg_codex_hook_lib import forward_to_user_prompt_submit_python, read_hook_input


def main() -> int:
    return forward_to_user_prompt_submit_python(
        read_hook_input(),
        (
            ".claude/scripts/vg-entry-hook.py",
            "scripts/vg-entry-hook.py",
        ),
        timeout=30,
    )


if __name__ == "__main__":
    sys.exit(main())
