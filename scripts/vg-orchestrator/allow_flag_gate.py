"""
TTY + env-approver gate for --allow-* flags — Phase O of v2.5.2.

Problem: AI subagents sometimes attempt to pass --allow-<gate> flags to
bypass validators. Those flags must carry a human identity so the
audit trail is non-repudiable.

Gate logic (verify_human_operator):
  1. If stdin is a TTY → genuine human session; approver = $USER / $USERNAME.
  2. Else if env var (default VG_HUMAN_OPERATOR) is set → explicit human
     override; approver = that value.
  3. Otherwise → AI subagent; block the flag.

Also provides:
  - log_allow_flag_used(...) — emits `allow_flag.used` event + OVERRIDE-DEBT-style entry
  - check_rubber_stamp(events, approver, flag, reason) — detect repeated
    approvals with identical reason-head (potential rubber-stamp pattern)
"""
from __future__ import annotations

import hashlib
import os
import sys
from typing import Optional

DEFAULT_APPROVER_ENV_VAR = "VG_HUMAN_OPERATOR"


def _is_tty() -> bool:
    """True when stdin is attached to a terminal (human interactive)."""
    try:
        return os.isatty(sys.stdin.fileno())
    except (ValueError, OSError):
        return False


def _tty_user() -> Optional[str]:
    """Best-effort username lookup for TTY session."""
    for var in ("USER", "USERNAME", "LOGNAME"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def verify_human_operator(
    flag_name: str,
    approver_env_var: str = DEFAULT_APPROVER_ENV_VAR,
) -> tuple[bool, Optional[str]]:
    """Return (is_human, approver_or_None).

    Rules:
      - TTY session → is_human=True, approver = $USER / $USERNAME
      - Env var set → is_human=True, approver = env value
      - Neither → is_human=False, approver=None (block)
    """
    if _is_tty():
        return True, _tty_user() or "unknown-tty-user"
    env_val = os.environ.get(approver_env_var, "").strip()
    if env_val:
        return True, env_val
    return False, None


def _reason_head(reason: str, n: int = 120) -> str:
    """Normalize reason to a hashable 'head' for rubber-stamp detection."""
    compressed = " ".join(reason.strip().split())
    return compressed[:n].lower()


def _reason_fingerprint(reason: str) -> str:
    """Hash the reason head for stable comparison even with long strings."""
    return hashlib.sha256(_reason_head(reason).encode("utf-8")).hexdigest()[:16]


def log_allow_flag_used(
    flag_name: str,
    approver: str,
    reason: str,
    ttl_days: int = 30,
    run_id: str = "unknown",
    phase: str = "",
    command: str = "",
) -> str:
    """Emit `allow_flag.used` event. Returns audit_id (event hash-prefix).

    Best-effort: if db module unreachable, returns a local audit_id without
    raising so caller can still log to override-debt ledger directly.
    """
    payload = {
        "flag": flag_name,
        "approver": approver,
        "reason": reason[:500],
        "reason_fp": _reason_fingerprint(reason),
        "ttl_days": int(ttl_days),
    }
    try:
        import db as _db  # type: ignore
        ev = _db.append_event(
            run_id=run_id,
            event_type="allow_flag.used",
            phase=phase,
            command=command,
            actor="user",
            outcome="INFO",
            payload=payload,
        )
        return f"AF-{ev['id']:05d}"
    except Exception:
        # Fallback: deterministic audit_id from reason_fp
        return f"AF-{payload['reason_fp']}"


def check_rubber_stamp(
    events: list[dict],
    approver: str,
    flag_name: str,
    reason: str,
    threshold: int = 3,
) -> bool:
    """Return True if (approver, flag, reason-head) has been seen at least
    `threshold` times among the provided allow_flag.used events."""
    fp = _reason_fingerprint(reason)
    hit = 0
    for ev in events:
        if ev.get("event_type") != "allow_flag.used":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, str):
            # payload came from SQLite payload_json — try to parse
            try:
                import json as _json
                payload = _json.loads(payload)
            except Exception:
                continue
        if payload.get("flag") != flag_name:
            continue
        if payload.get("approver") != approver:
            continue
        if payload.get("reason_fp") != fp:
            continue
        hit += 1
    return hit >= threshold
