#!/usr/bin/env python3
"""
vg-orchestrator-telemetry-repair.py — v3.6.0 (#173 Stage 6 / #169)

Standalone repair script. Reads .vg/events.db + the phase's step markers
and emits any lifecycle events that were touched-but-not-recorded. Idempotent
— never duplicates an event already in the chain.

Use when run-complete contract blocks with `missing event:
review.completed` or similar diagnostic. The repair adds the synthetic
event with `auto_emitted: true, repaired: true` flags so audit can
distinguish repaired events from real ones.

After v3.6.0, the orchestrator's `mark-step` command auto-emits these
events when the marker is touched (closes the gap proactively), so the
repair script is the fallback when:
  - phase was created pre-v3.6.0 (legacy events.db)
  - operator manually touched a marker file outside `mark-step`
  - mark-step was called but auto-emit failed (warn'd to stderr)

Usage:
  vg-orchestrator-telemetry-repair.py --phase <number>
  vg-orchestrator-telemetry-repair.py --phase <number> --dry-run
  vg-orchestrator-telemetry-repair.py --phase <number> --check    # exit 1 if repair needed

Exit codes:
  0 — repair complete (or nothing to repair)
  1 — --check mode: repair needed (operator should re-run without --check)
  2 — config error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
sys.path.insert(0, str(REPO_ROOT / "scripts" / "vg-orchestrator"))
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"))

# Mirrors MARKER_TO_AUTO_EVENT in scripts/vg-orchestrator/__main__.py.
# Kept inline so the repair script stays usable when the orchestrator
# package import fails (e.g., running against an older harness install).
MARKER_TO_EVENT: dict[tuple[str, str], str] = {
    ("build", "complete"): "build.completed",
    ("review", "complete"): "review.completed",
    ("test", "complete"): "test.completed",
    ("accept", "complete"): "accept.completed",
    ("blueprint", "complete"): "blueprint.completed",
    ("deploy", "complete"): "deploy.completed",
    ("next", "complete"): "next.completed",
    ("review", "phase3d_5_qa_checker"): "review.qa_check_completed",
    ("review", "phase2_5_recursive_lens_probe"): "review.recursive_probe_completed",
    ("review", "phase2c_pre_dispatch_gates"): "review.pre_dispatch_passed",
    ("review", "phase4_goal_comparison"): "review.goal_comparison_completed",
}


def discover_phase_dir(phase: str) -> Path | None:
    """Best-effort phase-dir lookup (matches contracts.resolve_phase_dir)."""
    for parent in ("dev-phases", ".vg/phases"):
        candidates = list((REPO_ROOT / parent).glob(f"{phase}*")) if (REPO_ROOT / parent).is_dir() else []
        if candidates:
            return candidates[0]
    # Allow explicit path passed as --phase
    p = Path(phase)
    if p.is_dir():
        return p
    return None


def scan_markers(phase_dir: Path) -> list[tuple[str, str]]:
    """Return list of (namespace, step_name) for every .done marker found."""
    out: list[tuple[str, str]] = []
    markers_dir = phase_dir / ".step-markers"
    if not markers_dir.is_dir():
        return out
    # Shared-namespace markers (legacy): phase/.step-markers/<step>.done
    for f in markers_dir.glob("*.done"):
        out.append(("shared", f.stem))
    # Per-namespace: phase/.step-markers/<namespace>/<step>.done
    for ns_dir in markers_dir.iterdir():
        if not ns_dir.is_dir():
            continue
        ns = ns_dir.name
        for f in ns_dir.glob("*.done"):
            out.append((ns, f.stem))
    return out


def _events_db_path() -> Path:
    return REPO_ROOT / ".vg" / "events.db"


def _import_db():
    """Lazy-import the orchestrator db module so the repair script works even
    when imports fail (we fall back to sqlite3 directly)."""
    try:
        import db as orch_db  # type: ignore
        return orch_db
    except Exception:
        return None


def _query_events(event_type: str | None = None) -> list[dict]:
    """Direct sqlite3 fallback when orchestrator db module unavailable."""
    import sqlite3
    p = _events_db_path()
    if not p.is_file():
        return []
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        if event_type:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type = ?", (event_type,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_missing_events(phase: str, phase_dir: Path) -> list[dict]:
    """Cross-reference markers against events.db. Return list of missing
    {marker_namespace, marker_step, event_type, run_id, phase}.

    run_id is best-effort — derived from the latest run that touched this phase.
    """
    markers = scan_markers(phase_dir)
    if not markers:
        return []

    orch_db = _import_db()
    # Build the set of event types already present for the phase
    present_event_types: set[str] = set()
    # Find a run_id to attribute repairs to — prefer the latest one for this phase
    run_id: str | None = None
    latest_ts: str = ""

    if orch_db is not None:
        for ev in orch_db.query_events(phase=phase, limit=10_000):
            present_event_types.add(ev.get("event_type", ""))
            ts = ev.get("ts", "")
            if ts > latest_ts:
                latest_ts = ts
                run_id = ev.get("run_id")
    else:
        for ev in _query_events():
            if ev.get("phase") == phase:
                present_event_types.add(ev.get("event_type", ""))
                ts = ev.get("ts", "")
                if ts > latest_ts:
                    latest_ts = ts
                    run_id = ev.get("run_id")

    missing: list[dict] = []
    for ns, step in markers:
        key = (ns, step)
        if key not in MARKER_TO_EVENT:
            continue
        ev_type = MARKER_TO_EVENT[key]
        if ev_type in present_event_types:
            continue
        missing.append({
            "marker_namespace": ns,
            "marker_step": step,
            "event_type": ev_type,
            "run_id": run_id,
            "phase": phase,
        })
    return missing


def repair_events(missing: list[dict]) -> int:
    """Emit the missing events. Returns repaired count."""
    if not missing:
        return 0
    orch_db = _import_db()
    if orch_db is None:
        print("\033[38;5;208mvg-orchestrator db module not importable — cannot repair.\033[0m", file=sys.stderr)
        print("   Run from the repo root so .claude/scripts/vg-orchestrator/ is on the path.", file=sys.stderr)
        return -1

    repaired = 0
    for m in missing:
        if not m.get("run_id"):
            print(f"  skip {m['event_type']}: no run_id found in events.db for phase {m['phase']}", file=sys.stderr)
            continue
        try:
            orch_db.append_event(
                run_id=m["run_id"],
                event_type=m["event_type"],
                phase=m["phase"],
                command=f"vg:{m['marker_namespace']}",
                actor="telemetry-repair",
                outcome="INFO",
                step=m["marker_step"],
                payload={
                    "auto_emitted": True,
                    "repaired": True,
                    "trigger_marker": m["marker_step"],
                    "trigger_namespace": m["marker_namespace"],
                    "source": "vg-orchestrator-telemetry-repair",
                },
            )
            repaired += 1
            print(f"  ✓ repaired {m['event_type']} (marker={m['marker_namespace']}/{m['marker_step']})")
        except Exception as exc:
            print(f"  ⛔ failed to emit {m['event_type']}: {exc}", file=sys.stderr)
    return repaired


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True, help="Phase number or path")
    ap.add_argument("--check", action="store_true",
                    help="Report missing events and exit 1 if any. Don't repair.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be repaired but don't write events.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    phase_dir = discover_phase_dir(args.phase)
    if not phase_dir:
        print(f"\033[38;5;208mphase dir not found for phase={args.phase}\033[0m", file=sys.stderr)
        return 2

    missing = find_missing_events(args.phase, phase_dir)

    if args.json:
        print(json.dumps({
            "phase": args.phase,
            "phase_dir": str(phase_dir),
            "missing_event_count": len(missing),
            "missing_events": missing,
        }, indent=2))
    else:
        if not missing:
            print(f"✓ No missing events for phase {args.phase} — telemetry is healthy.")
        else:
            print(f"Phase {args.phase}: {len(missing)} missing event(s) need repair:")
            for m in missing:
                print(f"  - {m['event_type']} (marker={m['marker_namespace']}/{m['marker_step']})")

    if args.check:
        return 1 if missing else 0
    if args.dry_run:
        return 0

    if missing:
        print(f"\nRepairing {len(missing)} event(s)...")
        repaired = repair_events(missing)
        if repaired < 0:
            return 2
        print(f"✓ Repaired {repaired}/{len(missing)} event(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
