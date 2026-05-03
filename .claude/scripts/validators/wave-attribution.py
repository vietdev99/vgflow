#!/usr/bin/env python3
"""
Validator: wave-attribution.py

Purpose: verify build wave commits match declared tasks. Phase 13 failure:
executor reported "done wave 2" but 0 commits actually landed. This
validator reads evidence_json from orchestrator events + git log, cross-
checks: every declared `tasks[*].status=completed` must have a commit SHA
that exists in git AND commit message cites the task ID.

Usage: wave-attribution.py --phase <N> --wave <wave_n> [--evidence-file FILE]
       wave-attribution.py --phase <N> --wave <wave_n> < evidence.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

COMMIT_PATTERN_RE = re.compile(
    r"^(feat|fix|refactor|test|chore|docs)\([\d.]+-\d+\):"
)


def git_commit_exists(sha: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", sha],
        capture_output=True, timeout=5,
    )
    return r.returncode == 0


def git_commit_message(sha: str) -> str:
    r = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        capture_output=True, text=True, timeout=5,
    )
    return r.stdout if r.returncode == 0 else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--wave", required=True, type=int)
    ap.add_argument("--evidence-file", default=None,
                    help="path to evidence.json; omit to read stdin")
    args = ap.parse_args()

    out = Output(validator="wave-attribution")
    with timer(out):
        # Load evidence
        if args.evidence_file:
            raw = Path(args.evidence_file).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        try:
            evidence_data = json.loads(raw)
        except json.JSONDecodeError as e:
            out.add(Evidence(
                type="schema_violation",
                message=f"evidence payload is not valid JSON: {e}",
            ))
            emit_and_exit(out)

        if evidence_data.get("wave") != args.wave:
            out.add(Evidence(
                type="schema_violation",
                message=f"evidence.wave ({evidence_data.get('wave')}) "
                        f"!= --wave ({args.wave})",
            ))
            emit_and_exit(out)

        tasks = evidence_data.get("tasks", [])
        commits = evidence_data.get("commits", [])
        commit_shas = {c.get("sha") for c in commits}

        completed_tasks = [t for t in tasks if t.get("status") == "completed"]
        if not completed_tasks:
            out.add(Evidence(
                type="count_below_threshold",
                message="Wave claimed complete but 0 tasks with status=completed",
            ))
            emit_and_exit(out)

        # Every completed task must have commit_sha AND commit must exist
        for t in completed_tasks:
            tid = t.get("id", "?")
            csha = t.get("commit_sha")
            if not csha:
                out.add(Evidence(
                    type="commit_missing",
                    message=f"task {tid} claims completed but commit_sha is null",
                    fix_hint=f"Ensure wave executor committed work for {tid} before emitting evidence.",
                ))
                continue
            if not git_commit_exists(csha):
                out.add(Evidence(
                    type="commit_missing",
                    message=f"task {tid} commit_sha {csha} not in git log",
                    actual=csha,
                ))
                continue
            # Check commit message pattern + mentions task id
            msg = git_commit_message(csha)
            first_line = msg.splitlines()[0] if msg else ""
            if not COMMIT_PATTERN_RE.match(first_line):
                out.warn(Evidence(
                    type="commit_mismatch",
                    message=f"task {tid} commit {csha} message does not match type(N-NN): pattern",
                    actual=first_line,
                ))
            if tid.split("-")[-1] not in first_line:
                out.warn(Evidence(
                    type="commit_mismatch",
                    message=f"task {tid} commit {csha} header doesn't reference task number",
                    actual=first_line,
                ))

        # Cross-check: every commit should map to a declared task
        declared_task_ids = {t.get("id") for t in tasks}
        orphan_commits = []
        for c in commits:
            sha = c.get("sha")
            msg = git_commit_message(sha) if sha else ""
            first_line = msg.splitlines()[0] if msg else ""
            m = re.match(r"^(feat|fix|refactor|test|chore|docs)\(([\d.]+-\d+)\):",
                         first_line)
            if m and m.group(2) not in declared_task_ids:
                orphan_commits.append((sha, m.group(2)))
        if orphan_commits:
            out.warn(Evidence(
                type="commit_mismatch",
                message=f"{len(orphan_commits)} commit(s) reference tasks not in declared list",
                actual=str(orphan_commits[:3]),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
