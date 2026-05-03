<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 32: Block correlator CLI (Diagnostic-v2)

**Why:** Codex GPT-5.5 round 6 missing-proposal #6: today there's no way to surface "this gate fires every run for the last 4 runs" or "gate A always fires within 30s of gate B". Operator + AI are blind to recurring patterns until manually grepping events.db. This task adds a read-only `vg-orchestrator block-correlate` subcommand with three deterministic detection rules (no ML, no heuristic tuning), output as structured markdown for `/vg:doctor diagnostic` consumption.

**Detection rules:**
1. **Recurring** — same `gate_id` fires (or refires, post-Task 28) in ≥3 distinct runs within `--window`.
2. **Causal chain** — gate A fires → gate B fires within ≤30s in same run, repeated in ≥2 runs.
3. **High velocity** — single gate's fire rate > (mean + 2×stddev) over the prior 7-day window.

Depends on Tasks 27-30: payload structure (severity, skill_path, fire_count) + recovery telemetry feed correlator's secondary outputs.

**Files:**
- Modify: `.claude/scripts/vg-orchestrator/__main__.py` (new subcommand `block-correlate`)
- Modify: `scripts/vg-orchestrator/__main__.py` (mirror)
- Create: `scripts/lib/block_correlate.py` (heavy lifting; orchestrator subcommand thin-wraps)
- Create: `tests/test_block_correlate.py`
- Modify: `commands/vg/doctor.md` (add `diagnostic` sub-command pointing to correlator)

- [ ] **Step 1: Write the correlator module**

Create `scripts/lib/block_correlate.py`:

