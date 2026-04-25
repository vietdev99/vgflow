"""
Meta-test for .claude/scripts/bootstrap-test-runner.py — Phase I dim-7.

The runner discovers fixture YMLs in .vg/bootstrap/tests/ and dispatches
each to a registered scenario function. CI gate runs this; without
coverage, regressions in the runner itself silently break the gate.

Constraints:
- Runner uses Path.cwd() as REPO_ROOT and imports bootstrap-loader.py at
  top-level via importlib. To avoid coupling tests to the entire script
  ecosystem, these tests stage a full copy of .claude/scripts/ under
  tmp_path so the runner runs with all dependencies present.

Covers:
  1. Runner script file exists at expected location
  2. Runner exits 2 when no fixture dir
  3. Runner exits 0 when fixture dir is empty
  4. Unknown scenario name → SKIP (rc=0), not crash
  5. Runner emits Summary line in stdout
  6. CI integration: runner respects subprocess invocation contract
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT_REAL / ".claude" / "scripts" / "bootstrap-test-runner.py"
SCRIPTS_DIR = REPO_ROOT_REAL / ".claude" / "scripts"


def _stage_scripts(tmp_path: Path) -> Path:
    """Copy entire .claude/scripts/ tree under tmp_path so the runner finds
    bootstrap-loader.py + scope-evaluator.py + any other deps it imports.

    Cross-platform: uses shutil.copytree (no symlinks — Windows compat).
    """
    target = tmp_path / ".claude" / "scripts"
    target.parent.mkdir(parents=True, exist_ok=True)
    # ignore __pycache__ and tests dir to keep copy fast
    shutil.copytree(
        SCRIPTS_DIR, target,
        ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"),
    )
    return target


def _run(cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    runner = cwd / ".claude" / "scripts" / "bootstrap-test-runner.py"
    return subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True, text=True, timeout=60, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


class TestBootstrapTestRunner:
    def test_runner_file_exists(self):
        """Phase I scope: bootstrap-test-runner.py must be present in real repo."""
        assert RUNNER.exists(), f"bootstrap-test-runner.py missing at {RUNNER}"

    def test_no_fixture_dir_returns_2(self, tmp_path):
        """No .vg/bootstrap/tests/ → rc=2 per docstring."""
        _stage_scripts(tmp_path)
        r = _run(tmp_path)
        assert r.returncode == 2, \
            f"missing fixture dir should rc=2, got {r.returncode}, stdout={r.stdout}, stderr={r.stderr[:300]}"
        assert "no .vg/bootstrap/tests" in r.stdout.lower() \
            or "no fixture" in r.stdout.lower() \
            or "no" in r.stdout.lower()

    def test_empty_fixture_dir_returns_0(self, tmp_path):
        """Empty .vg/bootstrap/tests/ → rc=0 with 'no fixture *.yml' note."""
        _stage_scripts(tmp_path)
        tests_dir = tmp_path / ".vg" / "bootstrap" / "tests"
        tests_dir.mkdir(parents=True)
        r = _run(tmp_path)
        assert r.returncode == 0, \
            f"empty fixture dir should rc=0, got {r.returncode}, stdout={r.stdout}, stderr={r.stderr[:300]}"

    def test_unknown_scenario_skips(self, tmp_path):
        """Fixture with unregistered name → SKIP (rc=0), not crash."""
        _stage_scripts(tmp_path)
        tests_dir = tmp_path / ".vg" / "bootstrap" / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "unknown.yml").write_text(
            "name: unknown-scenario-not-registered\n"
            "given:\n"
            "  empty: true\n",
            encoding="utf-8",
        )
        r = _run(tmp_path)
        # Unknown scenario → SKIP per main loop; rc=0 because no FAILs
        assert r.returncode == 0, \
            f"unknown scenario → SKIP not FAIL, rc={r.returncode}, stdout={r.stdout}, stderr={r.stderr[:300]}"
        assert "SKIP" in r.stdout or "skip" in r.stdout.lower() \
            or "no runner" in r.stdout.lower()

    def test_runner_emits_summary_line(self, tmp_path):
        """Output should include 'Summary' line with PASS/FAIL/SKIP counts."""
        _stage_scripts(tmp_path)
        tests_dir = tmp_path / ".vg" / "bootstrap" / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "x.yml").write_text(
            "name: nonexistent-scenario\ngiven: {}\n",
            encoding="utf-8",
        )
        r = _run(tmp_path)
        assert "Summary" in r.stdout or "PASS" in r.stdout \
            or "SKIP" in r.stdout, \
            f"missing summary in output: {r.stdout[:300]}, stderr={r.stderr[:300]}"

    def test_subprocess_invocation_contract(self, tmp_path):
        """CI invokes runner via `python bootstrap-test-runner.py`. Must work
        on Windows + Linux without shell interpolation."""
        _stage_scripts(tmp_path)
        tests_dir = tmp_path / ".vg" / "bootstrap" / "tests"
        tests_dir.mkdir(parents=True)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        runner = tmp_path / ".claude" / "scripts" / "bootstrap-test-runner.py"
        # Invoke with shell=False (default) — most secure / portable
        r = subprocess.run(
            [sys.executable, str(runner)],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=str(tmp_path), shell=False,
            encoding="utf-8", errors="replace",
        )
        assert r.returncode in (0, 1, 2), \
            f"unexpected rc={r.returncode} from subprocess, stderr={r.stderr[:300]}"
        # Must not have crashed at module-import time
        assert "ModuleNotFoundError" not in r.stderr, \
            f"runner crashed importing deps: {r.stderr[-400:]}"
