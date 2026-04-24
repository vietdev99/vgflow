"""
Repo-level advisory lock for VG orchestrator — Phase O of v2.5.2.

Prevents two concurrent /vg:* commands from racing on the same repo/phase.
Broader than db._flock (which serializes event writes only) — this lock
guards full pipeline transitions (e.g. /vg:build + /vg:review both wanting
to mutate the same phase).

Design:
  - Single JSON lockfile at .vg/.repo-lock.json
  - Advisory only: holder writes lock_token + pid + hostname + acquired_at
  - Stale detection: if pid no longer alive OR acquired_at + ttl < now,
    auto-break and emit lock.stale_broken event
  - Windows compat: getpid is portable. psutil optional; fall back to
    mtime-only staleness check when psutil not present.
  - Stdlib only — no third-party imports required for core path.

API:
  acquire_repo_lock(command, phase, ttl_seconds) -> lock_token | None
  release_repo_lock(lock_token) -> bool
  get_active_lock() -> dict | None
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
LOCKFILE = REPO_ROOT / ".vg" / ".repo-lock.json"
DEFAULT_TTL_SECONDS = 3600
STALE_BREAK_AFTER_SECONDS = 7200


def _pid_alive(pid: int) -> bool:
    """Return True if process with given pid is alive.

    Portable fallback: try psutil first (accurate), fall back to os.kill(pid, 0)
    on POSIX. On Windows without psutil, return True conservatively (mtime +
    TTL will still break the lock eventually).
    """
    if pid <= 0:
        return False
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    # POSIX path: os.kill(pid, 0) raises ProcessLookupError if dead
    if os.name == "posix":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we can't signal it — still alive
            return True
        except OSError:
            return False
    # Windows without psutil — best effort, rely on TTL for staleness
    return True


def _read_lockfile() -> Optional[dict]:
    if not LOCKFILE.exists():
        return None
    try:
        return json.loads(LOCKFILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_lockfile(data: dict) -> None:
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCKFILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(LOCKFILE))


def _remove_lockfile() -> None:
    try:
        LOCKFILE.unlink()
    except FileNotFoundError:
        pass


def _is_stale(lock: dict, now: float | None = None) -> tuple[bool, str]:
    """Return (stale, reason). Lock is stale if pid dead OR ttl elapsed."""
    now = now if now is not None else time.time()
    acquired_at = lock.get("acquired_at", 0)
    ttl = lock.get("ttl_seconds", DEFAULT_TTL_SECONDS)
    pid = lock.get("pid", 0)

    age = now - acquired_at
    # Hard stale break regardless of ttl — prevents forever-locks
    if age > STALE_BREAK_AFTER_SECONDS:
        return True, f"lock age {int(age)}s exceeds hard break {STALE_BREAK_AFTER_SECONDS}s"
    # Normal ttl-based stale
    if age > ttl:
        # Double-check pid — if still alive, extend ttl grace
        if not _pid_alive(pid):
            return True, f"ttl {ttl}s elapsed (age {int(age)}s) and pid {pid} not alive"
        # pid alive but over ttl → still call stale; holder should have refreshed
        return True, f"ttl {ttl}s elapsed (age {int(age)}s), pid {pid} still alive but lock expired"
    # Within ttl — check if pid is dead (crashed holder)
    if not _pid_alive(pid):
        return True, f"holder pid {pid} not alive (age {int(age)}s)"
    return False, ""


def _emit_stale_break(prior_lock: dict, reason: str) -> None:
    """Best-effort event emission — never raises."""
    try:
        # Lazy import to avoid circular (db imports nothing from here,
        # but keep import cost off module load).
        import db as _db  # type: ignore
        _db.append_event(
            run_id=prior_lock.get("lock_token", "unknown"),
            event_type="lock.stale_broken",
            phase=prior_lock.get("phase", ""),
            command=prior_lock.get("command", ""),
            actor="orchestrator",
            outcome="WARN",
            payload={
                "reason": reason,
                "prior_pid": prior_lock.get("pid"),
                "prior_acquired_at": prior_lock.get("acquired_at"),
                "prior_command": prior_lock.get("command"),
                "prior_phase": prior_lock.get("phase"),
            },
        )
    except Exception:
        pass


def acquire_repo_lock(command: str, phase: str,
                      ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[str]:
    """Try to acquire the repo lock. Returns lock_token on success, None if
    another live holder exists.

    Stale locks (dead pid or expired ttl) auto-break with a warning event.
    """
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_lockfile()
    if existing is not None:
        stale, reason = _is_stale(existing)
        if stale:
            _emit_stale_break(existing, reason)
            _remove_lockfile()
        else:
            # Live holder — fail acquire
            return None

    lock_token = str(uuid.uuid4())
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    data = {
        "lock_token": lock_token,
        "command": command,
        "phase": phase,
        "acquired_at": time.time(),
        "pid": os.getpid(),
        "hostname": hostname,
        "ttl_seconds": int(ttl_seconds),
    }
    _write_lockfile(data)
    # Re-read to guard against race with another acquirer
    verify = _read_lockfile()
    if verify and verify.get("lock_token") == lock_token:
        return lock_token
    return None


def release_repo_lock(lock_token: str) -> bool:
    """Release the lock if we own it. Returns True on success, False if the
    current lock has a different token (stale release or stolen)."""
    existing = _read_lockfile()
    if existing is None:
        return False
    if existing.get("lock_token") != lock_token:
        return False
    _remove_lockfile()
    return True


def get_active_lock() -> Optional[dict]:
    """Read current lock holder (or None if unlocked / stale)."""
    existing = _read_lockfile()
    if existing is None:
        return None
    stale, _ = _is_stale(existing)
    if stale:
        return None
    return existing


def force_release() -> bool:
    """Hard unlock — use only in recovery commands (e.g. /vg:recover).
    Returns True if a lockfile was removed, False if none existed."""
    if LOCKFILE.exists():
        _remove_lockfile()
        return True
    return False
