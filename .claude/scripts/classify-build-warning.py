#!/usr/bin/env python3
"""classify-build-warning.py — evidence-based 4-tier classifier (Codex feedback).

Per Codex review (2026-05-03): classifier is DETERMINISTIC FIRST. LLM is
advisory fallback (not used yet — P3). Output:

  {
    "classification": "IN_SCOPE | FORWARD_DEP | NEEDS_TRIAGE | OUT_OF_SCOPE",
    "confidence":     0.0 - 1.0,
    "evidence_refs_matched": ["task-39", "POST /api/invoices"],
    "owning_artifact": "PLAN.md | API-CONTRACTS.md | TEST-GOALS.md | (none)",
    "recommended_action": "<auto-fix | scope:next-phase | triage:user | drop>"
  }

Heuristic rules (high precision; ambiguity => NEEDS_TRIAGE not silent forward):
  R1 IN_SCOPE if evidence_refs[].task_id in PLAN/task-*.md basenames
  R2 IN_SCOPE if evidence_refs[].endpoint in API-CONTRACTS/*.md (path matched)
  R3 IN_SCOPE if evidence_refs[].file path is referenced in any PLAN/task-*.md
  R4 FORWARD_DEP if category in {fe_be_call_graph, contract_shape_mismatch}
     AND no R1/R2/R3 match — those categories CAN be in scope but the
     specific evidence didn't anchor → conservative forward
  R5 NEEDS_TRIAGE if the warning has cross-cutting hints (path contains
     'shared/', 'common/', 'lib/', 'utils/', 'middleware/') AND no R1-R3
  R6 ADVISORY if severity=ADVISORY in input AND no R1-R3 match
  Default: NEEDS_TRIAGE (Codex: "ambiguous → block as NEEDS_TRIAGE,
  not silently forward-dep")
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _plan_task_files(phase_dir: Path) -> list[Path]:
    return list((phase_dir / "PLAN").glob("task-*.md")) if (phase_dir / "PLAN").exists() else []


def _api_contract_paths(phase_dir: Path) -> list[str]:
    """Return list of contract path_templates ('POST /api/foo')."""
    out: list[str] = []
    cdir = phase_dir / "API-CONTRACTS"
    if not cdir.exists():
        return out
    METHOD_RE = re.compile(r"\*\*Method:\*\*\s*([A-Z]+)", re.IGNORECASE)
    PATH_RE = re.compile(r"\*\*Path:\*\*\s*(\S+)")
    for cp in cdir.glob("*.md"):
        if cp.name == "index.md":
            continue
        try:
            text = cp.read_text(encoding="utf-8")
        except OSError:
            continue
        m = METHOD_RE.search(text)
        p = PATH_RE.search(text)
        if m and p:
            out.append(f"{m.group(1).upper()} {p.group(1)}")
    return out


def _file_appears_in_plan(file_path: str, plan_tasks: list[Path]) -> bool:
    needle = file_path.lower()
    base = Path(file_path).name.lower()
    for tp in plan_tasks:
        try:
            text = tp.read_text(encoding="utf-8").lower()
        except OSError:
            continue
        if needle in text or base in text:
            return True
    return False


def _classify(warning: dict, phase_dir: Path) -> dict:
    plan_tasks = _plan_task_files(phase_dir)
    plan_task_ids = {tp.stem for tp in plan_tasks}  # task-01, task-02, ...
    contracts = _api_contract_paths(phase_dir)

    matched: list[str] = []
    refs = warning.get("evidence_refs", [])

    # R1: task_id match
    for r in refs:
        tid = r.get("task_id")
        if tid and tid in plan_task_ids:
            matched.append(tid)

    # R2: endpoint match
    for r in refs:
        ep = r.get("endpoint")
        if ep and any(ep.split("/")[0] in c.split("/")[0] and ep.split(" ")[0] == c.split(" ")[0] for c in contracts):
            matched.append(ep)

    # R3: file path appears in any PLAN task
    for r in refs:
        f = r.get("file")
        if f and _file_appears_in_plan(f, plan_tasks):
            matched.append(f)

    if matched:
        return {
            "classification": "IN_SCOPE",
            "confidence": 0.9,
            "evidence_refs_matched": matched,
            "owning_artifact": "PLAN.md" if any(m.startswith("task-") for m in matched) else "API-CONTRACTS.md",
            "recommended_action": "auto-fix",
        }

    cat = warning.get("category", "other")
    sev = warning.get("severity", "TRIAGE_REQUIRED")

    # R5: cross-cutting hints
    cross_cut = ("shared/", "common/", "lib/", "utils/", "middleware/")
    has_cross = any(any(p in (r.get("file") or "") for p in cross_cut) for r in refs)

    if has_cross:
        return {
            "classification": "NEEDS_TRIAGE",
            "confidence": 0.7,
            "evidence_refs_matched": [],
            "owning_artifact": "(cross-cutting)",
            "recommended_action": "triage:user",
        }

    # R4: deterministic gate categories without anchor → forward
    if cat in {"fe_be_call_graph", "contract_shape_mismatch"}:
        return {
            "classification": "FORWARD_DEP",
            "confidence": 0.6,
            "evidence_refs_matched": [],
            "owning_artifact": "API-CONTRACTS.md (next phase)",
            "recommended_action": "scope:next-phase",
        }

    # R6: ADVISORY input + no anchor → forward
    if sev == "ADVISORY":
        return {
            "classification": "FORWARD_DEP",
            "confidence": 0.5,
            "evidence_refs_matched": [],
            "owning_artifact": "(advisory)",
            "recommended_action": "drop",
        }

    # Default — Codex: never silent forward, prefer triage
    return {
        "classification": "NEEDS_TRIAGE",
        "confidence": 0.4,
        "evidence_refs_matched": [],
        "owning_artifact": "(unknown)",
        "recommended_action": "triage:user",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--warning", required=True, help="JSON warning evidence (or path to file)")
    args = parser.parse_args()

    pd = Path(args.phase_dir)
    if not pd.exists():
        print(f"ERROR: phase-dir missing: {pd}", file=sys.stderr)
        return 2

    raw = args.warning
    if Path(raw).exists():
        warning = json.loads(Path(raw).read_text(encoding="utf-8"))
    else:
        warning = json.loads(raw)

    result = _classify(warning, pd)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
