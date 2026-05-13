#!/usr/bin/env python3
"""emit-url-runtime-status.py — C11 Batch 2

Single canonical URL runtime status artifact. Replaces 3 fragmented skip/waive
flags (--allow-no-url-sync, --skip-runtime, --allow-runtime-drift) with one
status enum that downstream consumers can rely on.

Schema:
{
  "phase": "<N>",
  "ts": "<ISO>",
  "state": "passed|drift|skipped|unexecuted|waived",
  "reason": "<text>",
  "flags": {<original flags for audit>},
  "evidence_ref": "<optional path>"
}
"""
from __future__ import annotations
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


STATES = ["passed", "drift", "skipped", "unexecuted", "waived"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--state", required=True, choices=STATES)
    ap.add_argument("--reason", default="")
    ap.add_argument("--flags-json", default="{}")
    ap.add_argument("--evidence-ref", default="")
    ap.add_argument("--phase", default="")
    args = ap.parse_args()

    try:
        flags = json.loads(args.flags_json)
    except json.JSONDecodeError:
        flags = {}

    data = {
        "phase": args.phase or args.phase_dir.name,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": args.state,
        "reason": args.reason,
        "flags": flags,
    }
    if args.evidence_ref:
        data["evidence_ref"] = args.evidence_ref

    args.phase_dir.mkdir(parents=True, exist_ok=True)
    out = args.phase_dir / "url-runtime-status.json"
    fd, tmp = tempfile.mkstemp(dir=str(args.phase_dir), prefix=".url-runtime-status.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, out)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print(f"url-runtime-status: state={args.state} reason={args.reason or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
