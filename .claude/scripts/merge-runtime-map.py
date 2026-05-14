#!/usr/bin/env python3
"""merge-runtime-map.py — F5 Batch 19

Deterministic merge of per-view scan-*.json files into RUNTIME-MAP.json.
Replaces prose-instruction Glob merge in commands/vg/_shared/review/
lens-and-findings.md that allowed fabricated 80-byte stubs to satisfy
the contract.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--phase-number", default="")
    ap.add_argument("--run-id", default="")
    args = ap.parse_args()

    if not args.scan_dir.is_dir():
        print(f"ERROR: scan dir not found: {args.scan_dir}", file=sys.stderr)
        return 1

    scan_files = sorted(args.scan_dir.glob("scan-*.json"))
    if not scan_files:
        print(f"ERROR: no scan-*.json files in {args.scan_dir}", file=sys.stderr)
        print("       review browser tour produced no per-view scans — cannot merge.", file=sys.stderr)
        return 1

    views = []
    for sf in scan_files:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN: skipping {sf.name}: {e}", file=sys.stderr)
            continue
        view_entry = {
            "view": data.get("view", sf.stem.replace("scan-", "")),
            "url": data.get("url", ""),
            "elements": data.get("elements", []),
            "actions": data.get("actions", []),
            "goal_sequences": data.get("goal_sequences", []),
            "source_scan": sf.name,
            "scan_run_id": data.get("run_id", ""),
        }
        views.append(view_entry)

    if not views:
        print("ERROR: all scan files unparseable — refusing to write stub", file=sys.stderr)
        return 1

    out = {
        "schema_version": "1.0",
        "phase": args.phase_number,
        "run_id": args.run_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "view_count": len(views),
        "views": views,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"✓ F5: merged {len(views)} views → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
