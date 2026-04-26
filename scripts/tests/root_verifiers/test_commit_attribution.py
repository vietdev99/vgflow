"""
Tests for verify-commit-attribution.py — root verifier (.claude/scripts/).

Post-wave check: each commit only touches its own task's files.
Catches parallel-executor index-bleed where one agent's git add
lands in another's commit.

NOTE: Root verifier uses plain text + rc=0/1/2 — no JSON output, no
top-level verdict field. Schema gap inherited from pre-_common era.
Documented as discovery; test asserts via rc + text-pattern.

Covers:
  - Required args missing → rc=2 (argparse error)
  - phase-dir not found → rc=1
  - wave-tag not found in git → rc=1
  - No PLAN tasks parseable → rc=0 (warn, can't verify)
  - Single commit, single task, clean attribution → rc=0
  - Cross-attribution: commit X contains task Y's files → rc=2
  - Orchestrator commit (task 0) skipped from classification
  - --strict flag recognized
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "verify-commit-attribution.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _init_repo(tmp_path: Path) -> None:
    _git(["init", "-q", "-b", "main"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    _git(["config", "core.autocrlf", "false"], tmp_path)
    # Initial commit
    (tmp_path / "README.md").write_text("seed", encoding="utf-8")
    _git(["add", "."], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    _git(["tag", "wave-0-start"], tmp_path)


def _write_plan(phase_dir: Path, tasks: list[tuple[int, str, list[str]]]) -> None:
    """tasks: list of (task_num, file_path, also_edits)."""
    body = ["# PLAN\n"]
    for num, fp, also in tasks:
        body.append(f"### Task {num}\n")
        body.append(f"<file-path>{fp}</file-path>\n")
        if also:
            body.append(f"<also-edits>{', '.join(also)}</also-edits>\n")
        body.append("")
    (phase_dir / "PLAN.md").write_text("\n".join(body), encoding="utf-8")


def _commit_file(tmp_path: Path, rel_path: str, content: str,
                 phase: str, task: int, ctype: str = "feat") -> str:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(["add", rel_path], tmp_path)
    msg = f"{ctype}({phase}-{task:02d}): test commit\n"
    _git(["commit", "-q", "-m", msg], tmp_path)
    sha = _git(["rev-parse", "HEAD"], tmp_path).stdout.strip()
    return sha


class TestCommitAttribution:
    def test_required_args_missing(self, tmp_path):
        r = _run([], tmp_path)
        assert r.returncode == 2

    def test_phase_dir_not_found(self, tmp_path):
        _init_repo(tmp_path)
        r = _run([
            "--phase-dir", str(tmp_path / "nonexistent"),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 1
        assert "phase-dir not found" in r.stderr

    def test_wave_tag_not_found(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "missing-tag",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 1
        assert "wave-tag not found" in r.stderr

    def test_no_tasks_parseable_passes(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        # No PLAN*.md / no .wave-tasks/
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 0
        assert "no tasks parsed" in r.stderr

    def test_clean_attribution_passes(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        _write_plan(phase_dir, [
            (1, "apps/api/src/foo.ts", []),
            (2, "apps/api/src/bar.ts", []),
        ])
        # Each commit touches only its own task file
        _commit_file(tmp_path, "apps/api/src/foo.ts", "// task 1", "07", 1)
        _commit_file(tmp_path, "apps/api/src/bar.ts", "// task 2", "07", 2)
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 0, \
            f"clean → rc=0, got {r.returncode}, stdout={r.stdout[:300]}, stderr={r.stderr[:300]}"

    def test_cross_attribution_blocks(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        _write_plan(phase_dir, [
            (1, "apps/api/src/foo.ts", []),
            (2, "apps/web/src/bar.ts", []),
        ])
        # Commit for task 1 ALSO contains task 2's file
        (tmp_path / "apps/api/src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "apps/web/src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "apps/api/src/foo.ts").write_text("// 1", encoding="utf-8")
        (tmp_path / "apps/web/src/bar.ts").write_text("// 2 leaked", encoding="utf-8")
        _git(["add", "."], tmp_path)
        _git(["commit", "-q", "-m", "feat(07-01): cross-attribution"], tmp_path)
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 2, \
            f"cross-attribution → rc=2, got {r.returncode}, stdout={r.stdout[:400]}"
        assert "CROSS-ATTRIBUTION" in r.stdout or "cross-attribution" in r.stdout.lower()

    def test_orchestrator_task_zero_skipped(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        _write_plan(phase_dir, [(1, "apps/api/src/foo.ts", [])])
        # Task 0 commit — orchestrator bookkeeping
        _commit_file(tmp_path, "scripts/util.sh", "#!/bin/sh", "07", 0,
                     ctype="chore")
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
        ], tmp_path)
        assert r.returncode == 0
        assert "orchestrator commit (skipped)" in r.stdout

    def test_strict_flag_recognized(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-test"
        phase_dir.mkdir(parents=True)
        _write_plan(phase_dir, [(1, "apps/api/src/foo.ts", [])])
        _commit_file(tmp_path, "apps/api/src/foo.ts", "// 1", "07", 1)
        r = _run([
            "--phase-dir", str(phase_dir),
            "--wave-tag", "wave-0-start",
            "--wave-number", "1",
            "--strict",
        ], tmp_path)
        assert r.returncode in (0, 2)
        assert "unrecognized arguments" not in r.stderr.lower()
