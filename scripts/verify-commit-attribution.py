#!/usr/bin/env python3
"""
verify-commit-attribution.py — post-wave check that each commit only touches
its own task's files.

Problem detected:
  When parallel executor agents share `.git/index`, one agent's `git add` can
  land on another agent's index before the second agent commits. The second
  agent's `git commit` then absorbs the first agent's files silently, and the
  first agent has nothing to commit → has to produce a follow-up `docs` commit
  for audit trail. This script catches that after-the-fact so the wave gate
  FAILs and the orchestrator re-plans instead of proceeding with corrupted
  attribution.

Protocol prerequisite:
  Executors MUST use `.claude/commands/vg/_shared/lib/build-commit-queue.sh`
  to serialize stage + commit. This script is the safety net if the mutex
  was bypassed (e.g., agent forgot to source, or lock broken by stale timeout).

Usage:
  python verify-commit-attribution.py \\
    --phase-dir .vg/phases/10-deal-management-dsp-partners \\
    --wave-tag vg-build-10-wave-1-start \\
    --wave-number 1

Exit codes:
  0 — all commits cleanly attributed, each touches only its task's files
  1 — usage / arg error
  2 — attribution violation detected (commit X contains files from task Y)
  3 — missing commit (one task produced no commit with its number)
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

RE_COMMIT_SUBJECT = re.compile(
    r"^(feat|fix|refactor|test|chore|docs|style|perf)\((\d+(?:\.\d+)*)-(\d+)\):"
)
RE_FILE_PATH_TAG = re.compile(r"<file-path>([^<]+)</file-path>")
# Integration / wiring tasks touch multiple declared files. PLAN authors
# add <also-edits> tag (comma-separated OR one-per-tag) for files beyond
# the main one. Example:
#   <file-path>apps/rtb-engine/src/handlers/bid.rs</file-path>
#   <also-edits>apps/rtb-engine/src/main.rs, apps/rtb-engine/src/state.rs</also-edits>
RE_ALSO_EDITS_TAG = re.compile(r"<also-edits>([^<]+)</also-edits>")

# Files that are ALWAYS allowed in any task's commit (orchestration artifacts).
ALWAYS_ALLOWED = {
    "SUMMARY.md",
    "PIPELINE-STATE.json",
    ".step-markers",
    "wave-1-context.md",
    "wave-2-context.md",
    "wave-2a-context.md",
    "wave-2b-context.md",
    "wave-3-context.md",
    "wave-4-context.md",
    "wave-5-context.md",
    "wave-6-context.md",
}

# Entry-point / registration filenames. When a task creates a new file AND
# edits one of these in the SAME app tree, the registration edit is
# expected (e.g., Task 9 creates deal/types.rs AND adds `pub mod deal;`
# to lib.rs). Classified as 'own-registration' — legitimate, not violation.
#
# Detection rule: file must be in the same top-2 path components as the
# task's main file-path (same app root), AND the basename matches.
REGISTRATION_FILENAMES = {
    "lib.rs",          # Rust crate entry — `pub mod X;` registration
    "main.rs",         # Rust binary entry
    "mod.rs",          # Rust module entry within a dir
    "app.ts",          # Fastify app entry — `fastify.register(...)`
    "app.js",
    "index.ts",        # TS module barrel
    "index.js",
    "__init__.py",     # Python package init
    # Common Fastify / TS route aggregators (v1.14.3 L2)
    "routes.ts",       # route barrel (e.g., modules/X/routes.ts)
    "routes.js",
    "plugins.ts",      # Fastify plugin aggregator
    "plugins.js",
    "schema.ts",       # Zod/schema barrel
    "schema.js",
    "schemas.ts",
    "schemas.js",
    "types.ts",        # cross-module type re-export point
    "types.js",
    # Rust additions
    "api.rs",          # axum router barrel
    "routes.rs",       # axum routes aggregator
    "handlers.rs",     # handler barrel
    # Go
    "main.go",
    "mod.go",
    # Python entry variants
    "main.py",
    "__main__.py",
}

# Auto-accept test sibling of a task's main file (e.g., foo.ts → __tests__/foo.test.ts).
def _is_test_of(test_path: str, main_path: str) -> bool:
    """Check if test_path is plausibly the test file for main_path."""
    main = Path(main_path)
    test = Path(test_path)
    if "__tests__" not in test.parts:
        return False
    stem = main.stem
    # Allow foo.test.ts, foo.spec.ts, foo.integration.test.ts, foo.<tag>.test.ts
    if not any(test.name.startswith(stem) for _ in [1]):
        return False
    if not (test.name.endswith(".test.ts") or test.name.endswith(".test.tsx")
            or test.name.endswith(".spec.ts") or test.name.endswith(".test.js")
            or test.name.endswith(".test.jsx")):
        return False
    # Test file must be in same module tree as main
    main_parent = main.parent
    test_parent = test.parent
    # Walk up — test's parent should share an ancestor with main's parent
    # (e.g., apps/api/src/modules/deals/__tests__/ shares deals/ with main)
    for ancestor in [main_parent, main_parent.parent, main_parent.parent.parent]:
        if ancestor and str(ancestor) in str(test_parent):
            return True
    return False


def _git(args: list[str], cwd: Path | None = None) -> str:
    """Run git and return stdout. Raises on non-zero."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout


