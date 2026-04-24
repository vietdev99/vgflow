"""
Tests for vg-orchestrator/lock.py + verify-clean-failure-state.py
— Phase O of v2.5.2 hardening.

Covers lock.py:
  - acquire_repo_lock writes lockfile and returns token
  - second acquire while live holder → returns None (blocked)
  - release_repo_lock clears lockfile when token matches
  - release with wrong token → False, lockfile untouched
  - stale lock (ttl elapsed + dead pid) auto-broken on next acquire
  - get_active_lock returns None for stale locks
  - force_release clears any lockfile
  - Windows-compatible path handling (pathlib)

Covers verify-clean-failure-state.py:
  - clean state → exit 0
  - stale lock for run → exit 1
  - inflight leftover files → exit 1
  - untracked manifest entry → exit 1
  - check-current with no current-run.json → exit 0
  - JSON output parseable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCH_DIR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-clean-failure-state.py"


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """Give each test its own fake repo root so lockfile tests don't collide."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    # Re-import lock so it picks up the new VG_REPO_ROOT
    sys.path.insert(0, str(ORCH_DIR))
    if "lock" in sys.modules:
        del sys.modules["lock"]
    import lock as lock_mod
    # Patch its REPO_ROOT/LOCKFILE to match env (module read at import time)
    lock_mod.REPO_ROOT = tmp_path
    lock_mod.LOCKFILE = tmp_path / ".vg" / ".repo-lock.json"
    yield tmp_path, lock_mod


class TestAcquireRelease:
    def test_acquire_creates_lockfile(self, isolated_repo):
        root, lock = isolated_repo
        token = lock.acquire_repo_lock("vg:build", "7.14", ttl_seconds=60)
        assert token, "acquire should return a token"
        lockfile = root / ".vg" / ".repo-lock.json"
        assert lockfile.exists()
        data = json.loads(lockfile.read_text(encoding="utf-8"))
        assert data["lock_token"] == token
        assert data["command"] == "vg:build"
        assert data["phase"] == "7.14"
        assert data["pid"] == os.getpid()

    def test_second_acquire_blocked(self, isolated_repo):
        _, lock = isolated_repo
        t1 = lock.acquire_repo_lock("vg:build", "7.14")
        assert t1
        t2 = lock.acquire_repo_lock("vg:review", "7.14")
        assert t2 is None, "second acquire should fail while live holder"

    def test_release_with_matching_token(self, isolated_repo):
        root, lock = isolated_repo
        token = lock.acquire_repo_lock("vg:build", "7.14")
        assert lock.release_repo_lock(token) is True
        assert not (root / ".vg" / ".repo-lock.json").exists()

    def test_release_with_wrong_token(self, isolated_repo):
        root, lock = isolated_repo
        token = lock.acquire_repo_lock("vg:build", "7.14")
        assert lock.release_repo_lock("not-the-token") is False
        # Lockfile still present
        assert (root / ".vg" / ".repo-lock.json").exists()
        # Real owner can still release
        assert lock.release_repo_lock(token) is True

    def test_acquire_after_release_works(self, isolated_repo):
        _, lock = isolated_repo
        t1 = lock.acquire_repo_lock("vg:build", "7.14")
        assert lock.release_repo_lock(t1)
        t2 = lock.acquire_repo_lock("vg:review", "7.14")
        assert t2 and t2 != t1


class TestStale:
    def test_stale_lock_auto_broken(self, isolated_repo):
        root, lock = isolated_repo
        # Manually write a stale lockfile (dead pid + expired ttl)
        import time as _t
        lockfile = root / ".vg" / ".repo-lock.json"
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        lockfile.write_text(json.dumps({
            "lock_token": "old-token",
            "command": "vg:build",
            "phase": "7.13",
            # 99999: an impossibly-large pid that definitely isn't ours
            "pid": 99999999,
            "hostname": "ghost",
            "acquired_at": _t.time() - 100000,  # ancient
            "ttl_seconds": 60,
        }), encoding="utf-8")
        # New acquire should succeed (stale broken)
        new_token = lock.acquire_repo_lock("vg:review", "7.14")
        assert new_token and new_token != "old-token"

    def test_get_active_lock_returns_none_when_stale(self, isolated_repo):
        root, lock = isolated_repo
        import time as _t
        lockfile = root / ".vg" / ".repo-lock.json"
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        lockfile.write_text(json.dumps({
            "lock_token": "stale",
            "command": "vg:x",
            "phase": "x",
            "pid": 99999999,
            "hostname": "h",
            "acquired_at": _t.time() - 100000,
            "ttl_seconds": 60,
        }), encoding="utf-8")
        assert lock.get_active_lock() is None

    def test_get_active_lock_returns_data_when_live(self, isolated_repo):
        _, lock = isolated_repo
        token = lock.acquire_repo_lock("vg:build", "7.14", ttl_seconds=600)
        active = lock.get_active_lock()
        assert active is not None
        assert active["lock_token"] == token

    def test_force_release(self, isolated_repo):
        _, lock = isolated_repo
        lock.acquire_repo_lock("vg:build", "7.14")
        assert lock.force_release() is True
        assert lock.get_active_lock() is None
        # Idempotent
        assert lock.force_release() is False


