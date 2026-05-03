#!/usr/bin/env python3
"""
verify-plan-paths.py — validate PLAN.md file paths against the repo state.

Catches stale/drifted paths in PLAN before build — the class of bug that
showed up in Phase 10:
  - Task 2 PLAN said `apps/api/src/infrastructure/clickhouse/migrations/0017_add_deal_columns.sql`
    but that directory does not exist (real CH schemas in apps/workers/src/consumer/clickhouse/schemas.js)
  - Task 12 PLAN said `apps/rtb-engine/src/auction/pipeline.rs`
    but that directory does not exist (real auction entry in apps/rtb-engine/src/handlers/bid.rs)

Both were discovered only when the executor agent tried to open the file.
This script runs at blueprint time to catch them earlier.

Algorithm:
  1. Parse all <file-path> + <also-edits> tags from PLAN*.md
  2. Collect "paths that THIS phase will create" — any <file-path> of any task
     whose target file doesn't exist yet (is a NEW file)
  3. For each path, classify:
     - VALID: file exists OR parent dir exists OR parent dir will be created by another task in this phase
     - WARN:  parent dir doesn't exist AND no other task creates it (likely stale)
     - FAIL:  path is malformed / absolute / escapes repo root

Exit codes:
  0 — all paths valid
  1 — malformed paths OR all paths drifted (blocker)
  2 — some paths drifted (warnings only — planner may be creating new subsystems intentionally)

Usage (from blueprint.md step 2c):
  python verify-plan-paths.py --phase-dir .vg/phases/10-... [--strict]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RE_FILE_PATH = re.compile(r"<file-path>([^<]+)</file-path>")
RE_ALSO_EDITS = re.compile(r"<also-edits>([^<]+)</also-edits>")
RE_TASK_HEADER = re.compile(r"^### Task (\d+)[^\n]*", re.M)


def parse_plan(plan_file: Path) -> list[dict]:
    """Return list of task dicts with num, file_path, also_edits, line_range."""
    text = plan_file.read_text(encoding="utf-8", errors="replace")
    tasks = []
    # Split into per-task sections
    for m in re.finditer(r"^### Task (\d+)[^\n]*.*?(?=^### Task |\Z)", text, re.M | re.S):
        num = int(m.group(1))
        section = m.group(0)
        fp_m = RE_FILE_PATH.search(section)
        also: list[str] = []
        for ae in RE_ALSO_EDITS.finditer(section):
            for p in re.split(r"[,\n;]", ae.group(1)):
                p = p.strip()
                if p and not p.startswith("#") and not p.startswith("<!--"):
                    also.append(p)
        tasks.append({
            "num": num,
            "file_path": fp_m.group(1).strip() if fp_m else None,
            "also_edits": also,
        })
    return tasks


def classify_path(path: str, repo_root: Path, creator_parents: set[str]) -> tuple[str, str]:
    """
    Return (verdict, detail) — verdict ∈ {VALID, WARN, FAIL}.
    creator_parents = set of directory paths that will be created by this phase
    (derived from tasks whose <file-path> is a new file).
    """
    path_norm = path.replace("\\", "/").strip()

    # Basic sanity
    if not path_norm:
        return "FAIL", "empty path"
    if path_norm.startswith("/") or ":" in path_norm.split("/")[0]:
        return "FAIL", "absolute path (should be repo-relative)"
    if ".." in path_norm.split("/"):
        return "FAIL", "escapes repo root via ..  — normalize"

    # Directory-prefix in <also-edits> (e.g., "apps/rtb-engine/tests/") — treat as glob
    if path_norm.endswith("/"):
        dir_abs = repo_root / path_norm.rstrip("/")
        if dir_abs.is_dir():
            return "VALID", "directory exists (also-edits prefix)"
        return "WARN", f"directory prefix in also-edits does not exist: {path_norm}"

    file_abs = repo_root / path_norm
    if file_abs.exists():
        # Editing existing file — fine
        return "VALID", "file exists (editing)"

    # Check parent dir
    parent_abs = file_abs.parent
    parent_rel = str(parent_abs.relative_to(repo_root)).replace("\\", "/")
    if parent_abs.is_dir():
        return "VALID", "new file in existing dir"

    # Parent doesn't exist — will it be created by another task?
    # Walk UP the parent chain — if ANY ancestor is in creator_parents, OK
    current = parent_rel
    while current and current != ".":
        if current in creator_parents:
            return "VALID", f"parent dir created by another task ({current})"
        current = str(Path(current).parent).replace("\\", "/")
        if current == ".":
            break

    return "WARN", f"parent dir does not exist and no task creates it: {parent_rel}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    ap.add_argument("--strict", action="store_true",
                    help="Treat WARN as failure (exit 1 on any drift).")
    args = ap.parse_args()

    phase_dir = args.phase_dir
    if not phase_dir.exists():
        print(f"\033[38;5;208mphase-dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 1

    plans = list(phase_dir.glob("PLAN*.md"))
    if not plans:
        print(f"\033[33mno PLAN*.md found in {phase_dir} — nothing to verify\033[0m", file=sys.stderr)
        return 0

    all_tasks: list[dict] = []
    for p in plans:
        all_tasks.extend(parse_plan(p))

    if not all_tasks:
        print(f"\033[33mno tasks parsed from {plans[0].name} — verify PLAN format\033[0m", file=sys.stderr)
        return 0

    # Collect parent dirs of files THIS phase creates — but only if the task's
    # IMMEDIATE parent dir exists on HEAD (i.e., the task is a legitimate new-file
    # creator, not a path that itself looks stale). Then other tasks can create
    # siblings or children of that new file's dir.
    #
    # Example:
    #   Task 9 creates apps/rtb-engine/src/deal/types.rs (parent src/ exists on HEAD)
    #     → registers apps/rtb-engine/src/deal/ as a creator_parent
    #   Task 10 creates apps/rtb-engine/src/deal/cache.rs → parent is creator_parent → VALID
    creator_parents: set[str] = set()
    for t in all_tasks:
        if not t["file_path"]:
            continue
        fp = t["file_path"].replace("\\", "/")
        file_abs = args.repo_root / fp
        if file_abs.exists():
            continue
        # New file — check immediate parent exists on HEAD
        immediate_parent = file_abs.parent
        if immediate_parent.is_dir():
            parent_rel = str(immediate_parent.relative_to(args.repo_root)).replace("\\", "/")
            # Register the new dir this task will create (if any) — PLUS all
            # descendants along its own file's path are "will-be-created" too.
            # But NOT walk up past immediate_parent (that's already on HEAD).
            new_dir = str(Path(fp).parent).replace("\\", "/")
            if new_dir != parent_rel:
                # Task creates a sub-dir chain — register the whole chain below parent
                walk = new_dir
                while walk and walk != parent_rel and walk != ".":
                    creator_parents.add(walk)
                    walk = str(Path(walk).parent).replace("\\", "/")
            else:
                # Task creates a file directly in existing dir — no new dir to register
                pass

    # Classify every path
    print(f"━━━ PLAN path validation ({len(all_tasks)} tasks) ━━━")
    print(f"Phase: {phase_dir.name}")
    print()

    fail_count = 0
    warn_count = 0
    valid_count = 0

    for t in all_tasks:
        paths: list[tuple[str, str]] = []
        if t["file_path"]:
            paths.append(("file-path", t["file_path"]))
        for ae in t["also_edits"]:
            paths.append(("also-edits", ae))

        if not paths:
            print(f"  Task {t['num']}: (no <file-path> declared)")
            continue

        task_issues = []
        for tag, path in paths:
            verdict, detail = classify_path(path, args.repo_root, creator_parents)
            icon = {"VALID": "✓", "WARN": "", "FAIL": ""}[verdict]
            task_issues.append((tag, path, verdict, detail, icon))
            if verdict == "FAIL":
                fail_count += 1
            elif verdict == "WARN":
                warn_count += 1
            else:
                valid_count += 1

        # Only print tasks with issues (concise output)
        has_issue = any(v != "VALID" for _, _, v, _, _ in task_issues)
        if has_issue or len(task_issues) > 3:
            print(f"  Task {t['num']}:")
            for tag, path, verdict, detail, icon in task_issues:
                print(f"    {icon} <{tag}>{path}</{tag}>  [{verdict}] — {detail}")

    print()
    total = fail_count + warn_count + valid_count
    print(f"Paths checked: {total}  ({valid_count} valid, {warn_count} warnings, {fail_count} failures)")

    # v1.14.3 L1 — package-scope validation
    # Catches the "@vollxssp/api but real name is @vollx/api" class of drift
    # seen in Phase 10 Task 22. PLAN descriptions sometimes reference the wrong
    # npm scope; agent discovers at typecheck time (late + expensive).
    pkg_issues = _check_package_scopes(phase_dir, args.repo_root)
    if pkg_issues:
        print()
        print(f"\033[33m{len(pkg_issues)} package-scope mismatch(es) in PLAN:\033[0m")
        for issue in pkg_issues:
            print(f"    {issue}")
        warn_count += len(pkg_issues)

    if fail_count > 0:
        print(f"\n⛔ {fail_count} malformed path(s) — blueprint must be fixed before build.")
        return 1
    if warn_count > 0 and args.strict:
        print(f"\n⛔ {warn_count} drifted path(s) with --strict — blueprint must be fixed.")
        return 1
    if warn_count > 0:
        print(f"\n⚠ {warn_count} potentially drifted path(s). Verify these are intentional new subsystems.")
        print(f"  If they're stale PLAN paths, correct the PLAN before running /vg:build.")
        return 2

    print("\n✓ All PLAN paths valid (existing files or well-placed new files).")
    return 0


def _check_package_scopes(phase_dir: Path, repo_root: Path) -> list[str]:
    """Grep PLAN*.md for npm package references (@scope/name) and verify each
    exists in the monorepo via package.json 'name' field. Returns list of
    mismatch descriptions (empty = clean).
    """
    import json as _json

    # Collect all package.json names in repo (skip node_modules)
    known_names: set[str] = set()
    for pj in repo_root.rglob("package.json"):
        if "node_modules" in pj.parts:
            continue
        try:
            data = _json.loads(pj.read_text(encoding="utf-8", errors="ignore"))
            name = data.get("name")
            if name:
                known_names.add(name)
        except Exception:
            continue

    if not known_names:
        return []  # no packages found — skip check

    # Only flag @scoped packages — unscoped names like "react" are external deps
    scoped = {n for n in known_names if n.startswith("@")}
    if not scoped:
        return []

    # Derive valid scopes
    valid_scopes = {n.split("/")[0] for n in scoped}

    # Grep PLAN for @scope/name references
    plans = list(phase_dir.glob("PLAN*.md"))
    issues = []
    seen = set()  # dedupe same mismatch across files

    pkg_ref_re = re.compile(r"`?(@[A-Za-z0-9_-]+/[A-Za-z0-9_-]+)`?")
    for plan in plans:
        try:
            txt = plan.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in pkg_ref_re.finditer(txt):
            ref = m.group(1)
            if ref in known_names:
                continue
            scope = ref.split("/")[0]
            if scope not in valid_scopes:
                continue  # different scope entirely (e.g., @types/node) — not our concern
            # Same scope, different name → likely typo / drift
            if ref in seen:
                continue
            seen.add(ref)
            # Suggest nearest match
            candidates = sorted(n for n in scoped if n.startswith(scope + "/"))
            suggestion = f" (did you mean {candidates[0]}?)" if candidates else ""
            issues.append(f"PLAN references `{ref}` — not in monorepo{suggestion}")

    return issues


if __name__ == "__main__":
    sys.exit(main())
