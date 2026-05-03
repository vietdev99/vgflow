#!/usr/bin/env python3
"""verify-lens-runs-coverage.py — generalized lens coverage gate (Task 26).

For every applicability_status=APPLICABLE dispatch in LENS-DISPATCH-PLAN.json:
  1. Artifact exists at expected_artifact_path (BLOCK day 1)
  2. Artifact's plan_hash matches dispatch's plan_hash (BLOCK — anti-reuse)
  3. Artifact's lens matches dispatch's lens (BLOCK — anti-wrong-artifact)
  4. Artifact's goal_id matches (BLOCK)
  5. Artifact's steps[] non-empty (BLOCK)
  6. Artifact's steps with non-empty evidence_ref >= min_evidence_steps (BLOCK)
  7. Artifact's actions_taken >= min_actions_floor (ADVISORY for first 2 weeks)
  8. Artifact's required_probe_kinds all covered by steps[].name (ADVISORY)

Routes failures via classifier (Task 7) → STEP 5.5 fix-loop (Task 10).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_artifact(runs_dir: Path, expected_path: str) -> dict | None:
    p = runs_dir.parent / expected_path  # expected_path is "runs/<lens>/<goal>.json"
    if not p.exists():
        # Try resolving relative to runs_dir directly
        alt = runs_dir / Path(expected_path).name
        p = alt if alt.exists() else p
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _check_dispatch(dispatch: dict, plan_hash: str, runs_dir: Path) -> dict:
    """Return {dispatch_id, status, severity, issues}."""
    expected_path = dispatch.get("expected_artifact_path", "")
    if not expected_path:
        return {"dispatch_id": dispatch["dispatch_id"], "status": "MISSING",
                "severity": "BLOCK", "issues": ["expected_artifact_path empty"]}

    artifact = _load_artifact(runs_dir, expected_path)
    if artifact is None:
        return {"dispatch_id": dispatch["dispatch_id"], "status": "MISSING",
                "severity": "BLOCK", "issues": [f"artifact missing at {expected_path}"]}

    issues: list[str] = []
    severity = "PASS"
    if artifact.get("plan_hash") != plan_hash:
        issues.append(f"plan_hash mismatch (artifact={artifact.get('plan_hash')!r}, "
                      f"plan={plan_hash!r}) — possible reuse from prior run")
        severity = "BLOCK"
    if artifact.get("lens") != dispatch["lens"]:
        issues.append(f"lens mismatch (artifact={artifact.get('lens')!r}, "
                      f"dispatch={dispatch['lens']!r})")
        severity = "BLOCK"
    if artifact.get("goal_id") != dispatch["goal_id"]:
        issues.append(f"goal_id mismatch (artifact={artifact.get('goal_id')!r}, "
                      f"dispatch={dispatch['goal_id']!r})")
        severity = "BLOCK"

    steps = artifact.get("steps", [])
    if not steps:
        issues.append("steps[] empty")
        severity = "BLOCK"

    min_evidence = dispatch.get("min_evidence_steps", 1)
    evidence_steps = sum(1 for s in steps if s.get("evidence_ref"))
    if evidence_steps < min_evidence:
        issues.append(f"evidence_ref count {evidence_steps} < min {min_evidence}")
        severity = "BLOCK"

    min_actions = dispatch.get("min_actions_floor", 1)
    actions_taken = artifact.get("actions_taken", 0)
    if actions_taken < min_actions:
        issues.append(f"actions_taken {actions_taken} < floor {min_actions} (ADVISORY phase-in)")
        if severity == "PASS":
            severity = "ADVISORY"

    required_probes = set(dispatch.get("required_probe_kinds", []))
    if required_probes:
        observed_names = {s.get("name", "") for s in steps}
        missing_probes = required_probes - observed_names
        if missing_probes:
            issues.append(f"required_probe_kinds missing: {sorted(missing_probes)} (ADVISORY)")
            if severity == "PASS":
                severity = "ADVISORY"

    return {"dispatch_id": dispatch["dispatch_id"],
            "status": "FAIL" if severity == "BLOCK" else ("ADVISORY" if severity == "ADVISORY" else "PASS"),
            "severity": severity, "issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch-plan", required=True)
    parser.add_argument("--runs-dir", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    plan_path = Path(args.dispatch_plan)
    if not plan_path.exists():
        print(f"ERROR: dispatch plan missing: {plan_path}", file=sys.stderr)
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_hash = plan["plan_hash"]
    runs_dir = Path(args.runs_dir)

    results: list[dict] = []
    block_count = advisory_count = pass_count = skipped_count = 0
    for dispatch in plan["dispatches"]:
        if dispatch["applicability_status"] != "APPLICABLE":
            skipped_count += 1
            continue
        r = _check_dispatch(dispatch, plan_hash, runs_dir)
        results.append(r)
        if r["severity"] == "BLOCK":
            block_count += 1
        elif r["severity"] == "ADVISORY":
            advisory_count += 1
        else:
            pass_count += 1

    summary = {
        "phase": args.phase,
        "plan_hash": plan_hash,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": {"pass": pass_count, "advisory": advisory_count,
                   "block": block_count, "skipped": skipped_count},
        "results": results,
    }
    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if block_count > 0:
        print(f"⛔ Lens coverage gate: {block_count} BLOCK(s), {advisory_count} ADVISORY, "
              f"{pass_count} PASS, {skipped_count} skipped", file=sys.stderr)
        for r in results:
            if r["severity"] == "BLOCK":
                print(f"   - {r['dispatch_id']}: {'; '.join(r['issues'])}", file=sys.stderr)
        return 1

    print(f"✓ Lens coverage: {pass_count} PASS, {advisory_count} ADVISORY, "
          f"{skipped_count} skipped (plan_hash={plan_hash[:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
