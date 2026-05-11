"""v2.82.1 Stage 6.4 — per-env deploy lock."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts"))


@pytest.fixture
def lock_mod():
    from deploy import lock  # type: ignore[import-not-found]

    return lock


def test_acquire_creates_lock_file(tmp_path, lock_mod):
    with lock_mod.deploy_lock(tmp_path, env="prod") as path:
        assert path.exists(), "lock file should be present while held"
    # Released — file should be removed.
    assert not path.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows msvcrt.locking() blocks reads by other handles; POSIX flock allows them",
)
def test_acquire_writes_holder_metadata(tmp_path, lock_mod):
    with lock_mod.deploy_lock(tmp_path, env="prod") as path:
        body = path.read_text(encoding="utf-8")
        meta = json.loads(body)
        assert meta["env"] == "prod"
        assert isinstance(meta["pid"], int)
        assert meta["started_at"].startswith("20")  # ISO


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows msvcrt.locking() blocks reads by other handles; POSIX flock allows them",
)
def test_acquire_with_holder_meta_extras(tmp_path, lock_mod):
    with lock_mod.deploy_lock(
        tmp_path, env="prod", holder_meta={"caller": "test", "phase_context": "6"}
    ) as path:
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["caller"] == "test"
        assert meta["phase_context"] == "6"


def test_lock_per_env_independence(tmp_path, lock_mod):
    """Different envs use different lock files; can hold both."""
    with lock_mod.deploy_lock(tmp_path, env="prod"):
        with lock_mod.deploy_lock(tmp_path, env="staging"):
            pass


def test_lock_normalizes_unsafe_env_chars(tmp_path, lock_mod):
    """Slashes / parent-traversal in env names sanitized in lock filename."""
    with lock_mod.deploy_lock(tmp_path, env="dev/region-1") as path:
        assert "/" not in path.name


def _deploy_lock_holder(proj, barrier, release):
    from deploy.lock import deploy_lock  # type: ignore[import-not-found]

    with deploy_lock(proj, env="prod"):
        barrier.set()
        release.wait(5.0)


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX flock semantics tested separately"
)
def test_concurrent_acquire_raises_lock_held(tmp_path, lock_mod):
    """Second acquire while first is held raises DeployLockHeld."""
    # Use multiprocessing instead of threading because flock is per-process
    # (not per-thread on Linux).
    barrier = mp.Event()
    release = mp.Event()
    proj = str(tmp_path)

    p = mp.Process(target=_deploy_lock_holder, args=(proj, barrier, release))
    p.start()
    try:
        assert barrier.wait(5.0)
        with pytest.raises(lock_mod.DeployLockHeld) as exc_info:
            with lock_mod.deploy_lock(tmp_path, env="prod"):
                pass
        assert exc_info.value.env == "prod"
        assert exc_info.value.holder.get("pid") == p.pid
    finally:
        release.set()
        p.join(timeout=5.0)


def test_lock_released_after_exception(tmp_path, lock_mod):
    """If body raises, lock still released + file removed."""
    class Boom(Exception):
        pass

    try:
        with lock_mod.deploy_lock(tmp_path, env="prod") as path:
            held = path
            raise Boom()
    except Boom:
        pass
    assert not held.exists(), "lock file must be removed after exception"
    # And next acquire works
    with lock_mod.deploy_lock(tmp_path, env="prod"):
        pass
