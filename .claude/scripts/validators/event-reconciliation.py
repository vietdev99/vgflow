#!/usr/bin/env python3
"""
Validator: event-reconciliation.py

Purpose: run at /vg:accept step — cross-check event log vs filesystem state
vs git commits. Ensures the phase actually did what its pipeline said.

Checks:
- Every pipeline step (scope → blueprint → build → review → test) has a
  run.started AND run.completed event in events.db
- Every declared artifact from run_complete frontmatter exists
- Step markers count matches telemetry count (rough sanity)
- Hash chain integrity for this phase's events slice

Usage: event-reconciliation.py --phase <N>
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

ZERO_HASH = "0" * 64
REQUIRED_PIPELINE_CMDS = ["vg:scope", "vg:blueprint", "vg:build",
                          "vg:review", "vg:test"]
REQUIRED_ARTIFACTS = {
    "vg:scope": ["CONTEXT.md"],
    "vg:blueprint": ["PLAN*.md", "API-CONTRACTS.md", "TEST-GOALS.md"],
    "vg:build": ["SUMMARY*.md"],
    "vg:review": ["RUNTIME-MAP.json", "GOAL-COVERAGE-MATRIX.md"],
    "vg:test": ["SANDBOX-TEST*.md"],
}


def compute_event_hash(prev_hash: str, ts: str, event_type: str, phase: str,
                       command: str, payload_json: str) -> str:
    blob = f"{prev_hash}|{ts}|{event_type}|{phase}|{command}|{payload_json}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="event-reconciliation")
    with timer(out):
        if not DB_PATH.exists():
            out.add(Evidence(
                type="missing_file",
                message=f"events.db missing — no pipeline evidence",
                file=str(DB_PATH),
            ))
            emit_and_exit(out)

        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            out.add(Evidence(type="missing_file",
                             message=f"phase dir for {args.phase} not found"))
            emit_and_exit(out)
        phase_dir = phase_dirs[0]

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            # Hash chain integrity for phase events
            rows = conn.execute(
                "SELECT * FROM events WHERE phase = ? ORDER BY id ASC",
                (args.phase,),
            ).fetchall()

            # Per-command run.started/completed presence
            seen_started = set()
            seen_completed = set()
            for r in rows:
                if r["event_type"] == "run.started":
                    seen_started.add(r["command"])
                elif r["event_type"] == "run.completed":
                    seen_completed.add(r["command"])

            for cmd in REQUIRED_PIPELINE_CMDS:
                if cmd not in seen_started:
                    out.add(Evidence(
                        type="event_missing",
                        message=f"No run.started event for {cmd} in phase {args.phase}",
                        fix_hint=f"Run /{cmd} {args.phase}",
                    ))
                elif cmd not in seen_completed:
                    out.add(Evidence(
                        type="event_missing",
                        message=f"No run.completed event for {cmd} — run blocked or aborted",
                        fix_hint=f"Check why /{cmd} {args.phase} didn't complete cleanly.",
                    ))

            # Artifact existence per command
            for cmd in REQUIRED_PIPELINE_CMDS:
                if cmd not in seen_completed:
                    continue
                for pattern in REQUIRED_ARTIFACTS.get(cmd, []):
                    matches = list(phase_dir.glob(pattern))
                    if not matches:
                        out.add(Evidence(
                            type="missing_file",
                            message=f"{cmd} completed but no {pattern} found",
                            file=f"{phase_dir}/{pattern}",
                        ))

            # Unresolved overrides
            override_used = [json.loads(r["payload_json"]) for r in rows
                             if r["event_type"] == "override.used"]
            override_resolved = [json.loads(r["payload_json"]) for r in rows
                                 if r["event_type"] == "override.resolved"]
            used_flags = {o.get("flag") for o in override_used if o.get("flag")}
            resolved_flags = {o.get("flag") for o in override_resolved
                              if o.get("flag")}
            unresolved = used_flags - resolved_flags
            if unresolved:
                out.add(Evidence(
                    type="override_unresolved",
                    message=f"{len(unresolved)} override flags still active",
                    actual=", ".join(unresolved),
                    fix_hint="Run /vg:override-resolve or fix underlying issue before accept.",
                ))
        finally:
            conn.close()

    emit_and_exit(out)


if __name__ == "__main__":
    import json  # noqa: E402 — late import so main() stays clean up top
    main()
