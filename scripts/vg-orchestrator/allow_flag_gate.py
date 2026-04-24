"""
TTY + env-approver gate for --allow-* flags — Phase O of v2.5.2.

v2.5.2.1 UPGRADE: env path now supports HMAC-signed tokens.

Problem closed (CrossAI round 3 Codex + Claude consensus):
  v2.5.2's VG_HUMAN_OPERATOR env was raw handle string. AI subprocess
  could `os.environ["VG_HUMAN_OPERATOR"] = "real-human"` before exec;
  gate wave-through. Moved the "narrated vs behavioral" forge surface
  from validators to the gate itself.

Gate logic (verify_human_operator):
  1. TTY → genuine human session; approver = $USER / $USERNAME.
  2. Env var set with HMAC-signed token → verify signature + flag scope
     + expiry → approver = decoded handle.
  3. Env var set with raw string → BLOCK in strict mode; accept with
     `unsigned-warning` suffix in non-strict (legacy compat).
  4. Neither → AI subagent; block the flag.

Signing key at `~/.vg/.approver-key` (mode 0600 on POSIX; relies on user
profile dir protection on Windows). CLI `vg-auth.py approve` mints tokens
in TTY-only mode. AI subprocess without key-file read access cannot forge.

Also provides:
  - sign_approval / verify_approval primitives (exposed for tests + CLI)
  - log_allow_flag_used(...) — emits `allow_flag.used` event
  - check_rubber_stamp(...) — detect repeated approvals with identical
    reason-head (defense-in-depth on top of signature verification)
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Optional

DEFAULT_APPROVER_ENV_VAR = "VG_HUMAN_OPERATOR"
STRICT_MODE_ENV_VAR = "VG_ALLOW_FLAGS_STRICT_MODE"
APPROVER_KEY_DIR_ENV = "VG_APPROVER_KEY_DIR"  # test override


def _is_tty() -> bool:
    """True when stdin is attached to a terminal (human interactive)."""
    try:
        return os.isatty(sys.stdin.fileno())
    except (ValueError, OSError):
        return False


def _tty_user() -> Optional[str]:
    for var in ("USER", "USERNAME", "LOGNAME"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def _approver_key_path() -> Path:
    override = os.environ.get(APPROVER_KEY_DIR_ENV)
    if override:
        return Path(override) / "approver-key"
    return Path.home() / ".vg" / ".approver-key"


def _get_or_create_key() -> bytes:
    """Read the HMAC signing key; create it if missing.

    File is mode 0600 on POSIX so only the user can read it. Windows relies
    on user-profile dir protection — same-user AI subprocess CAN read it
    (documented limitation; see module docstring). For hostile environments,
    use TTY mode only (`allow_flags.strict_mode=true` + no env fallback).
    """
    path = _approver_key_path()
    if path.exists():
        return path.read_bytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    # Write + restrict before anyone else can read
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError, AttributeError):
        pass  # Windows or sandbox — best-effort
    return key


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Add padding back
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_approval(handle: str, flag: str, ttl_seconds: int,
                  now: Optional[int] = None) -> str:
    """Mint an HMAC-signed approval token.

    Format: base64url(payload_json) + "." + base64url(hmac_sha256(key, payload))

    Payload fields: handle, flag, issued_at, expires_at. `flag == "*"` grants
    approval for any --allow-* flag (use sparingly; defeats scoping).
    """
    if now is None:
        now = int(time.time())
    payload = {
        "handle": handle,
        "flag": flag,
        "issued_at": now,
        "expires_at": now + int(ttl_seconds),
    }
    payload_bytes = json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_get_or_create_key(), payload_bytes, hashlib.sha256).digest()
    return _b64url_encode(payload_bytes) + "." + _b64url_encode(sig)


def verify_approval(token: str, flag: str,
                    now: Optional[int] = None) -> tuple[bool, Optional[str], str]:
    """Verify an approval token. Return (valid, handle, reason).

    Reason codes: ok | malformed_token | signature_invalid | payload_corrupt
                  | token_expired | flag_mismatch
    """
    if not isinstance(token, str) or "." not in token:
        return False, None, "malformed_token"

    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
    except (ValueError, binascii.Error):
        return False, None, "malformed_token"

    expected = hmac.new(_get_or_create_key(), payload_bytes,
                        hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return False, None, "signature_invalid"

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, None, "payload_corrupt"

    if not isinstance(payload, dict):
        return False, None, "payload_corrupt"

    if now is None:
        now = int(time.time())
    exp = payload.get("expires_at", 0)
    if not isinstance(exp, int) or exp < now:
        return False, payload.get("handle"), "token_expired"

    flag_scope = payload.get("flag")
    if flag_scope not in (flag, "*"):
        return False, payload.get("handle"), "flag_mismatch"

    return True, payload.get("handle"), "ok"


def verify_human_operator(
    flag_name: str,
    approver_env_var: str = DEFAULT_APPROVER_ENV_VAR,
    strict: Optional[bool] = None,
) -> tuple[bool, Optional[str]]:
    """Return (is_human, approver_or_None).

    Strict mode (configurable via `VG_ALLOW_FLAGS_STRICT_MODE=true` or the
    explicit `strict` arg) REQUIRES either:
      - a TTY session, OR
      - a valid HMAC-signed token in the env var

    Non-strict (default, legacy compat) additionally accepts a raw handle
    string in the env var with an `unsigned-warning` suffix on the returned
    approver — so audit shows the gap clearly.
    """
    if _is_tty():
        return True, _tty_user() or "unknown-tty-user"

    if strict is None:
        strict = os.environ.get(STRICT_MODE_ENV_VAR, "").lower() in \
                 ("1", "true", "yes", "on")

    env_val = os.environ.get(approver_env_var, "").strip()
    if not env_val:
        return False, None

    # Try signed token first (tokens always contain a "." separator from b64
    # payload + sig). If env var has no "." it's either a raw handle or
    # garbage — never a valid token.
    if "." in env_val:
        valid, handle, _reason = verify_approval(env_val, flag_name)
        if valid:
            return True, handle
        # Invalid token — always block regardless of strict mode
        # (someone tried to forge; don't fall through to raw-string path)
        return False, None

    # Raw-string env var path
    if strict:
        return False, None
    return True, f"{env_val} [unsigned-warning]"


def _reason_head(reason: str, n: int = 120) -> str:
    compressed = " ".join(reason.strip().split())
    return compressed[:n].lower()


def _reason_fingerprint(reason: str) -> str:
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
    payload = {
        "flag": flag_name,
        "approver": approver,
        "reason": reason[:500],
        "reason_fp": _reason_fingerprint(reason),
        "ttl_days": int(ttl_days),
        "signed": "[unsigned-warning]" not in approver,
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
        return f"AF-{payload['reason_fp']}"


def check_rubber_stamp(
    events: list[dict],
    approver: str,
    flag_name: str,
    reason: str,
    threshold: int = 3,
) -> bool:
    fp = _reason_fingerprint(reason)
    hit = 0
    for ev in events:
        if ev.get("event_type") != "allow_flag.used":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
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
