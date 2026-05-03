#!/usr/bin/env python3
"""
v2.7 Phase J — interactive migration: ~/.vg/.approver-key → OS keychain.

Reads the legacy plaintext key from ~/.vg/.approver-key, writes it to the
OS-native keychain (Keychain Access on macOS, Credential Manager on
Windows, Secret Service on Linux) via the stdlib-compatible `keyring`
package, verifies the round-trip, then prompts the operator to delete
the file.

Idempotent: a second run detects the keychain is already populated and
exits without re-writing or re-prompting for deletion (unless --force).

CLI:
    migrate-approver-key-to-keychain.py [--dry-run] [--force]

Exit codes:
    0  migration succeeded OR keychain already populated (idempotent)
    1  generic failure (missing source file, etc.)
    2  keychain backend unavailable (operator must install `keyring` or
       remain on file-based storage; documented in
       docs/onboarding-keychain.md)
    3  round-trip verification failed (set succeeded but get returned
       different bytes — possible corruption)
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

# Reach the gate module — same dir as us once installed under .claude/scripts/
REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_DIR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
sys.path.insert(0, str(GATE_DIR))

import importlib.util as _ilu  # noqa: E402

_SPEC = _ilu.spec_from_file_location(
    "allow_flag_gate", GATE_DIR / "allow_flag_gate.py"
)
_GATE = _ilu.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_GATE)

KEYCHAIN_USERNAME = _GATE.KEYCHAIN_USERNAME


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _import_keyring():
    try:
        import keyring  # type: ignore
        import keyring.errors  # type: ignore
        return keyring
    except ImportError:
        return None


def _confirm(prompt: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate ~/.vg/.approver-key to OS keychain."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Inspect state and report actions without modifying anything.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite keychain even if already populated; "
             "still prompt for file deletion.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Auto-confirm destructive prompts (file deletion). "
             "Useful for scripted migrations.",
    )
    args = parser.parse_args()

    cfg = _GATE._read_keychain_config()
    service_name = cfg["service_name"]
    fallback_path = Path(
        os.path.expanduser(cfg.get("fallback_file_path", "~/.vg/.approver-key"))
    )
    # Honor APPROVER_KEY_DIR override for testability
    override = os.environ.get(_GATE.APPROVER_KEY_DIR_ENV)
    if override:
        fallback_path = Path(override) / "approver-key"

    print(f"[migrate] service_name = {service_name!r}")
    print(f"[migrate] file path    = {fallback_path}")

    keyring = _import_keyring()
    if keyring is None:
        print(
            "[migrate] FAIL: `keyring` package not importable.\n"
            "   Install:\n"
            "     macOS:   pip install keyring\n"
            "     Windows: pip install keyring\n"
            "     Linux:   pip install keyring secretstorage\n"
            "   See docs/onboarding-keychain.md for headless-CI guidance.",
            file=sys.stderr,
        )
        return 2

    # --- Step 1: inspect keychain ---
    try:
        existing = keyring.get_password(service_name, KEYCHAIN_USERNAME)
    except keyring.errors.KeyringError as e:
        print(
            f"[migrate] FAIL: keychain backend error: {e}\n"
            f"   Backend: {keyring.get_keyring()}\n"
            f"   See docs/onboarding-keychain.md for backend setup.",
            file=sys.stderr,
        )
        return 2

    if existing is not None and not args.force:
        print(
            "[migrate] OK (idempotent): keychain already populated. "
            "Nothing to do.\n"
            "   Re-run with --force to overwrite from file."
        )
        return 0

    # --- Step 2: read source file ---
    if not fallback_path.exists():
        if existing is not None:
            print(
                "[migrate] keychain populated and no source file present "
                "— migration unnecessary."
            )
            return 0
        print(
            f"[migrate] FAIL: source file {fallback_path} missing AND "
            f"keychain empty.\n"
            f"   Nothing to migrate. Run a /vg:* command from a TTY to "
            f"auto-create the key, then re-run this script.",
            file=sys.stderr,
        )
        return 1

    try:
        key_bytes = fallback_path.read_bytes()
    except OSError as e:
        print(f"[migrate] FAIL: cannot read {fallback_path}: {e}",
              file=sys.stderr)
        return 1

    if len(key_bytes) < 16:
        print(
            f"[migrate] FAIL: source file too small ({len(key_bytes)} bytes); "
            "expected ≥16 bytes of HMAC key material.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        action = "OVERWRITE" if existing is not None else "WRITE"
        print(
            f"[migrate] DRY-RUN: would {action} keychain entry "
            f"({len(key_bytes)} bytes) and prompt to delete "
            f"{fallback_path}."
        )
        return 0

    # --- Step 3: write to keychain ---
    encoded = _b64url_encode(key_bytes)
    try:
        keyring.set_password(service_name, KEYCHAIN_USERNAME, encoded)
    except keyring.errors.KeyringError as e:
        print(
            f"[migrate] FAIL: keyring.set_password raised: {e}",
            file=sys.stderr,
        )
        return 2

    # --- Step 4: round-trip verify ---
    try:
        roundtrip = keyring.get_password(service_name, KEYCHAIN_USERNAME)
    except keyring.errors.KeyringError as e:
        print(f"[migrate] FAIL: round-trip get failed: {e}", file=sys.stderr)
        return 3

    if roundtrip != encoded:
        print(
            "[migrate] FAIL: round-trip mismatch — keychain returned "
            "different bytes after set. Aborting; file NOT deleted.",
            file=sys.stderr,
        )
        return 3
    try:
        decoded = _b64url_decode(roundtrip)
    except (ValueError, Exception):
        print(
            "[migrate] FAIL: round-trip decode failed; data corruption.",
            file=sys.stderr,
        )
        return 3
    if decoded != key_bytes:
        print(
            "[migrate] FAIL: decoded round-trip differs from source bytes.",
            file=sys.stderr,
        )
        return 3

    print("[migrate] OK: keychain populated; round-trip verified.")

    # --- Step 5: optional file deletion ---
    if args.yes:
        delete = True
    else:
        delete = _confirm(
            f"[migrate] Delete legacy file {fallback_path}? "
            "(Recommended — closes the same-user AI read surface)",
            default_yes=False,
        )
    if delete:
        try:
            fallback_path.unlink()
            print(f"[migrate] OK: deleted {fallback_path}.")
        except OSError as e:
            print(
                f"[migrate] WARN: keychain populated but file delete failed: {e}\n"
                f"   Manually remove {fallback_path} when convenient.",
                file=sys.stderr,
            )
            return 0
    else:
        print(
            f"[migrate] OK: file kept at {fallback_path} as fallback. "
            "Keychain is primary; file will be used only if keychain "
            "becomes unavailable."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
