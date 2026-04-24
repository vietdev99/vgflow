"""
Tests for verify-review-loop-evidence.py — Phase R of v2.5.2.

Validates behavioral check: consecutive review iterations must show source
file deltas (via git) OR explicit `resolution: "no_fix_needed"`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-review-loop-evidence.py"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd),
        encoding="utf-8", errors="replace", env=env,
    )


def _setup_mini_repo(tmp_path: Path) -> Path:
    _git("init", "--initial-branch=main", cwd=tmp_path)
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "a.ts").write_text("export const x = 1\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "initial", cwd=tmp_path)
    return tmp_path


def _make_commit(tmp_path: Path, path: str, content: str, msg: str) -> str:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git("add", path, cwd=tmp_path)
    _git("commit", "-m", msg, cwd=tmp_path)
    result = _git("rev-parse", "HEAD", cwd=tmp_path)
    return result.stdout.strip()


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, cwd=str(cwd), env=env,
        encoding="utf-8", errors="replace",
    )


def _write_iter(phase_dir: Path, n: int, commit: str,
                resolution: str | None = None) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    data = {"iter_number": n, "commit_sha": commit}
    if resolution:
        data["resolution"] = resolution
    (phase_dir / f"review-iter-{n:02d}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


class TestReviewLoopEvidence:
    def test_iter_with_source_delta_passes(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "apps/a.ts", "export const x = 2\n", "iter1 fix")
        c2 = _make_commit(repo, "apps/a.ts", "export const x = 3\n", "iter2 fix")

        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)
        _write_iter(phase_dir, 2, c2)

        r = _run(
            ["--phase-dir", ".vg/phases/test", "--quiet"],
            cwd=repo,
        )
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_empty_iter_fails(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "apps/b.ts", "x\n", "iter1 fix")
        # Second iter has same commit as first (no progress)
        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)
        _write_iter(phase_dir, 2, c1)

        r = _run(
            ["--phase-dir", ".vg/phases/test"],
            cwd=repo,
        )
        assert r.returncode == 1
        assert "empty" in r.stdout.lower()

    def test_explicit_no_fix_needed_passes(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "apps/c.ts", "x\n", "iter1")
        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)
        _write_iter(phase_dir, 2, c1, resolution="no_fix_needed")

        r = _run(
            ["--phase-dir", ".vg/phases/test", "--quiet"],
            cwd=repo,
        )
        assert r.returncode == 0

    def test_diff_outside_relevant_paths_counts_as_empty(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "docs/readme.md", "doc1\n", "iter1 docs")
        c2 = _make_commit(repo, "docs/readme.md", "doc2\n", "iter2 docs")
        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)
        _write_iter(phase_dir, 2, c2)

        # docs/ not in require-diff-paths, so empty iteration
        r = _run(
            ["--phase-dir", ".vg/phases/test",
             "--require-diff-paths", "apps/**"],
            cwd=repo,
        )
        assert r.returncode == 1

    def test_single_iter_benign_pass(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "apps/d.ts", "x\n", "iter1")
        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)

        r = _run(
            ["--phase-dir", ".vg/phases/test", "--quiet"],
            cwd=repo,
        )
        assert r.returncode == 0

    def test_no_iter_files_benign_pass(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        phase_dir = repo / ".vg" / "phases" / "empty"
        phase_dir.mkdir(parents=True)
        r = _run(
            ["--phase-dir", ".vg/phases/empty", "--quiet"],
            cwd=repo,
        )
        assert r.returncode == 0

    def test_missing_phase_dir_exits_2(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        r = _run(
            ["--phase-dir", ".vg/phases/nonexistent"],
            cwd=repo,
        )
        assert r.returncode == 2

    def test_json_output(self, tmp_path):
        repo = _setup_mini_repo(tmp_path)
        c1 = _make_commit(repo, "apps/e.ts", "x\n", "iter1")
        c2 = _make_commit(repo, "apps/e.ts", "y\n", "iter2")
        phase_dir = repo / ".vg" / "phases" / "test"
        _write_iter(phase_dir, 1, c1)
        _write_iter(phase_dir, 2, c2)
        r = _run(
            ["--phase-dir", ".vg/phases/test", "--json"],
            cwd=repo,
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["pairs_checked"] == 1
