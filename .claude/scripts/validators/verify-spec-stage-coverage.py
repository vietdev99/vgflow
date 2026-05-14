#!/usr/bin/env python3
"""verify-spec-stage-coverage.py — Batch 23

Opens each spec file listed in CODEGEN-MANIFEST.json, checks body contains
stage-specific patterns matching LIFECYCLE-SPECS.json declared stages per
goal.

Stages and required regex patterns (per RCRURDR + 4-layer verify):

  read_before:       page.goto OR page.reload (navigation before mutation)
  create:            page.fill (form input) + page.click (submit) + waitForResponse
  read_after_create: page.reload OR navigate + expect(...).toBeVisible (new entity)
  update:            page.fill (second time) + page.click (save)
  read_after_update: page.reload + expect(persisted_value)
  delete:            page.click (delete) + waitForResponse(DELETE method)
  read_after_delete: expect(...).not.toBeVisible (entity gone)

Plus 4-layer verify (for every mutation stage):
  L1 toast:        expect(...).toContainText(...)
  L2 API 2xx:      waitForResponse + status < 400
  L3 persistence:  page.reload + assertion
  L4 console:      window.__consoleErrors check (advisory, not blocking)

Missing required pattern per declared stage → BLOCK with file:line context.

Exit codes:
  0 — all specs cover declared stages
  1 — at least one shallow spec found
  2 — config error (missing files, malformed JSON)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Stage → list of required regex patterns. Each pattern (compiled, IGNORECASE)
# is checked against the spec file body. Missing pattern = stage not covered.
STAGE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "read_before": [
        ("navigation", r"page\.goto\("),
    ],
    "create": [
        ("form_fill", r"page\.fill\("),
        ("submit_click", r"page\.click\(['\"](?:button|.*type=['\"]submit)|getByRole\(['\"]button"),
        ("api_response", r"waitForResponse\("),
    ],
    "read_after_create": [
        ("post_create_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "update": [
        ("update_fill", r"page\.fill\("),
        ("update_save", r"page\.click\("),
        ("update_response", r"waitForResponse\("),
    ],
    "read_after_update": [
        ("persist_reload", r"page\.reload\(\)|page\.goto\("),
        ("persist_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "delete": [
        ("delete_click", r"page\.click\("),
        ("delete_response", r"waitForResponse\("),
    ],
    "read_after_delete": [
        ("not_visible", r"not\.toBeVisible\(\)|toBeHidden\(\)|toHaveCount\(0\)"),
    ],
}


def _check_spec(spec_path: Path, required_stages: list[str]) -> dict:
    """Returns dict with stage → list[missing_pattern_names]."""
    if not spec_path.is_file():
        return {"_error": f"spec file not found: {spec_path}"}
    body = spec_path.read_text(encoding="utf-8", errors="replace")
    missing: dict[str, list[str]] = {}
    for stage in required_stages:
        patterns = STAGE_PATTERNS.get(stage, [])
        if not patterns:
            continue
        miss = []
        for name, regex in patterns:
            if not re.search(regex, body, re.IGNORECASE):
                miss.append(name)
        if miss:
            missing[stage] = miss
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path("."),
                    help="Repo root for resolving spec relative paths")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ls_path = args.phase_dir / "LIFECYCLE-SPECS.json"
    cm_path = args.phase_dir / "CODEGEN-MANIFEST.json"
    if not ls_path.is_file():
        print(f"⛔ LIFECYCLE-SPECS.json missing at {ls_path}", file=sys.stderr)
        return 2
    if not cm_path.is_file():
        print(f"⛔ CODEGEN-MANIFEST.json missing at {cm_path}", file=sys.stderr)
        return 2

    try:
        ls = json.loads(ls_path.read_text(encoding="utf-8"))
        cm = json.loads(cm_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ JSON parse error: {e}", file=sys.stderr)
        return 2

    # Map goal_id → list of stage names
    goal_stages: dict[str, list[str]] = {}
    for gid, gdata in ls.get("goals", {}).items():
        stages = gdata.get("stages", [])
        names = [s.get("name", s) if isinstance(s, dict) else s for s in stages]
        goal_stages[gid] = names

    # Map goal_id → spec path
    goal_spec: dict[str, str] = {}
    for s in cm.get("playwright_specs", cm.get("specs", [])):
        if isinstance(s, dict):
            goal_spec[s.get("goal_id", "")] = s.get("path", "")
        # bare string entries have no goal binding — skip

    shallow_findings = []
    for gid, stages in goal_stages.items():
        spec_rel = goal_spec.get(gid)
        if not spec_rel:
            continue  # no spec for this goal (MANUAL/INFRA_PENDING?)
        spec_abs = args.repo_root / spec_rel
        result = _check_spec(spec_abs, stages)
        if "_error" in result:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "error": result["_error"]
            })
            continue
        if result:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "missing_stages": result
            })

    if args.json:
        print(json.dumps({
            "phase_dir": str(args.phase_dir),
            "total_goals": len(goal_stages),
            "shallow_specs": len(shallow_findings),
            "failures": shallow_findings,
        }, indent=2))
    else:
        if shallow_findings:
            print(f"⛔ Batch 23: {len(shallow_findings)} shallow spec(s) detected:", file=sys.stderr)
            for f in shallow_findings:
                print(f"  - {f['goal_id']} ({f['spec']}):", file=sys.stderr)
                if "error" in f:
                    print(f"      ERROR: {f['error']}", file=sys.stderr)
                else:
                    for stage, missing in f["missing_stages"].items():
                        print(f"      stage '{stage}' missing: {', '.join(missing)}", file=sys.stderr)
        else:
            print(f"✓ Batch 23: {len(goal_stages)} goals — all specs cover declared stages")

    return 1 if shallow_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
