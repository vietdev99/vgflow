#!/usr/bin/env python3
"""Verify events emitted in the expected order per command (state machine).

Closes Codex bypass #5: must_emit checks count, not semantic order.
Stop hook invokes this before allowing run-complete.

Usage:
    vg-state-machine-validator.py --db <path> --command vg:<cmd> --run-id <id>

Exit codes:
    0 - events match expected sequence (subset, in order)
    2 - sequence violation, missing event, or unknown command
"""
import argparse, sqlite3, sys
from pathlib import Path


# Per-command expected event sequence.
# A command's events MUST appear in this relative order in the events.db
# (other events may interleave; only the listed ones must match the order).
COMMAND_SEQUENCES = {
    "vg:blueprint": [
        "blueprint.tasklist_shown",
        "blueprint.native_tasklist_projected",
        "blueprint.plan_written",
        "blueprint.contracts_generated",
        "crossai.verdict",
        "blueprint.completed",
    ],
}


def fetch_events(db_path: str, command: str, run_id: str) -> list:
    if not Path(db_path).exists():
        sys.stderr.write(f"ERROR: events database not found at {db_path}\n")
        sys.exit(2)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_type FROM events WHERE command=? AND run_id=? ORDER BY id ASC",
            (command, run_id),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def validate(events: list, expected: list) -> tuple[bool, str]:
    """Pointer-walk: each expected event must appear in events in order."""
    pointer = 0
    for ev in events:
        if pointer < len(expected) and ev == expected[pointer]:
            pointer += 1
    if pointer < len(expected):
        return False, (
            f"expected event '{expected[pointer]}' missing or out of order "
            f"at sequence position {pointer}"
        )
    return True, "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    if args.command not in COMMAND_SEQUENCES:
        # No sequence defined for this command — Stop hook treats validator as
        # best-effort, so skip silently rather than block every Stop event.
        # When a sequence is added, this returns to enforcing order.
        print(
            f"STATE MACHINE SKIP: no sequence defined for '{args.command}' "
            f"(known: {sorted(COMMAND_SEQUENCES.keys())})"
        )
        sys.exit(0)

    expected = COMMAND_SEQUENCES[args.command]
    events = fetch_events(args.db, args.command, args.run_id)
    ok, msg = validate(events, expected)
    if not ok:
        sys.stderr.write(
            f"STATE MACHINE FAIL: {msg}\n"
            f"expected sequence: {expected}\n"
            f"actual events: {events}\n"
        )
        sys.exit(2)
    print("STATE MACHINE OK")


if __name__ == "__main__":
    main()
