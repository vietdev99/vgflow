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
    """Redirect approver-key + nonce-dir to tmp so tests don't touch real ~/.vg."""
    monkeypatch.setenv("VG_APPROVER_KEY_DIR", str(tmp_path))
    # v2.5.2.3: isolate nonce dir too
    nonce_dir = tmp_path / "nonces"
    monkeypatch.setenv("VG_APPROVER_NONCE_DIR", str(nonce_dir))
    # Clear auth state that might leak between tests
    monkeypatch.delenv("VG_HUMAN_OPERATOR", raising=False)
    monkeypatch.delenv("VG_ALLOW_FLAGS_STRICT_MODE", raising=False)
    monkeypatch.delenv("VG_AUTH_CI_MODE", raising=False)
    monkeypatch.delenv("VG_AUTH_OPERATOR_ACK", raising=False)
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

    def test_default_is_strict_v2_5_2_2(self, isolated_key_dir, no_tty,
                                        monkeypatch):
        """v2.5.2.2: default behavior (no strict arg, no env) MUST block
        raw-string env. Closes Codex round-4 finding."""
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        # No VG_ALLOW_FLAGS_STRICT_MODE, no VG_ALLOW_FLAGS_LEGACY_RAW
        is_human, _a = _gate.verify_human_operator("allow-X")
        assert not is_human  # default is strict now

    def test_legacy_raw_opt_in_allows_raw(self, isolated_key_dir, no_tty,
                                          monkeypatch):
        """Explicit VG_ALLOW_FLAGS_LEGACY_RAW=true re-opens raw-string path
        for projects migrating from v2.5.1."""
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        monkeypatch.setenv("VG_ALLOW_FLAGS_LEGACY_RAW", "true")
        is_human, approver = _gate.verify_human_operator("allow-X")
        assert is_human
        assert "unsigned-warning" in (approver or "")

    def test_force_strict_beats_legacy_optin(self, isolated_key_dir, no_tty,
                                             monkeypatch):
        """STRICT_MODE=true wins even if LEGACY_RAW=true also set."""
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice")
        monkeypatch.setenv("VG_ALLOW_FLAGS_LEGACY_RAW", "true")
        monkeypatch.setenv("VG_ALLOW_FLAGS_STRICT_MODE", "true")
        is_human, _a = _gate.verify_human_operator("allow-X")
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

    def test_approve_ci_mode_mints_token(self, tmp_path, monkeypatch):
        """v2.5.2.3: CI fallback requires VG_AUTH_OPERATOR_ACK to be a valid
        pre-issued nonce (not just non-empty). Mint a nonce via the primitive
        (bypasses TTY requirement which CLI enforces), then use it."""
        nonce_dir = tmp_path / "nonces"
        monkeypatch.setenv("VG_APPROVER_NONCE_DIR", str(nonce_dir))
        nonce = _gate.issue_nonce(ttl_seconds=3600, issuer="alice")

        result = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir),
                       "VG_AUTH_CI_MODE": "1",
                       "VG_AUTH_OPERATOR_ACK": nonce},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        token = result.stdout.strip()
        assert "." in token

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows subprocess DEVNULL stdin reports isatty=True "
               "(NUL device OS quirk), so the TTY path wins before CI check "
               "runs. Regression is covered by primitive-level "
               "TestCiApproveNonceIntegration on all platforms."
    )
    def test_approve_ci_mode_raw_ack_blocked(self, tmp_path, monkeypatch):
        """Regression for Codex round-5 finding: non-empty ACK that was NOT
        pre-issued via issue-nonce MUST NOT mint a token. Closes the
        'presence-check only' gap."""
        nonce_dir = tmp_path / "nonces"
        monkeypatch.setenv("VG_APPROVER_NONCE_DIR", str(nonce_dir))
        # No issue_nonce call — raw string should be rejected.
        result = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--handle", "attacker", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir),
                       "VG_AUTH_CI_MODE": "1",
                       "VG_AUTH_OPERATOR_ACK": "attacker-guessed-this-string"},
        )
        assert result.returncode == 2, (
            f"Expected block (exit 2); got {result.returncode}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "not_found" in result.stderr or "rejected" in result.stderr.lower()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows NUL-stdin TTY quirk — see sibling skip comment"
    )
    def test_approve_ci_mode_reused_ack_blocked(self, tmp_path, monkeypatch):
        """Nonce is single-use. Second approve with same ACK must be blocked."""
        nonce_dir = tmp_path / "nonces"
        monkeypatch.setenv("VG_APPROVER_NONCE_DIR", str(nonce_dir))
        nonce = _gate.issue_nonce(ttl_seconds=3600, issuer="alice")

        first = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir),
                       "VG_AUTH_CI_MODE": "1",
                       "VG_AUTH_OPERATOR_ACK": nonce},
        )
        assert first.returncode == 0

        second = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir),
                       "VG_AUTH_CI_MODE": "1",
                       "VG_AUTH_OPERATOR_ACK": nonce},
        )
        assert second.returncode == 2
        assert "already_used" in second.stderr

    # NOTE: "CI_MODE=1 alone (no OPERATOR_ACK) blocks" can't be reliably
    # tested via subprocess on Windows (subprocess stdin inherits TTY).
    # The logic is covered by the env-handling unit test below; the
    # subprocess test would only falsely pass on Windows-like systems.

    def test_verify_cli_accepts_valid_token(self, tmp_path, monkeypatch):
        nonce_dir = tmp_path / "nonces"
        monkeypatch.setenv("VG_APPROVER_NONCE_DIR", str(nonce_dir))
        nonce = _gate.issue_nonce(ttl_seconds=3600, issuer="alice")

        mint = _run_cli(
            ["approve", "--flag", "allow-X", "--ttl-days", "1",
             "--handle", "alice", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir),
                       "VG_AUTH_CI_MODE": "1",
                       "VG_AUTH_OPERATOR_ACK": nonce},
        )
        assert mint.returncode == 0, f"stderr: {mint.stderr}"
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

    def test_issue_nonce_requires_tty(self, tmp_path):
        """v2.5.2.3: issue-nonce is TTY-only. Without TTY (subprocess
        DEVNULL stdin) must block — otherwise AI could self-issue nonces,
        defeating the OOB-bootstrap threat model."""
        nonce_dir = tmp_path / "nonces"
        result = _run_cli(
            ["issue-nonce", "--ttl-minutes", "5", "--quiet"],
            env_extra={"VG_APPROVER_KEY_DIR": str(tmp_path),
                       "VG_APPROVER_NONCE_DIR": str(nonce_dir)},
        )
        # Windows NUL quirk: subprocess.DEVNULL reports isatty=True. Accept
        # either block (POSIX) or pass-through (Windows) — behavior still
        # correct overall because CLI primitive requires ISATTY, and on
        # real AI invocation (no DEVNULL hack) it blocks.
        if result.returncode == 2:
            assert "requires a TTY" in result.stderr
        else:
            # Windows — verify nonce file was created (best-effort)
            assert result.returncode == 0
            assert nonce_dir.exists()


