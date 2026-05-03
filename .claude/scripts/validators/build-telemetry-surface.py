#!/usr/bin/env python3
"""
Validator: build-telemetry-surface.py

B11.2 (v2.4 hardening, 2026-04-23): cross-step telemetry feedback —
review entry reads recent build telemetry + surfaces FAIL/BLOCK events
so user (and review phase 3 fix-loop) doesn't re-discover what build
already knew.

Before B11.2: review phase 1 code scan + phase 2 browser discovery
re-discovered bugs that build telemetry had already flagged at commit
time (typecheck fail on wave 3, contract runtime mismatch, commit
attribution phantom cite). User re-learns. Info drops silently between
phases.

After B11.2: validator queries telemetry.jsonl for build events from
this phase within recent window, surfaces any FAIL/BLOCK outcomes as
review findings with origin tag `[from-build-telemetry]`, so phase 3
fix-loop pre-populates its candidate list.

Non-blocking: WARN only. Build already blocked those issues; review's
job is to confirm they're now fixed, not re-block.

Usage:
  build-telemetry-surface.py --phase <N> [--window-hours 24]

Exit codes:
  0 PASS (clean) or WARN (findings to surface)
  (Never 1 — non-blocking by design)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
TELEMETRY_PATH = REPO_ROOT / ".vg" / "telemetry.jsonl"

# Build-related step/command patterns we care about
BUILD_COMMAND_RE = {"vg:build"}
BUILD_STEPS = {
    "build.run-complete", "build.wave-complete", "build.post-mortem",
    "build.contract-runtime", "build.typecheck", "build.commit-attr",
}
INTERESTING_OUTCOMES = {"BLOCK", "FAIL", "ERROR"}


def _parse_event(line: str) -> dict | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _within_window(event: dict, cutoff: datetime) -> bool:
    ts = event.get("ts")
    if not ts:
        return False
    try:
        # Handle Z suffix + microsecond variance
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        evt_time = datetime.fromisoformat(ts)
        if evt_time.tzinfo is None:
            evt_time = evt_time.replace(tzinfo=timezone.utc)
        return evt_time >= cutoff
    except (ValueError, TypeError):
        return False


def _is_interesting(event: dict, phase: str) -> bool:
    if event.get("phase") != phase:
        return False
    cmd = event.get("command") or ""
    step = event.get("step") or ""
    outcome = event.get("outcome") or ""
    event_type = event.get("event_type") or ""

    is_build_related = (
        cmd in BUILD_COMMAND_RE
        or step.startswith("build.")
        or any(bs in step for bs in BUILD_STEPS)
        or "build" in event_type.lower()
    )
    return is_build_related and outcome in INTERESTING_OUTCOMES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--window-hours", type=int, default=24,
                    help="only surface events newer than this window")
    args = ap.parse_args()

    out = Output(validator="build-telemetry-surface")
    with timer(out):
        find_phase_dir(args.phase)  # just for resolution side-effect
        if not TELEMETRY_PATH.exists():
            # No telemetry = no build feedback to surface; PASS silently
            emit_and_exit(out)

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=args.window_hours)

        findings: list[dict] = []
        try:
            with TELEMETRY_PATH.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = _parse_event(line)
                    if not event:
                        continue
                    if not _within_window(event, cutoff):
                        continue
                    if _is_interesting(event, args.phase):
                        findings.append({
                            "ts": event.get("ts", ""),
                            "step": event.get("step", "?"),
                            "outcome": event.get("outcome", "?"),
                            "gate_id": event.get("gate_id") or "?",
                            "event_type": event.get("event_type", "?"),
                        })
        except OSError:
            emit_and_exit(out)

        if not findings:
            emit_and_exit(out)

        # Dedupe on (step, outcome, gate_id) — same gate firing 5× is still
        # one signal, not five
        seen: set[tuple] = set()
        unique: list[dict] = []
        for f in findings:
            key = (f["step"], f["outcome"], f["gate_id"])
            if key not in seen:
                seen.add(key)
                unique.append(f)

        sample = "; ".join(
            f"[{f['ts'][:19]}] {f['step']} {f['outcome']} gate={f['gate_id']}"
            for f in unique[:10]
        )

        # Always WARN, never BLOCK — build already blocked these at commit time
        out.warn(Evidence(
            type="build_telemetry_surfaced",
            message=t(
                "build_telemetry_surface.found.message",
                count=len(unique),
                window=args.window_hours,
            ),
            actual=sample,
            fix_hint=t("build_telemetry_surface.found.fix_hint"),
        ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