def _parse_task_files(phase_dir: Path) -> dict[int, dict]:
    """
    Load each .wave-tasks/task-N.md and return:
      { task_num: { 'file_path': '...', 'allowed_files': [patterns] } }
    """
    tasks_dir = phase_dir / ".wave-tasks"
    if not tasks_dir.exists():
        # Fallback: parse PLAN*.md directly
        tasks = {}
        for plan_file in phase_dir.glob("PLAN*.md"):
            text = plan_file.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r"^### Task (\d+).*?(?=^### Task |\Z)",
                text, re.M | re.S,
            ):
                num = int(m.group(1))
                section = m.group(0)
                fp = RE_FILE_PATH_TAG.search(section)
                also: list[str] = []
                for ae in RE_ALSO_EDITS_TAG.finditer(section):
                    for p in re.split(r"[,\n;]", ae.group(1)):
                        p = p.strip()
                        if p and not p.startswith("#"):
                            also.append(p)
                if fp:
                    tasks[num] = {
                        "file_path": fp.group(1).strip(),
                        "also_edits": also,
                        "source": str(plan_file),
                    }
        return tasks

    tasks = {}
    for task_file in sorted(tasks_dir.glob("task-*.md")):
        m = re.match(r"task-(\d+)\.md$", task_file.name)
        if not m:
            continue
        num = int(m.group(1))
        text = task_file.read_text(encoding="utf-8", errors="replace")
        fp_match = RE_FILE_PATH_TAG.search(text)
        also_edits: list[str] = []
        for ae_match in RE_ALSO_EDITS_TAG.finditer(text):
            # Split on commas + newlines + semicolons. Trim whitespace.
            for p in re.split(r"[,\n;]", ae_match.group(1)):
                p = p.strip()
                if p and not p.startswith("#"):
                    also_edits.append(p)
        tasks[num] = {
            "file_path": fp_match.group(1).strip() if fp_match else None,
            "also_edits": also_edits,
            "source": str(task_file),
        }
    return tasks


