#!/usr/bin/env python3
"""prefix-iso.py — portable line-oriented ISO-8601 timestamp prefixer.

Replaces `date -u +%Y-%m-%dT%H:%M:%S.%3N` (GNU-only; macOS BSD date
silently emits literal `%3N`). Pure Python = portable Mac+Linux+
Windows-via-Git-Bash.

Reads stdin line-by-line, writes `<ISO-UTC-Z> <line>` to stdout.
"""
from __future__ import annotations

import datetime as _dt
import sys


def main() -> int:
    try:
        for line in sys.stdin:
            ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            sys.stdout.write(f"{ts} {line}")
            sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
