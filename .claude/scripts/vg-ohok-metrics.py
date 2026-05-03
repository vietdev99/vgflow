#!/usr/bin/env python3
"""
vg-ohok-metrics.py — behavioral OHOK (One Hit One Kill) measurement.

Problem (Gemini OHOK v2 review 2026-04-22):
  Syntactic checks — "validator registered, hook wired, file exists" — can
  all be green while behavioral reality (actual test pass rate, % of phases
  completing without AI intervention, frequency of escape-hatch usage) is
  bad. Workflow claims 8/10 OHOK but user still feels it's 3/10 because
  the DATA says otherwise.

This script reads `.vg/events.db` (authoritative event log) and emits true
behavioral measurements:
  - OHOK score: % of phase runs reaching run.completed PASS with 0 overrides
  - Override pressure: mean overrides per run, top 10 bypass flags
  - Promote-manual usage: per-phase, flag phases near quota
  - Command success rate: per-command pass/fail/abort breakdown
  - Validator health: which validators BLOCK most often

Usage:
  python vg-ohok-metrics.py               # plain text dashboard
  python vg-ohok-metrics.py --json        # machine-readable JSON
  python vg-ohok-metrics.py --since 30d   # only last 30 days
  python vg-ohok-metrics.py --command build  # filter to one command

Exit codes:
  0 — metrics rendered successfully
  1 — DB missing or unreadable
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DB_PATH = REPO_ROOT / ".vg" / "events.db"

# ANSI color codes (stripped when piped)
def _c(code: str) -> str:
    return code if sys.stdout.isatty() else ""

GREEN = _c("\033[32m")
RED = _c("\033[31m")
YELLOW = _c("\033[33m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RESET = _c("\033[0m")


def _parse_since(since: str) -> datetime | None:
    """Parse '30d', '7d', '24h', or ISO date into a cutoff datetime."""
    if not since:
        return None
    since = since.strip().lower()
    now = datetime.now(timezone.utc)
    if since.endswith("d"):
        try:
            return now - timedelta(days=int(since[:-1]))
        except ValueError:
            return None
    if since.endswith("h"):
        try:
            return now - timedelta(hours=int(since[:-1]))
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_events(since_dt: datetime | None, command_filter: str | None) -> list[dict]:
    """Read events from SQLite DB. Returns newest-first sorted by id."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        q = "SELECT id, run_id, event_type, phase, command, actor, outcome, " \
            "ts, payload_json FROM events"
        params: list = []
        conds: list[str] = []
        if since_dt:
            conds.append("ts >= ?")
            params.append(since_dt.isoformat().replace("+00:00", "Z"))
        if command_filter:
            conds.append("command = ?")
            params.append(f"vg:{command_filter}" if not command_filter.startswith("vg:")
                          else command_filter)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload_json"] or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def compute_metrics(events: list[dict]) -> dict:
    """Primary analysis. Returns dict with all measurements."""
    # Group events by run_id — each run is one /vg:* invocation
    by_run: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_run[e["run_id"]].append(e)

    # Analyze each run
    run_outcomes: list[dict] = []
    for run_id, evs in by_run.items():
        # Sort chronologically
        evs.sort(key=lambda x: x["id"])
        first = evs[0]
        command = first["command"]
        phase = first["phase"]

        outcome = "UNKNOWN"
        finalized = False
        override_used_count = 0
        validation_blocks = 0
        blocked_attempts = 0      # OHOK-5: count run.blocked events (intermediate failures)
        promote_manual_count = 0
        repaired = False          # OHOK-5: any run-repair invocation
        stale_cleared = False     # OHOK-5: run was stale-cleared at some point
        override_flags: list[str] = []

        for e in evs:
            et = e["event_type"]
            if et == "run.completed":
                outcome = e.get("outcome", "PASS")
                finalized = True
            elif et == "run.aborted":
                outcome = "ABORTED"
                finalized = True
            elif et == "run.blocked":
                outcome = "BLOCKED"
                blocked_attempts += 1
                # don't mark finalized — might continue after fix
            elif et == "run.stale_cleared":
                stale_cleared = True
                # OHOK-5 (Codex): stale-cleared runs were abandoned, must be
                # counted as finalized=ABORTED so they stay in the denominator.
                outcome = "STALE_CLEARED"
                finalized = True
            elif et == "run.repaired" or et == "run.resumed":
                repaired = True
            elif et == "override.used":
                override_used_count += 1
                flag = (e.get("payload") or {}).get("flag")
                if flag:
                    override_flags.append(flag)
            elif et == "goal.promoted_manual":
                promote_manual_count += 1
            elif et.startswith("validation.") and (e.get("outcome") == "BLOCK"):
                validation_blocks += 1

        # OHOK-5 (Codex P0): tightened definition. A run is OHOK only if it
        # reached PASS in ONE shot — no validation BLOCKs, no prior blocked
        # attempts, no repairs/resumes, no overrides, no manual promotions,
        # and wasn't stale-cleared. "Failed-first-fixed-later" no longer
        # counts. This is the TRUE one-hit-one-kill measurement.
        is_ohok = (
            outcome == "PASS"
            and override_used_count == 0
            and promote_manual_count == 0
            and validation_blocks == 0
            and blocked_attempts == 0
            and not repaired
            and not stale_cleared
        )

        run_outcomes.append({
            "run_id": run_id[:8],
            "command": command,
            "phase": phase,
            "outcome": outcome,
            "finalized": finalized,
            "override_used": override_used_count,
            "validation_blocks": validation_blocks,
            "blocked_attempts": blocked_attempts,
            "promote_manual": promote_manual_count,
            "repaired": repaired,
            "stale_cleared": stale_cleared,
            "override_flags": override_flags,
            "is_ohok": is_ohok,
        })

    # Aggregate
    total_runs = len(run_outcomes)
    finalized_runs = [r for r in run_outcomes if r["finalized"]]
    completed_pass = [r for r in run_outcomes if r["outcome"] == "PASS"]
    ohok_runs = [r for r in run_outcomes if r["is_ohok"]]
    aborted = [r for r in run_outcomes if r["outcome"] == "ABORTED"]
    blocked_not_finalized = [r for r in run_outcomes
                             if r["outcome"] == "BLOCKED" and not r["finalized"]]

    # OHOK rate: divided by FINALIZED runs (blocked-in-progress shouldn't count)
    ohok_rate = (len(ohok_runs) / len(finalized_runs) * 100) if finalized_runs else 0.0
    pass_rate = (len(completed_pass) / len(finalized_runs) * 100) if finalized_runs else 0.0

    # Per-command breakdown
    by_cmd: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "pass": 0, "ohok": 0, "aborted": 0, "blocked": 0}
    )
    for r in run_outcomes:
        cmd = r["command"]
        by_cmd[cmd]["total"] += 1
        if r["outcome"] == "PASS":
            by_cmd[cmd]["pass"] += 1
        if r["is_ohok"]:
            by_cmd[cmd]["ohok"] += 1
        if r["outcome"] == "ABORTED":
            by_cmd[cmd]["aborted"] += 1
        if r["outcome"] == "BLOCKED" and not r["finalized"]:
            by_cmd[cmd]["blocked"] += 1

    # Override pressure
    all_flags = [f for r in run_outcomes for f in r["override_flags"]]
    top_flags = Counter(all_flags).most_common(10)
    mean_overrides = sum(r["override_used"] for r in run_outcomes) / max(total_runs, 1)

    # Promote-manual distribution
    manual_by_phase: dict[str, int] = defaultdict(int)
    for r in run_outcomes:
        if r["promote_manual"]:
            manual_by_phase[r["phase"]] += r["promote_manual"]
    # flag phases near quota (3)
    near_quota = [(p, n) for p, n in manual_by_phase.items() if n >= 2]
    near_quota.sort(key=lambda x: -x[1])

    # Validator failure distribution
    validator_blocks: Counter[str] = Counter()
    for e in events:
        if e["event_type"].startswith("validation.") and e.get("outcome") == "BLOCK":
            v = (e.get("payload") or {}).get("validator") or "unknown"
            validator_blocks[v] += 1

    # Phase sample size
    distinct_phases = len({r["phase"] for r in run_outcomes if r["phase"]})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_runs": total_runs,
        "finalized_runs": len(finalized_runs),
        "distinct_phases": distinct_phases,
        "completed_pass": len(completed_pass),
        "ohok_runs": len(ohok_runs),
        "aborted": len(aborted),
        "blocked_in_progress": len(blocked_not_finalized),
        "ohok_rate_pct": round(ohok_rate, 1),
        "pass_rate_pct": round(pass_rate, 1),
        "mean_overrides_per_run": round(mean_overrides, 2),
        "top_override_flags": top_flags,
        "by_command": dict(by_cmd),
        "promote_manual_by_phase": dict(manual_by_phase),
        "near_quota_phases": near_quota,
        "validator_blocks_top": validator_blocks.most_common(10),
        "runs": run_outcomes,
    }


