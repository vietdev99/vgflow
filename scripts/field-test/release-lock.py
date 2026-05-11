#!/usr/bin/env python3
"""scripts/field-test/release-lock.py — release a stuck .vg/field-test/.active lock.

If a previous /vg:field-test session crashed without releasing its atomic
lock directory, this helper:
  - Reads owner pid from .vg/field-test/.active/pid.
  - Checks if the PID is alive (POSIX: kill -0; Windows: tasklist).
  - Removes the lock dir iff the PID is dead.
  - --force overrides the liveness check.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True,
            )
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root containing .vg/")
    ap.add_argument("--force", action="store_true",
                    help="Remove lock even if PID file claims a live owner")
    args = ap.parse_args()

    lock = Path(args.root) / ".vg" / "field-test" / ".active"
    if not lock.exists():
        print("✓ no lock present", file=sys.stderr)
        return 0

    pid_file = lock / "pid"
    pid = 0
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            pid = 0

    if not args.force and pid > 0 and _pid_alive(pid):
        owner = (lock / "owner").read_text(encoding="utf-8").strip() if (lock / "owner").exists() else "?"
        print(
            f"⛔ lock owner pid={pid} (sid={owner}) is still alive — refusing release. "
            f"Use --force to override.",
            file=sys.stderr,
        )
        return 1

    forced = args.force and pid > 0 and _pid_alive(pid)

    shutil.rmtree(lock, ignore_errors=False)
    if forced:
        print(f"✓ force-released lock (pid={pid}, liveness check bypassed)", file=sys.stderr)
    else:
        print(f"✓ released stuck lock (pid={pid} not alive)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
