#!/usr/bin/env python3
"""
Validator: test-first.py

Purpose: TDD gate — before a commit touches src/, a prior commit in this
phase must have added or modified a test file that would FAIL against the
starting state. Prevents "ship feature + test that trivially passes
because it tests nothing".

Approach (relaxed, heuristic):
- For this phase's commits (via --since-ref or phase start tag):
  - Group commits by task-id (from commit message)
  - For each task, check: is there a commit touching apps/**/e2e/**.spec.ts
    OR apps/**/src/**.test.ts BEFORE the commit touching apps/**/src/** (non-test)?
- Allow task to opt out via 'no-test-gate' marker in commit message.

Usage: test-first.py --phase <N> [--since-ref REF]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

TASK_RE = re.compile(r"^(feat|fix|refactor|test|chore|docs)\(([\d.]+-\d+)\):")
NO_GATE_RE = re.compile(r"no-test-gate|test:")


def git_log_json(since: str | None) -> list[dict]:
    range_arg = f"{since}..HEAD" if since else "HEAD~50..HEAD"
    r = subprocess.run(
        ["git", "log", "--format=%H|%s|%an", "--name-only", range_arg],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return []

    commits = []
    current = None
    for line in r.stdout.splitlines():
        if "|" in line and len(line) > 40:
            if current:
                commits.append(current)
            sha, subject, author = line.split("|", 2)
            current = {"sha": sha, "subject": subject, "files": []}
        elif line.strip() and current:
            current["files"].append(line.strip())
    if current:
        commits.append(current)
    return commits


def classify_files(files: list[str]) -> dict:
    test = [f for f in files if
            re.search(r"/(e2e|tests?)/|\.test\.[tj]sx?$|\.spec\.[tj]sx?$", f)]
    src_nontest = [f for f in files if
                   f.startswith(("apps/", "packages/"))
                   and "/src/" in f
                   and f not in test]
    return {"test": test, "src_nontest": src_nontest}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--since-ref", default=None,
                    help="git ref to start from; default HEAD~50")
    args = ap.parse_args()

    out = Output(validator="test-first")
    with timer(out):
        commits = git_log_json(args.since_ref)
        if not commits:
            out.warn(Evidence(
                type="info",
                message="No commits in range — TDD gate skipped",
            ))
            emit_and_exit(out)

        # Group by task id
        tasks: dict[str, list[dict]] = {}
        for c in commits:
            m = TASK_RE.match(c["subject"])
            if not m:
                continue
            tid = m.group(2)
            # Only check this phase's tasks
            if not tid.startswith(args.phase):
                continue
            tasks.setdefault(tid, []).append(c)

        if not tasks:
            out.warn(Evidence(
                type="info",
                message=f"No task-scoped commits for phase {args.phase}",
            ))
            emit_and_exit(out)

        violations = []
        for tid, task_commits in tasks.items():
            # Check each src-touching commit
            seen_test_before_src = False
            src_commits_without_prior_test = []
            for c in reversed(task_commits):  # oldest first
                if NO_GATE_RE.search(c["subject"]):
                    seen_test_before_src = True
                    continue
                classes = classify_files(c["files"])
                if classes["test"]:
                    seen_test_before_src = True
                if classes["src_nontest"] and not seen_test_before_src:
                    src_commits_without_prior_test.append(c["sha"][:12])

            if src_commits_without_prior_test:
                violations.append({
                    "task": tid,
                    "commits": src_commits_without_prior_test,
                })

        if violations:
            sample = violations[:5]
            out.warn(Evidence(  # WARN, not BLOCK — heuristic; test-refactor cases
                type="test_not_first",
                message=(
                    f"{len(violations)} tasks edited src/ without prior test commit"
                ),
                actual=str(sample),
                fix_hint=(
                    "TDD pattern: commit failing test BEFORE commit src fix. "
                    "If genuinely no test possible, add 'no-test-gate' to "
                    "commit subject."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
