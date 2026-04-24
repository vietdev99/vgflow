"""
Tests for v2.5.2.1 HMAC-signed allow-flag tokens.

Covers the forge surface that CrossAI round 3 consensus (Codex + Claude)
flagged: `VG_HUMAN_OPERATOR` env path was a raw handle string, AI
subprocess could self-set the value and bypass the gate.

New behavior:
  - Env var can contain HMAC-signed token with flag scope + expiry.
  - Signing key at $VG_APPROVER_KEY_DIR/approver-key (test isolation)
    or ~/.vg/.approver-key (production).
  - Strict mode blocks raw-string env entirely; non-strict returns with
    `[unsigned-warning]` suffix on approver (visible in audit).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Import allow_flag_gate via importlib (vg-orchestrator dir has a dash)
import importlib.util as _ilu
_GATE_PATH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / \
             "allow_flag_gate.py"
_spec = _ilu.spec_from_file_location("allow_flag_gate_test", _GATE_PATH)
_gate = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_gate)

VG_AUTH_CLI = REPO_ROOT / ".claude" / "scripts" / "vg-auth.py"


@pytest.fixture
def isolated_key_dir(tmp_path, monkeypatch):
    """Redirect approver-key to tmp so tests don't touch real ~/.vg."""
    monkeypatch.setenv("VG_APPROVER_KEY_DIR", str(tmp_path))
    # Clear auth state that might leak between tests
    monkeypatch.delenv("VG_HUMAN_OPERATOR", raising=False)
    monkeypatch.delenv("VG_ALLOW_FLAGS_STRICT_MODE", raising=False)
    return tmp_path


@pytest.fixture
def no_tty(monkeypatch):
    """Force _is_tty() to return False (simulate AI subagent context)."""
    monkeypatch.setattr(_gate, "_is_tty", lambda: False)


