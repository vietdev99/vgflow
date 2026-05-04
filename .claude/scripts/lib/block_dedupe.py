"""block_dedupe — query events.db for an open block before emitting.

An "open" block = `vg.block.fired` exists for (run_id, gate_id) AND no
`vg.block.handled` for the same pair has been emitted since.

This helper exposes BOTH a Python API (used by vg-verify-claim.py) AND a
CLI (used by bash hooks via `python3 scripts/lib/block_dedupe.py
--check-open --run-id X --gate-id Y`).

Codex GPT-5.5 round 6: same gate_id × run_id without intervening handled
should produce ONE obligation, not N. Stop hook pairing reads
unique-fired count (excluding refired) to compute open obligations.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

EVENTS_DB_REL = ".vg/events.db"


def _resolve_db(repo_root: str | Path | None) -> Path:
    if repo_root:
        return Path(repo_root) / EVENTS_DB_REL
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env) / EVENTS_DB_REL
    p = Path.cwd()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand / EVENTS_DB_REL
    return p / EVENTS_DB_REL


def has_open_block(run_id: str, gate_id: str,
                   repo_root: str | Path | None = None) -> tuple[bool, int]:
    """Return (is_open, prior_fire_count_for_this_gate).

    prior_fire_count counts fired+refired events for the gate in the run,
    used to populate refired payload's `fire_count` field.
    """
    db = _resolve_db(repo_root)
    if not db.exists():
        return False, 0
    conn = None
    try:
        conn = sqlite3.connect(str(db), timeout=2.0)
        last_fired = conn.execute(
            "SELECT id FROM events WHERE run_id = ? AND event_type IN "
            "('vg.block.fired', 'vg.block.refired') AND "
            "json_extract(payload_json, '$.gate') = ? "
            "ORDER BY id DESC LIMIT 1",
            (run_id, gate_id),
        ).fetchone()
        if not last_fired:
            return False, 0

        handled_after = conn.execute(
            "SELECT 1 FROM events WHERE run_id = ? AND event_type = 'vg.block.handled' AND "
            "json_extract(payload_json, '$.gate') = ? AND id > ? LIMIT 1",
            (run_id, gate_id, last_fired[0]),
        ).fetchone()

        prior_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND event_type IN "
            "('vg.block.fired', 'vg.block.refired') AND "
            "json_extract(payload_json, '$.gate') = ?",
            (run_id, gate_id),
        ).fetchone()[0]

        return (handled_after is None), prior_count
    except sqlite3.Error:
        return False, 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-open", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gate-id", required=True)
    parser.add_argument("--repo-root")
    args = parser.parse_args()

    is_open, prior_count = has_open_block(args.run_id, args.gate_id, args.repo_root)
    # Output format: "OPEN <prior_count>" or "CLOSED <prior_count>"
    print(f"{'OPEN' if is_open else 'CLOSED'} {prior_count}")
    return 0 if is_open else 1


if __name__ == "__main__":
    sys.exit(main())
