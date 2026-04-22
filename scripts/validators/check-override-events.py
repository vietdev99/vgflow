#!/usr/bin/env python3
"""
check-override-events.py — OHOK Batch 5 B9.

Validates override-debt entries with `resolved_by_event_id` are REAL —
the cited event_id must exist in telemetry.jsonl (or events.db if
v2.2 orchestrator).

Before this validator: user (or buggy AI) could write `resolved_by_event_id:
"deadbeef-fake-0000"` into OVERRIDE-DEBT.md and accept.md 3c gate would
pass without checking the event actually exists. Honour-system loophole
identified in OHOK-9 audit.

Verdict:
- PASS: all `resolved_by_event_id` values correspond to real events
- BLOCK: one or more resolved_by_event_id is not found in telemetry
- WARN: legacy=true entries without event_id (acceptable — pre-v1.8.0)

Usage:
  check-override-events.py --register <path> [--telemetry <path>] [--events-db <path>]

At least one of --telemetry or --events-db must be readable. If both
present, events are checked against the union.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, timer


def _extract_event_ids_from_jsonl(path: Path) -> set[str]:
    """Parse telemetry.jsonl for event_id values (any event type)."""
    event_ids: set[str] = set()
    if not path.exists():
        return event_ids
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            eid = evt.get("event_id") or evt.get("id")
            if eid:
                event_ids.add(str(eid))
    except OSError:
        pass
    return event_ids


def _extract_event_ids_from_db(path: Path) -> set[str]:
    """Parse events.db (sqlite) for event_id values. v2.2+ orchestrator
    stores events in a hash-chained SQLite table instead of jsonl."""
    event_ids: set[str] = set()
    if not path.exists():
        return event_ids
    try:
        conn = sqlite3.connect(str(path))
        # Schema: events(id INTEGER PK, this_hash TEXT, ...). The 'this_hash'
        # serves as the canonical event_id in v2.2 schema.
        for row in conn.execute("SELECT this_hash FROM events WHERE this_hash IS NOT NULL"):
            event_ids.add(str(row[0]))
        conn.close()
    except sqlite3.Error:
        pass
    return event_ids


def _parse_override_debt(path: Path) -> list[dict]:
    """Parse OVERRIDE-DEBT.md YAML-frontmatter-style entries.

    Expected format:
      ## Entry <id>
      - gate_id: ...
      - status: UNRESOLVED | RESOLVED | WONT_FIX
      - resolved_by_event_id: <uuid or null>
      - legacy: true | false
    """
    if not path.exists():
        return []
    # Line-based parse (safer than regex for empty-value lines + Windows \r\n).
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: list[dict] = []
    current: dict[str, object] | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r").rstrip()  # strip \r + trailing whitespace
        if line.startswith("## "):
            if current is not None:
                entries.append(current)
            current = {"heading": line[3:].strip()}
            continue
        if current is None:
            continue
        # Match `- key: [value]` — empty value allowed
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:].lstrip()
        if ":" not in body:
            continue
        k, _, v = body.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not re.match(r'^[a-z_]+$', k):
            continue
        if v.lower() in ("true", "false"):
            current[k] = (v.lower() == "true")
        elif v.lower() in ("null", "none", ""):
            current[k] = ""
        else:
            current[k] = v
    if current is not None:
        entries.append(current)
    return entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", default=".vg/OVERRIDE-DEBT.md",
                    help="path to override-debt register")
    ap.add_argument("--telemetry", default=".vg/telemetry.jsonl",
                    help="path to telemetry.jsonl (legacy + v2.2)")
    ap.add_argument("--events-db", default=".vg/events.db",
                    help="path to events.db (v2.2+ sqlite)")
    ap.add_argument("--phase", default="",
                    help="optional phase filter — only check entries "
                         "scoped to this phase")
    args = ap.parse_args()

    out = Output(validator="check-override-events")
    with timer(out):
        repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())
        register = repo / args.register if not Path(args.register).is_absolute() \
                   else Path(args.register)
        telemetry = repo / args.telemetry if not Path(args.telemetry).is_absolute() \
                    else Path(args.telemetry)
        events_db = repo / args.events_db if not Path(args.events_db).is_absolute() \
                    else Path(args.events_db)

        if not register.exists():
            # No register = no overrides to check. PASS.
            emit_and_exit(out)
            return

        entries = _parse_override_debt(register)
        if args.phase:
            entries = [e for e in entries if args.phase in e.get("heading", "")
                       or e.get("phase", "") == args.phase]

        # Collect all known event IDs (union of jsonl + db)
        known_ids = _extract_event_ids_from_jsonl(telemetry)
        known_ids |= _extract_event_ids_from_db(events_db)

        if not known_ids and entries:
            out.warn(Evidence(
                type="missing_file",
                message="No telemetry source readable — cannot verify "
                        f"resolved_by_event_id claims ({len(entries)} entries skipped)",
                file=f"{telemetry} / {events_db}",
                fix_hint="Ensure telemetry pipeline running, or this is a "
                         "fresh project with no events yet.",
            ))
            emit_and_exit(out)
            return

        phantom_count = 0
        legacy_count = 0
        verified_count = 0
        for entry in entries:
            status = str(entry.get("status", "")).upper()
            event_id = str(entry.get("resolved_by_event_id", "")).strip()
            legacy = bool(entry.get("legacy", False))

            # Only RESOLVED entries need event verification
            if status != "RESOLVED":
                continue

            if legacy:
                legacy_count += 1
                continue  # Legacy entries allowed without event_id

            if not event_id:
                out.add(Evidence(
                    type="missing_field",
                    message=f"RESOLVED entry without resolved_by_event_id: "
                            f"{entry.get('heading', '<unknown>')}",
                    file=str(register),
                    fix_hint="Resolved overrides must cite the gate re-run "
                             "event. Mark legacy:true if pre-v1.8.0.",
                ))
                continue

            if event_id not in known_ids:
                phantom_count += 1
                out.add(Evidence(
                    type="phantom_event",
                    message=f"resolved_by_event_id '{event_id}' not found in "
                            f"telemetry — override entry '{entry.get('heading')}' "
                            f"claims fake resolution",
                    file=str(register),
                    expected="event in telemetry.jsonl or events.db",
                    actual=f"event_id={event_id} absent",
                    fix_hint="Either (a) re-run the gate so it emits a real "
                             "override_resolved event, (b) mark legacy:true if "
                             "pre-v1.8.0 entry, or (c) revert status to UNRESOLVED.",
                ))
            else:
                verified_count += 1

        if phantom_count == 0:
            # No phantoms detected — PASS. Add summary evidence for audit.
            out.evidence.append(Evidence(
                type="summary",
                message=f"verified={verified_count}, legacy={legacy_count}, "
                        f"phantom=0",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
