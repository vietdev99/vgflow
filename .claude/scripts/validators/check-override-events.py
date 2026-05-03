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


def _extract_events_from_jsonl(path: Path) -> dict[str, dict]:
    """Parse telemetry.jsonl into {event_id: {gate_id, event_type, phase}}.

    Returns dict keyed by event_id so validator can verify event's gate_id
    matches the override entry's gate_id (CrossAI R6 finding: without this,
    any unrelated real event can "resolve" any override).
    """
    events: dict[str, dict] = {}
    if not path.exists():
        return events
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
            if not eid:
                continue
            payload = evt.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            events[str(eid)] = {
                "gate_id": str(evt.get("gate_id") or payload.get("gate_id") or ""),
                "event_type": str(evt.get("event_type") or evt.get("type") or ""),
                "phase": str(evt.get("phase") or payload.get("phase") or ""),
            }
    except OSError:
        pass
    return events


def _extract_events_from_db(path: Path) -> dict[str, dict]:
    """Parse events.db (sqlite) — v2.2 hash-chained table.

    Schema: events(id PK, this_hash TEXT, event_type TEXT, payload TEXT json).
    'this_hash' is the canonical event_id. gate_id is extracted from payload json.
    """
    events: dict[str, dict] = {}
    if not path.exists():
        return events
    try:
        conn = sqlite3.connect(str(path))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
        select_cols = ["this_hash"]
        if "event_type" in cols:
            select_cols.append("event_type")
        if "payload" in cols:
            select_cols.append("payload")
        q = f"SELECT {', '.join(select_cols)} FROM events WHERE this_hash IS NOT NULL"
        for row in conn.execute(q):
            this_hash = str(row[0])
            event_type = ""
            gate_id = ""
            phase = ""
            idx = 1
            if "event_type" in cols:
                event_type = str(row[idx] or "")
                idx += 1
            if "payload" in cols and row[idx] is not None:
                try:
                    p = json.loads(row[idx])
                    if isinstance(p, dict):
                        gate_id = str(p.get("gate_id") or "")
                        phase = str(p.get("phase") or "")
                except (json.JSONDecodeError, TypeError):
                    pass
            events[this_hash] = {
                "gate_id": gate_id,
                "event_type": event_type,
                "phase": phase,
            }
        conn.close()
    except sqlite3.Error:
        pass
    return events


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

        # Collect events into indexed dict (union jsonl + db).
        # Each event: {gate_id, event_type, phase} — gate_id used for binding check.
        known_events: dict[str, dict] = {}
        known_events.update(_extract_events_from_jsonl(telemetry))
        # DB takes precedence on conflict (v2.2 canonical store)
        known_events.update(_extract_events_from_db(events_db))

        if not known_events and entries:
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
        mismatch_count = 0
        legacy_count = 0
        legacy_violations = 0
        verified_count = 0
        for entry in entries:
            status = str(entry.get("status", "")).upper()
            event_id = str(entry.get("resolved_by_event_id", "")).strip()
            legacy = bool(entry.get("legacy", False))
            entry_gate = str(entry.get("gate_id", "")).strip()
            legacy_reason = str(entry.get("legacy_reason", "")).strip()

            # Only RESOLVED entries need event verification
            if status != "RESOLVED":
                continue

            if legacy:
                # CrossAI R6: legacy:true was unconditional bypass. Now requires
                # non-empty legacy_reason explaining why (e.g., "pre-v1.8.0
                # telemetry not emitted", "manual migration from gsd-legacy").
                if not legacy_reason:
                    legacy_violations += 1
                    out.add(Evidence(
                        type="legacy_without_reason",
                        message=f"legacy:true entry missing legacy_reason: "
                                f"{entry.get('heading', '<unknown>')}",
                        file=str(register),
                        expected="- legacy_reason: <text explaining why no event_id>",
                        fix_hint="Add `- legacy_reason: <reason>` field. Accepted "
                                 "reasons: 'pre-v1.8.0', 'migration from gsd', "
                                 "or specific incident reference.",
                    ))
                else:
                    legacy_count += 1
                continue

            if not event_id:
                out.add(Evidence(
                    type="missing_field",
                    message=f"RESOLVED entry without resolved_by_event_id: "
                            f"{entry.get('heading', '<unknown>')}",
                    file=str(register),
                    fix_hint="Resolved overrides must cite the gate re-run "
                             "event. Mark legacy:true + legacy_reason if "
                             "pre-v1.8.0.",
                ))
                continue

            if event_id not in known_events:
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
                             "override_resolved event, (b) mark legacy:true + "
                             "legacy_reason if pre-v1.8.0 entry, or (c) revert "
                             "status to UNRESOLVED.",
                ))
                continue

            # Event exists — verify gate_id binding (CrossAI R6 critical fix).
            # Without this check, ANY unrelated real event could "resolve"
            # ANY override. Now: override's gate_id must match event's gate_id.
            evt = known_events[event_id]
            evt_gate = evt.get("gate_id", "")
            if entry_gate and evt_gate and entry_gate != evt_gate:
                mismatch_count += 1
                out.add(Evidence(
                    type="gate_id_mismatch",
                    message=f"Override '{entry.get('heading')}' gate_id="
                            f"'{entry_gate}' but resolved_by_event_id "
                            f"'{event_id}' is for gate_id='{evt_gate}'",
                    file=str(register),
                    expected=f"event with gate_id={entry_gate}",
                    actual=f"event gate_id={evt_gate}",
                    fix_hint="Re-run the correct gate to emit matching event, "
                             "or cite the right event_id. Cross-gate event "
                             "reuse is not valid resolution.",
                ))
            elif entry_gate and not evt_gate:
                # Event has no gate_id — ambiguous. WARN + count as verified
                # (weak but not fraud).
                out.warn(Evidence(
                    type="gate_id_unverified",
                    message=f"Event '{event_id}' has no gate_id metadata — "
                            f"cannot verify binding to override "
                            f"'{entry.get('heading')}' (gate={entry_gate})",
                    file=str(register),
                    fix_hint="Ensure gate emitters include gate_id in payload.",
                ))
                verified_count += 1
            else:
                verified_count += 1

        total_blocks = phantom_count + mismatch_count + legacy_violations
        if total_blocks == 0:
            out.evidence.append(Evidence(
                type="summary",
                message=f"verified={verified_count}, legacy={legacy_count}, "
                        f"phantom=0, mismatch=0, legacy_violations=0",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
