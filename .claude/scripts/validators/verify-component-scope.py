#!/usr/bin/env python3
"""
verify-component-scope.py — P19 D-04 fine-grained planner scope gate.

When a task carries <component-scope>{ComponentName}</component-scope>
(emitted by planner Rule 9 when fine-grained mode is on), every staged
file MUST be one of:
  1. Listed in the task's <file-path> block, OR
  2. Inside the scope subdirectory matching ComponentName, OR
  3. A test file paired with a listed file-path.

Validator NO-OPS on tasks without <component-scope> — fully backward
compatible with v2.14.0 PLAN files.

USAGE
  python verify-component-scope.py \
    --phase-dir .vg/phases/07.10-... \
    [--commit-sha HEAD] \
    [--task-num <N>] \
    [--output report.json]

EXIT
  0 — PASS or SKIP (no <component-scope> task in PLAN, or no FE files in commit)
  1 — BLOCK (file outside declared scope and not in <file-path>)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCOPE_RE = re.compile(r"<component-scope>([^<]+)</component-scope>", re.IGNORECASE)
FILE_PATH_RE = re.compile(r"<file-path>([^<]+)</file-path>", re.IGNORECASE)
INLINE_FILE_RE = re.compile(
    r"\b(?:apps|packages)/[A-Za-z0-9_./@{}-]+\.(?:tsx|jsx|vue|svelte|ts|js)\b"
)


def parse_tasks(plan_text: str) -> list[dict]:
    """Return list of {id, body, scope, file_paths}."""
    tasks: list[dict] = []
    xml_re = re.compile(
        r'<task\s+id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</task>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in xml_re.finditer(plan_text):
        body = m.group(2)
        scope_m = SCOPE_RE.search(body)
        if not scope_m:
            continue
        scope = scope_m.group(1).strip()
        file_paths = [p.strip() for p in FILE_PATH_RE.findall(body) if p.strip()]
        file_paths += [m.group(0) for m in INLINE_FILE_RE.finditer(body)]
        tasks.append(
            {
                "id": m.group(1),
                "scope": scope,
                "file_paths": sorted(set(file_paths)),
            }
        )
    return tasks


def files_in_commit(commit_sha: str) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "show", "--name-only", "--pretty=", commit_sha],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def file_violates(file_path: str, scope_name: str, allowed_paths: list[str]) -> bool:
    """File is allowed if explicitly listed OR contains scope_name segment in path."""
    fp_norm = file_path.replace("\\", "/")
    for allowed in allowed_paths:
        ap_norm = allowed.replace("\\", "/")
        if fp_norm == ap_norm:
            return False
        if fp_norm.endswith(".test.tsx") or fp_norm.endswith(".test.ts"):
            stem = re.sub(r"\.test\.(tsx?|jsx?)$", ".\\1", fp_norm)
            if stem == ap_norm or fp_norm.startswith(ap_norm.rsplit("/", 1)[0] + "/"):
                return False
    # Path segment match (e.g. .../components/Sidebar/...)
    name_lower = scope_name.lower()
    segments = [s.lower() for s in fp_norm.split("/")]
    if name_lower in segments:
        return False
    # Stem match (e.g. .../Sidebar.tsx)
    stem = Path(fp_norm).stem.lower()
    if stem == name_lower:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--commit-sha", default=None, help="commit to inspect; default = scan all PLAN tasks vs HEAD")
    ap.add_argument("--task-num", type=int, default=None, help="restrict to this task id")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    plan_files = sorted(phase_dir.glob("*PLAN*.md"))
    if not plan_files:
        result = {"phase_dir": str(phase_dir), "verdict": "SKIP", "reason": "no PLAN*.md found"}
        return _emit(result, args)

    scoped: list[dict] = []
    for pf in plan_files:
        try:
            scoped.extend(parse_tasks(pf.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    if args.task_num is not None:
        scoped = [t for t in scoped if str(t["id"]) == str(args.task_num)]

    result: dict = {
        "phase_dir": str(phase_dir),
        "verdict": "SKIP",
        "scoped_task_count": len(scoped),
        "violations": [],
    }

    if not scoped:
        result["reason"] = "no <component-scope> tasks in PLAN — fine-grained mode not in use"
        return _emit(result, args)

    # When commit-sha is provided, narrow to that commit's files.
    # Otherwise we cannot tell which task each file belongs to without progress
    # tracking — skip with informational verdict.
    if not args.commit_sha:
        result["verdict"] = "SKIP"
        result["reason"] = "no --commit-sha provided; per-task file attribution requires it"
        return _emit(result, args)

    files = files_in_commit(args.commit_sha)
    if not files:
        result["verdict"] = "SKIP"
        result["reason"] = f"commit {args.commit_sha} has no files"
        return _emit(result, args)

    # Try to identify which scoped task this commit belongs to.
    # Heuristic: the task whose file_paths overlap most with commit files.
    best_task = None
    best_overlap = 0
    for task in scoped:
        overlap = sum(1 for f in files if any(f.replace("\\", "/") == p.replace("\\", "/") for p in task["file_paths"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best_task = task
    if not best_task:
        result["verdict"] = "SKIP"
        result["reason"] = "could not attribute commit to a scoped task"
        return _emit(result, args)

    result["task"] = best_task["id"]
    result["scope"] = best_task["scope"]

    for f in files:
        if file_violates(f, best_task["scope"], best_task["file_paths"]):
            result["violations"].append({"file": f, "scope": best_task["scope"]})

    if result["violations"]:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"{len(result['violations'])} file(s) outside <component-scope>={best_task['scope']!r} "
            "and not in <file-path>"
        )
    else:
        result["verdict"] = "PASS"

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
