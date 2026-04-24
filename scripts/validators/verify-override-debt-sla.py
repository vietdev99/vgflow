#!/usr/bin/env python3
"""
verify-override-debt-sla.py — Phase O of v2.5.2 hardening.

Parse .vg/OVERRIDE-DEBT.md (or alternate via --debt-file) and flag entries
that have been `status: open` past the SLA window (--max-days, default 30).

Entry format (YAML-ish, one block per entry):
  - id: OD-007
    opened: 2026-03-01
    status: open
    reason: "..."
    flag: --allow-foo

Exit codes:
  0 = all clear (no breaches)
  1 = SLA breaches found
  2 = malformed debt file

Usage:
  verify-override-debt-sla.py --debt-file .vg/OVERRIDE-DEBT.md --max-days 30
  verify-override-debt-sla.py --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Match lines like "  opened: 2026-03-01" or "**opened:** 2026-03-01"
_OPENED_RE = re.compile(
    r"\*?\*?opened\*?\*?\s*:\s*\"?(?P<date>\d{4}-\d{2}-\d{2})\"?",
    re.IGNORECASE,
)
# Also accept logged_at (current format in __main__.py cmd_override)
_LOGGED_AT_RE = re.compile(
    r"\*?\*?logged_at\*?\*?\s*:\s*\"?(?P<date>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"\*?\*?status\*?\*?\s*:\s*\"?(?P<status>\w+)\"?",
    re.IGNORECASE,
)
_ID_RE = re.compile(
    r"(?:id\s*:\s*|-\s*id\s*:\s*)\"?(?P<id>OD-[\w\-]+)\"?",
    re.IGNORECASE,
)


def _parse_debt_file(path: Path) -> list[dict]:
    """Split the markdown into entries and extract id/opened/status per entry.

    Strategy:
      - Split on lines starting with '- id:' (YAML-style list separator)
      - OR split on markdown headings matching '## OD-XXX'
      - For each entry text blob, grep first opened/logged_at date + first
        status keyword
    """
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8", errors="replace")

    # Split into entries. Both YAML list form and markdown heading form supported.
    # Use lookahead so the separator stays with the block.
    blocks = re.split(
        r"(?=^\s*-\s+id\s*:\s*OD-|^\s*##\s+OD-|^\s*###\s+OD-)",
        text, flags=re.MULTILINE,
    )

    entries: list[dict] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        id_m = _ID_RE.search(block)
        if not id_m:
            # Try markdown heading
            head = re.search(r"#+\s+(OD-[\w\-]+)", block)
            if not head:
                continue
            entry_id = head.group(1)
        else:
            entry_id = id_m.group("id")

        opened_m = _OPENED_RE.search(block) or _LOGGED_AT_RE.search(block)
        if not opened_m:
            continue
        status_m = _STATUS_RE.search(block)
        status = status_m.group("status").lower() if status_m else "open"
        # Normalize synonyms — "active" is treated as "open"
        if status in ("active", "pending", "outstanding"):
            status = "open"
        if status in ("closed", "done", "fixed"):
            status = "resolved"
        entries.append({
            "id": entry_id,
            "opened": opened_m.group("date"),
            "status": status,
        })
    return entries


def _days_since(opened_str: str, today: datetime.date) -> int:
    opened = datetime.datetime.strptime(opened_str, "%Y-%m-%d").date()
    return (today - opened).days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debt-file", default=".vg/OVERRIDE-DEBT.md",
                        help="Path to override debt register")
    parser.add_argument("--max-days", type=int, default=30,
                        help="SLA window in days (default 30)")
    parser.add_argument("--today", default=None,
                        help="Override today's date (YYYY-MM-DD) for testing")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    debt_path = Path(args.debt_file)
    if not debt_path.is_absolute():
        debt_path = Path.cwd() / debt_path

    if not debt_path.exists():
        msg = f"debt file not found: {debt_path} — treating as zero breaches"
        if args.json:
            print(json.dumps({"ok": True, "breach_count": 0, "note": msg}))
        else:
            print(msg)
        return 0

    try:
        entries = _parse_debt_file(debt_path)
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"⛔ parse failed: {e}", file=sys.stderr)
        return 2

    if args.today:
        today = datetime.datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = datetime.date.today()

    breaches = []
    for e in entries:
        if e["status"] != "open":
            continue
        try:
            age = _days_since(e["opened"], today)
        except ValueError:
            continue
        if age > args.max_days:
            breaches.append({
                "id": e["id"],
                "opened": e["opened"],
                "age_days": age,
                "max_days": args.max_days,
            })

    breaches.sort(key=lambda b: b["age_days"], reverse=True)
    top10 = breaches[:10]

    result = {
        "ok": len(breaches) == 0,
        "debt_file": str(debt_path),
        "total_entries": len(entries),
        "open_entries": sum(1 for e in entries if e["status"] == "open"),
        "breach_count": len(breaches),
        "max_days": args.max_days,
        "top_breaches": top10,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["ok"]:
            print(
                f"✓ override-debt SLA OK — "
                f"{result['open_entries']} open, 0 breaches (max {args.max_days}d)"
            )
        else:
            print(
                f"⛔ {len(breaches)} SLA breach(es) "
                f"(> {args.max_days}d old):"
            )
            for b in top10:
                print(
                    f"  - {b['id']}: opened {b['opened']} "
                    f"({b['age_days']} days ago)"
                )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