def _run_cli(args: list[str], env_extra: dict | None = None,
             stdin_input: str | None = None,
             force_no_tty_stdin: bool = True,
             ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    # Close stdin so subprocess isatty() returns False (important for TTY-gate tests).
    # When running pytest from an interactive shell, the shell's TTY would
    # otherwise be inherited.
    stdin = subprocess.DEVNULL if (stdin_input is None and force_no_tty_stdin) \
            else subprocess.PIPE if stdin_input is not None else None
    return subprocess.run(
        [sys.executable, str(VG_AUTH_CLI), *args],
        capture_output=True, text=True, timeout=15,
        env=env, input=stdin_input, stdin=stdin,
        encoding="utf-8", errors="replace",
    )


# ─── Sign / verify primitives ──────────────────────────────────────────


class TestSignVerify:
    def test_sign_and_verify_roundtrip(self, isolated_key_dir):
        token = _gate.sign_approval("alice", "allow-X", ttl_seconds=3600)
        valid, handle, reason = _gate.verify_approval(token, "allow-X")
        assert valid
        assert handle == "alice"
        assert reason == "ok"

    def test_expired_token_blocked(self, isolated_key_dir):
        # TTL 0 → immediate expiry
        token = _gate.sign_approval("alice", "allow-X", ttl_seconds=0,
                                    now=int(time.time()) - 10)
        valid, _handle, reason = _gate.verify_approval(token, "allow-X")
        assert not valid
        assert reason == "token_expired"

    def test_wrong_flag_blocked(self, isolated_key_dir):
        token = _gate.sign_approval("alice", "allow-X", ttl_seconds=3600)
        valid, _handle, reason = _gate.verify_approval(token, "allow-Y")
        assert not valid
        assert reason == "flag_mismatch"

    def test_wildcard_flag_grants_any(self, isolated_key_dir):
        token = _gate.sign_approval("alice", "*", ttl_seconds=3600)
        valid, _h, reason = _gate.verify_approval(token, "allow-anything")
        assert valid

    def test_tampered_payload_blocked(self, isolated_key_dir):
        token = _gate.sign_approval("alice", "allow-X", ttl_seconds=3600)
        payload_b64, sig_b64 = token.split(".", 1)
        # Tamper: mint a fake payload but keep original sig
        fake_payload = _gate._b64url_encode(
            b'{"handle":"attacker","flag":"allow-X",'
            b'"issued_at":1,"expires_at":9999999999}')
        bad = fake_payload + "." + sig_b64
        valid, _h, reason = _gate.verify_approval(bad, "allow-X")
        assert not valid
        assert reason == "signature_invalid"

    def test_malformed_token_blocked(self, isolated_key_dir):
        valid, _h, reason = _gate.verify_approval("not-a-token", "allow-X")
        assert not valid
        assert reason == "malformed_token"


# ─── verify_human_operator integration ─────────────────────────────────


class TestVerifyHumanOperator:
    def test_tty_session_passes_without_env(self, isolated_key_dir,
                                            monkeypatch):
        monkeypatch.setattr(_gate, "_is_tty", lambda: True)
        monkeypatch.setenv("USER", "alice")
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert is_human
        assert approver == "alice"

    def test_no_env_blocks(self, isolated_key_dir, no_tty):
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert not is_human
        assert approver is None

    def test_signed_token_passes(self, isolated_key_dir, no_tty,
                                 monkeypatch):
        token = _gate.sign_approval("alice", "allow-X", ttl_seconds=3600)
        monkeypatch.setenv("VG_HUMAN_OPERATOR", token)
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert is_human
        assert approver == "alice"

    def test_wrong_flag_in_token_blocks(self, isolated_key_dir, no_tty,
                                        monkeypatch):
        token = _gate.sign_approval("alice", "allow-Y", ttl_seconds=3600)
        monkeypatch.setenv("VG_HUMAN_OPERATOR", token)
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert not is_human

    def test_forged_token_blocks(self, isolated_key_dir, no_tty,
                                 monkeypatch):
        # Attacker constructs a fake token shape
        fake = "abc.def"
        monkeypatch.setenv("VG_HUMAN_OPERATOR", fake)
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert not is_human
        assert approver is None

    def test_raw_string_env_non_strict_accepts_with_warning(
            self, isolated_key_dir, no_tty, monkeypatch):
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        is_human, approver = _gate.verify_human_operator(
            "allow-X", strict=False)
        assert is_human
        assert "unsigned-warning" in (approver or "")

    def test_raw_string_env_strict_blocks(self, isolated_key_dir, no_tty,
                                          monkeypatch):
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        is_human, approver = _gate.verify_human_operator(
            "allow-X", strict=True)
        assert not is_human

    def test_strict_mode_via_env(self, isolated_key_dir, no_tty,
                                 monkeypatch):
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        monkeypatch.setenv("VG_ALLOW_FLAGS_STRICT_MODE", "true")
        is_human, _a = _gate.verify_human_operator("allow-X")
        assert not is_human


# ─── Negative test: AI subprocess cannot forge ─────────────────────────


class TestAiSubprocessCannotForge:
    """
    The v2.5.2.1 claim: AI subagent that spawns a subprocess WITHOUT key-file
    access cannot forge a valid signed token. This simulates that by having
    the subprocess point at a DIFFERENT key dir than the one where real
    tokens were minted.
    """

    def test_subprocess_with_wrong_keydir_cannot_validate(
            self, tmp_path, monkeypatch):
        # User's real key dir: has a key
        real_dir = tmp_path / "real_keys"
        real_dir.mkdir()

        # Mint a token in real_dir
        monkeypatch.setenv("VG_APPROVER_KEY_DIR", str(real_dir))
        good_token = _gate.sign_approval("alice", "allow-X",
                                         ttl_seconds=3600)

        # AI's fake key dir (different random key will be auto-generated)
        fake_dir = tmp_path / "ai_keys"
        fake_dir.mkdir()

        # Subprocess uses fake_dir → the token was signed with a different key
        # → signature verify must fail
        result = subprocess.run(
            [sys.executable, str(VG_AUTH_CLI),
             "verify", "--token", good_token, "--flag", "allow-X"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "VG_APPROVER_KEY_DIR": str(fake_dir),
                 "PYTHONIOENCODING": "utf-8"},
            encoding="utf-8", errors="replace",
        )
        assert result.returncode == 1
        assert "INVALID" in result.stdout or "signature_invalid" in result.stdout

    def test_env_var_tampering_by_subprocess_blocks(
            self, isolated_key_dir, no_tty, monkeypatch):
        """Simulates: AI subagent sets VG_HUMAN_OPERATOR to an arbitrary
        string before spawning a subprocess. Strict mode MUST block."""
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "pretending-to-be-vietdev99")
        monkeypatch.setenv("VG_ALLOW_FLAGS_STRICT_MODE", "true")
        is_human, _a = _gate.verify_human_operator("allow-security-baseline")
        assert not is_human


# ─── CLI tests ─────────────────────────────────────────────────────────


class TestVgAuthCli:
    # NOTE: a direct "subprocess without TTY is blocked" test is not portable —
    # Windows `stdin=subprocess.DEVNULL` reports isatty=True for the NUL
    # device, and capture_output on Unix inherits parent TTY. The TTY check
    # LOGIC is covered by the monkeypatch tests above (test_no_env_blocks,
    # test_tty_session_passes_without_env). The CLI merely delegates.

    def test_approve_force_no_tty_mints_token(self, tmp_path):
        result = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--force-no-tty", "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        token = result.stdout.strip()
        assert "." in token  # payload.sig

    def test_verify_cli_accepts_valid_token(self, tmp_path):
        mint = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--force-no-tty", "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path)},
        )
        assert mint.returncode == 0
        token = mint.stdout.strip()

        verify = _run_cli(
            ["verify", "--token", token, "--flag", "allow-X"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path)},
        )
        assert verify.returncode == 0
        assert "VALID" in verify.stdout

    def test_init_creates_key_file(self, tmp_path):
        result = _run_cli(
            ["init"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert (tmp_path / "approver-key").exists()
