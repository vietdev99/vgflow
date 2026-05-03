#!/usr/bin/env python3
"""
verify-validator-drift.py — Phase S of v2.5.2 hardening.

Problem closed:
  With 20+ validators in registry.yaml, some will drift over time:
  always-pass (FP rate too high → candidate for tightening OR disable),
  never-fire (zero detection over 100 runs → dead code), or perf
  regression (runtime 2x+ baseline). Without meta-observability, ops
  team can't see what's broken.

This validator queries orchestrator SQLite events (validator outcomes +
timings emitted by _common.py) over a lookback window and flags drift.

Detection patterns:
  1. always_pass_high_fp — validator fires >= min_runs AND 100% pass
     (likely useless; can be demoted to warn OR removed)
  2. never_fires — validator enabled in registry but 0 runs in lookback
     (dead / not wired / wrong phase binding)
  3. perf_regression — p95 runtime > 2x registry target_ms
  4. always_block — validator fires >= min_runs AND 100% block
     (likely false-positive pattern; investigation needed)

Exit codes:
  0 = no drift in lookback window
  1 = drift detected (exit 1 advisory in report; orchestrator surfaces for ops)
  2 = config error (DB not found, registry malformed)

Usage:
  verify-validator-drift.py --db-path .vg/state/events.db
  verify-validator-drift.py --lookback-days 30 --min-runs 10
  verify-validator-drift.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
DEFAULT_DB = REPO_ROOT / ".vg" / "state" / "events.db"
DEFAULT_REGISTRY = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"


def _load_registry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(text) or {}
    except ImportError:
        data = _yaml_minimal(text)
    return data.get("validators", [])


def _yaml_minimal(text: str) -> dict:
    entries = []
    current = {}
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if stripped == "validators:" and indent == 0:
            in_list = True
            continue
        if not in_list:
            continue
        if stripped.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            rest = stripped[2:]
            if ":" in rest:
                k, _, v = rest.partition(":")
                current[k.strip()] = v.strip().strip("'\"")
            continue
        if ":" in stripped and current is not None:
            k, _, v = stripped.partition(":")
            v = v.strip().strip("'\"")
            if v.isdigit():
                current[k.strip()] = int(v)
            else:
                current[k.strip()] = v
    if current:
        entries.append(current)
    return {"validators": entries}


def _query_validator_stats(db_path: Path, lookback_days: int) -> dict:
    """
    Returns {validator_name: {runs, pass, fail, block, warn, durations_ms:[...]}}.

    Expected events table schema (minimal):
      event_type (TEXT) — e.g. "validator.run"
      payload (TEXT) — JSON with {validator: str, verdict: PASS|FAIL|BLOCK|WARN, duration_ms: int}
      timestamp (TEXT) — ISO
    """
    stats: dict[str, dict] = {}
    if not db_path.exists():
        return stats

    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        # Be permissive about actual column layout — try common schemas
        cur.execute("""
            SELECT event_type, payload, timestamp
            FROM events
            WHERE event_type LIKE 'validator.%'
              AND timestamp >= ?
        """, (cutoff,))
        rows = cur.fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return stats

    for event_type, payload_raw, _ts in rows:
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except json.JSONDecodeError:
            continue

        name = payload.get("validator") or payload.get("name")
        if not name:
            continue

        rec = stats.setdefault(name, {
            "runs": 0, "pass": 0, "fail": 0, "block": 0, "warn": 0,
            "durations_ms": [],
        })
        rec["runs"] += 1
        verdict = (payload.get("verdict") or "").upper()
        if verdict == "PASS":
            rec["pass"] += 1
        elif verdict == "FAIL":
            rec["fail"] += 1
        elif verdict == "BLOCK":
            rec["block"] += 1
        elif verdict == "WARN":
            rec["warn"] += 1

        duration = payload.get("duration_ms")
        if isinstance(duration, (int, float)):
            rec["durations_ms"].append(duration)

    return stats


def _p95(values: list[float]) -> float:
    if not values:
        return 0
    sorted_v = sorted(values)
    idx = max(0, int(len(sorted_v) * 0.95) - 1)
    return sorted_v[idx]


def _discover_validator_files(validators_dir: Path) -> list[dict]:
    """Walk scripts/validators/ for *.py files. Return list of {id, path}."""
    if not validators_dir.exists():
        return []
    out = []
    for p in sorted(validators_dir.glob("*.py")):
        stem = p.stem
        if stem.startswith("_") or stem == "registry":
            continue
        rid = stem
        for prefix in ("verify-", "validate-", "evaluate-"):
            if rid.startswith(prefix):
                rid = rid[len(prefix):]
                break
        out.append({"id": rid, "path": str(p)})
    return out


def _detect_registry_coverage(registry: list[dict],
                              validators_dir: Path) -> list[dict]:
    """v2.5.2.1: flag validators on disk but missing from registry.

    This closes CrossAI round 3 finding: registry cataloged only 24 of 60+
    validators, so drift detection was blind to ~36 uncataloged scripts.
    """
    cataloged = {e.get("id") for e in registry if e.get("id")}
    on_disk = _discover_validator_files(validators_dir)
    findings = []
    for v in on_disk:
        if v["id"] not in cataloged:
            findings.append({
                "validator": v["id"],
                "pattern": "missing_from_registry",
                "severity": "warn",
                "detail": f"file {v['path']!r} exists but no registry entry. "
                          f"Run .claude/scripts/backfill-registry.py --apply.",
            })
    return findings


def _detect_drift(registry: list[dict], stats: dict, min_runs: int,
                  fp_threshold: float) -> list[dict]:
    findings = []

    for entry in registry:
        rid = entry.get("id")
        if not rid:
            continue
        if entry.get("disabled"):
            continue

        target_ms = entry.get("runtime_target_ms") or 0

        # Registry IDs may need normalized lookup — events record filename stem
        rec = stats.get(rid) or stats.get(f"verify-{rid}") or \
              stats.get(f"validate-{rid}") or {}
        runs = rec.get("runs", 0)

        if runs == 0:
            findings.append({
                "validator": rid,
                "pattern": "never_fires",
                "severity": "info",
                "detail": f"0 runs in lookback window (registry says active)",
            })
            continue

        if runs < min_runs:
            continue  # insufficient sample

        pass_rate = rec["pass"] / runs
        block_rate = rec["block"] / runs
        fail_rate = rec["fail"] / runs

        if pass_rate >= 1.0:
            findings.append({
                "validator": rid,
                "pattern": "always_pass",
                "severity": "warn",
                "detail": f"{runs} runs, 100% pass — likely too permissive",
            })

        if (block_rate + fail_rate) >= fp_threshold:
            findings.append({
                "validator": rid,
                "pattern": "high_block_rate",
                "severity": "warn",
                "detail": f"{runs} runs, {round((block_rate+fail_rate)*100, 1)}% block/fail "
                          f">= threshold {fp_threshold*100:.0f}%",
            })

        if target_ms:
            p95 = _p95(rec["durations_ms"])
            if p95 > target_ms * 2:
                findings.append({
                    "validator": rid,
                    "pattern": "perf_regression",
                    "severity": "warn",
                    "detail": f"p95 {round(p95)}ms > 2x target {target_ms}ms",
                })

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db-path", default=str(DEFAULT_DB))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--lookback-days", type=int, default=30)
    ap.add_argument("--min-runs", type=int, default=10,
                    help="Minimum runs to assess (below = skip)")
    ap.add_argument("--fp-threshold", type=float, default=0.8,
                    help="block/fail rate above = high-FP pattern (default 0.8)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    registry_path = Path(args.registry)
    db_path = Path(args.db_path)

    registry = _load_registry(registry_path)
    if not registry:
        print(f"\033[38;5;208mregistry empty or unreadable: {registry_path}\033[0m",
              file=sys.stderr)
        return 2

    stats = _query_validator_stats(db_path, args.lookback_days)

    # v2.5.2.1: check registry coverage first (missing-from-registry findings)
    # Then behavioral drift on cataloged entries.
    validators_dir = registry_path.parent
    findings = _detect_registry_coverage(registry, validators_dir)
    findings += _detect_drift(
        registry, stats, args.min_runs, args.fp_threshold,
    )

    report = {
        "validator": "verify-validator-drift",
        # v2.6 (2026-04-25): WARN (advisory) — drift findings tell ops
        # which validators to demote/disable/optimize but don't hard-block.
        "verdict": "PASS" if not findings else "WARN",
        "db_path": str(db_path),
        "registry": str(registry_path),
        "lookback_days": args.lookback_days,
        "validators_tracked": len(registry),
        "validators_with_events": len(stats),
        "findings": findings,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if findings:
            print(f"\033[33mValidator drift: {len(findings)} finding(s)\033[0m\n")
            for f in findings:
                print(f"  [{f['pattern']}] {f['validator']}: {f['detail']}")
        elif not args.quiet:
            print(f"✓ No validator drift — {len(registry)} tracked, "
                  f"{len(stats)} with events in {args.lookback_days}d window")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
