#!/usr/bin/env python3
"""verify-utility-reuse.py — blueprint-time gate preventing PLAN tasks from
redeclaring helper functions that already exist in the shared utility contract.

Run from blueprint (`/vg:blueprint`) step 2c AFTER PLAN generation, BEFORE build.

Strategy:
  1. Read PROJECT.md → parse the "## Shared Utility Contract" table
     → build {name → module} map of canonical exports.
  2. Read the phase's PLAN*.md file(s) → extract each task's description +
     <file-path> + any embedded code snippets.
  3. For each task, regex-scan description for phrases like:
       "add formatCurrency helper", "create formatDate util",
       "function formatCurrency", "const formatCurrency ="
  4. If a task description proposes a helper whose name matches a contract
     export AND file-path is NOT packages/utils/src/ → emit BLOCK finding.
  5. If a task proposes a NEW helper name (not in contract) AND phase description
     suggests re-use (>2 <file-path> entries or mentions "reused across") →
     emit WARN: "Add this to @vollxssp/utils first, then reference."

Exit codes:
  0 — clean (no violations)
  1 — blocking violations (block PLAN — force re-plan)
  2 — warnings only (pass-through, log for acceptance audit)

Usage:
  python3 verify-utility-reuse.py \
    --project .vg/PROJECT.md \
    --phase-dir .vg/phases/10-deal-management-dsp-partners
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple


class ContractExport(NamedTuple):
    name: str
    module: str


class Finding(NamedTuple):
    severity: str          # "BLOCK" | "WARN"
    task_num: str
    helper_name: str
    plan_file: str
    message: str


def parse_contract(project_md: Path) -> Dict[str, str]:
    """Parse the Shared Utility Contract table. Return {name: module_path}."""
    if not project_md.exists():
        return {}
    txt = project_md.read_text(encoding="utf-8", errors="ignore")
    # Find the section
    m = re.search(
        r"^##\s+Shared Utility Contract\s*$(.+?)^##\s+",
        txt, re.M | re.S,
    )
    if not m:
        return {}
    section = m.group(1)
    # Rows look like: | `formatCurrency` | `money.ts` | Money display | ... |
    contract: Dict[str, str] = {}
    for row in re.finditer(
        r"^\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|\s*`([^`]+)`", section, re.M
    ):
        contract[row.group(1)] = row.group(2)
    return contract


def parse_plan_tasks(plan_md: Path) -> List[Tuple[str, str, List[str]]]:
    """Return list of (task_num, description_block, file_paths)."""
    if not plan_md.exists():
        return []
    txt = plan_md.read_text(encoding="utf-8", errors="ignore")
    tasks: List[Tuple[str, str, List[str]]] = []
    # Split on "### Task N" headers
    parts = re.split(r"^###\s+Task\s+(\d+(?:\.\d+)?)", txt, flags=re.M)
    # parts[0] = preamble, then alternating num/body
    for i in range(1, len(parts), 2):
        task_num = parts[i].strip()
        body = parts[i + 1] if (i + 1) < len(parts) else ""
        # Extract <file-path> blocks (may be comma or + separated paths)
        paths: List[str] = []
        for fp in re.finditer(r"<file-path>([^<]+)</file-path>", body):
            raw = fp.group(1)
            for p in re.split(r"[+,]", raw):
                p = p.strip()
                if p:
                    paths.append(p)
        # Also <also-edits>
        for ae in re.finditer(r"<also-edits>([^<]+)</also-edits>", body):
            for p in re.split(r"[+,\s]+", ae.group(1)):
                p = p.strip()
                if p:
                    paths.append(p)
        tasks.append((task_num, body, paths))
    return tasks


HELPER_DECL_PATTERNS = [
    re.compile(r"\b(?:function|const|let)\s+([a-z][A-Za-z0-9_]*)\s*[=\(]"),
    re.compile(r"\bexport\s+(?:function|const)\s+([a-z][A-Za-z0-9_]*)\b"),
    re.compile(r"\badd\s+(?:helper|utility|util|function)\s+(?:called\s+)?`?([a-z][A-Za-z0-9_]*)`?", re.I),
    re.compile(r"\bcreate\s+(?:helper|utility|util)\s+`?([a-z][A-Za-z0-9_]*)`?", re.I),
    re.compile(r"\bimplement\s+`?([a-z][A-Za-z0-9_]*)`?\s+(?:helper|utility|util)", re.I),
]


def extract_declared_helpers(body: str) -> List[str]:
    """Return helper names the task proposes to declare/add."""
    names: set[str] = set()
    for pat in HELPER_DECL_PATTERNS:
        for m in pat.finditer(body):
            name = m.group(1)
            # Skip obviously non-helper names (React components start with uppercase,
            # already filtered by [a-z] anchor, but skip common false positives)
            if name in {
                "use", "it", "describe", "beforeAll", "afterAll",
                "beforeEach", "afterEach", "expect", "test", "if",
                "else", "for", "while", "do", "return", "async",
                "await", "try", "catch", "throw", "new", "this",
                "class", "true", "false", "null", "undefined",
            }:
                continue
            if len(name) < 3:
                continue
            names.add(name)
    return sorted(names)


def classify_file_path(paths: List[str]) -> str:
    """Return 'utils' if any path is in packages/utils/, else 'other'."""
    for p in paths:
        if "packages/utils/" in p or p.startswith("packages/utils"):
            return "utils"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, help="Path to PROJECT.md")
    ap.add_argument("--phase-dir", required=True, help="Phase directory")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    project_md = Path(args.project)
    phase_dir = Path(args.phase_dir)

    contract = parse_contract(project_md)
    if not contract:
        print("⚠ No Shared Utility Contract section found in PROJECT.md — skipping check.")
        return 0

    plan_files = sorted(phase_dir.glob("PLAN*.md"))
    if not plan_files:
        print(f"⚠ No PLAN*.md in {phase_dir} — nothing to check.")
        return 0

    findings: List[Finding] = []
    total_tasks = 0

    for plan in plan_files:
        tasks = parse_plan_tasks(plan)
        total_tasks += len(tasks)
        for task_num, body, paths in tasks:
            declared = extract_declared_helpers(body)
            file_class = classify_file_path(paths)
            for name in declared:
                if name in contract:
                    if file_class == "utils":
                        # Declared in packages/utils/ — that IS the canonical place, OK
                        continue
                    findings.append(Finding(
                        severity="BLOCK",
                        task_num=task_num,
                        helper_name=name,
                        plan_file=str(plan.relative_to(phase_dir.parent.parent) if phase_dir.parent.parent in plan.parents else plan),
                        message=(
                            f"Task {task_num} declares `{name}` in {paths[0] if paths else '<unknown>'} "
                            f"but `{name}` already exists in @vollxssp/utils "
                            f"({contract[name]}). Import instead of re-declaring."
                        ),
                    ))
                else:
                    # NEW helper. Flag WARN if task paths span >1 non-utils file
                    # (suggests reuse potential) and paths don't include packages/utils.
                    non_utils = [p for p in paths if "packages/utils" not in p]
                    if len(non_utils) >= 2 and file_class == "other":
                        findings.append(Finding(
                            severity="WARN",
                            task_num=task_num,
                            helper_name=name,
                            plan_file=str(plan.name),
                            message=(
                                f"Task {task_num} declares NEW helper `{name}` across "
                                f"{len(non_utils)} non-utils files. If used elsewhere in "
                                f"the phase (or future phases), add to @vollxssp/utils "
                                f"first via Task 0, then import."
                            ),
                        ))

    blocks = [f for f in findings if f.severity == "BLOCK"]
    warns = [f for f in findings if f.severity == "WARN"]

    if args.json:
        import json
        print(json.dumps({
            "total_tasks": total_tasks,
            "contract_size": len(contract),
            "blocks": [f._asdict() for f in blocks],
            "warns": [f._asdict() for f in warns],
        }, indent=2))
    else:
        print(f"━━━ Utility Reuse Check ━━━")
        print(f"Contract exports: {len(contract)}")
        print(f"PLAN tasks checked: {total_tasks}")
        print(f"BLOCK findings: {len(blocks)}")
        print(f"WARN findings: {len(warns)}")
        print()
        for f in blocks:
            print(f"⛔ BLOCK Task {f.task_num} — `{f.helper_name}`")
            print(f"   {f.message}")
        for f in warns:
            print(f"⚠ WARN Task {f.task_num} — `{f.helper_name}`")
            print(f"   {f.message}")

    if blocks:
        return 1
    if warns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
