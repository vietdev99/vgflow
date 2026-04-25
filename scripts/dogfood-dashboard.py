#!/usr/bin/env python3
"""
VG v2.6 Phase E (2026-04-26) — dogfood dashboard generator.

Reads .vg/events.jsonl + shells out to vg-orchestrator quarantine status
--json + bootstrap-conflict-detector outputs. Aggregates 5 sections into
a single-file HTML dashboard at .vg/dashboard.html.

Stdlib only (json, subprocess, pathlib, html, datetime). NO frameworks,
NO SQL parser — events.jsonl is canonical. Performance budget: <5s for
10-phase lookback on typical 5-10MB jsonl.

Usage:
  python3 .claude/scripts/dogfood-dashboard.py
  python3 .claude/scripts/dogfood-dashboard.py --lookback-phases 5 --output /tmp/d.html
  python3 .claude/scripts/dogfood-dashboard.py --max-events 50000

Sections:
  1. Autonomy %     — total events ÷ human-intervention events per phase
  2. Override rate  — override.used count per phase + reason histogram
  3. Friction time  — step duration per skill (timestamps in events.jsonl)
  4. Shadow corr.   — bootstrap.shadow_prediction events (Phase A telemetry)
  5. Conflict + quarantine — Phase C conflict pairs + quarantine CLI snapshot
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path


# ────────────────────────── repo-root resolution ──────────────────────────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
EVENTS_JSONL = REPO_ROOT / ".vg" / "events.jsonl"
TEMPLATE = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates"
    / "dashboard-template.html"
)
DEFAULT_OUTPUT = REPO_ROOT / ".vg" / "dashboard.html"
ORCH_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"

# Events that count as "human intervention" — denominator for autonomy %
HUMAN_INTERVENTION_TYPES = frozenset({
    "override.used",
    "human.confirm",
    "user.prompt_response",
    "deviation.architectural",
    "quarantine.re_enabled",
})


# ────────────────────────── data loading ──────────────────────────────────

def load_events(path: Path, max_events: int = 200_000) -> list[dict]:
    """Read events.jsonl line-by-line. Tolerate missing/empty file + bad lines."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    events: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(events) >= max_events:
                break
    return events


def filter_by_lookback(events: list[dict], lookback_phases: int) -> list[dict]:
    """Keep events from the last N distinct phases (most-recent N).

    Empty `phase` field counted as one synthetic bucket; orchestrator-level
    events still surface even when phase is unset.
    """
    if lookback_phases <= 0:
        return events
    seen_order: list[str] = []
    seen_set: set[str] = set()
    # Walk newest → oldest, collect last-N distinct phases
    for ev in reversed(events):
        ph = (ev.get("phase") or "").strip() or "(no-phase)"
        if ph not in seen_set:
            seen_set.add(ph)
            seen_order.append(ph)
            if len(seen_order) >= lookback_phases:
                break
    keep = set(seen_order)
    return [
        ev for ev in events
        if ((ev.get("phase") or "").strip() or "(no-phase)") in keep
    ]


# ────────────────────────── subprocess shells ─────────────────────────────

