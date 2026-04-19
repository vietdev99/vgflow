#!/usr/bin/env python3
"""
verify-goal-test-binding.py — Gate 5 for /vg:build step 8d post-wave.

Enforces: every task in a wave with <goals-covered>G-XX</goals-covered> MUST
have a test file modification in its commit that references either:
  (a) the goal id (G-XX) literally, or
  (b) at least one keyword extracted from TEST-GOALS.md success_criteria.

Rationale: closes the gap where AI can add a task claiming to cover a goal
without ever writing a test touching it. Post-wave typecheck + build + affected
unit gate can all pass even if tests never reference the goal.

Usage:
  python verify-goal-test-binding.py \
      --phase-dir .vg/phases/07.12-conversion-tracking-pixel \
      --wave-tag  vg-build-7.12-wave-2-start \
      --wave-number 2 \
      [--strict|--lenient] [--json]

Exit codes:
  0 — all tasks with goals have bound tests
  1 — at least one task fails binding (strict mode)
  2 — script error (bad args, missing artifacts)

Lenient mode prints warnings and exits 0 — used for first-time migration.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# English stopwords + VG/dev vocabulary that carry no discrimination
STOPWORDS = {
    "the", "and", "with", "for", "from", "into", "that", "this", "these", "those",
    "should", "must", "can", "will", "may", "has", "have", "had", "does", "did",
    "return", "returns", "returned", "contain", "contains", "exists", "exist",
    "verify", "verifies", "check", "checks", "ensure", "ensures", "shows",
    "display", "displays", "show", "render", "renders", "when", "then", "given",
    "value", "values", "field", "fields", "data", "state", "user", "users",
    "page", "pages", "route", "routes", "api", "http", "get", "post", "put",
    "delete", "patch", "endpoint", "request", "response", "body", "status",
    "code", "error", "errors", "valid", "invalid", "correct", "expected",
    "test", "tests", "testing", "tested", "work", "works", "working",
    "button", "click", "clicks", "clicked", "form", "forms", "input", "inputs",
    "name", "names", "type", "types", "number", "numbers", "list", "lists",
    "create", "creates", "created", "update", "updates", "updated", "delete",
    "deletes", "deleted", "successful", "successfully", "success", "failed",
    "all", "any", "one", "two", "three", "new", "old", "some", "each", "every",
    "also", "only", "both", "either", "more", "less", "most", "least",
    "after", "before", "during", "while", "without", "within", "against",
    "about", "above", "below", "between", "through", "over", "under",
}

# File patterns that count as test files
TEST_GLOB_RE = re.compile(
    # Web / backend: *.test.ts, *.spec.tsx, *.test.py, *.spec.rs, *.test.go
    r"\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs|py|rs|go)$"
    # Flutter: foo_test.dart
    r"|_test\.dart$"
    # iOS XCTest: FooTests.swift, FooTest.swift
    r"|Tests?\.swift$"
    # Android JUnit: FooTest.kt, FooTests.kt
    r"|Tests?\.kt$"
    # Maestro declarative mobile flow: foo.maestro.yaml / foo.maestro.yml
    r"|\.maestro\.ya?ml$"
)


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run git, return stdout. Empty string on failure."""
    try:
        out = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
        )
        return out.stdout or ""
    except Exception:
        return ""


def extract_keywords(text: str, min_len: int = 4, max_keywords: int = 15) -> set[str]:
    """
    Extract lowercase alphanumeric tokens from success criteria text.
    Drops stopwords and short tokens. Returns deduped set.
    """
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{%d,}" % (min_len - 1), text.lower())
    kws = set()
    for t in tokens:
        if t in STOPWORDS:
            continue
        kws.add(t)
        if len(kws) >= max_keywords:
            break
    return kws


