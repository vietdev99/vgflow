"""FIXTURES-CACHE.json — RFC v9 D2/D13 cross-run state.

What lives in the cache:
- Captured values from the last successful recipe execution (so /vg:test
  codegen can reuse `pending_id` etc. without re-running mutations).
- Lease metadata (RFC v9 D13 concurrency): owner_session, expires_at,
  recipe_hash. Two parallel /vg:review sessions cannot both consume the
  same destructive fixture row.
- Cache key = sha256 of recipe text. Recipe edit invalidates cache.

File layout:
    .vg/phases/{phase}/FIXTURES-CACHE.json
    {
      "schema_version": "1.0",
      "entries": {
        "G-10": {
          "recipe_hash": "sha256:abc...",
          "captured": { "pending_id": "...", "amount": 0.01 },
          "lease": {
            "owner_session": "vg-3.2-review-12345",
            "expires_at": "2026-05-02T10:30:00Z",
            "consume_semantics": "destructive"
          },
          "executed_at": "2026-05-02T10:00:00Z"
        }
      }
    }

Concurrency model: file-locked write via fcntl.LOCK_EX (POSIX). Atomic
rename on save. Stale leases (expired) are reapable by any session — TTL
acts as a lease watchdog so a crashed session can't hold a fixture forever.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = "1.0"


class CacheError(Exception):
    """Cache I/O or state error."""


class LeaseError(Exception):
    """Lease conflict (someone else owns destructive fixture)."""


def recipe_hash(recipe_text: str) -> str:
    return "sha256:" + hashlib.sha256(recipe_text.encode("utf-8")).hexdigest()


def cache_path(phase_dir: Path) -> Path:
    return phase_dir / "FIXTURES-CACHE.json"


@contextmanager
def _exclusive_lock(path: Path, timeout_s: float = 5.0) -> Iterator[None]:
    """fcntl-based exclusive lock on a sidecar .lock file.

    POSIX-only. Times out after `timeout_s` to avoid hangs from crashed
    sessions that left the lock acquired (rare — fcntl release on process
    exit, but defensive).
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.time() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.time() > deadline:
                    raise CacheError(
                        f"Could not acquire {lock_path} within {timeout_s}s"
                    ) from e
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def load(phase_dir: Path) -> dict[str, Any]:
    path = cache_path(phase_dir)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CacheError(f"FIXTURES-CACHE.json corrupt at {path}: {e}") from e


