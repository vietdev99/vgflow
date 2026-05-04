#!/usr/bin/env python3
"""
Validator: override-debt-balance.py

Purpose: every --allow-*, --skip-*, --override-reason flag used in this run
must have a corresponding override.used event AND a human reason (>=4 chars).
Prevents silent escape via flags.

Usage: override-debt-balance.py --phase <N> --run-id <UUID> --flags "--skip-crossai --force"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"

FLAG_RE = re.compile(r"--(?:allow|skip)-[a-z-]+|--override-reason(?:=\S+)?|--force")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--flags", default="",
                    help="the args string as used; validator parses flags")
    args = ap.parse_args()

    out = Output(validator="override-debt-balance")
    with timer(out):
        used_flags = set(FLAG_RE.findall(args.flags))
        if not used_flags:
            # Nothing to check
            emit_and_exit(out)

        if not DB_PATH.exists():
            out.add(Evidence(
                type="missing_file",
                message=f"events.db missing at {DB_PATH} — can't verify overrides",
            ))
            emit_and_exit(out)

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT payload_json FROM events WHERE run_id = ? AND event_type = 'override.used'",
                (args.run_id,),
            ).fetchall()
        finally:
            conn.close()

        logged_flags = {}
        for r in rows:
            pl = json.loads(r["payload_json"])
            flag = pl.get("flag")
            reason = pl.get("reason", "")
            if flag:
                logged_flags[flag] = reason

        unresolved = []
        weak_reason = []
        for flag in used_flags:
            # --override-reason may have =value suffix stripped
            base_flag = flag.split("=", 1)[0]
            matched = logged_flags.get(flag) or logged_flags.get(base_flag)
            if matched is None:
                unresolved.append(flag)
            elif len(matched.strip()) < 4:
                weak_reason.append(f"{flag} (reason too short)")

        if unresolved:
            out.add(Evidence(
                type="override_unresolved",
                message=f"{len(unresolved)} override flags used without debt entry",
                actual=", ".join(unresolved),
                fix_hint=(
                    "vg-orchestrator override --flag <f> --reason <text> "
                    "before calling run-complete."
                ),
            ))
        if weak_reason:
            out.warn(Evidence(
                type="override_unresolved",
                message=f"{len(weak_reason)} overrides have reason <4 chars",
                actual=", ".join(weak_reason),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
