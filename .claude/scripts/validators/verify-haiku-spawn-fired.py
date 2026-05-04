#!/usr/bin/env python3
"""
Validator: verify-haiku-spawn-fired.py — Phase 15 D-17

Asserts /vg:review actually fired step 2b-2 Haiku scanner spawn for phases
with UI profile. Closes regression where review run could complete (or abort)
without ever attempting spawn — leaving exhaustive view scan empty.

Logic:
  1. Resolve phase profile from phase SPECS.md frontmatter `platform`.
  2. If profile NOT in {web-fullstack, web-frontend-only, mobile-rn, mobile-flutter, mobile-native}:
       SKIP — no UI profile, spawn not expected. Return PASS.
  3. If phase scope explicitly declares `spawn_mode: none`:
       SKIP — opt-out. Return PASS.
  4. Query events.db: find latest /vg:review run for this phase.
  5. PHANTOM-AWARE check (per T9.5 / INVESTIGATION-D17.md §3-§4):
       Phantom signature:
         - run.started.payload.args == ""  (empty arg)
         - COUNT(step.marked events) == 0  (no real work)
         - run.aborted within 60s of run.started
       If phantom → SKIP (don't BLOCK).
  6. Real run: assert ≥1 `review.haiku_scanner_spawned` event in run.
       Missing → BLOCK with diagnostic (was it abort? was it skip-discovery?).

Usage:  verify-haiku-spawn-fired.py --phase 7.14.3
        verify-haiku-spawn-fired.py --phase 7.14.3 --run-id <uuid>   # specific run
Output: vg.validator-output JSON on stdout
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
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

UI_PROFILES = {
    "web-fullstack", "web-frontend-only",
    "mobile-rn", "mobile-flutter", "mobile-native",
}
SPAWN_EVENT = "review.haiku_scanner_spawned"
PHANTOM_ABORT_WINDOW_SEC = 60


def _events_db_path() -> Path:
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    return repo / ".vg" / "events.db"


def _phase_profile(phase_dir: Path) -> str | None:
    """Read SPECS.md frontmatter `platform` field (per specs.v1.json)."""
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return None
    text = specs.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    fm_body = m.group(1)
    pm = re.search(r"^platform:\s*[\"']?([a-z\-]+)[\"']?",
                   fm_body, re.MULTILINE)
    return pm.group(1) if pm else None


def _phase_spawn_mode(phase_dir: Path) -> str | None:
    """Read CONTEXT.md (or scope artifacts) for explicit spawn_mode override."""
    for fname in ("CONTEXT.md", "SCOPE.md", "SPECS.md"):
        p = phase_dir / fname
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^\s*spawn_mode:\s*[\"']?([a-z]+)[\"']?",
                      text, re.MULTILINE)
        if m:
            return m.group(1)
    return None


def _is_phantom_run(events: list[dict], started_at: str | None,
                    completed_at: str | None) -> bool:
    """Per INVESTIGATION-D17.md §3-§4 phantom signature."""
    # Signal 1: empty args on run.started
    started_evt = next((e for e in events if e["event_type"] == "run.started"), None)
    if not started_evt:
        return False
    payload = json.loads(started_evt["payload_json"]) if started_evt["payload_json"] else {}
    if payload.get("args", "").strip() != "":
        return False

    # Signal 2: 0 step.marked events
    step_marked_count = sum(1 for e in events if e["event_type"] == "step.marked")
    if step_marked_count != 0:
        return False

    # Signal 3: aborted within 60s of started
    abort_evt = next((e for e in events if e["event_type"] == "run.aborted"), None)
    if not abort_evt:
        return False
    if started_at and completed_at:
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            delta_sec = (t1 - t0).total_seconds()
            if delta_sec > PHANTOM_ABORT_WINDOW_SEC:
                return False
        except (ValueError, TypeError):
            return False  # can't determine timing → don't claim phantom

    return True


def _latest_review_run(conn: sqlite3.Connection, phase: str,
                       run_id: str | None = None) -> dict | None:
    if run_id:
        row = conn.execute(
            "SELECT run_id, command, phase, args, started_at, completed_at, outcome "
            "FROM runs WHERE run_id = ?", (run_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT run_id, command, phase, args, started_at, completed_at, outcome "
            "FROM runs WHERE phase = ? AND command = 'vg:review' "
            "ORDER BY started_at DESC LIMIT 1", (phase,),
        ).fetchone()
    if not row:
        return None
    keys = ["run_id", "command", "phase", "args", "started_at", "completed_at", "outcome"]
    return dict(zip(keys, row))


def _events_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT event_type, ts, step, outcome, payload_json "
        "FROM events WHERE run_id = ? ORDER BY id", (run_id,),
    )
    return [dict(zip(("event_type", "ts", "step", "outcome", "payload_json"), r))
            for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--run-id", help="Optional — validate specific run instead of latest")
    args = ap.parse_args()

    out = Output(validator="haiku-spawn-fired")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        profile = _phase_profile(phase_dir)
        if profile is None:
            out.warn(Evidence(
                type="info",
                message=f"Could not resolve profile from SPECS.md (no platform field?). Skipping.",
                file=str(phase_dir / "SPECS.md"),
            ))
            emit_and_exit(out)
        if profile not in UI_PROFILES:
            out.evidence.append(Evidence(
                type="info",
                message=(f"Profile '{profile}' is non-UI — Haiku spawn not "
                         f"expected. Skipping (PASS)."),
            ))
            emit_and_exit(out)

        spawn_mode = _phase_spawn_mode(phase_dir)
        if spawn_mode == "none":
            out.evidence.append(Evidence(
                type="info",
                message="spawn_mode: none explicitly declared — opt-out PASS.",
            ))
            emit_and_exit(out)

        db_path = _events_db_path()
        if not db_path.exists():
            out.warn(Evidence(
                type="missing_file",
                message=f"events.db not found at {db_path} — cannot verify spawn",
                fix_hint="Ensure orchestrator initialized .vg/events.db. Run any /vg: command first.",
            ))
            emit_and_exit(out)

        conn = sqlite3.connect(str(db_path))
        try:
            run = _latest_review_run(conn, args.phase, args.run_id)
            if not run:
                out.warn(Evidence(
                    type="info",
                    message=(f"No /vg:review runs found for phase {args.phase} "
                             f"in events.db — skipping (no run to verify yet)."),
                ))
                emit_and_exit(out)

            events = _events_for_run(conn, run["run_id"])

            # Phantom-aware skip
            if _is_phantom_run(events, run["started_at"], run["completed_at"]):
                out.evidence.append(Evidence(
                    type="info",
                    message=(f"Run {run['run_id'][:8]} matches phantom signature "
                             f"(args='', 0 step markers, aborted within "
                             f"{PHANTOM_ABORT_WINDOW_SEC}s) — SKIP per Phase 15 "
                             f"D-17 phantom-aware logic. See INVESTIGATION-D17.md §3."),
                ))
                emit_and_exit(out)

            spawn_count = sum(1 for e in events if e["event_type"] == SPAWN_EVENT)
            if spawn_count == 0:
                # Real run with 0 spawn → BLOCK
                step_summary = ", ".join(sorted(set(
                    e["step"] for e in events if e["step"]
                ))[:8])
                out.add(Evidence(
                    type="event_missing",
                    message=(f"Run {run['run_id'][:8]} ({profile}, outcome="
                             f"{run['outcome']}) has 0 '{SPAWN_EVENT}' events "
                             f"despite UI profile + real run signature"),
                    expected=f"≥1 {SPAWN_EVENT} event",
                    actual=0,
                    fix_hint=(
                        f"Investigate why /vg:review step 2b-2 didn't spawn. "
                        f"Steps reached: [{step_summary}]. Check telemetry emit "
                        f"placement (T9.4 — emit BEFORE Agent call). If review "
                        f"used --skip-discovery or --evaluate-only, declare "
                        f"`spawn_mode: none` in CONTEXT.md."
                    ),
                ))
            else:
                out.evidence.append(Evidence(
                    type="info",
                    message=(f"Run {run['run_id'][:8]} fired {spawn_count} "
                             f"Haiku scanner(s) — D-17 satisfied"),
                ))
        finally:
            conn.close()

    emit_and_exit(out)


if __name__ == "__main__":
    main()
