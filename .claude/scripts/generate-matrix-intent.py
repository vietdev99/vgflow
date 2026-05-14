#!/usr/bin/env python3
"""generate-matrix-intent.py — F7 Batch 22

Reads GOAL-COVERAGE-MATRIX.json + RUNTIME-MAP.json (optional).
Computes per-goal verdict (READY_BEHAVIORAL / READY_STRUCTURAL / BLOCKED /
NOT_SCANNED). Writes MATRIX-INTENT.json.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _compute_verdict(goal: dict) -> tuple[str, str]:
    """Returns (verdict, reason)."""
    endpoint = goal.get("endpoint_observed", False)
    selectors = goal.get("selectors_resolved", False)
    assertions = goal.get("assertion_evidence_persisted", False)
    if endpoint and selectors:
        if assertions:
            return ("READY_BEHAVIORAL", "endpoint+selectors+assertion evidence persisted")
        return ("READY_STRUCTURAL", "endpoint+selectors OK; replay required")
    if not endpoint:
        return ("BLOCKED", "endpoint missing in RUNTIME-MAP")
    if not selectors:
        return ("BLOCKED", "selectors unresolved")
    return ("NOT_SCANNED", "goal not exercised during discovery")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--phase-number", default="")
    args = ap.parse_args()

    gcm_path = args.phase_dir / "GOAL-COVERAGE-MATRIX.json"
    if not gcm_path.is_file():
        print(f"⛔ GOAL-COVERAGE-MATRIX.json missing at {gcm_path}", file=sys.stderr)
        return 1
    try:
        gcm = json.loads(gcm_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ GOAL-COVERAGE-MATRIX.json parse error: {e}", file=sys.stderr)
        return 1

    out_goals = []
    for g in gcm.get("goals", []):
        verdict, reason = _compute_verdict(g)
        out_goals.append({
            "goal_id": g.get("goal_id", ""),
            "verdict": verdict,
            "reason": reason,
        })

    result = {
        "phase": args.phase_number,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "goals": out_goals,
        "summary": {
            "READY_BEHAVIORAL": sum(1 for g in out_goals if g["verdict"] == "READY_BEHAVIORAL"),
            "READY_STRUCTURAL": sum(1 for g in out_goals if g["verdict"] == "READY_STRUCTURAL"),
            "BLOCKED": sum(1 for g in out_goals if g["verdict"] == "BLOCKED"),
            "NOT_SCANNED": sum(1 for g in out_goals if g["verdict"] == "NOT_SCANNED"),
        }
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"✓ MATRIX-INTENT.json written: {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
