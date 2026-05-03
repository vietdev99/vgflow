#!/usr/bin/env python3
"""emit-dispatch-plan.py — emit LENS-DISPATCH-PLAN.json before any worker spawns.

Inputs:
  - phase TEST-GOALS/G-*.md (goal IDs + metadata)
  - lens-prompts/lens-*.md (frontmatter — applies_to_*, complexity, tier)
  - vg.config.md (review.lens_overrides for project-specific skips)

Output:
  - ${PHASE_DIR}/LENS-DISPATCH-PLAN.json (canonical manifest, schema-validated)

Trust anchor (Codex round 5):
  Every (lens × goal) intent must be declared here BEFORE spawn. Coverage gate
  later asserts every APPLICABLE dispatch has matching artifact. plan_hash
  pinned in each artifact prevents reuse from prior runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LENS_DIR = REPO / "commands" / "vg" / "_shared" / "lens-prompts"


def _read_lens_frontmatter(lens_path: Path) -> dict:
    text = lens_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _read_goal_metadata(goal_path: Path) -> dict:
    text = goal_path.read_text(encoding="utf-8")
    out: dict = {"goal_id": goal_path.stem}
    m = re.search(r"\*\*goal_type:\*\*\s*(\S+)", text)
    out["goal_type"] = m.group(1).strip() if m else "unknown"
    m = re.search(r"\*\*element_class:\*\*\s*(\S+)", text)
    out["element_class"] = m.group(1).strip() if m else None
    m = re.search(r"\*\*resource:\*\*\s*(\S+)", text)
    out["resource"] = m.group(1).strip() if m else None
    m = re.search(r"\*\*view:\*\*\s*(\S+)", text)
    out["view"] = m.group(1).strip() if m else None
    return out


def _classify_applicability(lens_fm: dict, goal: dict, profile: str) -> tuple[str, str]:
    """Return (status, reason). Status ∈ APPLICABLE, N/A, SKIPPED_BY_POLICY, SKIPPED_BY_OVERRIDE."""
    profiles = lens_fm.get("applies_to_phase_profiles", [])
    if profiles and profile not in profiles:
        return ("N/A", f"lens not applicable to phase profile {profile}")
    element_classes = lens_fm.get("applies_to_element_classes", [])
    if element_classes and goal.get("element_class"):
        if goal["element_class"] not in element_classes:
            return ("N/A", f"lens not applicable to element_class {goal['element_class']}")
    if lens_fm.get("bug_class") in {"state-coherence", "bizlogic"}:
        if goal.get("goal_type") == "read_only":
            return ("N/A", "mutation lens not applicable to read-only goal")
    return ("APPLICABLE", "matches frontmatter applies_to_* + goal type")


def _git_commit_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:40] if r.returncode == 0 else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def _canonical_hash(dispatches: list[dict]) -> str:
    """sha256 of canonical JSON of dispatches sorted by dispatch_id."""
    sorted_d = sorted(dispatches, key=lambda d: d["dispatch_id"])
    blob = json.dumps(sorted_d, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--profile", default="web-fullstack")
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--policy-overrides", help="JSON file of lens-overrides (skip reasons)")
    parser.add_argument("--lens-dir", default=str(LENS_DIR),
                        help="Override lens prompts directory (default: project lens-prompts dir)")
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    goals_dir = phase_dir / "TEST-GOALS"
    if not goals_dir.exists():
        print(f"ERROR: TEST-GOALS missing at {goals_dir}", file=sys.stderr)
        return 1

    overrides = {}
    if args.policy_overrides and Path(args.policy_overrides).exists():
        overrides = json.loads(Path(args.policy_overrides).read_text(encoding="utf-8"))

    lens_dir = Path(args.lens_dir)
    dispatches: list[dict] = []
    for lens_path in sorted(lens_dir.glob("lens-*.md")):
        lens_fm = _read_lens_frontmatter(lens_path)
        lens_name = lens_fm.get("name", lens_path.stem)
        for goal_path in sorted(goals_dir.glob("G-*.md")):
            goal = _read_goal_metadata(goal_path)
            status, reason = _classify_applicability(lens_fm, goal, args.profile)

            override_key = f"{lens_name}/{goal['goal_id']}"
            if override_key in overrides:
                status = "SKIPPED_BY_POLICY"
                reason = overrides[override_key].get("reason", "policy skip")

            dispatch_id = f"{lens_name}__{goal['goal_id']}"
            expected_path = (f"runs/{lens_name}/{goal['goal_id']}.json"
                             if status == "APPLICABLE" else "")
            est_budget = lens_fm.get("estimated_action_budget", 30) or 30
            dispatches.append({
                "dispatch_id": dispatch_id,
                "lens": lens_name,
                "goal_id": goal["goal_id"],
                "view": goal.get("view"),
                "element_class": goal.get("element_class"),
                "resource": goal.get("resource"),
                "role": None,
                "applicability_status": status,
                "applicability_reason": reason,
                "expected_artifact_path": expected_path,
                "worker_tier": lens_fm.get("recommended_worker_tier", "haiku"),
                "worker_tool": "claude",
                "min_actions_floor": lens_fm.get("min_actions_floor", max(5, int(est_budget * 0.4))),
                "min_evidence_steps": lens_fm.get("min_evidence_steps", 3),
                "required_probe_kinds": lens_fm.get("required_probe_kinds", []),
            })

    plan = {
        "review_run_id": args.review_run_id,
        "phase": args.phase,
        "commit_sha": _git_commit_sha(),
        "emitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dispatches": dispatches,
        "plan_hash": _canonical_hash(dispatches),
    }

    Path(args.output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    n_app = sum(1 for d in dispatches if d['applicability_status'] == 'APPLICABLE')
    print(f"✓ LENS-DISPATCH-PLAN.json written: {len(dispatches)} dispatches "
          f"({n_app} APPLICABLE), plan_hash={plan['plan_hash'][:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
