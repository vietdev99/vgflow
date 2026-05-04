#!/usr/bin/env python3
"""
verify-crud-runs-coverage.py — v2.35.0 closes #51 invariant 3, R8-B 2026-05-05.

Hard invariant covering BOTH the kit-declared path and the universal
mutation-goal path (R8-B):

  Path A (kit-declared, original 2.35.0 invariant):
    For every (resource × role) declared in CRUD-SURFACES.md where
    `kit: crud-roundtrip`, a corresponding run artifact must exist at
    `runs/{resource}-{role}.json` with `coverage.attempted >= 1` and every
    non-skipped step has `evidence_ref` populated. Catches AI gaming the
    verdict gate by writing empty run artifacts.

  Path B (universal mutation-goal coverage, R8-B 2026-05-05):
    For every TEST-GOALS/G-NN.md that qualifies under either:
      (1) `goal_class: crud-roundtrip` (frontmatter / bullet form), OR
      (2) inline ```yaml-rcrurd``` fence containing `lifecycle: rcrurdr`,
    at least one run artifact in `runs/` must reference that goal. Closes
    the closed-loop review-layer gap where mutation goals could slip
    through without lifecycle proof when the phase did not author a
    CRUD-SURFACES.md or did not tag resources with kit: crud-roundtrip.

Discrepancy with R8-B audit suggestion: the audit hinted at per-goal
artifacts under `${PHASE_DIR}/.runs/<goal>.crud-roundtrip.json`. The
existing convention is `${PHASE_DIR}/runs/<resource>-<role>.json` (no dot
prefix, no per-goal split — workers are fanned out per resource×role
pair, not per goal). To keep the gate honest without a workflow rewrite,
Path B accepts ANY of these run shapes for the qualifying goal:
  - `runs/<goal_id>.json` (per-goal artifact, future-proof)
  - any `runs/*.json` whose body mentions the goal_id literally
  - any `runs/*.json` whose `goals[]` / `goal_ids[]` field contains it
WARN if a qualifying goal has NO match.

Usage:
  verify-crud-runs-coverage.py --phase-dir <path>
  verify-crud-runs-coverage.py --phase-dir <path> --severity warn

Exit codes:
  0 — all expected runs present + populated (or severity=warn)
  1 — gap found (severity=block)
  2 — config error (phase dir missing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ─── Helpers ──────────────────────────────────────────────────────────


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_crud_surfaces(phase_dir: Path) -> dict:
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


# R8-B regexes — match goal_class declared as either YAML frontmatter
# (`goal_class: crud-roundtrip`) or markdown bullet form
# (`**goal_class:** crud-roundtrip`, `- goal_class: crud-roundtrip`).
_GOAL_CLASS_RE = re.compile(
    r"^\s*(?:[*_-]+\s*)?goal_class\s*[:*_]*\s*:?\s*[*_]*\s*crud-roundtrip\b",
    re.MULTILINE | re.IGNORECASE,
)
# Permissive variant (catches `**goal_class:** crud-roundtrip`).
_GOAL_CLASS_BULLET_RE = re.compile(
    r"\bgoal_class\s*[:*]+\s*\**\s*crud-roundtrip\b",
    re.IGNORECASE,
)
_YAML_RCRURD_FENCE_RE = re.compile(
    r"```yaml-rcrurd\s*\n(.+?)\n```",
    re.DOTALL,
)
_LIFECYCLE_RCRURDR_RE = re.compile(
    r"^\s*lifecycle\s*:\s*rcrurdr\s*$",
    re.MULTILINE,
)


def _qualifies_universal(goal_text: str) -> tuple[bool, list[str]]:
    """R8-B: does this TEST-GOAL qualify for universal CRUD round-trip?

    Returns (qualifies, reasons) where reasons names the matching
    condition(s) for evidence in error output.
    """
    reasons: list[str] = []
    if _GOAL_CLASS_RE.search(goal_text) or _GOAL_CLASS_BULLET_RE.search(goal_text):
        reasons.append("goal_class:crud-roundtrip")
    fence = _YAML_RCRURD_FENCE_RE.search(goal_text)
    if fence and _LIFECYCLE_RCRURDR_RE.search(fence.group(1)):
        reasons.append("lifecycle:rcrurdr")
    return (bool(reasons), reasons)


def _discover_universal_goals(phase_dir: Path) -> list[tuple[str, list[str], Path]]:
    """Walk TEST-GOALS/ and return [(goal_id, reasons, path), ...] for qualifying goals."""
    goals_dir = phase_dir / "TEST-GOALS"
    if not goals_dir.is_dir():
        return []
    out: list[tuple[str, list[str], Path]] = []
    for p in sorted(goals_dir.glob("G-*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ok, reasons = _qualifies_universal(text)
        if ok:
            out.append((p.stem, reasons, p))
    return out


def _run_artifacts_for_goal(runs_dir: Path, goal_id: str) -> list[Path]:
    """Return run artifact paths covering a goal_id under multiple shapes:
       - runs/<goal_id>.json (per-goal, future-proof)
       - any runs/*.json (excluding INDEX.json) whose body mentions
         the goal_id literally OR has it in goals[]/goal_ids[].
    """
    if not runs_dir.is_dir():
        return []
    matches: list[Path] = []
    direct = runs_dir / f"{goal_id}.json"
    if direct.is_file():
        matches.append(direct)
    for run_path in sorted(runs_dir.glob("*.json")):
        if run_path.name == "INDEX.json":
            continue
        if run_path == direct:
            continue
        try:
            body = run_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Cheap text contains first; if hit, optionally double-check JSON
        # structure (goals[]/goal_ids[]) but text-contains is enough for
        # the back-stop gate.
        if goal_id in body:
            matches.append(run_path)
            continue
        try:
            obj = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        listy_fields = []
        for key in ("goals", "goal_ids", "covered_goals"):
            v = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(v, list):
                listy_fields.extend(str(x) for x in v)
        if goal_id in listy_fields:
            matches.append(run_path)
    return matches


# ─── Path A: kit-declared invariant (existing 2.35.0 logic) ───────────


def _check_kit_declared(phase_dir: Path, surfaces: dict) -> list[dict]:
    gaps: list[dict] = []
    resources = surfaces.get("resources") or []
    expected: list[tuple[str, str]] = []
    for resource in resources:
        if resource.get("kit") != "crud-roundtrip":
            continue
        roles = (resource.get("base") or {}).get("roles") or []
        for role in roles:
            expected.append((resource.get("name"), role))

    if not expected:
        return []

    runs_dir = phase_dir / "runs"
    for resource_name, role in expected:
        run_path = runs_dir / f"{resource_name}-{role}.json"
        if not run_path.is_file():
            gaps.append({
                "path_kind": "kit_declared",
                "resource": resource_name,
                "role": role,
                "reason": "run_artifact_missing",
                "expected_path": str(run_path),
            })
            continue

        run = load_json(run_path)
        coverage = run.get("coverage") or {}
        if int(coverage.get("attempted", 0)) < 1:
            gaps.append({
                "path_kind": "kit_declared",
                "resource": resource_name,
                "role": role,
                "reason": "coverage_attempted_zero",
                "path": str(run_path),
            })
            continue

        steps = run.get("steps") or []
        for idx, step in enumerate(steps):
            if step.get("status") == "skipped":
                continue
            if not step.get("evidence_ref"):
                gaps.append({
                    "path_kind": "kit_declared",
                    "resource": resource_name,
                    "role": role,
                    "reason": "step_missing_evidence_ref",
                    "step_index": idx,
                    "step_name": step.get("name"),
                    "path": str(run_path),
                })
                break

    return gaps


# ─── Path B: universal mutation-goal coverage (R8-B) ──────────────────


def _check_universal(phase_dir: Path) -> tuple[list[dict], int]:
    """Return (gaps, qualifying_count).

    A qualifying mutation goal MUST have at least one run artifact
    covering it, otherwise BLOCK with reason `universal_run_artifact_missing`.
    """
    universal = _discover_universal_goals(phase_dir)
    if not universal:
        return ([], 0)

    runs_dir = phase_dir / "runs"
    gaps: list[dict] = []
    for goal_id, reasons, goal_path in universal:
        artifacts = _run_artifacts_for_goal(runs_dir, goal_id)
        if not artifacts:
            gaps.append({
                "path_kind": "universal",
                "goal_id": goal_id,
                "qualifies_via": reasons,
                "reason": "universal_run_artifact_missing",
                "goal_file": str(goal_path),
                "expected_path": str(runs_dir / f"{goal_id}.json"),
                "fix_hint": (
                    "Mutation goal qualifies for CRUD round-trip (via "
                    f"{', '.join(reasons)}) but no run artifact in {runs_dir}/ "
                    "references it. Re-run /vg:review (Phase 2d will dispatch "
                    "the round-trip worker) or, for legacy phases, override "
                    "with --skip-crud-coverage-universal --override-reason=<text>."
                ),
            })
    return (gaps, len(universal))


# ─── Main ────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    # ── Path A: kit-declared (back-compat) ──
    surfaces = load_crud_surfaces(phase_dir)
    kit_gaps = _check_kit_declared(phase_dir, surfaces)
    kit_resources = surfaces.get("resources") or []
    kit_expected = sum(
        1 for r in kit_resources
        if r.get("kit") == "crud-roundtrip"
        for _ in (r.get("base") or {}).get("roles") or []
    )

    # ── Path B: universal R8-B ──
    universal_gaps, universal_count = _check_universal(phase_dir)

    gaps = kit_gaps + universal_gaps

    # If neither path produced any expected work, emit the original
    # "no resources declare kit: crud-roundtrip" PASS message.
    if kit_expected == 0 and universal_count == 0:
        if args.json:
            print(json.dumps({
                "phase_dir": str(phase_dir),
                "expected_runs": 0,
                "universal_qualifying": 0,
                "gaps": [],
                "gate_pass": True,
                "severity": args.severity,
            }, indent=2))
        elif not args.quiet:
            if not surfaces.get("resources"):
                print(f"  (no resources in CRUD-SURFACES.md, no universal qualifying goals — passing)")
            else:
                print(f"  (no resources declare kit: crud-roundtrip, no universal qualifying goals — passing)")
        return 0

    payload = {
        "phase_dir": str(phase_dir),
        "expected_runs": kit_expected,
        "universal_qualifying": universal_count,
        "gaps": gaps,
        "gate_pass": len(gaps) == 0,
        "severity": args.severity,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not gaps:
            print(
                f"✓ CRUD runs coverage OK "
                f"(kit-declared: {kit_expected} pair(s), "
                f"universal: {universal_count} qualifying goal(s))"
            )
        else:
            kit_count = sum(1 for g in gaps if g.get("path_kind") == "kit_declared")
            uni_count = sum(1 for g in gaps if g.get("path_kind") == "universal")
            print(
                f"✗ CRUD runs coverage: {len(gaps)} gap(s) "
                f"(kit-declared: {kit_count}, universal R8-B: {uni_count})"
            )
            for g in gaps:
                if g.get("path_kind") == "kit_declared":
                    print(f"   [kit] {g['resource']} × {g['role']}: {g['reason']}")
                else:
                    print(f"   [universal R8-B] {g['goal_id']} ({','.join(g.get('qualifies_via', []))}): {g['reason']}")

    if gaps and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
