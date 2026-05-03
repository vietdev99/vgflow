"""
Tests for verify-auth-flow-smoke.py — UNQUARANTINABLE.

Static smoke test for auth flow integrity. 6 checks: login/logout pair,
**Auth:** declaration, rate-limit, login form shape, email enumeration
protection, reset token TTL.

Covers:
  - Missing phase-dir → PASS (graceful)
  - Phase with no auth endpoints → PASS (skip)
  - Login WITH logout pair → PASS
  - Login WITHOUT logout → BLOCK (C1)
  - Auth endpoint WITHOUT **Auth:** declaration → BLOCK (C2)
  - Login WITHOUT rate-limit → BLOCK (C3)
  - forgot-password without enum protection → BLOCK (C5)
  - reset-password without TTL → WARN (C6)
  - --strict escalates WARN to BLOCK
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-auth-flow-smoke.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _setup(tmp_path: Path, contracts: str, slug: str = "99.0-auth") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    (pdir / "API-CONTRACTS.md").write_text(contracts, encoding="utf-8")
    return pdir


COMPLETE_AUTH = """# API Contracts

### POST /api/auth/login

**Auth:** public
**Rate-limit:** 5/min per IP, 10/hour per email

Login endpoint.

### POST /api/auth/logout

**Auth:** session
"""

NO_LOGOUT = """# API Contracts

### POST /api/auth/login

**Auth:** public
**Rate-limit:** 5/min
"""

NO_AUTH_DECL = """# API Contracts

### POST /api/auth/login

**Rate-limit:** 5/min

### POST /api/auth/logout

**Auth:** session
"""

NO_RATE_LIMIT = """# API Contracts

### POST /api/auth/login

**Auth:** public

Login.

### POST /api/auth/logout

**Auth:** session
"""

FORGOT_NO_ENUM_PROTECT = """# API Contracts

### POST /api/auth/login
**Auth:** public
**Rate-limit:** 5/min

### POST /api/auth/logout
**Auth:** session

### POST /api/auth/forgot-password
**Auth:** public
**Rate-limit:** 3/min

Sends reset email.
"""

FORGOT_WITH_ENUM_PROTECT = """# API Contracts

### POST /api/auth/login
**Auth:** public
**Rate-limit:** 5/min

### POST /api/auth/logout
**Auth:** session

### POST /api/auth/forgot-password
**Auth:** public
**Rate-limit:** 3/min

Returns 200 with generic response regardless of email existence to
prevent email enumeration.
"""

RESET_NO_TTL = """# API Contracts

### POST /api/auth/login
**Auth:** public
**Rate-limit:** 5/min

### POST /api/auth/logout
**Auth:** session

### POST /api/auth/reset-password
**Auth:** public
**Rate-limit:** 5/min

Resets the password.
"""


class TestAuthFlowSmoke:
    def test_missing_phase_graceful(self, tmp_path):
        r = _run(["--phase", "99.99"], tmp_path)
        assert r.returncode == 0
        assert "Traceback" not in r.stderr

    def test_no_auth_endpoints_skips(self, tmp_path):
        _setup(tmp_path, "# API\n### GET /api/users\n**Auth:** session\n")
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"non-auth phase should PASS, stdout={r.stdout}"

    def test_complete_auth_flow_passes(self, tmp_path):
        _setup(tmp_path, COMPLETE_AUTH)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"complete flow should PASS, stdout={r.stdout}"

    def test_login_without_logout_blocks(self, tmp_path):
        _setup(tmp_path, NO_LOGOUT)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"missing logout should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_missing_auth_declaration_blocks(self, tmp_path):
        _setup(tmp_path, NO_AUTH_DECL)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"missing **Auth:** should BLOCK, rc={r.returncode}, stdout={r.stdout}"

    def test_missing_rate_limit_blocks(self, tmp_path):
        _setup(tmp_path, NO_RATE_LIMIT)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"missing rate-limit should BLOCK, rc={r.returncode}, stdout={r.stdout}"

    def test_forgot_password_no_enum_protection_blocks(self, tmp_path):
        _setup(tmp_path, FORGOT_NO_ENUM_PROTECT)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"forgot-password without enum protect should BLOCK, stdout={r.stdout}"

    def test_forgot_password_with_enum_protection_passes(self, tmp_path):
        _setup(tmp_path, FORGOT_WITH_ENUM_PROTECT)
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, \
            f"forgot-password with enum protect should PASS, stdout={r.stdout}"

    def test_reset_password_no_ttl_warns(self, tmp_path):
        _setup(tmp_path, RESET_NO_TTL)
        r = _run(["--phase", "99.0"], tmp_path)
        # WARN — rc=0 but verdict=WARN
        assert r.returncode == 0, \
            f"missing TTL should WARN (not BLOCK), rc={r.returncode}, stdout={r.stdout}"
        verdict = _verdict(r.stdout)
        assert verdict in ("WARN", "PASS")

    def test_strict_escalates_warn_to_block(self, tmp_path):
        _setup(tmp_path, RESET_NO_TTL)
        r = _run(["--phase", "99.0", "--strict"], tmp_path)
        # With --strict, missing TTL becomes BLOCK
        assert r.returncode == 1, \
            f"--strict should escalate WARN→BLOCK, rc={r.returncode}, stdout={r.stdout}"
