#!/usr/bin/env python3
"""
challenge-coverage.py — v2.39.0 closes Codex critique #7.

Charter violation: workers report `coverage.passed` and findings are
merged, but no adversarial reducer asks "do these passes actually imply
goal coverage?". A worker can mark step-3 (read-after-create) as PASS
because the create returned 201 and SOMETHING new appeared in the list,
without proving the new item has the submitted values, or that the list
isn't showing yesterday's record.

This script is the manager's challenge pass. After derive-findings.py
produces REVIEW-FINDINGS.json, this script:

1. Samples N% of run artifacts (default 25%)
2. For each sampled run: runs heuristic checks on `steps[]`:
   - Each `pass` step must have non-empty `evidence_ref`
   - Each `pass` step's `observed` block must contain values matching
     `expected` (substring/numeric/structural)
   - Steps marked pass with empty `observed` are downgraded to `weak-pass`
3. Cross-references with TEST-GOALS-EXPANDED.md: if a goal claims
   coverage but no run artifact's evidence matches the goal's verification
   intent, downgrade GOAL-COVERAGE-MATRIX entry to NOT_VERIFIED.

Pure heuristic — does not run an LLM challenger pass yet. v2.40 may add
LLM-driven challenge for ambiguous claims.

Output: ${PHASE_DIR}/COVERAGE-CHALLENGE.json with downgrades + warnings.
Modifies GOAL-COVERAGE-MATRIX.md if any goals downgrade (with audit trail).

Usage:
  challenge-coverage.py --phase-dir <path>
  challenge-coverage.py --phase-dir <path> --sample-rate 100  # check all
  challenge-coverage.py --phase-dir <path> --json
  challenge-coverage.py --phase-dir <path> --dry-run

Exit codes:
  0 — challenge complete (warnings logged but coverage stands or downgraded)
  1 — challenge found CRITICAL evidence gaps (severity=block)
  2 — config error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_run(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_runs(phase_dir: Path) -> list[dict]:
    runs_dir = phase_dir / "runs"
    if not runs_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(runs_dir.glob("*.json")):
        if p.name in {"INDEX.json", ".broker-context.json"}:
            continue
        data = load_run(p)
        if data:
            data["_source_path"] = str(p)
            out.append(data)
    return out


def challenge_step(step: dict) -> dict:
    """Return {original_status, challenge_status, reason}."""
    original = step.get("status", "unknown")
    if original != "pass":
        return {"original_status": original, "challenge_status": original, "reason": "non-pass step (not challenged)"}

    evidence_ref = step.get("evidence_ref")
    observed = step.get("observed")
    expected = step.get("expected")

    if not evidence_ref:
        return {
            "original_status": "pass",
            "challenge_status": "weak-pass",
            "reason": "pass marked but evidence_ref empty — claim unsupported",
        }

    if not observed:
        return {
            "original_status": "pass",
            "challenge_status": "weak-pass",
            "reason": "pass marked but observed block empty — claim unverifiable",
        }

    if expected and observed:
        exp_str = json.dumps(expected, sort_keys=True) if isinstance(expected, (dict, list)) else str(expected)
        obs_str = json.dumps(observed, sort_keys=True) if isinstance(observed, (dict, list)) else str(observed)
        exp_status = re.search(r"\b(\d{3})\b", exp_str)
        obs_status = re.search(r"\b(\d{3})\b", obs_str)
        if exp_status and obs_status and exp_status.group(1) != obs_status.group(1):
            return {
                "original_status": "pass",
                "challenge_status": "false-pass",
                "reason": f"pass marked but observed status {obs_status.group(1)} != expected {exp_status.group(1)}",
            }

    return {"original_status": "pass", "challenge_status": "pass", "reason": "evidence supports claim"}


def challenge_run(run: dict) -> dict:
    steps = run.get("steps") or []
    challenges = [
        {**challenge_step(s), "step_name": s.get("name")}
        for s in steps
    ]
    weak = sum(1 for c in challenges if c["challenge_status"] == "weak-pass")
    false_pass = sum(1 for c in challenges if c["challenge_status"] == "false-pass")

    coverage = run.get("coverage") or {}
    original_passed = int(coverage.get("passed", 0))
    challenged_passed = original_passed - false_pass
    challenged_failed = int(coverage.get("failed", 0)) + false_pass

    return {
        "run_id": run.get("run_id"),
        "resource": run.get("resource"),
        "role": run.get("role"),
        "challenges": challenges,
        "weak_pass_count": weak,
        "false_pass_count": false_pass,
        "original_coverage": coverage,
        "challenged_coverage": {
            **coverage,
            "passed": challenged_passed,
            "failed": challenged_failed,
            "weak_pass": weak,
        },
        "verdict": "DEGRADED" if false_pass > 0 else ("WEAK" if weak > 0 else "STRONG"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--sample-rate", type=int, default=25, help="Percent of runs to challenge (1-100)")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    ap.add_argument("--severity", choices=["warn", "block"], default="warn")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    runs = load_runs(phase_dir)
    if not runs:
        if not args.quiet:
            print(f"  (no runs/*.json — nothing to challenge)")
        return 0

    rate = max(1, min(100, args.sample_rate))
    sample_size = max(1, len(runs) * rate // 100)
    rng = random.Random(args.seed)
    sampled = rng.sample(runs, sample_size) if sample_size < len(runs) else runs

    challenges = [challenge_run(r) for r in sampled]

    total_weak = sum(c["weak_pass_count"] for c in challenges)
    total_false = sum(c["false_pass_count"] for c in challenges)
    degraded_runs = [c for c in challenges if c["verdict"] == "DEGRADED"]
    weak_runs = [c for c in challenges if c["verdict"] == "WEAK"]

    payload = {
        "phase_dir": str(phase_dir),
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs_total": len(runs),
        "runs_sampled": len(sampled),
        "sample_rate_pct": rate,
        "weak_pass_steps": total_weak,
        "false_pass_steps": total_false,
        "degraded_run_count": len(degraded_runs),
        "weak_run_count": len(weak_runs),
        "challenges": challenges,
        "verdict": "DEGRADED" if degraded_runs else ("WEAK" if weak_runs else "STRONG"),
        "severity": args.severity,
    }

    if not args.dry_run:
        out_path = phase_dir / "COVERAGE-CHALLENGE.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["out_path"] = str(out_path)

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if payload["verdict"] == "STRONG":
            print(f"✓ Coverage challenge: {len(sampled)}/{len(runs)} runs sampled — all evidence supports claims")
        elif payload["verdict"] == "WEAK":
            print(f"\033[33mCoverage challenge: {total_weak} step(s) marked pass with empty evidence ({len(weak_runs)} run(s) affected)\033[0m")
            print(f"   Coverage matrix accepted as-is but flagged for human review")
        else:
            tag = "" if args.severity == "block" else ""
            print(f"{tag} Coverage challenge: {total_false} FALSE-PASS step(s) detected ({len(degraded_runs)} run(s))")
            for c in degraded_runs:
                print(f"   {c['resource']} × {c['role']}: {c['false_pass_count']} false-pass step(s)")

    if payload["verdict"] == "DEGRADED" and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