# ─── verify-clean-failure-state.py ────────────────────────────────

def _run_validator(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd), env=env, encoding="utf-8", errors="replace",
    )


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=False)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=str(root), check=False,
    )


class TestCleanFailureState:
    def test_clean_state_exit_zero(self, tmp_path):
        _init_git(tmp_path)
        run_id = "clean-run-abc"
        r = _run_validator(["--run-id", run_id, "--json"], tmp_path)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] is True
        assert out["finding_count"] == 0

    def test_stale_lock_detected(self, tmp_path):
        _init_git(tmp_path)
        run_id = "dirty-run-xyz"
        lockfile = tmp_path / ".vg" / ".repo-lock.json"
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        lockfile.write_text(json.dumps({
            "lock_token": run_id, "run_id": run_id,
            "command": "vg:build", "phase": "7",
            "pid": 1, "hostname": "h", "acquired_at": 0, "ttl_seconds": 60,
        }), encoding="utf-8")
        r = _run_validator(["--run-id", run_id, "--json"], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert out["ok"] is False
        kinds = {f["kind"] for f in out["findings"]}
        assert "STALE_LOCK_THIS_RUN" in kinds

    def test_inflight_leftover_detected(self, tmp_path):
        _init_git(tmp_path)
        run_id = "inflight-run"
        inflight = tmp_path / ".vg" / "runs" / run_id / "tmp"
        inflight.mkdir(parents=True, exist_ok=True)
        (inflight / "half-written.txt").write_text("oops", encoding="utf-8")
        r = _run_validator(["--run-id", run_id, "--json"], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        kinds = {f["kind"] for f in out["findings"]}
        assert "INFLIGHT_LEFTOVER" in kinds

    def test_check_current_no_run(self, tmp_path):
        _init_git(tmp_path)
        r = _run_validator(["--check-current"], tmp_path)
        assert r.returncode == 0
        assert "nothing to verify" in r.stdout or "no current-run" in r.stdout

    def test_manifest_untracked_orphan_detected(self, tmp_path):
        _init_git(tmp_path)
        run_id = "orphan-run"
        manifest = tmp_path / ".vg" / "runs" / run_id / "evidence-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        artifact = tmp_path / "apps" / "api" / "half.ts"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("export const x = 1;\n", encoding="utf-8")
        manifest.write_text(json.dumps({
            "run_id": run_id,
            "entries": [
                {"path": "apps/api/half.ts", "sha256": "abc"},
            ],
        }), encoding="utf-8")
        r = _run_validator(["--run-id", run_id, "--json"], tmp_path)
        out = json.loads(r.stdout)
        kinds = {f["kind"] for f in out["findings"]}
        assert "ORPHAN_UNTRACKED" in kinds
        assert r.returncode == 1

    def test_manifest_entry_in_dot_vg_is_ok(self, tmp_path):
        _init_git(tmp_path)
        run_id = "vg-entry-run"
        manifest = tmp_path / ".vg" / "runs" / run_id / "evidence-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        artifact = tmp_path / ".vg" / "phases" / "7.14" / "PLAN.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("# plan\n", encoding="utf-8")
        manifest.write_text(json.dumps({
            "run_id": run_id,
            "entries": [
                {"path": ".vg/phases/7.14/PLAN.md", "sha256": "abc"},
            ],
        }), encoding="utf-8")
        r = _run_validator(["--run-id", run_id, "--json"], tmp_path)
        out = json.loads(r.stdout)
        assert out["ok"] is True, out