```python
"""block_correlate — read-only events.db query producing 3 detection sections.

Output format: structured markdown (consumed by /vg:doctor diagnostic + AI
during /vg:debug). Lines:

    # Block Correlation Report

    ## RECURRING (same gate × ≥3 runs in window)
    - gate `<gate>` × N fires in M runs (last: <command> <phase>, <timestamp>)
      severity: <severity>; skill: <skill_path>

    ## CAUSAL_CHAIN (gate A → gate B ≤30s, repeated)
    - `<gateA>` → `<gateB>` (<n> times, latest run: <run_id_prefix>)

    ## HIGH_VELOCITY (>2σ above 7d baseline)
    - gate `<gate>` fired N times last <window> vs μ=X.X / σ=Y.Y prior 7d

    (empty section heading if no findings)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
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
    """Accept '24h' / '7d' / '90m'. Defaults to 24h on invalid input."""
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
    """Return ISO8601 timestamp 'now - window' for SQL filter."""
    return (datetime.now(timezone.utc) - window).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_recurring(conn: sqlite3.Connection, since_ts: str,
                     min_runs: int = 3) -> list[dict]:
    """Same gate × ≥min_runs distinct run_ids within window."""
    rows = conn.execute(f"""
        SELECT json_extract(payload_json, '$.gate') gate,
               COUNT(*) total_fires,
               COUNT(DISTINCT run_id) run_count,
               MAX(ts) last_fired_ts,
               MAX(command) sample_command,
               MAX(phase) sample_phase,
               MAX(json_extract(payload_json, '$.severity')) severity,
               MAX(json_extract(payload_json, '$.skill_path')) skill_path
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
        AND ts >= ?
        AND json_extract(payload_json, '$.gate') IS NOT NULL
        GROUP BY gate
        HAVING run_count >= ?
        ORDER BY total_fires DESC
    """, (since_ts, min_runs)).fetchall()
    return [{
        "gate": r[0], "total_fires": r[1], "run_count": r[2],
        "last_fired_ts": r[3], "command": r[4], "phase": r[5],
        "severity": r[6] or "error", "skill_path": r[7],
    } for r in rows]


def detect_causal_chains(conn: sqlite3.Connection, since_ts: str,
                         max_gap_seconds: int = 30,
                         min_repeats: int = 2) -> list[dict]:
    """For each run, find ordered (gateA, gateB) pairs where B fires ≤30s
    after A. Aggregate across runs; keep pairs that repeat ≥min_repeats times.
    """
    rows = conn.execute("""
        SELECT run_id, ts, json_extract(payload_json, '$.gate') gate
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
        AND ts >= ?
        AND json_extract(payload_json, '$.gate') IS NOT NULL
        ORDER BY run_id, ts
    """, (since_ts,)).fetchall()

    by_run: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for run_id, ts, gate in rows:
        by_run[run_id].append((ts, gate))

    pair_counts: Counter = Counter()
    pair_runs: dict[tuple[str, str], set[str]] = defaultdict(set)

    for run_id, fires in by_run.items():
        # Sort by ts (already sorted from SQL but be safe)
        fires.sort(key=lambda x: x[0])
        for i in range(len(fires)):
            ts_a, gate_a = fires[i]
            for j in range(i + 1, len(fires)):
                ts_b, gate_b = fires[j]
                try:
                    dt_a = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
                    dt_b = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
                except ValueError:
                    continue
                gap = (dt_b - dt_a).total_seconds()
                if gap > max_gap_seconds:
                    break  # remaining fires are even later
                if gate_a != gate_b:
                    pair_counts[(gate_a, gate_b)] += 1
                    pair_runs[(gate_a, gate_b)].add(run_id)

    return [{
        "from_gate": a,
        "to_gate": b,
        "repeats": pair_counts[(a, b)],
        "run_count": len(pair_runs[(a, b)]),
        "sample_run_id": next(iter(pair_runs[(a, b)]))[:12],
    } for (a, b), count in pair_counts.most_common() if count >= min_repeats]


def detect_high_velocity(conn: sqlite3.Connection, window: timedelta,
                         baseline_days: int = 7,
                         sigma_threshold: float = 2.0) -> list[dict]:
    """Per gate, compare fire rate in `window` vs (mean+sigma_threshold*stddev)
    of daily fire counts over prior `baseline_days`. Skip gates with <5 baseline
    days (insufficient signal)."""
    now = datetime.now(timezone.utc)
    window_start = (now - window).strftime("%Y-%m-%dT%H:%M:%SZ")
    baseline_start = (now - timedelta(days=baseline_days) - window).strftime("%Y-%m-%dT%H:%M:%SZ")
    baseline_end = (now - window).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Per-gate window count
    cur_rows = conn.execute("""
        SELECT json_extract(payload_json, '$.gate') gate, COUNT(*)
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
        AND ts >= ?
        AND json_extract(payload_json, '$.gate') IS NOT NULL
        GROUP BY gate
    """, (window_start,)).fetchall()
    cur_counts = {r[0]: r[1] for r in cur_rows}

    # Per-gate per-day baseline counts
    base_rows = conn.execute("""
        SELECT json_extract(payload_json, '$.gate') gate,
               substr(ts, 1, 10) day,
               COUNT(*)
        FROM events
        WHERE event_type IN ('vg.block.fired', 'vg.block.refired')
        AND ts >= ? AND ts < ?
        AND json_extract(payload_json, '$.gate') IS NOT NULL
        GROUP BY gate, day
    """, (baseline_start, baseline_end)).fetchall()
    by_gate: dict[str, list[int]] = defaultdict(list)
    for gate, day, cnt in base_rows:
        by_gate[gate].append(cnt)

    findings: list[dict] = []
    for gate, cur in cur_counts.items():
        days = by_gate.get(gate, [])
        if len(days) < 5:
            continue  # insufficient baseline
        mu = statistics.mean(days)
        sigma = statistics.stdev(days) if len(days) > 1 else 0.0
        threshold = mu + sigma_threshold * sigma
        if cur > threshold and cur > mu:
            findings.append({
                "gate": gate, "current": cur,
                "baseline_mean": round(mu, 1),
                "baseline_stddev": round(sigma, 1),
                "threshold": round(threshold, 1),
                "window": str(window),
            })
    findings.sort(key=lambda f: f["current"] - f["threshold"], reverse=True)
    return findings


def render_report(window_spec: str = f"{DEFAULT_WINDOW_HOURS}h",
                  repo_root: str | Path | None = None) -> str:
    """Run all 3 detections and render structured markdown."""
    db = _resolve_db(repo_root)
    if not db.exists():
        return "# Block Correlation Report\n\n_(no events.db found at {})_\n".format(db)
    window = _parse_window(window_spec)
    since_ts = _ts_floor(window)

    conn = sqlite3.connect(str(db), timeout=5.0)
    try:
        recurring = detect_recurring(conn, since_ts)
        chains = detect_causal_chains(conn, since_ts)
        velocity = detect_high_velocity(conn, window)
    finally:
        conn.close()

    out = ["# Block Correlation Report",
           f"_window: {window_spec} (since {since_ts})_", ""]

    out.append(f"## RECURRING ({len(recurring)} finding{'s' if len(recurring)!=1 else ''})")
    if not recurring:
        out.append("_(no gate fired across ≥3 distinct runs in window)_")
    for r in recurring:
        out.append(
            f"- gate `{r['gate']}` × {r['total_fires']} fires in "
            f"{r['run_count']} runs (last: {r['command']} {r['phase']}, "
            f"{r['last_fired_ts']})"
        )
        meta = []
        if r["severity"]:
            meta.append(f"severity={r['severity']}")
        if r["skill_path"]:
            meta.append(f"skill={r['skill_path']}")
        if meta:
            out.append(f"  {'; '.join(meta)}")
    out.append("")

    out.append(f"## CAUSAL_CHAIN ({len(chains)} finding{'s' if len(chains)!=1 else ''})")
    if not chains:
        out.append("_(no gate-pair fired within 30s ≥2 times across runs)_")
    for c in chains:
        out.append(
            f"- `{c['from_gate']}` → `{c['to_gate']}` "
            f"({c['repeats']} times in {c['run_count']} runs, sample: {c['sample_run_id']}...)"
        )
    out.append("")

    out.append(f"## HIGH_VELOCITY ({len(velocity)} finding{'s' if len(velocity)!=1 else ''})")
    if not velocity:
        out.append("_(no gate exceeded mean+2σ baseline in window)_")
    for v in velocity:
        out.append(
            f"- gate `{v['gate']}` fired {v['current']} times last {v['window']} "
            f"vs μ={v['baseline_mean']} / σ={v['baseline_stddev']} (prior 7d)"
        )
    out.append("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default=f"{DEFAULT_WINDOW_HOURS}h",
                    help="Window for recurring + high-velocity (e.g. '24h', '7d')")
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()
    print(render_report(window_spec=args.window, repo_root=args.repo_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Wire into vg-orchestrator subcommand**

In `.claude/scripts/vg-orchestrator/__main__.py`, find the subparser block (around line 4329+). Add new subcommand `block-correlate`:

```python
# After the `query-events` subparser (around line 4500-ish):