def fetch_quarantine_state() -> dict:
    """Shell out to vg-orchestrator quarantine status --json. Tolerate failure."""
    try:
        result = subprocess.run(
            ["python3", str(ORCH_SCRIPT), "quarantine", "status", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return {"schema": "quarantine.status.v1", "total": 0, "entries": [],
            "disabled_count": 0, "stale_unquarantinable": []}


# ────────────────────────── aggregations ──────────────────────────────────

def aggregate_autonomy(events: list[dict]) -> list[dict]:
    """Per phase: total events vs human-intervention count → autonomy %."""
    totals: dict[str, int] = defaultdict(int)
    human: dict[str, int] = defaultdict(int)
    for ev in events:
        ph = (ev.get("phase") or "").strip() or "(no-phase)"
        totals[ph] += 1
        if ev.get("event_type") in HUMAN_INTERVENTION_TYPES:
            human[ph] += 1
    rows = []
    for ph in sorted(totals.keys()):
        t = totals[ph]
        h = human[ph]
        autonomy = ((t - h) / t * 100.0) if t else 0.0
        rows.append({
            "phase": ph,
            "total_events": t,
            "human_events": h,
            "autonomy_pct": autonomy,
        })
    return rows


def aggregate_override(events: list[dict]) -> list[dict]:
    """Group override.used by phase, with reason histogram."""
    by_phase: dict[str, list[str]] = defaultdict(list)
    for ev in events:
        if ev.get("event_type") != "override.used":
            continue
        ph = (ev.get("phase") or "").strip() or "(no-phase)"
        payload = ev.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        reason = (payload.get("reason") or payload.get("flag")
                  or payload.get("override_reason") or "unspecified")
        by_phase[ph].append(str(reason)[:80])
    rows = []
    for ph in sorted(by_phase.keys()):
        reasons = by_phase[ph]
        hist = Counter(reasons).most_common(5)
        rows.append({
            "phase": ph,
            "count": len(reasons),
            "top_reasons": hist,
        })
    return rows


def aggregate_friction(events: list[dict]) -> list[dict]:
    """Avg/median step duration per skill — pair *.started with *.complete by run_id+step."""
    started: dict[tuple, datetime] = {}
    durations: dict[str, list[float]] = defaultdict(list)
    for ev in events:
        et = ev.get("event_type", "")
        if not et:
            continue
        ts = _parse_ts(ev.get("ts"))
        if ts is None:
            continue
        key = (ev.get("run_id") or "", ev.get("command") or "",
               ev.get("step") or "")
        if et.endswith(".started") or et == "step.started":
            started[key] = ts
        elif (et.endswith(".complete") or et.endswith(".completed")
              or et == "step.complete"):
            start_ts = started.pop(key, None)
            if start_ts is None:
                continue
            delta = (ts - start_ts).total_seconds()
            if delta < 0 or delta > 86400:  # sanity clamp 1d
                continue
            skill = ev.get("command") or "(unknown)"
            durations[skill].append(delta)
    rows = []
    for skill in sorted(durations.keys()):
        vals = durations[skill]
        if not vals:
            continue
        rows.append({
            "skill": skill,
            "n": len(vals),
            "avg_s": sum(vals) / len(vals),
            "p50_s": _median(vals),
            "max_s": max(vals),
        })
    rows.sort(key=lambda r: r["avg_s"], reverse=True)
    return rows


def aggregate_shadow(events: list[dict]) -> list[dict]:
    """Per rule: shadow correctness from bootstrap.shadow_prediction events.

    Schema (Phase A): payload includes rule_id, predicted_outcome, actual_outcome.
    Correctness = (predicted == actual) / n.
    """
    by_rule: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0})
    for ev in events:
        if ev.get("event_type") != "bootstrap.shadow_prediction":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        rule_id = payload.get("rule_id")
        if not rule_id:
            continue
        predicted = payload.get("predicted_outcome") or payload.get("predicted")
        actual = payload.get("actual_outcome") or payload.get("actual")
        bucket = by_rule[rule_id]
        bucket["n"] += 1
        if predicted is not None and actual is not None and predicted == actual:
            bucket["correct"] += 1
    rows = []
    for rid in sorted(by_rule.keys()):
        b = by_rule[rid]
        rate = (b["correct"] / b["n"] * 100.0) if b["n"] else 0.0
        rows.append({"rule_id": rid, "n": b["n"], "correct": b["correct"],
                     "correctness_pct": rate})
    rows.sort(key=lambda r: (-r["n"], r["rule_id"]))
    return rows


def aggregate_conflicts() -> list[dict]:
    """Read Phase C conflict pairs from .vg/bootstrap/conflicts.json if present."""
    candidates = [
        REPO_ROOT / ".vg" / "bootstrap" / "conflicts.json",
        REPO_ROOT / ".vg" / "conflicts.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pairs = data.get("pairs") or data.get("conflicts") or data
        if not isinstance(pairs, list):
            continue
        rows = []
        for pr in pairs[:200]:
            if not isinstance(pr, dict):
                continue
            rows.append({
                "rule_a": pr.get("rule_a") or pr.get("a") or "",
                "rule_b": pr.get("rule_b") or pr.get("b") or "",
                "winner": pr.get("winner"),
                "similarity": pr.get("similarity"),
                "reason": pr.get("reason") or pr.get("conflict_kind") or "",
            })
        return rows
    return []


# ────────────────────────── helpers ───────────────────────────────────────

def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, ValueError):
            return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    # tolerate 'Z' suffix and missing microseconds
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _median(vals: list[float]) -> float:
    n = len(vals)
    if not n:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _fmt_secs(s: float) -> str:
    if s < 1:
        return f"{s*1000:.0f}ms"
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


