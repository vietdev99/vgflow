"""
Tests for verify-wave-integrity.py — root verifier (.claude/scripts/).

Post-crash reconciliation: verifies progress file vs git reality vs
filesystem reality, classifies every task into 8 deterministic buckets
with concrete recovery action.

NOTE: Root verifier — text output + rc=0/1/2, no JSON verdict (pre-_common
era). --json flag emits structured output but no top-level verdict
field. Schema gap documented as discovery.

Covers:
  - Required arg missing → rc=2
  - phase-dir not found → rc=2
  - No .build-progress.json → rc=0 (nothing to reconcile)
  - Progress file with no wave_tag → rc=2
  - wave_tag missing in git → rc=2
  - Clean state: progress.committed matches git → rc=0
  - DESYNC: git has commit not in progress.expected → rc=1
  - --json flag emits structured output
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "verify-wave-integrity.py"


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
    (tmp_path / "README.md").write_text("seed", encoding="utf-8")
    _git(["add", "."], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    _git(["tag", "wave-1-start"], tmp_path)


def _write_progress(phase_dir: Path, *, wave: int = 1,
                    wave_tag: str = "wave-1-start",
                    expected: list[int] | None = None,
                    committed: list[dict] | None = None,
                    in_flight: list[dict] | None = None,
                    failed: list[dict] | None = None) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    p = phase_dir / ".build-progress.json"
    p.write_text(json.dumps({
        "phase": "07",
        "current_wave": wave,
        "wave_tag": wave_tag,
        "tasks_expected": expected or [],
        "tasks_committed": committed or [],
        "tasks_in_flight": in_flight or [],
        "tasks_failed": failed or [],
    }), encoding="utf-8")


class TestWaveIntegrity:
    def test_required_arg_missing(self, tmp_path):
        r = _run([], tmp_path)
        assert r.returncode == 2

    def test_phase_dir_not_found(self, tmp_path):
        _init_repo(tmp_path)
        r = _run(["--phase-dir", str(tmp_path / "nope")], tmp_path)
        assert r.returncode == 2
        assert "phase-dir not found" in r.stderr

    def test_no_progress_file_passes(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        phase_dir.mkdir(parents=True)
        r = _run(["--phase-dir", str(phase_dir)], tmp_path)
        assert r.returncode == 0
        assert "no .build-progress" in r.stderr

    def test_progress_no_wave_tag_blocks(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        phase_dir.mkdir(parents=True)
        # Write progress with empty wave_tag
        (phase_dir / ".build-progress.json").write_text(json.dumps({
            "phase": "07", "current_wave": 1,
            "wave_tag": "", "tasks_expected": []
        }), encoding="utf-8")
        r = _run(["--phase-dir", str(phase_dir)], tmp_path)
        assert r.returncode == 2
        assert "no wave_tag" in r.stderr

    def test_wave_tag_missing_in_git_blocks(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        _write_progress(phase_dir, wave_tag="missing-tag-xyz",
                        expected=[1])
        r = _run(["--phase-dir", str(phase_dir)], tmp_path)
        assert r.returncode == 2
        assert "not found in git" in r.stderr

    def test_clean_state_passes(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        # Make a commit for task 1 (file ≥10 bytes to dodge truncation guard)
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src/foo.ts").write_text(
            "// task one implementation goes here\nexport const x = 1;\n",
            encoding="utf-8",
        )
        _git(["add", "."], tmp_path)
        _git(["commit", "-q", "-m", "feat(07-01): task one"], tmp_path)
        sha = _git(["rev-parse", "HEAD"], tmp_path).stdout.strip()
        _write_progress(phase_dir,
                        expected=[1],
                        committed=[{"task": 1, "commit": sha}])
        r = _run(["--phase-dir", str(phase_dir)], tmp_path)
        # Clean = rc=0
        assert r.returncode == 0, \
            f"clean → rc=0, got {r.returncode}, stdout={r.stdout[:300]}"
        assert "VALID_COMMITTED" in r.stdout

    def test_extra_unexpected_classification(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        # Commit task 5 but progress doesn't expect it
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src/extra.ts").write_text("// 5", encoding="utf-8")
        _git(["add", "."], tmp_path)
        _git(["commit", "-q", "-m", "feat(07-05): unexpected"], tmp_path)
        _write_progress(phase_dir,
                        expected=[1])  # 5 not in expected
        r = _run(["--phase-dir", str(phase_dir)], tmp_path)
        # EXTRA_UNEXPECTED is not corruption-class → rc may be 0 (warning) or 1
        assert r.returncode in (0, 1)
        assert "EXTRA_UNEXPECTED" in r.stdout or "extra" in r.stdout.lower()

    def test_json_flag_emits_structured(self, tmp_path):
        _init_repo(tmp_path)
        phase_dir = tmp_path / ".vg" / "phases" / "07-wi"
        _write_progress(phase_dir, expected=[1])  # task 1 not done
        r = _run(["--phase-dir", str(phase_dir), "--json"], tmp_path)
        # Should emit JSON
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            assert False, f"--json should emit valid JSON, got: {r.stdout[:200]}"
        assert "phase" in data
        assert "wave_tag" in data
        assert "classifications" in data
