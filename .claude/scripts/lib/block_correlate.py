"""block_correlate — read-only events.db query producing 3 detection sections.

Output format: structured markdown (consumed by /vg:doctor diagnostic + AI
during /vg:debug).

Detection rules (deterministic, no ML):
  1. RECURRING — same gate_id fires in >= min_runs distinct runs within window.
  2. CAUSAL CHAIN — gate A fires → gate B fires within ≤30s in same run, ≥2 runs.
  3. HIGH_VELOCITY — single gate's fire rate > (mean + 2*stddev) over prior 7-day window.

Dependencies: Task 27/28/29/30 payload structure (severity, skill_path,
fire_count) — gracefully handles their absence.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVENTS_DB_REL = ".vg/events.db"
DEFAULT_WINDOW_HOURS = 24


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


def _parse_window(spec: str) -> timedelta:
    if not spec:
        return timedelta(hours=DEFAULT_WINDOW_HOURS)
    spec = spec.strip().lower()
    try:
        if spec.endswith("h"):
            return timedelta(hours=int(spec[:-1]))
        if spec.endswith("d"):
            return timedelta(days=int(spec[:-1]))
        if spec.endswith("m"):
            return timedelta(minutes=int(spec[:-1]))
    except ValueError:
        pass
    return timedelta(hours=DEFAULT_WINDOW_HOURS)


def _ts_floor(window: timedelta) -> str:
    return (datetime.now(timezone.utc) - window).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_recurring(conn: sqlite3.Connection, since_ts: str,
                     min_runs: int = 3) -> list[dict]:
    rows = conn.execute("""
        SELECT json_extract(payload_json, '$.gate') gate,
               COUNT(*) total_fires,
               COUNT(DISTINCT run_id) run_count,
               MAX(ts) last_fired_ts
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
          AND ts >= ?
          AND json_extract(payload_json, '$.gate') IS NOT NULL
        GROUP BY gate
        HAVING run_count >= ?
        ORDER BY run_count DESC, total_fires DESC
    """, (since_ts, min_runs)).fetchall()
    return [
        {"gate": r[0], "total_fires": r[1], "run_count": r[2], "last_fired_ts": r[3]}
        for r in rows
    ]


def detect_causal_chains(conn: sqlite3.Connection, since_ts: str,
                          window_seconds: int = 30,
                          min_repeats: int = 2) -> list[dict]:
    """Pairs (A, B) where A fires then B fires within window_seconds in same run, in ≥min_repeats runs."""
    rows = conn.execute("""
        SELECT run_id, json_extract(payload_json, '$.gate') gate, ts
        FROM events
        WHERE event_type = 'vg.block.fired'
          AND ts >= ?
          AND json_extract(payload_json, '$.gate') IS NOT NULL
        ORDER BY run_id, ts
    """, (since_ts,)).fetchall()

    by_run: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for run_id, gate, ts in rows:
        by_run[run_id].append((gate, ts))

    pair_runs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for run_id, fires in by_run.items():
        for i in range(len(fires)):
            ga, ta = fires[i]
            try:
                ta_dt = datetime.fromisoformat(ta.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            for j in range(i + 1, len(fires)):
                gb, tb = fires[j]
                if gb == ga:
                    continue
                try:
                    tb_dt = datetime.fromisoformat(tb.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if (tb_dt - ta_dt).total_seconds() <= window_seconds:
                    pair_runs[(ga, gb)].add(run_id)
                    break

    return [
        {"gate_a": ga, "gate_b": gb, "repeat_count": len(runs),
         "runs_sample": sorted(runs)[:3]}
        for (ga, gb), runs in pair_runs.items()
        if len(runs) >= min_repeats
    ]


def detect_high_velocity(conn: sqlite3.Connection, window: timedelta,
                          baseline_days: int = 7) -> list[dict]:
    """Per gate: current window count > mean(daily_count over baseline) + 2*stddev."""
    now_ts = datetime.now(timezone.utc)
    window_start = (now_ts - window).strftime("%Y-%m-%dT%H:%M:%SZ")
    baseline_start = (now_ts - timedelta(days=baseline_days) - window).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    baseline_end = (now_ts - window).strftime("%Y-%m-%dT%H:%M:%SZ")

    current = conn.execute("""
        SELECT json_extract(payload_json, '$.gate') gate, COUNT(*)
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
          AND ts >= ?
          AND json_extract(payload_json, '$.gate') IS NOT NULL
        GROUP BY gate
    """, (window_start,)).fetchall()

    findings: list[dict] = []
    for gate, cur_count in current:
        baseline_rows = conn.execute("""
            SELECT DATE(ts) day, COUNT(*) cnt
            FROM events
            WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
              AND ts >= ? AND ts < ?
              AND json_extract(payload_json, '$.gate') = ?
            GROUP BY day
        """, (baseline_start, baseline_end, gate)).fetchall()
        counts = [r[1] for r in baseline_rows]
        if len(counts) < 2:
            continue
        mean = statistics.mean(counts)
        stdev = statistics.pstdev(counts)
        threshold = mean + 2 * stdev
        if cur_count > threshold and cur_count >= 3:
            findings.append({
                "gate": gate,
                "current_count": cur_count,
                "baseline_mean": round(mean, 2),
                "baseline_stdev": round(stdev, 2),
                "threshold": round(threshold, 2),
            })
    return sorted(findings, key=lambda f: -f["current_count"])


def render_markdown(recurring: list[dict],
                    causal: list[dict],
                    high_velocity: list[dict],
                    window_spec: str) -> str:
    lines = ["# Block Correlation Report", ""]
    lines.append(f"Window: `{window_spec}`")
    lines.append("")

    lines.append(f"## RECURRING (same gate × ≥3 runs in window) — {len(recurring)} finding(s)")
    lines.append("")
    if recurring:
        for r in recurring:
            lines.append(f"- gate `{r['gate']}` × {r['total_fires']} fires in "
                         f"{r['run_count']} runs (last: {r['last_fired_ts']})")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append(f"## CAUSAL_CHAIN (gate A → gate B ≤30s, repeated) — {len(causal)} finding(s)")
    lines.append("")
    if causal:
        for c in causal:
            sample = ", ".join(c["runs_sample"])
            lines.append(f"- `{c['gate_a']}` → `{c['gate_b']}` "
                         f"({c['repeat_count']} runs, sample: {sample})")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append(f"## HIGH_VELOCITY (>2σ above 7d baseline) — {len(high_velocity)} finding(s)")
    lines.append("")
    if high_velocity:
        for h in high_velocity:
            lines.append(f"- gate `{h['gate']}` fired {h['current_count']} times in window "
                         f"vs μ={h['baseline_mean']} σ={h['baseline_stdev']} prior 7d "
                         f"(threshold {h['threshold']})")
    else:
        lines.append("_(none)_")
    lines.append("")

    return "\n".join(lines)


def correlate(repo_root: str | Path | None, window_spec: str = "24h",
              min_runs: int = 3) -> str:
    db = _resolve_db(repo_root)
    if not db.exists():
        return "# Block Correlation Report\n\n_(events.db not found)_\n"
    window = _parse_window(window_spec)
    since_ts = _ts_floor(window)
    conn = None
    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        recurring = detect_recurring(conn, since_ts, min_runs=min_runs)
        causal = detect_causal_chains(conn, since_ts)
        high_v = detect_high_velocity(conn, window)
    except sqlite3.Error as e:
        return f"# Block Correlation Report\n\n_(query error: {e})_\n"
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    return render_markdown(recurring, causal, high_v, window_spec)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="24h", help="e.g. 24h, 7d, 90m")
    parser.add_argument("--min-runs", type=int, default=3)
    parser.add_argument("--repo-root")
    parser.add_argument("--output", help="Write to file instead of stdout")
    args = parser.parse_args()

    md = correlate(args.repo_root, args.window, args.min_runs)
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"✓ Wrote {args.output}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
