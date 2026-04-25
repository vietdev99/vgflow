#!/usr/bin/env python3
"""
verify-allow-flag-audit.py — Phase O of v2.5.2 hardening.

Analyze `allow_flag.used` events from the orchestrator events DB and detect:
  - Rubber-stamp: same (approver, flag, reason-fingerprint) repeated
    >= --rubber-stamp-threshold times in --lookback-days
  - Approval fatigue: a single approver authorizing >= --fatigue-threshold
    distinct flags in the lookback window
  - Repeat-flag: one flag used >= --repeat-flag-threshold times total —
    signal that the underlying gate needs a policy fix rather than
    repeated overrides

Exit codes:
  0 = no patterns detected
  1 = one or more patterns detected
  2 = config error

Usage:
  verify-allow-flag-audit.py --db-path .vg/events.db --lookback-days 30
  verify-allow-flag-audit.py --json
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path


def _resolve_db_path(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    return root / ".vg" / "events.db"


def _lookback_cutoff(days: int) -> str:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - \
        datetime.timedelta(days=days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_events(db_path: Path, since: str) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, ts, event_type, phase, command, payload_json "
            "FROM events WHERE event_type = 'allow_flag.used' "
            "AND ts >= ? ORDER BY id ASC",
            (since,),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        out.append({
            "id": r["id"],
            "ts": r["ts"],
            "event_type": r["event_type"],
            "phase": r["phase"],
            "command": r["command"],
            "payload": payload,
        })
    return out


def _detect_rubber_stamp(events: list[dict], threshold: int) -> list[dict]:
    """Return list of (approver, flag, reason_fp, count) combos over threshold."""
    counter: collections.Counter[tuple] = collections.Counter()
    for ev in events:
        p = ev.get("payload", {}) or {}
        key = (
            p.get("approver", "?"),
            p.get("flag", "?"),
            p.get("reason_fp", p.get("reason", "")[:16]),
        )
        counter[key] += 1
    out = []
    for (approver, flag, reason_fp), count in counter.items():
        if count >= threshold:
            out.append({
                "approver": approver,
                "flag": flag,
                "reason_fp": reason_fp,
                "count": count,
            })
    return sorted(out, key=lambda x: x["count"], reverse=True)


def _detect_approval_fatigue(events: list[dict], threshold: int) -> list[dict]:
    """Approvers who greenlit >= `threshold` distinct flags in lookback."""
    by_approver: dict[str, set] = collections.defaultdict(set)
    count_by_approver: dict[str, int] = collections.defaultdict(int)
    for ev in events:
        p = ev.get("payload", {}) or {}
        a = p.get("approver", "?")
        by_approver[a].add(p.get("flag", "?"))
        count_by_approver[a] += 1
    out = []
    for approver, flags in by_approver.items():
        if len(flags) >= threshold:
            out.append({
                "approver": approver,
                "distinct_flags": sorted(flags),
                "distinct_flag_count": len(flags),
                "total_events": count_by_approver[approver],
            })
    return sorted(out, key=lambda x: x["distinct_flag_count"], reverse=True)


def _detect_repeat_flag(events: list[dict], threshold: int) -> list[dict]:
    """Flags used >= threshold times total across any approvers."""
    counter: collections.Counter[str] = collections.Counter()
    for ev in events:
        p = ev.get("payload", {}) or {}
        counter[p.get("flag", "?")] += 1
    out = []
    for flag, count in counter.items():
        if count >= threshold:
            out.append({"flag": flag, "count": count})
    return sorted(out, key=lambda x: x["count"], reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None,
                        help="Path to events.db (default .vg/events.db)")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--rubber-stamp-threshold", type=int, default=3)
    parser.add_argument("--fatigue-threshold", type=int, default=5)
    parser.add_argument("--repeat-flag-threshold", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--phase", help="(orchestrator-injected; ignored — flag audit is project-wide)")
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db_path)
    if not db_path.exists():
        out = {
            "validator": "verify-allow-flag-audit",
            "verdict": "PASS",
            "ok": True,
            "note": f"no events.db at {db_path} — nothing to audit",
            "rubber_stamps": [],
            "approval_fatigue": [],
            "repeat_flags": [],
        }
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(out["note"])
        return 0

    since = _lookback_cutoff(args.lookback_days)
    events = _load_events(db_path, since)

    rubber = _detect_rubber_stamp(events, args.rubber_stamp_threshold)
    fatigue = _detect_approval_fatigue(events, args.fatigue_threshold)
    repeat = _detect_repeat_flag(events, args.repeat_flag_threshold)

    findings_total = len(rubber) + len(fatigue) + len(repeat)
    result = {
        "validator": "verify-allow-flag-audit",
        # v2.6 (2026-04-25): WARN (not BLOCK) — audit findings highlight
        # ops behavior patterns (rubber-stamping, approval fatigue, repeat
        # flag use) that operators should review but shouldn't hard-block ship.
        "verdict": "PASS" if findings_total == 0 else "WARN",
        "ok": findings_total == 0,
        "db_path": str(db_path),
        "lookback_days": args.lookback_days,
        "event_count": len(events),
        "rubber_stamps": rubber,
        "approval_fatigue": fatigue,
        "repeat_flags": repeat,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["ok"]:
            print(
                f"✓ allow-flag audit clean — {len(events)} event(s) in last "
                f"{args.lookback_days}d, no patterns"
            )
        else:
            print(
                f"⛔ allow-flag patterns detected "
                f"({len(events)} events in last {args.lookback_days}d):"
            )
            if rubber:
                print(f"  Rubber-stamp ({len(rubber)}):")
                for r in rubber[:5]:
                    print(
                        f"    - {r['approver']} on {r['flag']}: "
                        f"{r['count']} uses (fp={r['reason_fp'][:8]})"
                    )
            if fatigue:
                print(f"  Approval fatigue ({len(fatigue)}):")
                for f in fatigue[:5]:
                    print(
                        f"    - {f['approver']}: "
                        f"{f['distinct_flag_count']} distinct flags"
                    )
            if repeat:
                print(f"  Repeat flags ({len(repeat)}):")
                for r in repeat[:5]:
                    print(f"    - {r['flag']}: {r['count']} uses")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