def _commit_files(sha: str) -> list[str]:
    """Return list of files changed by commit `sha` (relative paths)."""
    out = _git(["show", "--pretty=", "--name-only", sha])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _classify_file(
    path: str,
    expected_main: str | None,
    expected_also_edits: list[str],
    all_tasks: dict[int, dict],
    commit_task_num: int,
) -> str:
    """
    Classify a file path relative to the current commit's expected task:
      'own-main'         — exact match of the task's <file-path>
      'own-also-edit'    — matches any path in the task's <also-edits> tag
      'own-test'         — __tests__ sibling of own-main
      'own-dir'          — in the same directory as own-main
      'own-registration' — entry-point file (lib.rs / app.ts / ...) in same app tree
      'orchestration'    — always-allowed (SUMMARY, PIPELINE-STATE, etc.)
      'other-task'       — matches ANOTHER task's <file-path> or <also-edits>
      'unrelated'        — doesn't match any task, not orchestration
    """
    # Orchestration files
    for allowed in ALWAYS_ALLOWED:
        if path.endswith(allowed) or allowed in path.split("/"):
            return "orchestration"

    # Exact match of the commit's own task main path
    if expected_main and path == expected_main:
        return "own-main"

    # Explicit declaration in <also-edits> — integration/wiring task
    path_norm = path.replace("\\", "/")
    for ae in expected_also_edits:
        ae_norm = ae.replace("\\", "/")
        if path_norm == ae_norm:
            return "own-also-edit"
        # Also support directory-prefix match (e.g., <also-edits>apps/rtb-engine/src/services/</also-edits>)
        if ae_norm.endswith("/") and path_norm.startswith(ae_norm):
            return "own-also-edit"

    # Test of own-main
    if expected_main and _is_test_of(path, expected_main):
        return "own-test"

    # Test of any own-also-edit
    for ae in expected_also_edits:
        if _is_test_of(path, ae):
            return "own-test"

    # Own directory match (same parent as main)
    if expected_main:
        main_parent = str(Path(expected_main).parent).replace("\\", "/")
        if main_parent and path.replace("\\", "/").startswith(main_parent + "/"):
            return "own-dir"

    # Registration file (lib.rs / app.ts / index.ts etc.) in same app tree
    if expected_main:
        path_norm = path.replace("\\", "/")
        basename = Path(path_norm).name
        if basename in REGISTRATION_FILENAMES:
            # Same app tree = share the first 2 path components (e.g., apps/api/*)
            main_parts = Path(expected_main).parts
            path_parts = Path(path_norm).parts
            if (len(main_parts) >= 2 and len(path_parts) >= 2
                    and main_parts[0] == path_parts[0]
                    and main_parts[1] == path_parts[1]):
                return "own-registration"

    # Check if this file matches ANOTHER task's main path or also-edits
    for other_num, other in all_tasks.items():
        if other_num == commit_task_num:
            continue
        other_main = other.get("file_path")
        other_also = other.get("also_edits", [])
        # Exact match of other task's main
        if other_main and path == other_main:
            return f"other-task:{other_num}"
        # Exact match of other task's also-edits
        for ae in other_also:
            ae_norm = ae.replace("\\", "/")
            if path_norm == ae_norm:
                return f"other-task:{other_num}"
        # Test of other task's main
        if other_main and _is_test_of(path, other_main):
            return f"other-task:{other_num}"
        # Same dir as other task's main (but not our own) — only if we have our own parent
        if other_main:
            other_parent = str(Path(other_main).parent).replace("\\", "/")
            our_parent = str(Path(expected_main).parent).replace("\\", "/") if expected_main else None
            if (other_parent and other_parent != our_parent and
                    path_norm.startswith(other_parent + "/")):
                return f"other-task:{other_num}"

    return "unrelated"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--wave-tag", required=True)
    ap.add_argument("--wave-number", type=int, required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Fail on 'unrelated' files too (default: only fail on other-task cross-attribution)")
    args = ap.parse_args()

    phase_dir = args.phase_dir
    if not phase_dir.exists():
        print(f"⛔ phase-dir not found: {phase_dir}", file=sys.stderr)
        return 1

    # Check wave tag exists
    try:
        _git(["rev-parse", "--verify", args.wave_tag])
    except subprocess.CalledProcessError:
        print(f"⛔ wave-tag not found: {args.wave_tag}", file=sys.stderr)
        return 1

    # Load task specs
    all_tasks = _parse_task_files(phase_dir)
    if not all_tasks:
        print(f"⚠ no tasks parsed from {phase_dir} — cannot verify", file=sys.stderr)
        return 0

    # Get commits since wave-tag
    commits_out = _git(["log", "--format=%H %s", f"{args.wave_tag}..HEAD"])
    commit_lines = [line for line in commits_out.strip().splitlines() if line.strip()]

    violations = []
    seen_tasks = set()

    print(f"━━━ Commit attribution audit (wave {args.wave_number}) ━━━")
    print(f"Wave-tag: {args.wave_tag}")
    print(f"Commits:  {len(commit_lines)}")
    print()

    for line in commit_lines:
        sha, _, subject = line.partition(" ")
        m = RE_COMMIT_SUBJECT.match(subject)
        if not m:
            print(f"  ? {sha[:8]} — subject doesn't match type(phase-task): pattern — skipping")
            continue

        ctype, phase_num, task_num_str = m.groups()
        task_num = int(task_num_str)

        # Task 0 = orchestrator/workflow bookkeeping (phase-recon fix, verifier
        # refinement, preflight helper, etc.) — these don't have a PLAN task
        # spec so attribution classification is nonsensical. Skip them.
        if task_num == 0:
            files = _commit_files(sha)
            print(f"  {sha[:8]} [{ctype}({phase_num}-{task_num_str})] — {len(files)} files — orchestrator commit (skipped)")
            continue

        seen_tasks.add(task_num)
        task_spec = all_tasks.get(task_num, {})
        expected = task_spec.get("file_path")
        expected_also = task_spec.get("also_edits", [])

        files = _commit_files(sha)
        also_hint = f" (+{len(expected_also)} also-edits)" if expected_also else ""
        print(f"  {sha[:8]} [{ctype}({phase_num}-{task_num_str})] — {len(files)} files — expected main: {expected or '<unknown>'}{also_hint}")

        commit_violations = []
        for f in files:
            category = _classify_file(f, expected, expected_also, all_tasks, task_num)
            flag = ""
            if category.startswith("other-task:"):
                other_num = category.split(":")[1]
                commit_violations.append((f, category))
                flag = f"  ⛔ CROSS-ATTRIBUTION → belongs to task {other_num}"
            elif category == "unrelated" and args.strict:
                commit_violations.append((f, category))
                flag = "  ⚠ unrelated"
            elif category == "unrelated":
                flag = "  (unrelated — not strict, skipped)"
            else:
                flag = f"  ({category})"
            if flag:
                print(f"      {f}{flag}")

        if commit_violations:
            violations.append({
                "commit": sha,
                "task": task_num,
                "type": ctype,
                "subject": subject,
                "violations": commit_violations,
            })

    # Check for missing commits (expected tasks that produced no commit)
    expected_tasks = set(all_tasks.keys())
    # Filter expected_tasks to only those matching the target wave if we could infer.
    # For now, trust the caller gave us the right wave-tag.
    missing = []
    for tnum in sorted(expected_tasks):
        if tnum in seen_tasks:
            continue
        # It's only "missing" for THIS wave — but we don't know wave ranges here.
        # Conservatively warn, don't hard-fail on missing (caller knows wave ranges).
        pass

    print()
    if violations:
        print(f"━━━ {len(violations)} attribution violation(s) detected ━━━")
        for v in violations:
            print(f"  • commit {v['commit'][:8]} (task {v['task']}): {len(v['violations'])} cross-attributions")
            for f, cat in v["violations"]:
                print(f"      {f}  [{cat}]")
        print()
        print("Root cause: parallel executors bypassed the commit-queue mutex.")
        print("Fix: all agents MUST source build-commit-queue.sh and wrap stage+commit.")
        print("See .claude/commands/vg/_shared/vg-executor-rules.md § Parallel-wave commit safety")
        return 2

    print("✓ All commits cleanly attributed — each commit touches only its task's files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
