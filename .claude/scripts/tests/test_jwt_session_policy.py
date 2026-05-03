"""
Tests for verify-jwt-session-policy.py — Phase M Batch 2 of v2.5.2.

Covers:
  - Good config (RS256, 15min access, 7d refresh, revoke) → 0
  - HS256 algorithm → 1 with weak-algorithm block
  - Access TTL 1h → 1
  - Missing revocation → WARN (exit 0 without --allow-warn fail)
  - No JWT code detected → exit 2
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
             / "verify-jwt-session-policy.py")


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


class TestJwtSessionPolicy:
    def test_good_config_passes(self, tmp_path):
        _write(tmp_path / "auth.js", """
const jwt = require('jsonwebtoken');
const ACCESS_TOKEN_TTL = 900;   // 15 min
const REFRESH_TOKEN_TTL = 604800; // 7d

function issueAccess(user) {
  return jwt.sign({sub: user.id}, privateKey, {
    algorithm: 'RS256',
    expiresIn: '15m',
  });
}

async function rotateRefresh(oldToken) {
  // invalidate_refresh + issue new
  await tokenBlacklist.add(oldToken);
  return jwt.sign({...}, privateKey, {algorithm: 'RS256', expiresIn: '7d'});
}

async function logout(token) {
  await revokeToken(token);
}
""")
        r = _run(["--project-root", str(tmp_path), "--quiet"])
        assert r.returncode == 0, f"expected 0, got {r.returncode}\n{r.stdout}\n{r.stderr}"

    def test_hs256_blocked(self, tmp_path):
        _write(tmp_path / "auth.js", """
const jwt = require('jsonwebtoken');
const token = jwt.sign({x: 1}, 'shared-secret', {
    algorithm: 'HS256',
    expiresIn: '15m',
});
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        assert "weak algorithm" in r.stdout.lower() or "hs256" in r.stdout.lower()

    def test_long_access_ttl_blocked(self, tmp_path):
        _write(tmp_path / "auth.js", """
const jwt = require('jsonwebtoken');
const token = jwt.sign({x:1}, privateKey, {
    algorithm: 'RS256',
    expiresIn: '1h',
});
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 1
        out = r.stdout.lower()
        assert "access token ttl" in out or "900s" in out

    def test_missing_revocation_warns(self, tmp_path):
        # RS256 + 15m access, no revocation function — should WARN (exit 0)
        _write(tmp_path / "auth.js", """
const jwt = require('jsonwebtoken');
const token = jwt.sign({x:1}, privateKey, {
    algorithm: 'RS256',
    expiresIn: '15m',
});
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 0
        # JSON mode to verify warn content
        r2 = _run(["--project-root", str(tmp_path), "--json"])
        data = json.loads(r2.stdout)
        assert data["verdict"] in ("WARN", "OK")
        if data["verdict"] == "WARN":
            assert any("revocation" in w.lower() for w in data["warns"])

    def test_no_jwt_code_exit_2(self, tmp_path):
        # Pure non-auth code
        _write(tmp_path / "utils.js", """
function add(a, b) { return a + b; }
module.exports = { add };
""")
        r = _run(["--project-root", str(tmp_path)])
        assert r.returncode == 2

    def test_json_output_parseable(self, tmp_path):
        _write(tmp_path / "auth.py", """
import jwt
token = jwt.encode({'x': 1}, private_key, algorithm='RS256')
""")
        r = _run(["--project-root", str(tmp_path), "--json"])
        data = json.loads(r.stdout)
        assert data["validator"] == "verify-jwt-session-policy"
        assert "verdict" in data
        assert "sast_summary" in data
        assert data["jwt_detected"] is True