def parse_plan_tasks(phase_dir: Path) -> dict[int, dict]:
    """
    Parse PLAN*.md files into task records.

    Returns: { task_number: {goals: [G-XX, ...], title: str, file: str} }
    """
    tasks: dict[int, dict] = {}
    plan_files = sorted(phase_dir.glob("*PLAN*.md"))
    # Prefer consolidated PLAN.md over numbered per-task plans if both exist
    consolidated = [p for p in plan_files if re.match(r"^PLAN(\.md)?$", p.name) or p.name == "PLAN.md"]
    if consolidated:
        plan_files = consolidated

    for plan in plan_files:
        try:
            text = plan.read_text(encoding="utf-8")
        except Exception:
            continue

        # Split into task blocks — "### Task N" or "## Task N" or "Task N —"
        task_pattern = re.compile(
            r"(?:^|\n)(?:#{2,4}\s*)?Task\s+(\d+)(?:\s*[—:\-]|\s)",
            re.IGNORECASE,
        )
        matches = list(task_pattern.finditer(text))
        if not matches:
            # Fallback: plan-file-per-task convention like "07.12-03-PLAN.md"
            m_fn = re.match(r".*-(\d+)-PLAN\.md$", plan.name)
            if m_fn:
                n = int(m_fn.group(1))
                goals = re.findall(r"<goals-covered>([^<]+)</goals-covered>", text)
                flat = []
                for g in goals:
                    flat.extend(re.findall(r"G-\d+", g))
                tasks[n] = {
                    "goals": sorted(set(flat)),
                    "title": plan.name,
                    "file": str(plan),
                }
            continue

        for i, m in enumerate(matches):
            n = int(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            goals = re.findall(r"<goals-covered>([^<]+)</goals-covered>", body)
            flat = []
            for g in goals:
                flat.extend(re.findall(r"G-\d+", g))
            tasks[n] = {
                "goals": sorted(set(flat)),
                "title": body.strip().splitlines()[0][:80] if body.strip() else f"Task {n}",
                "file": str(plan),
            }
    return tasks


def parse_test_goals(phase_dir: Path) -> dict[str, set[str]]:
    """
    Parse TEST-GOALS.md: for each G-XX, extract keywords from the block.

    Returns: { "G-XX": {keyword, ...} }
    """
    tg_file = phase_dir / "TEST-GOALS.md"
    goals: dict[str, set[str]] = {}
    if not tg_file.exists():
        return goals
    try:
        text = tg_file.read_text(encoding="utf-8")
    except Exception:
        return goals

    # Match G-XX headers; tolerate "## Goal G-01" / "## G-01:" / "| G-01 |"
    pattern = re.compile(r"(?m)^(?:#{1,4}\s*(?:Goal\s+)?|\|\s*)(G-\d+)")
    starts = [(m.group(1), m.start()) for m in pattern.finditer(text)]
    for i, (gid, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        block = text[start:end]
        goals[gid] = extract_keywords(block)
    return goals


def find_task_commit(phase_num: str, task_num: int, wave_tag: str) -> str | None:
    """Find the commit for a task since wave tag. Matches 'type(phase-TASKNUM):'."""
    task_str = f"{task_num:02d}"
    log = run_git(["log", "--format=%H %s", f"{wave_tag}..HEAD"])
    # Build phase match: strip leading zeros, match either "7.12" or "07.12"
    norm_phase = phase_num.lstrip("0") or phase_num
    for line in log.splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, subj = parts
        # Match  "xxx(7.12-03):" or "xxx(07.12-03):"
        m = re.search(r"\((\d+(?:\.\d+)*)-(\d+)\)", subj)
        if not m:
            continue
        commit_phase = m.group(1).lstrip("0") or m.group(1)
        commit_task = int(m.group(2))
        if commit_phase == norm_phase and commit_task == task_num:
            return sha
    return None


def files_changed_in_commit(sha: str) -> list[str]:
    out = run_git(["show", "--name-only", "--pretty=format:", sha])
    return [l.strip() for l in out.splitlines() if l.strip()]


def test_file_content(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def check_binding(
    task_num: int,
    goals: list[str],
    commit_sha: str,
    goal_keywords: dict[str, set[str]],
) -> tuple[bool, str]:
    """
    Return (passed, reason).

    Pass criteria: at least ONE modified test file in the commit either:
      - contains any of the goal ids (G-XX) literally, OR
      - contains at least one keyword from any claimed goal's TEST-GOALS block.
    """
    if not commit_sha:
        return False, f"no commit found for task {task_num}"

    changed = files_changed_in_commit(commit_sha)
    test_files = [f for f in changed if TEST_GLOB_RE.search(f)]

    if not test_files:
        return False, (
            f"task claims {', '.join(goals)} but no test file "
            f"(*.test.ts/*.spec.ts/etc.) in commit {commit_sha[:8]}"
        )

    # Collect all keywords across claimed goals
    all_keywords: set[str] = set()
    for gid in goals:
        all_keywords |= goal_keywords.get(gid, set())

    for tf in test_files:
        content = test_file_content(tf)
        if not content:
            continue
        # (a) literal goal id match
        for gid in goals:
            if gid in content:
                return True, f"test {tf} references {gid} literally"
        # (b) keyword match
        lower = content.lower()
        for kw in all_keywords:
            if kw in lower:
                return True, f"test {tf} contains keyword '{kw}'"

    return False, (
        f"task claims {', '.join(goals)} but none of the {len(test_files)} "
        f"test file(s) reference goal ids or keywords: {sorted(all_keywords)[:10]}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--wave-tag", required=True)
    ap.add_argument("--wave-number", type=int, required=True)
    ap.add_argument("--tasks", help="Comma-separated task numbers (default: all since wave tag)")
    ap.add_argument("--lenient", action="store_true", help="Warn instead of fail")
    ap.add_argument("--json", action="store_true", help="Emit JSON report to stdout")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(f"⛔ phase-dir not found: {phase_dir}", file=sys.stderr)
        return 2

    # Phase number: strip leading zeros from dir name like "07.12-..."
    phase_num = re.match(r"^(\d+(?:\.\d+)*)", phase_dir.name).group(1)

    tasks = parse_plan_tasks(phase_dir)
    if not tasks:
        print(f"⚠ no tasks found in {phase_dir}/*PLAN*.md — nothing to verify", file=sys.stderr)
        return 0

    goal_keywords = parse_test_goals(phase_dir)

    # Filter to requested tasks if --tasks provided
    if args.tasks:
        requested = {int(t) for t in args.tasks.split(",") if t.strip()}
        tasks = {n: t for n, t in tasks.items() if n in requested}

    report = {"phase": phase_num, "wave": args.wave_number, "results": []}
    failures = 0

    for task_num in sorted(tasks.keys()):
        task = tasks[task_num]
        goals = task["goals"]

        # Skip tasks that explicitly opt out
        if not goals or goals == ["no-goal-impact"]:
            report["results"].append({
                "task": task_num, "goals": goals, "status": "skipped",
                "reason": "no goals claimed (or explicit no-goal-impact)",
            })
            continue

        sha = find_task_commit(phase_num, task_num, args.wave_tag)
        if not sha:
            # Task may not be in this wave — skip silently
            continue

        passed, reason = check_binding(task_num, goals, sha, goal_keywords)
        entry = {
            "task": task_num,
            "goals": goals,
            "commit": sha[:8],
            "status": "pass" if passed else "fail",
            "reason": reason,
        }
        report["results"].append(entry)
        if not passed:
            failures += 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Goal-test binding — phase {phase_num} wave {args.wave_number}")
        for r in report["results"]:
            icon = {"pass": "✓", "fail": "✗", "skipped": "·"}.get(r["status"], "?")
            goals_str = ",".join(r["goals"]) if r["goals"] else "-"
            print(f"  {icon} Task {r['task']:>2} [{goals_str}] {r['reason']}")
        print(f"  Total: {len(report['results'])} tasks, {failures} failed")

    if failures and not args.lenient:
        print("", file=sys.stderr)
        print(f"⛔ {failures} task(s) claim goals without bound tests.", file=sys.stderr)
        print("   Each task listing <goals-covered>G-XX</goals-covered> MUST commit", file=sys.stderr)
        print("   a test file referencing either the goal id or a keyword from its", file=sys.stderr)
        print("   success criteria in TEST-GOALS.md.", file=sys.stderr)
        print("", file=sys.stderr)
        print("   Fix by:", file=sys.stderr)
        print("     (a) add a test file citing the goal, OR", file=sys.stderr)
        print("     (b) remove the <goals-covered> line if task truly doesn't touch the goal, OR", file=sys.stderr)
        print("     (c) mark <goals-covered>no-goal-impact</goals-covered> (explicit skip, audit trail)", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
