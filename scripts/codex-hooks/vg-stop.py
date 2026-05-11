#!/usr/bin/env python3
"""Codex Stop wrapper for VGFlow runtime-contract verification."""
from __future__ import annotations

import sys

from vg_codex_hook_lib import forward_to_stop_python, read_hook_input


def main() -> int:
    return forward_to_stop_python(
        read_hook_input(),
        (
            ".claude/scripts/vg-verify-claim.py",
            "scripts/vg-verify-claim.py",
        ),
        timeout=90,
    )


if __name__ == "__main__":
    sys.exit(main())