def _ohok_color(rate: float) -> str:
    if rate >= 80:
        return GREEN
    if rate >= 50:
        return YELLOW
    return RED


def render_text(m: dict) -> str:
    """Pretty dashboard."""
    lines: list[str] = []
    a = lines.append
    a(f"{BOLD}━━━ VG OHOK metrics (behavioral truth) ━━━{RESET}")
    a(f"{DIM}Generated: {m['generated_at']}{RESET}")
    a(f"{DIM}Repo: {REPO_ROOT}{RESET}")
    a("")

    # Sample size warning
    n = m["finalized_runs"]
    phases = m["distinct_phases"]
    if n < 20:
        a(f"{YELLOW}⚠ Small sample: {n} finalized runs across {phases} phases. "
          f"OHOK rate statistically noisy under 20 runs.{RESET}")
    a("")

    # OHOK score — headline
    ohok_rate = m["ohok_rate_pct"]
    pass_rate = m["pass_rate_pct"]
    c = _ohok_color(ohok_rate)
    a(f"{BOLD}OHOK RATE: {c}{ohok_rate:.1f}%{RESET}   "
      f"({m['ohok_runs']}/{m['finalized_runs']} finalized runs completed "
      f"PASS with 0 overrides + 0 manual promotions)")
    a(f"PASS rate: {pass_rate:.1f}% ({m['completed_pass']}/{m['finalized_runs']})")
    a(f"Aborted: {m['aborted']}  Blocked (in progress): {m['blocked_in_progress']}")
    a(f"Mean overrides/run: {m['mean_overrides_per_run']}")
    a("")

    # Per-command breakdown
    a(f"{BOLD}Per-command breakdown:{RESET}")
    a(f"{'COMMAND':<20} {'TOTAL':>6} {'PASS':>6} {'OHOK':>6} {'ABORT':>6} {'BLOCK':>6}")
    a("─" * 60)
    for cmd in sorted(m["by_command"].keys()):
        s = m["by_command"][cmd]
        ohok_pct = (s["ohok"] / s["total"] * 100) if s["total"] else 0
        cc = _ohok_color(ohok_pct)
        a(f"{cmd:<20} {s['total']:>6} {s['pass']:>6} "
          f"{cc}{s['ohok']:>6}{RESET} {s['aborted']:>6} {s['blocked']:>6}")
    a("")

    # Top override flags
    if m["top_override_flags"]:
        a(f"{BOLD}Top override flags (bypass pressure):{RESET}")
        for flag, count in m["top_override_flags"]:
            bar = "█" * min(count, 30)
            a(f"  {count:>4}x  {flag:<40} {RED}{bar}{RESET}")
        a("")

    # Promote-manual near quota
    if m["near_quota_phases"]:
        a(f"{BOLD}Promote-manual usage (quota=3):{RESET}")
        for phase, count in m["near_quota_phases"]:
            warn = f"{RED}AT QUOTA{RESET}" if count >= 3 else f"{YELLOW}NEAR QUOTA{RESET}"
            a(f"  Phase {phase:<10} {count}/3  {warn}")
        a("")

    # Validator blocks top 10
    if m["validator_blocks_top"]:
        a(f"{BOLD}Validators firing most BLOCKs:{RESET}")
        for v, count in m["validator_blocks_top"]:
            a(f"  {count:>4}x  {v}")
        a("")

    # Interpretation hint
    a(f"{DIM}Interpretation:")
    a(f"  - OHOK ≥80%:  workflow mature, trust AI runs")
    a(f"  - OHOK 50-80%: useful but needs oversight on pipeline transitions")
    a(f"  - OHOK <50%:  user intervention needed >50% of time — investigate")
    a(f"                top override flags to see what AI keeps skipping.{RESET}")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of text dashboard")
    ap.add_argument("--since", default=None,
                    help="only include events since <Nd|Nh|ISO-date>")
    ap.add_argument("--command", default=None,
                    help="filter to one command (build, review, etc.)")
    ap.add_argument("--out", default=None,
                    help="write output to file instead of stdout")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"\033[38;5;208mevents.db not found at {DB_PATH}\033[0m", file=sys.stderr)
        return 1

    since_dt = _parse_since(args.since) if args.since else None
    events = fetch_events(since_dt, args.command)
    metrics = compute_metrics(events)

    if args.json:
        out_text = json.dumps(metrics, indent=2, default=str)
    else:
        out_text = render_text(metrics)

    if args.out:
        Path(args.out).write_text(out_text, encoding="utf-8")
        print(f"✓ Metrics written to {args.out}")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
