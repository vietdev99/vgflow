#!/usr/bin/env python3
"""Task 42 — CLI entry point for generate_wave_context.

This hyphenated shim exists so the bash invocation
  python3 scripts/generate-wave-context.py --phase-dir ...
works alongside the importable form
  from generate_wave_context import generate_wave_context

All logic lives in generate_wave_context.py (underscored module).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is on sys.path for sibling import.
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from generate_wave_context import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
