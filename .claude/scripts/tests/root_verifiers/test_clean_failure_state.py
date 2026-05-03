"""
Tests for verify-clean-failure-state.py — UNQUARANTINABLE.

Phase O of v2.5.2 hardening. After failed run, ensures repo is clean:
no stale lock, no .inflight/ leftovers, manifest entries either
git-tracked or rolled back.

Note: this validator uses rc 0/1/2 directly (NOT the _common Output
schema), and shells out to git. Tests mock git or use real git in
tmp_path.

Covers:
  - --check-current with no current-run.json → PASS
  - --run-id with empty run_id arg → rc=2 (config error)
  - Run-id with no manifest, no lock → PASS
  - Run-id with stale lockfile → rc=1
  - Run-id with .inflight/ leftover file → rc=1
  - Manifest with .vg/ path entries → PASS (allowed uncommitted)
  - Manifest with rollback.json marking entry → PASS
  - Unparseable manifest → rc=1 with finding
  - --json output is structured
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-clean-failure-state.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _init_git(tmp_path: Path) -> None:
    """Initialize empty git repo so git ls-tree calls don't break."""
    subprocess.run(
        ["git", "init", "-q"], cwd=str(tmp_path),
        capture_output=True, timeout=5,
    )


class TestCleanFailureState:
    def test_check_current_no_run_passes(self, tmp_path):
        _init_git(tmp_path)
        r = _run(["--check-current"], tmp_path)
        assert r.returncode == 0, f"no current-run should PASS, stdout={r.stdout}"

    def test_empty_run_id_returns_config_error(self, tmp_path):
        _init_git(tmp_path)
        # current-run.json with empty run_id
        (tmp_path / ".vg").mkdir()
        (tmp_path / ".vg" / "current-run.json").write_text(
            json.dumps({"run_id": ""}), encoding="utf-8",
        )
        r = _run(["--check-current"], tmp_path)
        assert r.returncode == 2, f"empty run_id should rc=2, got {r.returncode}"

    def test_run_id_no_artifacts_passes(self, tmp_path):
        _init_git(tmp_path)
        r = _run(["--run-id", "abc12345"], tmp_path)
        assert r.returncode == 0, f"clean state should PASS, stdout={r.stdout}"

    def test_stale_lockfile_blocks(self, tmp_path):
        _init_git(tmp_path)
        run_id = "abc12345-stale"
        (tmp_path / ".vg").mkdir(exist_ok=True)
        (tmp_path / ".vg" / ".repo-lock.json").write_text(
            json.dumps({"lock_token": run_id, "run_id": run_id}),
            encoding="utf-8",
        )
        r = _run(["--run-id", run_id], tmp_path)
        assert r.returncode == 1, f"stale lock should rc=1, got {r.returncode}"
        assert "STALE_LOCK" in r.stdout or "lockfile" in r.stdout.lower()

    def test_inflight_leftover_blocks(self, tmp_path):
        _init_git(tmp_path)
        run_id = "leftover-run"
        inflight = tmp_path / ".vg" / "runs" / run_id / ".inflight"
        inflight.mkdir(parents=True)
        (inflight / "partial.txt").write_text("incomplete write\n", encoding="utf-8")
        r = _run(["--run-id", run_id], tmp_path)
        assert r.returncode == 1, f"inflight leftover should rc=1, got {r.returncode}"
        assert "INFLIGHT" in r.stdout or "leftover" in r.stdout.lower() \
            or "tmp" in r.stdout.lower() or ".inflight" in r.stdout

    def test_manifest_vg_path_allowed(self, tmp_path):
        _init_git(tmp_path)
        run_id = "vg-paths-run"
        run_dir = tmp_path / ".vg" / "runs" / run_id
        run_dir.mkdir(parents=True)
        # Files must EXIST on disk — validator's .vg/ skip applies only when
        # the path is present (otherwise it falls through to ORPHAN_MISSING).
        summary = tmp_path / ".vg" / "phases" / "99.0" / "SUMMARY.md"
        summary.parent.mkdir(parents=True)
        summary.write_text("ok\n", encoding="utf-8")
        scratch = tmp_path / ".planning" / "scratch.md"
        scratch.parent.mkdir(parents=True)
        scratch.write_text("ok\n", encoding="utf-8")
        (run_dir / "evidence-manifest.json").write_text(
            json.dumps({"entries": [
                {"path": ".vg/phases/99.0/SUMMARY.md"},
                {"path": ".planning/scratch.md"},
            ]}), encoding="utf-8",
        )
        r = _run(["--run-id", run_id], tmp_path)
        assert r.returncode == 0, \
            f".vg/ paths should pass, stdout={r.stdout}, stderr={r.stderr}"

    def test_manifest_rollback_marker_clears(self, tmp_path):
        _init_git(tmp_path)
        run_id = "rolled-back-run"
        run_dir = tmp_path / ".vg" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "evidence-manifest.json").write_text(
            json.dumps({"entries": [
                {"path": "apps/api/foo.ts"},
            ]}), encoding="utf-8",
        )
        (run_dir / "rollback.json").write_text(
            json.dumps({"entries": [{"path": "apps/api/foo.ts"}]}),
            encoding="utf-8",
        )
        r = _run(["--run-id", run_id], tmp_path)
        assert r.returncode == 0, \
            f"rolled-back path should clear, stdout={r.stdout}"

    def test_unparseable_manifest_returns_finding(self, tmp_path):
        _init_git(tmp_path)
        run_id = "bad-manifest"
        run_dir = tmp_path / ".vg" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "evidence-manifest.json").write_text("{not_json", encoding="utf-8")
        r = _run(["--run-id", run_id], tmp_path)
        assert r.returncode == 1, f"bad manifest → rc=1, got {r.returncode}"
        assert "MANIFEST" in r.stdout or "UNPARSEABLE" in r.stdout \
            or "json" in r.stdout.lower()

    def test_json_output_structured(self, tmp_path):
        _init_git(tmp_path)
        r = _run(["--run-id", "any-id", "--json"], tmp_path)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"--json should be parseable: {r.stdout[:200]}")
        assert "ok" in data
        assert "run_id" in data
        assert "findings" in data
