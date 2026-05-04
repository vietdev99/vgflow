#!/usr/bin/env python3
"""
Validator: build-crossai-required.py — OHOK-7 MANDATORY enforcement.

Post-/vg:build completion must include ≥1 CrossAI verification iteration.
This is the WIRED-OR-NOTHING gate that prevents AI from treating the
"run CrossAI after build" instruction as a promise/docs-only requirement.

Required events in the current run's event stream:

1. At least 1 `build.crossai_iteration_started` event (proves loop ran).
2. One of these terminal events (proves loop reached an accepted end state):
   - `build.crossai_loop_complete` — CrossAI PASS before max iterations
   - `build.crossai_loop_exhausted` — hit max (5) iterations, user decides
   - `build.crossai_loop_user_override` — user chose to defer/skip after
                                            exhaustion (logs HARD debt)

Missing either → BLOCK with explicit command to run the loop.

This validator is dispatched by the orchestrator at `/vg:build run-complete`.
Registered in COMMAND_VALIDATORS['vg:build'].
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir, read_active_run_id  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"

TERMINAL_EVENTS = {
    "build.crossai_loop_complete",
    "build.crossai_loop_exhausted",
    "build.crossai_loop_user_override",
}


def _read_current_run_id() -> str | None:
    """Resolve the current /vg:build run_id with multi-session safety.

    Pre-fix: read .vg/current-run.json directly, racing with concurrent
    sessions (issue: validator saw foreign run_id when another session
    overwrote the global pointer mid-loop). Now defers to the shared
    helper that prefers per-session active-run file > matching legacy
    snapshot > SQLite events.db query for an open vg:build row in this
    session.
    """
    return read_active_run_id(repo_root=REPO_ROOT, command_filter="vg:build")


def _count_events_in_run(run_id: str, event_types: set[str]) -> dict[str, int]:
    """Return counts of each event type for this run."""
    if not DB_PATH.exists():
        return {e: 0 for e in event_types}
    counts = {e: 0 for e in event_types}
    conn = sqlite3.connect(str(DB_PATH))
    try:
        placeholders = ",".join("?" for _ in event_types)
        rows = conn.execute(
            f"SELECT event_type, COUNT(*) FROM events "
            f"WHERE run_id = ? AND event_type IN ({placeholders}) "
            f"GROUP BY event_type",
            [run_id, *event_types],
        ).fetchall()
        for et, n in rows:
            counts[et] = n
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return counts


def _read_event_stream(run_id: str, event_types: list[str]) -> list[dict]:
    """OHOK-8: read full event stream (payload + order) for semantic checks.
    Returns newest-first by id descending."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    try:
        placeholders = ",".join("?" for _ in event_types)
        rows = conn.execute(
            f"SELECT id, event_type, actor, outcome, payload_json FROM events "
            f"WHERE run_id = ? AND event_type IN ({placeholders}) "
            f"ORDER BY id DESC",
            [run_id, *event_types],
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        d = {"id": r[0], "event_type": r[1], "actor": r[2], "outcome": r[3]}
        try:
            d["payload"] = json.loads(r[4] or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="build-crossai-required")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            # No phase dir — phase-exists validator will catch it upstream.
            emit_and_exit(out)

        run_id = _read_current_run_id()
        if not run_id:
            # No active run when run-complete validators fire would be unusual.
            # Phase-exists / other validators fire first; if we're here without
            # a run, skip quietly (loop requirement doesn't apply).
            emit_and_exit(out)

        check_events = TERMINAL_EVENTS | {"build.crossai_iteration_started"}
        counts = _count_events_in_run(run_id, check_events)

        iter_count = counts.get("build.crossai_iteration_started", 0)
        terminal_count = sum(counts.get(e, 0) for e in TERMINAL_EVENTS)

        if iter_count == 0:
            out.add(Evidence(
                type="crossai_loop_never_ran",
                message=(
                    "/vg:build run-complete without any "
                    "build.crossai_iteration_started event. OHOK-7 requires "
                    "MANDATORY CrossAI build verification after wave execution "
                    "— this is NOT a promise, NOT optional. Missing events.db "
                    "evidence = loop didn't actually run."
                ),
                expected="≥1 build.crossai_iteration_started event for this run",
                actual=f"iteration_started events = {iter_count}",
                fix_hint=(
                    "Run the loop now + re-attempt run-complete:\n"
                    "  python .claude/scripts/vg-build-crossai-loop.py "
                    f"--phase {args.phase} --iteration 1 --max-iterations 5\n"
                    "If it exits 1 (blocks found), dispatch a Sonnet fix "
                    "subagent with the findings JSON, apply fixes, commit, "
                    "then re-invoke with --iteration 2. Repeat up to 5x.\n"
                    "If exit 0 → loop is clean; main Claude emits "
                    "build.crossai_loop_complete to satisfy this gate.\n"
                    "If 5 hit without clean → prompt user for: continue / "
                    "defer / skip+debt."
                ),
            ))
            emit_and_exit(out)

        if terminal_count == 0:
            # Loop ran but never reached an accepted terminal state
            out.add(Evidence(
                type="crossai_loop_no_terminal",
                message=(
                    f"Loop ran {iter_count} iteration(s) but no terminal "
                    f"event emitted (loop_complete / loop_exhausted / "
                    f"loop_user_override). Build cannot complete without "
                    f"the caller (main Claude) deciding how the loop ends."
                ),
                expected="one of: " + ", ".join(sorted(TERMINAL_EVENTS)),
                actual=f"iterations={iter_count}, terminal events=0",
                fix_hint=(
                    "After running iterations, main Claude must run the\n"
                    "loop script or issue emit-crossai-terminal via the\n"
                    "dedicated orchestrator subcommand:\n"
                    "  - loop_complete: emitted automatically by the loop\n"
                    "    script when iteration exits CLEAN (0 BLOCK)\n"
                    "  - loop_exhausted: python vg-orchestrator\n"
                    "    emit-crossai-terminal loop_exhausted (after 5 iter)\n"
                    "  - loop_user_override: requires override.used with\n"
                    "    --flag=skip-crossai-build-loop first"
                ),
            ))
            emit_and_exit(out)

        # OHOK-8 round-3 P0.2: SEMANTIC check on terminal event, not shape.
        # Previously: "any terminal event = PASS". Codex/Gemini flagged AI
        # could run loop + see BLOCKS_FOUND + forge loop_complete anyway.
        # New: for loop_complete, the most-recent iteration_complete MUST
        # have outcome=CLEAN. Otherwise it's a forged terminal.
        stream = _read_event_stream(
            run_id,
            ["build.crossai_iteration_started",
             "build.crossai_iteration_complete",
             "build.crossai_loop_complete",
             "build.crossai_loop_exhausted",
             "build.crossai_loop_user_override",
             "override.used"],
        )

        # Find the most recent terminal event (stream is newest-first)
        terminal_evt = next(
            (e for e in stream if e["event_type"] in TERMINAL_EVENTS), None,
        )
        if not terminal_evt:
            # Shouldn't happen (terminal_count >0 above) but be safe
            out.add(Evidence(
                type="crossai_terminal_parse_error",
                message="Count showed terminal event but stream read returned none",
            ))
            emit_and_exit(out)

        term_type = terminal_evt["event_type"]

        if term_type == "build.crossai_loop_complete":
            # Must have a preceding iteration_complete with outcome=CLEAN
            # BEFORE the terminal event (id-wise: lower id since stream is
            # newest-first)
            preceding_ic = [
                e for e in stream
                if e["event_type"] == "build.crossai_iteration_complete"
                and e["id"] < terminal_evt["id"]
            ]
            if not preceding_ic:
                out.add(Evidence(
                    type="crossai_forged_terminal",
                    message=(
                        "build.crossai_loop_complete emitted but NO preceding "
                        "build.crossai_iteration_complete exists. Terminal "
                        "event forged without running actual iteration."
                    ),
                    fix_hint=(
                        "The loop script (vg-build-crossai-loop.py) emits "
                        "loop_complete automatically when iteration reaches "
                        "CLEAN. Do not emit it manually via CLI — reserved."
                    ),
                ))
                emit_and_exit(out)
            last_ic_outcome = (preceding_ic[0]["payload"].get("outcome") or "")
            if last_ic_outcome.upper() != "CLEAN":
                out.add(Evidence(
                    type="crossai_premature_complete",
                    message=(
                        f"build.crossai_loop_complete emitted but last "
                        f"iteration_complete outcome was {last_ic_outcome!r}, "
                        f"not CLEAN. Terminal emitted despite BLOCK findings."
                    ),
                    expected="iteration_complete.outcome=CLEAN before loop_complete",
                    actual=f"iteration_complete.outcome={last_ic_outcome!r}",
                    fix_hint=(
                        "Fix the BLOCK findings first (spawn Sonnet fix "
                        "subagent), re-run loop iteration N+1, then terminal "
                        "emits on CLEAN exit."
                    ),
                ))
                emit_and_exit(out)

        elif term_type == "build.crossai_loop_exhausted":
            # Must have actually reached max_iterations
            started_events = [
                e for e in stream
                if e["event_type"] == "build.crossai_iteration_started"
            ]
            max_iter = (terminal_evt["payload"].get("iterations")
                        or terminal_evt["payload"].get("max_iterations") or 5)
            if len(started_events) < int(max_iter):
                out.add(Evidence(
                    type="crossai_premature_exhausted",
                    message=(
                        f"loop_exhausted emitted with only "
                        f"{len(started_events)} iteration(s), less than "
                        f"max_iterations={max_iter}."
                    ),
                    fix_hint="Run remaining iterations before declaring exhausted.",
                ))
                emit_and_exit(out)

        elif term_type == "build.crossai_loop_user_override":
            # Must have a preceding override.used event with skip-crossai-*
            skip_overrides = [
                e for e in stream
                if e["event_type"] == "override.used"
                and "crossai" in str(e["payload"].get("flag", "")).lower()
            ]
            if not skip_overrides:
                out.add(Evidence(
                    type="crossai_user_override_unbacked",
                    message=(
                        "loop_user_override emitted but no corresponding "
                        "override.used event with --flag containing 'crossai'. "
                        "User override requires HARD debt log first."
                    ),
                    fix_hint=(
                        "Run: python vg-orchestrator override "
                        "--flag=skip-crossai-build-loop "
                        "--reason='<ticket URL or commit SHA, ≥50ch>' "
                        "before emitting the terminal event."
                    ),
                ))
                emit_and_exit(out)

        # All semantic checks passed — PASS silently


    emit_and_exit(out)


if __name__ == "__main__":
    main()
