"""Tests for scripts/runtime/fixture_cache.py — RFC v9 PR-A3."""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime import fixture_cache as fc  # noqa: E402


def test_recipe_hash_stable():
    h1 = fc.recipe_hash("schema_version: 1.0\n")
    h2 = fc.recipe_hash("schema_version: 1.0\n")
    h3 = fc.recipe_hash("schema_version: 1.1\n")
    assert h1 == h2
    assert h1 != h3
    assert h1.startswith("sha256:")


def test_load_returns_empty_when_missing(tmp_path):
    data = fc.load(tmp_path)
    assert data["entries"] == {}
    assert data["schema_version"] == fc.SCHEMA_VERSION


def test_save_then_load_roundtrip(tmp_path):
    fc.save(tmp_path, {"schema_version": "1.0", "entries": {"G-1": {"foo": "bar"}}})
    data = fc.load(tmp_path)
    assert data["entries"]["G-1"] == {"foo": "bar"}


def test_acquire_lease_destructive_first_session_succeeds(tmp_path):
    lease = fc.acquire_lease(
        tmp_path, "G-10",
        owner_session="sess-A",
        consume_semantics="destructive",
        ttl_seconds=60,
    )
    assert lease["owner_session"] == "sess-A"
    assert lease["consume_semantics"] == "destructive"


def test_acquire_lease_destructive_second_session_fails(tmp_path):
    fc.acquire_lease(tmp_path, "G-10", owner_session="sess-A",
                       consume_semantics="destructive", ttl_seconds=60)
    with pytest.raises(fc.LeaseError, match="sess-A"):
        fc.acquire_lease(tmp_path, "G-10", owner_session="sess-B",
                           consume_semantics="destructive", ttl_seconds=60)


def test_acquire_lease_read_only_shared(tmp_path):
    fc.acquire_lease(tmp_path, "G-10", owner_session="sess-A",
                       consume_semantics="read_only", ttl_seconds=60)
    # Second read_only co-tenancy: should NOT raise
    fc.acquire_lease(tmp_path, "G-10", owner_session="sess-B",
                       consume_semantics="read_only", ttl_seconds=60)


def test_acquire_lease_read_only_blocks_destructive(tmp_path):
    fc.acquire_lease(tmp_path, "G-10", owner_session="sess-A",
                       consume_semantics="read_only", ttl_seconds=60)
    with pytest.raises(fc.LeaseError):
        fc.acquire_lease(tmp_path, "G-10", owner_session="sess-B",
                           consume_semantics="destructive", ttl_seconds=60)


def test_expired_lease_is_reapable(tmp_path):
    # Manually plant an expired lease
    expired_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(timespec="seconds")
    fc.save(tmp_path, {"schema_version": "1.0", "entries": {"G-1": {
        "lease": {
            "owner_session": "stale-sess",
            "expires_at": expired_iso,
            "consume_semantics": "destructive",
        },
    }}})
    # New session should take over
    lease = fc.acquire_lease(tmp_path, "G-1", owner_session="fresh",
                                consume_semantics="destructive", ttl_seconds=60)
    assert lease["owner_session"] == "fresh"


def test_release_lease_only_by_owner(tmp_path):
    fc.acquire_lease(tmp_path, "G-1", owner_session="sess-A",
                       consume_semantics="destructive", ttl_seconds=60)
    assert fc.release_lease(tmp_path, "G-1", "sess-B") is False  # foreign
    assert fc.release_lease(tmp_path, "G-1", "sess-A") is True
    # After release: another session can take it
    fc.acquire_lease(tmp_path, "G-1", owner_session="sess-C",
                       consume_semantics="destructive", ttl_seconds=60)


def test_recipe_hash_drift_invalidates_captured(tmp_path):
    # Acquire lease + write captured under hash-A
    fc.acquire_lease(tmp_path, "G-1", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60,
                       recipe_hash_value="sha256:hash-A")
    fc.write_captured(tmp_path, "G-1", {"pid": "p1"}, owner_session="s",
                        recipe_hash_value="sha256:hash-A")
    assert fc.get_captured(tmp_path, "G-1") == {"pid": "p1"}
    # Release + re-acquire with new hash → captured dropped
    fc.release_lease(tmp_path, "G-1", "s")
    fc.acquire_lease(tmp_path, "G-1", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60,
                       recipe_hash_value="sha256:hash-B")
    assert fc.get_captured(tmp_path, "G-1") is None


def test_write_captured_requires_lease(tmp_path):
    with pytest.raises(fc.LeaseError, match="not owned"):
        fc.write_captured(tmp_path, "G-1", {"x": 1}, owner_session="s")


def test_find_orphans(tmp_path):
    fc.acquire_lease(tmp_path, "G-1", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60)
    fc.acquire_lease(tmp_path, "G-orphan", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60)
    orphans = fc.find_orphans(tmp_path, known_goals={"G-1", "G-2"})
    assert orphans == ["G-orphan"]


def test_reap_orphans_removes_them(tmp_path):
    fc.acquire_lease(tmp_path, "G-keep", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60)
    fc.acquire_lease(tmp_path, "G-drop", owner_session="s",
                       consume_semantics="destructive", ttl_seconds=60)
    n = fc.reap_orphans(tmp_path, known_goals={"G-keep"})
    assert n == 1
    data = fc.load(tmp_path)
    assert "G-drop" not in data["entries"]
    assert "G-keep" in data["entries"]


def test_reap_expired_leases(tmp_path):
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
    fresh = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
    fc.save(tmp_path, {"schema_version": "1.0", "entries": {
        "G-old": {"lease": {"owner_session": "x", "expires_at": expired,
                            "consume_semantics": "destructive"}},
        "G-new": {"lease": {"owner_session": "x", "expires_at": fresh,
                            "consume_semantics": "destructive"}},
    }})
    n = fc.reap_expired_leases(tmp_path)
    assert n == 1
    data = fc.load(tmp_path)
    assert "lease" not in data["entries"]["G-old"]
    assert data["entries"]["G-new"]["lease"]["owner_session"] == "x"


def test_concurrent_acquire_destructive_serializes(tmp_path):
    """Many threads racing on the same destructive goal → exactly one wins."""
    winners: list[str] = []
    losers: list[str] = []
    barrier = threading.Barrier(8)

    def race(name: str) -> None:
        barrier.wait()
        try:
            fc.acquire_lease(tmp_path, "G-race", owner_session=name,
                               consume_semantics="destructive", ttl_seconds=60)
            winners.append(name)
        except fc.LeaseError:
            losers.append(name)

    threads = [threading.Thread(target=race, args=(f"sess-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(winners) == 1, f"Expected 1 winner, got {len(winners)}: {winners}"
    assert len(losers) == 7
    assert len(winners) + len(losers) == 8


def test_lease_extension_same_session_succeeds(tmp_path):
    fc.acquire_lease(tmp_path, "G-1", owner_session="sess",
                       consume_semantics="destructive", ttl_seconds=60)
    # Same session re-acquires (renewal)
    lease2 = fc.acquire_lease(tmp_path, "G-1", owner_session="sess",
                                 consume_semantics="destructive", ttl_seconds=120)
    assert lease2["owner_session"] == "sess"