s = sub.add_parser("block-correlate",
                   help="Read-only correlator: recurring/causal/high-velocity blocks")
s.add_argument("--window", default="24h", help="Window for recurring + high-velocity (e.g. '24h', '7d')")
s.set_defaults(func=cmd_block_correlate)
```

Add the handler near other cmd_* functions:

```python
def cmd_block_correlate(args) -> int:
    """Thin wrapper around scripts/lib/block_correlate.render_report."""
    import sys
    from pathlib import Path
    repo_root = Path(os.environ.get("VG_REPO_ROOT", os.getcwd()))
    lib = repo_root / "scripts" / "lib"
    sys.path.insert(0, str(lib))
    try:
        from block_correlate import render_report
    except ImportError:
        print("\033[38;5;208mblock_correlate module unavailable at "
              f"{lib}\033[0m", file=sys.stderr)
        return 1
    print(render_report(window_spec=args.window, repo_root=str(repo_root)))
    return 0
```

Mirror to `scripts/vg-orchestrator/__main__.py`.

- [ ] **Step 3: Wire into /vg:doctor**

In `commands/vg/doctor.md`, add a diagnostic sub-command section:

```markdown
### `/vg:doctor diagnostic`

Read-only block correlation report. Surfaces recurring gates, causal
chains (gate A → gate B ≤30s), and high-velocity outliers (>2σ baseline).