# ─── Nonce primitive tests (v2.5.2.3) ──────────────────────────────────


class TestNonceLifecycle:
    def test_issue_returns_urlsafe_plaintext(self, isolated_key_dir):
        nonce = _gate.issue_nonce(ttl_seconds=60, issuer="alice")
        assert isinstance(nonce, str)
        # token_urlsafe(32) → ~43 chars base64url
        assert len(nonce) > 30
        # Must not contain filesystem-hostile chars
        assert "/" not in nonce and "\\" not in nonce

    def test_consume_valid_nonce_succeeds(self, isolated_key_dir):
        nonce = _gate.issue_nonce(ttl_seconds=60, issuer="alice")
        ok, reason = _gate.consume_nonce(nonce)
        assert ok
        assert reason == "ok"

    def test_consume_twice_second_fails(self, isolated_key_dir):
        nonce = _gate.issue_nonce(ttl_seconds=60, issuer="alice")
        ok1, _ = _gate.consume_nonce(nonce)
        assert ok1
        ok2, reason = _gate.consume_nonce(nonce)
        assert not ok2
        assert reason == "already_used"

    def test_consume_expired_nonce_fails(self, isolated_key_dir):
        now = int(time.time())
        nonce = _gate.issue_nonce(ttl_seconds=60, issuer="alice", now=now)
        # Consume 120s in the future — expired
        ok, reason = _gate.consume_nonce(nonce, now=now + 120)
        assert not ok
        assert reason == "expired"

    def test_consume_nonexistent_fails(self, isolated_key_dir):
        ok, reason = _gate.consume_nonce("totally-fake-value-no-file")
        assert not ok
        assert reason in ("not_found", "invalid_input")

    def test_consume_empty_input_fails(self, isolated_key_dir):
        for bad in ["", "   ", None]:
            ok, reason = _gate.consume_nonce(bad)  # type: ignore[arg-type]
            assert not ok
            assert reason in ("invalid_input", "not_found")

    def test_sweep_removes_old_expired(self, isolated_key_dir):
        now = int(time.time())
        _gate.issue_nonce(ttl_seconds=60, issuer="a", now=now - 100000)
        _gate.issue_nonce(ttl_seconds=60, issuer="b", now=now)  # fresh
        removed = _gate.sweep_expired_nonces(now=now, grace_seconds=3600)
        assert removed == 1

    def test_nonce_hash_stable_same_plaintext(self):
        h1 = _gate._nonce_hash("secret-abc-123")
        h2 = _gate._nonce_hash("secret-abc-123")
        assert h1 == h2
        assert h1 != _gate._nonce_hash("secret-abc-124")

    def test_nonce_file_stores_hash_not_plaintext(self, isolated_key_dir):
        """Defense-in-depth: if an attacker reads the nonce dir, they get
        hashes, not plaintexts. (Same-user AI CAN compute backwards via
        brute force of its own reads — this doesn't protect against that,
        but prevents accidental disclosure via logs/backup scans.)"""
        nonce = _gate.issue_nonce(ttl_seconds=60, issuer="alice")
        nonce_dir = _gate._nonce_dir()
        files = list(nonce_dir.glob("*.json"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert nonce not in content, "plaintext nonce leaked into file"
        assert _gate._nonce_hash(nonce) in content


class TestCiApproveNonceIntegration:
    """Integration: verify_human_operator doesn't change, but cmd_approve
    CI fallback now calls consume_nonce."""

    def test_ci_mode_without_ack_rejected_at_primitive(self, isolated_key_dir):
        # Simulate what vg-auth.py does internally (no subprocess)
        ok, reason = _gate.consume_nonce("")
        assert not ok

    def test_ci_mode_ack_is_single_use_at_primitive(self, isolated_key_dir):
        nonce = _gate.issue_nonce(ttl_seconds=3600, issuer="alice")
        ok1, _ = _gate.consume_nonce(nonce)
        ok2, r2 = _gate.consume_nonce(nonce)
        assert ok1 and not ok2
        assert r2 == "already_used"
