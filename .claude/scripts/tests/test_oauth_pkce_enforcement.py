"""
Tests for verify-oauth-pkce-enforcement.py — Phase M Batch 2 of v2.5.2.

Covers:
  - Full PKCE + state + nonce → 0
  - Missing PKCE on public client → 1
  - State missing → 1
  - No OAuth detected → 0 (nothing to verify)
  - PKCE present but not S256 method → 1
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
             / "verify-oauth-pkce-enforcement.py")


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


class TestOAuthPkceEnforcement:
    def test_full_pkce_state_nonce_passes(self, tmp_path):
        _write(tmp_path / "auth.js", """
// Uses openid-client with PKCE, state, nonce
const { Issuer, generators } = require('openid-client');

async function buildAuthUrl(client) {
  const code_verifier = generators.codeVerifier();
  const code_challenge = generators.codeChallenge(code_verifier);
  const state = generators.state();
  const nonce = generators.nonce();
  return client.authorizationUrl({
    scope: 'openid email',
    code_challenge,
    code_challenge_method: 'S256',
    state,
    nonce,
  });
}

async function callback(req, storedState, storedNonce) {
  const params = client.callbackParams(req);
  if (params.state !== storedState) throw new Error('state mismatch');
  const tokenSet = await client.callback(redirect_uri, params, {
    code_verifier,
    state: storedState,
    nonce: storedNonce,
  });
  // verify_nonce check inside callback
  if (tokenSet.claims().nonce !== storedNonce) throw new Error('nonce mismatch');
  return tokenSet;
}
""")
        r = _run(["--project-root", str(tmp_path), "--quiet"])
        assert r.returncode == 0, f"stdout={r.stdout} stderr={r.stderr}"

    def test_missing_pkce_on_public_client_blocks(self, tmp_path):
        _write(tmp_path / "oauth.js", """
// Public SPA client, uses passport-oauth2 but no PKCE
const passport = require('passport-oauth2');
const public_client = true;
function authorizeUrl() {
  return '/oauth/authorize?client_id=abc&state=xyz';
}
function callback(req) {
  if (req.query.state !== req.session.state) throw 'bad state';
}
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        assert "pkce" in r.stdout.lower()

    def test_state_missing_blocks(self, tmp_path):
        _write(tmp_path / "oauth.js", """
const passport = require('passport-oauth2');
// PKCE present, but NO state param anywhere
function build() {
  return '/oauth/authorize?code_challenge=abc&code_challenge_method=S256';
}
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        assert "state" in r.stdout.lower()

    def test_no_oauth_detected_passes(self, tmp_path):
        _write(tmp_path / "utils.js", """
function hello() { return 'world'; }
module.exports = { hello };
""")
        r = _run(["--project-root", str(tmp_path), "--quiet"])
        assert r.returncode == 0

    def test_pkce_plain_method_blocked(self, tmp_path):
        _write(tmp_path / "oauth.js", """
// passport-oauth2 confidential-ish but insecure PKCE method
const passport = require('passport-oauth2');
function build() {
  return buildUrl({
    code_challenge: 'abc',
    code_challenge_method: 'plain',
    state: 'xyz',
  });
}
function cb(req, stored) {
  if (req.query.state === stored) return ok();
}
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        out = r.stdout.lower()
        assert "s256" in out or "plain" in out

    def test_json_output_parseable(self, tmp_path):
        _write(tmp_path / "oauth.js", """
const passport = require('passport-oauth2');
function build() { return '/oauth/authorize?state=x&code_challenge=y&code_challenge_method=S256'; }
function cb(r, s) { if (r.query.state === s) return 1; }
""")
        r = _run(["--project-root", str(tmp_path), "--json"])
        data = json.loads(r.stdout)
        assert data["validator"] == "verify-oauth-pkce-enforcement"
        assert "verdict" in data
        assert data["oauth_detected"] is True