# ────────────────────────── HTML renderers ────────────────────────────────

def render_autonomy(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No events in lookback window.</p>'
    out = ['<table class="sortable"><thead><tr>',
           '<th>Phase</th><th>Total events</th><th>Human events</th>',
           '<th>Autonomy %</th><th></th></tr></thead><tbody>']
    for r in rows:
        bar_w = max(2, min(120, int(r["autonomy_pct"] * 1.2)))
        out.append(
            f'<tr><td>{escape(r["phase"])}</td>'
            f'<td class="num">{r["total_events"]}</td>'
            f'<td class="num">{r["human_events"]}</td>'
            f'<td class="num">{r["autonomy_pct"]:.1f}%</td>'
            f'<td><span class="bar" style="width:{bar_w}px"></span></td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_override(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No override.used events.</p>'
    out = ['<table class="sortable"><thead><tr>',
           '<th>Phase</th><th>Overrides</th><th>Top reasons</th></tr></thead><tbody>']
    for r in rows:
        reason_pills = " ".join(
            f'<span class="pill">{escape(reason)} ×{count}</span>'
            for reason, count in r["top_reasons"]
        )
        out.append(
            f'<tr><td>{escape(r["phase"])}</td>'
            f'<td class="num">{r["count"]}</td>'
            f'<td>{reason_pills}</td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_friction(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No paired started/complete events.</p>'
    out = ['<table class="sortable"><thead><tr>',
           '<th>Skill</th><th>Runs</th><th>Avg</th><th>P50</th><th>Max</th>',
           '</tr></thead><tbody>']
    for r in rows:
        out.append(
            f'<tr><td><code>{escape(r["skill"])}</code></td>'
            f'<td class="num">{r["n"]}</td>'
            f'<td class="num">{_fmt_secs(r["avg_s"])}</td>'
            f'<td class="num">{_fmt_secs(r["p50_s"])}</td>'
            f'<td class="num">{_fmt_secs(r["max_s"])}</td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_shadow(rows: list[dict]) -> str:
    if not rows:
        return ('<p class="empty">No bootstrap.shadow_prediction events. '
                'Phase A telemetry not yet flowing — dashboard will populate '
                'as new candidates run in shadow mode.</p>')
    out = ['<table class="sortable"><thead><tr>',
           '<th>Rule</th><th>Samples</th><th>Correct</th>',
           '<th>Correctness %</th></tr></thead><tbody>']
    for r in rows:
        cls = ("good" if r["correctness_pct"] >= 95
               else "warn" if r["correctness_pct"] >= 80
               else "bad")
        out.append(
            f'<tr><td><code>{escape(r["rule_id"])}</code></td>'
            f'<td class="num">{r["n"]}</td>'
            f'<td class="num">{r["correct"]}</td>'
            f'<td class="num"><span class="pill {cls}">{r["correctness_pct"]:.1f}%</span></td>'
            f'</tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_conflicts(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No conflict pairs detected (Phase C clean).</p>'
    out = ['<table class="sortable"><thead><tr>',
           '<th>Rule A</th><th>Rule B</th><th>Sim</th><th>Winner</th>',
           '<th>Reason</th></tr></thead><tbody>']
    for r in rows:
        sim = r.get("similarity")
        sim_str = f"{sim:.2f}" if isinstance(sim, (int, float)) else "—"
        winner = r.get("winner") or "—"
        out.append(
            f'<tr><td><code>{escape(r["rule_a"])}</code></td>'
            f'<td><code>{escape(r["rule_b"])}</code></td>'
            f'<td class="num">{sim_str}</td>'
            f'<td>{escape(str(winner))}</td>'
            f'<td>{escape(str(r["reason"]))}</td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_quarantine(state: dict) -> str:
    entries = state.get("entries") or []
    if not entries:
        return '<p class="empty">All validators healthy.</p>'
    out = [
        f'<p class="empty">Total: {state.get("total", 0)} · '
        f'Disabled: {state.get("disabled_count", 0)} · '
        f'Stale: {len(state.get("stale_unquarantinable") or [])}</p>',
        '<table class="sortable"><thead><tr>',
        '<th>Validator</th><th>Status</th><th>Fails</th><th>Last fail</th>',
        '</tr></thead><tbody>',
    ]
    for e in entries:
        tags = []
        if e.get("disabled"):
            tags.append('<span class="pill bad">DISABLED</span>')
        if e.get("unquarantinable"):
            tags.append('<span class="pill badge-locked">UNQUARANTINABLE</span>')
        if not tags:
            tags.append('<span class="pill good">active</span>')
        out.append(
            f'<tr><td><code>{escape(e["validator"])}</code></td>'
            f'<td>{"".join(tags)}</td>'
            f'<td class="num">{e.get("consecutive_fails", 0)}</td>'
            f'<td>{escape(str(e.get("last_fail_at") or "—"))}</td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


# ────────────────────────── orchestrator ──────────────────────────────────

def build_dashboard(events: list[dict], lookback: int,
                    output_path: Path) -> dict:
    """Render dashboard, return summary stats for caller (CLI/tests)."""
    if not TEMPLATE.exists():
        # Inline fallback template — keep generator usable even if asset missing.
        template = (
            "<!DOCTYPE html><html><body><h1>VG Dogfood Dashboard</h1>"
            "<!-- META_GENERATED -->"
            "<!-- AUTONOMY_TABLE --><!-- OVERRIDE_TABLE -->"
            "<!-- FRICTION_TABLE --><!-- SHADOW_TABLE -->"
            "<!-- CONFLICT_TABLE --><!-- QUARANTINE_TABLE -->"
            "<!-- FOOTER --></body></html>"
        )
    else:
        template = TEMPLATE.read_text(encoding="utf-8")

    filtered = filter_by_lookback(events, lookback)
    autonomy = aggregate_autonomy(filtered)
    overrides = aggregate_override(filtered)
    friction = aggregate_friction(filtered)
    shadow = aggregate_shadow(filtered)
    conflicts = aggregate_conflicts()
    quarantine_state = fetch_quarantine_state()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = (
        f"Generated {escape(now)} · {len(filtered)} events · "
        f"lookback {lookback} phase(s)"
    )
    footer = (
        f"VG dogfood-dashboard · {len(events)} total events scanned · "
        f"autonomy={len(autonomy)} phases · friction={len(friction)} skills"
    )

    rendered = (
        template
        .replace("<!-- META_GENERATED -->", meta)
        .replace("<!-- AUTONOMY_TABLE -->", render_autonomy(autonomy))
        .replace("<!-- OVERRIDE_TABLE -->", render_override(overrides))
        .replace("<!-- FRICTION_TABLE -->", render_friction(friction))
        .replace("<!-- SHADOW_TABLE -->", render_shadow(shadow))
        .replace("<!-- CONFLICT_TABLE -->", render_conflicts(conflicts))
        .replace("<!-- QUARANTINE_TABLE -->", render_quarantine(quarantine_state))
        .replace("<!-- FOOTER -->", footer)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    return {
        "output": str(output_path),
        "events_scanned": len(events),
        "events_after_lookback": len(filtered),
        "phases_in_autonomy": len(autonomy),
        "skills_in_friction": len(friction),
        "rules_in_shadow": len(shadow),
        "conflict_pairs": len(conflicts),
        "quarantine_entries": quarantine_state.get("total", 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate VG dogfood dashboard (single-file HTML).")
    ap.add_argument("--lookback-phases", type=int, default=10,
                    help="Keep events from last N distinct phases (default 10)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Output HTML path (default {DEFAULT_OUTPUT})")
    ap.add_argument("--max-events", type=int, default=200_000,
                    help="Hard cap on events read (perf safeguard)")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress summary stdout (still writes file)")
    args = ap.parse_args()

    events = load_events(EVENTS_JSONL, max_events=args.max_events)
    summary = build_dashboard(events, args.lookback_phases, args.output)

    if not args.quiet:
        print(f"✓ Dashboard generated → {summary['output']}")
        print(f"  events scanned: {summary['events_scanned']}")
        print(f"  after lookback: {summary['events_after_lookback']}")
        print(f"  phases: {summary['phases_in_autonomy']} · "
              f"skills: {summary['skills_in_friction']} · "
              f"shadow rules: {summary['rules_in_shadow']} · "
              f"conflicts: {summary['conflict_pairs']} · "
              f"quarantine: {summary['quarantine_entries']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
