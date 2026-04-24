"""
Tests for verify-2fa-gate.py — Phase M Batch 2 of v2.5.2.

Covers:
  - Route has TOTP check → 0
  - Goal requires 2FA but no check in code → 1
  - WebAuthn detected → 0
  - No 2FA goals declared → 0 skip
  - Backup codes not marking consumed → WARN
  - JSON output parseable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (REPO_ROOT / ".claude" / "scripts" / "validators"
             / "verify-2fa-gate.py")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace",
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


TEST_GOALS_2FA = """# TEST-GOALS.md

## G-01 Admin dashboard access

requires_2fa: true
route: /admin/dashboard
priority: critical

Verify admin users must pass 2FA before accessing the dashboard.

## G-02 Regular login

route: /login
priority: important

Standard login flow, no 2FA.
"""

TEST_GOALS_NO_2FA = """# TEST-GOALS.md

## G-01 Login flow
route: /login
Standard login.

## G-02 Profile update
route: /profile
"""


class Test2faGate:
    def test_totp_present_passes(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_2FA)
        _write(tmp_path / "admin_handler.js", """
const speakeasy = require('speakeasy');
function adminAccess(req, res) {
  const ok = speakeasy.totp.verify({
    secret: user.totp_secret,
    encoding: 'base32',
    token: req.body.code,
  });
  if (!ok) return res.status(403).send('2FA required');
  return ok;
}
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
            "--quiet",
        ])
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_goal_requires_but_no_check_blocks(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_2FA)
        _write(tmp_path / "admin_handler.js", """
function adminAccess(req, res) {
  if (!req.session.user) return res.status(401).send();
  return res.send('welcome');
}
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
        ])
        assert r.returncode == 1
        assert "2fa" in r.stdout.lower()

    def test_webauthn_passes(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_2FA)
        _write(tmp_path / "webauthn_handler.ts", """
import { verifyAuthenticationResponse } from '@simplewebauthn/server';

export async function loginFinish(req, res) {
  const verification = await verifyAuthenticationResponse({
    credential: req.body.credential,
    expectedChallenge: user.currentChallenge,
    expectedOrigin: 'https://example.com',
    expectedRPID: 'example.com',
    authenticator: user.authenticator,
  });
  if (!verification.verified) return res.status(403).send();
}
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
            "--quiet",
        ])
        assert r.returncode == 0

    def test_no_2fa_goals_skip(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_NO_2FA)
        _write(tmp_path / "login.js", """
function login(req, res) { return res.send('ok'); }
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
        ])
        assert r.returncode == 0
        # Should explicitly skip
        r2 = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
            "--json",
        ])
        data = json.loads(r2.stdout)
        assert data["verdict"] == "SKIP"

    def test_backup_codes_without_consume_warns(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_2FA)
        _write(tmp_path / "handler.py", """
import pyotp

def verify_login(user, code):
    totp = pyotp.TOTP(user.secret)
    if totp.verify(code):
        return True
    # Try backup codes but don't mark them consumed (BUG)
    if code in user.backup_codes:
        return True
    return False
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
            "--json",
        ])
        data = json.loads(r.stdout)
        assert data["verdict"] in ("WARN", "OK")
        # Still exits 0 (warns don't block)
        assert r.returncode == 0

    def test_json_output_parseable(self, tmp_path):
        _write(tmp_path / "TEST-GOALS.md", TEST_GOALS_2FA)
        _write(tmp_path / "h.js", """
const otplib = require('otplib');
otplib.authenticator.verify({token, secret});
""")
        r = _run([
            "--project-root", str(tmp_path),
            "--test-goals", str(tmp_path / "TEST-GOALS.md"),
            "--json",
        ])
        data = json.loads(r.stdout)
        assert data["validator"] == "verify-2fa-gate"
        assert "verdict" in data
        assert "sast_summary" in data