def save(phase_dir: Path, data: dict[str, Any]) -> None:
    path = cache_path(phase_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    tmp.replace(path)


def acquire_lease(
    phase_dir: Path,
    goal: str,
    *,
    owner_session: str,
    consume_semantics: str,
    ttl_seconds: int = 1800,
    recipe_hash_value: str | None = None,
) -> dict[str, Any]:
    """Atomically claim a fixture row.

    Rules:
    - read_only: shared lease — any session can co-hold.
    - destructive: exclusive — fail if another session's lease is unexpired.
    - Expired leases are reapable (any session can take over).
    - Same session re-acquiring its own lease extends expiry.
    - recipe_hash mismatch → cache invalid; reset captured + take lease.
    """
    if consume_semantics not in {"read_only", "destructive"}:
        raise LeaseError(f"unknown consume_semantics: {consume_semantics}")

    path = cache_path(phase_dir)
    with _exclusive_lock(path):
        data = load(phase_dir)
        entries = data.setdefault("entries", {})
        entry = entries.get(goal) or {}
        existing_lease = entry.get("lease") or {}
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + ttl_seconds

        if existing_lease:
            try:
                ex_t = datetime.fromisoformat(
                    existing_lease["expires_at"].replace("Z", "+00:00")
                ).timestamp()
            except (KeyError, ValueError):
                ex_t = 0
            ex_owner = existing_lease.get("owner_session")
            ex_sem = existing_lease.get("consume_semantics")
            still_valid = ex_t > now.timestamp()

            if still_valid and ex_owner != owner_session:
                if ex_sem == "destructive" or consume_semantics == "destructive":
                    raise LeaseError(
                        f"Goal {goal} held by {ex_owner!r} (expires_at={existing_lease.get('expires_at')}); "
                        f"consume_semantics={ex_sem}/{consume_semantics} → exclusive conflict"
                    )

        # Recipe hash drift → drop captured (stale)
        if recipe_hash_value and entry.get("recipe_hash") and \
                entry["recipe_hash"] != recipe_hash_value:
            entry.pop("captured", None)

        entry["lease"] = {
            "owner_session": owner_session,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(timespec="seconds"),
            "consume_semantics": consume_semantics,
        }
        if recipe_hash_value:
            entry["recipe_hash"] = recipe_hash_value
        entries[goal] = entry
        save(phase_dir, data)
        return entry["lease"]


def release_lease(phase_dir: Path, goal: str, owner_session: str) -> bool:
    """Drop lease only if owned by the session. Returns True if released."""
    path = cache_path(phase_dir)
    with _exclusive_lock(path):
        data = load(phase_dir)
        entries = data.get("entries") or {}
        entry = entries.get(goal)
        if not entry or "lease" not in entry:
            return False
        if entry["lease"].get("owner_session") != owner_session:
            return False
        del entry["lease"]
        save(phase_dir, data)
        return True


def write_captured(
    phase_dir: Path,
    goal: str,
    captured: dict[str, Any],
    *,
    owner_session: str,
    recipe_hash_value: str | None = None,
) -> None:
    """Persist captured store after successful recipe run.

    Idempotency: only the lease holder may write captured values.
    """
    path = cache_path(phase_dir)
    with _exclusive_lock(path):
        data = load(phase_dir)
        entries = data.setdefault("entries", {})
        entry = entries.get(goal) or {}
        lease = entry.get("lease") or {}
        if lease.get("owner_session") != owner_session:
            raise LeaseError(
                f"write_captured: goal {goal} not owned by {owner_session!r} "
                f"(owner={lease.get('owner_session')!r})"
            )
        entry["captured"] = captured
        entry["executed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if recipe_hash_value:
            entry["recipe_hash"] = recipe_hash_value
        entries[goal] = entry
        save(phase_dir, data)


def get_captured(phase_dir: Path, goal: str) -> dict[str, Any] | None:
    """Return last successful captured store for goal (no lock)."""
    data = load(phase_dir)
    entry = (data.get("entries") or {}).get(goal) or {}
    captured = entry.get("captured")
    return dict(captured) if isinstance(captured, dict) else None


def find_orphans(phase_dir: Path, known_goals: set[str]) -> list[str]:
    """Return goals in cache that no longer exist in known_goals (TEST-GOALS)."""
    data = load(phase_dir)
    entries = data.get("entries") or {}
    return [g for g in entries if g not in known_goals]


def reap_orphans(phase_dir: Path, known_goals: set[str]) -> int:
    """Remove cache entries for goals not in known_goals. Returns # removed."""
    path = cache_path(phase_dir)
    with _exclusive_lock(path):
        data = load(phase_dir)
        entries = data.get("entries") or {}
        orphans = [g for g in entries if g not in known_goals]
        for g in orphans:
            del entries[g]
        save(phase_dir, data)
        return len(orphans)


def reap_expired_leases(phase_dir: Path) -> int:
    """Remove expired leases. Returns # removed."""
    path = cache_path(phase_dir)
    with _exclusive_lock(path):
        data = load(phase_dir)
        entries = data.get("entries") or {}
        now_t = datetime.now(timezone.utc).timestamp()
        n = 0
        for g, entry in entries.items():
            lease = entry.get("lease") or {}
            try:
                ex_t = datetime.fromisoformat(
                    lease["expires_at"].replace("Z", "+00:00")
                ).timestamp()
            except (KeyError, ValueError):
                continue
            if ex_t < now_t:
                del entry["lease"]
                n += 1
        save(phase_dir, data)
        return n
