#!/usr/bin/env python3
"""token-budget.py — Rule 6 (token budgets not advisory) Batch 13

Per-task + per-session token usage tracker. Default budgets from
tinbeta/AGENTS.md Rule 6: 4000/task, 30000/session.

Usage:
  --add N --task T-XX           Accumulate N tokens against task
  --check --task T-XX           Report PASS/WARN/BLOCK (warn>=80%, block>=100%)
  --check --session             Report session-wide state
  --allow-overrun               Bypass BLOCK (still emits WARN)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PER_TASK = 4000
DEFAULT_PER_SESSION = 30000


def _read_ledger(path: Path) -> dict:
    if not path.is_file():
        return {
            "tasks": {},
            "session_used": 0,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tasks": {}, "session_used": 0}


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".token-budget.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Rule 6 token budget tracker")
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--task", default="")
    ap.add_argument("--add", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--session", action="store_true")
    ap.add_argument("--allow-overrun", action="store_true")
    ap.add_argument("--per-task", type=int, default=DEFAULT_PER_TASK)
    ap.add_argument("--per-session", type=int, default=DEFAULT_PER_SESSION)
    args = ap.parse_args()

    ledger_path = args.phase_dir / ".token-budget.json"
    data = _read_ledger(ledger_path)
    data.setdefault("tasks", {})

    # ADD action
    if args.add > 0:
        if args.task:
            t = data["tasks"].setdefault(args.task, {"used": 0})
            t["used"] += args.add
        data["session_used"] = data.get("session_used", 0) + args.add
        _write_atomic(ledger_path, data)
        print(f"+{args.add} tokens (task={args.task or 'none'}, session={data['session_used']})")
        return 0

    # CHECK action
    if args.check:
        if args.task:
            used = data.get("tasks", {}).get(args.task, {}).get("used", 0)
            budget = args.per_task
            scope = f"task {args.task}"
        elif args.session:
            used = data.get("session_used", 0)
            budget = args.per_session
            scope = "session"
        else:
            print("ERROR: --check requires --task or --session", file=sys.stderr)
            return 2

        pct = (used / budget * 100) if budget > 0 else 0
        if pct >= 100:
            print(f"BLOCK Rule 6: {scope} {used}/{budget} ({pct:.0f}%) over budget")
            if not args.allow_overrun:
                return 1
            print("   --allow-overrun set; continuing with WARN")
        elif pct >= 80:
            print(f"WARN Rule 6: {scope} {used}/{budget} ({pct:.0f}%) approaching budget")
        else:
            print(f"OK Rule 6: {scope} {used}/{budget} ({pct:.0f}%) within budget")
        return 0

    print("ERROR: must pass --add or --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