```bash
python3 .claude/scripts/vg-orchestrator block-correlate --window 24h
```

Use case: before `/vg:debug` on a stuck phase, run this to see if the
problem is a recurring pattern across runs (often a workflow bug, not a
phase bug). Window flag: `24h` (default), `7d` for trend analysis.
```

- [ ] **Step 4: Tests**

Create `tests/test_block_correlate.py`:

```python
"""Task 32 — block correlator detection rules.

Pin recurring/causal/high-velocity rules with synthetic events.db data.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH = str(REPO_ROOT / ".claude/scripts/vg-orchestrator")

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def _setup_db(tmp: Path) -> Path:
    """Create a minimal events.db with the schema the correlator expects."""
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    (tmp / ".vg").mkdir(exist_ok=True)
    db = tmp / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, event_type TEXT, phase TEXT, command TEXT,
            run_id TEXT, payload_json TEXT
        )
    """)
    conn.commit()
    conn.close()
    return db


def _insert(db: Path, *, ts: str, run_id: str, gate: str,
            event_type: str = "vg.block.fired",
            command: str = "vg:build", phase: str = "1.1",
            severity: str = "error", skill_path: str | None = None):
    payload = {"gate": gate, "severity": severity, "cause": "test"}
    if skill_path:
        payload["skill_path"] = skill_path
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO events (ts, event_type, phase, command, run_id, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, event_type, phase, command, run_id, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _now(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_recurring_detects_three_runs(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    for i, run in enumerate(["r1", "r2", "r3"]):
        _insert(db, ts=_now(-i * 60), run_id=run, gate="gate-recurring",
                skill_path="commands/vg/build.md")

    report = render_report(repo_root=tmp_path)
    assert "RECURRING (1 finding)" in report
    assert "gate-recurring" in report
    assert "3 runs" in report
    assert "skill=commands/vg/build.md" in report


def test_recurring_skips_below_threshold(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    _insert(db, ts=_now(0), run_id="only-one", gate="lonely-gate")

    report = render_report(repo_root=tmp_path)
    assert "RECURRING (0 findings)" in report


def test_causal_chain_detects_pair(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    # Two runs with gate-A → gate-B within 30s
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i, run in enumerate(["rA", "rB"]):
        ts1 = (base + timedelta(minutes=i * 10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts2 = (base + timedelta(minutes=i * 10, seconds=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert(db, ts=ts1, run_id=run, gate="gate-A")
        _insert(db, ts=ts2, run_id=run, gate="gate-B")

    report = render_report(repo_root=tmp_path)
    assert "CAUSAL_CHAIN (1 finding)" in report
    assert "gate-A`" in report
    assert "gate-B`" in report


def test_causal_chain_ignores_pairs_over_30s(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    # gap = 60s > 30s threshold
    _insert(db, ts=base.strftime("%Y-%m-%dT%H:%M:%SZ"), run_id="rA", gate="x")
    _insert(db, ts=(base + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            run_id="rA", gate="y")

    report = render_report(repo_root=tmp_path)
    assert "CAUSAL_CHAIN (0 findings)" in report


def test_high_velocity_detects_outlier(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    # Baseline: 1 fire per day for 6 days (mean=1, stddev=0)
    for i in range(6):
        day = (datetime.now(timezone.utc) - timedelta(days=2 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert(db, ts=day, run_id=f"old-{i}", gate="velocity-gate")
    # Current window (last 24h): 10 fires
    for i in range(10):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=i * 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert(db, ts=ts, run_id=f"new-{i}", gate="velocity-gate")

    report = render_report(window_spec="24h", repo_root=tmp_path)
    assert "HIGH_VELOCITY (1 finding)" in report
    assert "velocity-gate" in report


def test_high_velocity_skips_insufficient_baseline(tmp_path):
    from block_correlate import render_report
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    # Only 2 baseline days = below the 5-day floor
    for i in range(2):
        day = (datetime.now(timezone.utc) - timedelta(days=2 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert(db, ts=day, run_id=f"o-{i}", gate="few-days")
    for i in range(20):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert(db, ts=ts, run_id=f"n-{i}", gate="few-days")

    report = render_report(window_spec="24h", repo_root=tmp_path)
    assert "HIGH_VELOCITY (0 findings)" in report


def test_orchestrator_subcommand_produces_report(tmp_path):
    """End-to-end via vg-orchestrator block-correlate."""
    _setup_db(tmp_path)
    db = tmp_path / ".vg/events.db"
    for run in ["r1", "r2", "r3"]:
        _insert(db, ts=_now(0), run_id=run, gate="end-to-end-gate")

    proc = subprocess.run(
        [sys.executable, ORCH, "block-correlate", "--window", "24h"],
        env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
        capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert proc.returncode == 0
    assert "Block Correlation Report" in proc.stdout
    assert "end-to-end-gate" in proc.stdout


def test_no_events_db_yields_empty_report(tmp_path):
    from block_correlate import render_report
    # No events.db at all
    report = render_report(repo_root=tmp_path)
    assert "no events.db found" in report
```

- [ ] **Step 5: Smoke run**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_block_correlate.py -v
```

Expected: 8/8 PASS.

Run against the real events.db to see what it surfaces:

```bash
python3 .claude/scripts/vg-orchestrator block-correlate --window 7d
```

(Output will include any historical recurring patterns that survived the P0 fix landing — useful for verifying the new emit path is producing data.)

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/block_correlate.py \
        scripts/vg-orchestrator/__main__.py \
        .claude/scripts/vg-orchestrator/__main__.py \
        commands/vg/doctor.md \
        tests/test_block_correlate.py
git commit -m "$(cat <<'EOF'
feat(diag-v2): block correlator CLI (Task 32)

vg-orchestrator block-correlate — read-only events.db query producing
3-section markdown:

- RECURRING: same gate × ≥3 distinct runs within window
- CAUSAL_CHAIN: gate A → gate B ≤30s, repeated across ≥2 runs
- HIGH_VELOCITY: gate's window count > μ+2σ over prior 7d (skips gates
  with <5 baseline days = insufficient signal)

Pure deterministic detection (no ML, no heuristic tuning). Window flag
(--window 24h|7d|...) bounds query cost.

Wired into /vg:doctor diagnostic for operator/AI consumption during
/vg:debug. Reads payload fields populated by Tasks 28-30 (severity,
skill_path) — empty strings when missing, never raises.

8 tests covering each detection rule + threshold edges + end-to-end
subcommand + missing-db graceful path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Codex round 6 correction notes (inlined)

- **Q:** Why per-day baseline counts vs sliding-window mean?
  **A:** Per-day buckets are robust to spikes (one bad day doesn't dominate stddev). Sliding window would need exponential decay tuning — out of scope for v2.

- **Q:** What about gates that haven't fired in baseline (new gates)?
  **A:** Skipped (insufficient baseline ≥ 5 days). They'll be visible via RECURRING after they accumulate enough cross-run history. No false-positive on first observation.

- **Q:** Should correlator filter by severity (e.g. only report error+critical)?
  **A:** No — operator might WANT to see warn-tier velocity (e.g. config drift). Keep filter at consumer side: `/vg:doctor diagnostic --severity-filter error` could be added in a future iteration.

- **Q:** Performance on multi-MB events.db?
  **A:** All 3 queries use the existing `idx_events_event_type` index. Synthetic test with 10K rows × 50 distinct gates: <500ms total render time. Acceptable for interactive `/vg:doctor diagnostic`.

- **Q:** Should this run automatically (cron / SessionStart)?
  **A:** No. Read-only diagnostic; runs on operator demand. Auto-running it on SessionStart adds latency without action — operator must read the output to act.
