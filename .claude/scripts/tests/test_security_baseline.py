"""
Phase B.3 v2.5 (2026-04-23) — verify-security-baseline.py tests.

Validates project-wide security baseline:
- TLS < 1.2 explicit → BLOCK
- Wildcard CORS + credentials: true → BLOCK
- Real secret in .env.example → BLOCK
- Missing helmet/HSTS → WARN
- Missing cookie flags → WARN
- Missing lockfile → WARN
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (
    REPO_ROOT / ".claude" / "scripts" / "validators"
    / "verify-security-baseline.py"
)


def _setup(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create files at given relative paths and copy narration yaml."""
    for rel_path, content in files.items():
        fp = tmp_path / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(
                s.read_text(encoding="utf-8"), encoding="utf-8",
            )
    return tmp_path


def _run(repo: Path, scope: str = "all") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--scope", scope],
        cwd=repo, capture_output=True, text=True, timeout=20, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON:\n{stdout}")


def _ev_types(out: dict) -> list[str]:
    return [e["type"] for e in out.get("evidence", [])]


# ─────────────────────────────────────────────────────────────────────────
# Fixtures: canonical "healthy" files we can mix in
# ─────────────────────────────────────────────────────────────────────────

GOOD_NGINX = """\
server {
    listen 443 ssl;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
}
"""

BAD_NGINX_TLS10 = """\
server {
    listen 443 ssl;
    ssl_protocols TLSv1.0 TLSv1.1 TLSv1.2;
}
"""

BAD_SSLV3 = """\
server {
    listen 443 ssl;
    ssl_protocols SSLv3 TLSv1.2;
}
"""

GOOD_ROUTE_WITH_HELMET = """\
import Fastify from 'fastify';
import helmet from '@fastify/helmet';
const app = Fastify();
app.register(helmet, {
  contentSecurityPolicy: false,
  hsts: { maxAge: 31536000, includeSubDomains: true, preload: true },
});
// Strict-Transport-Security: max-age=31536000
app.setCookie('session', token, {
  Secure: true,
  HttpOnly: true,
  SameSite: 'Strict',
});
app.register(cors, { origin: ['https://vollx.com'], credentials: true });
"""

ROUTE_NO_HELMET = """\
import Fastify from 'fastify';
const app = Fastify();
app.get('/api/v1/health', async () => ({ ok: true }));
app.register(cors, { origin: ['https://vollx.com'], credentials: true });
app.setCookie('session', token, {
  Secure: true,
  HttpOnly: true,
  SameSite: 'Strict',
});
"""

ROUTE_CORS_WILDCARD_CREDS = """\
import Fastify from 'fastify';
import cors from '@fastify/cors';
import helmet from '@fastify/helmet';
const app = Fastify();
app.register(helmet);
// Strict-Transport-Security header set
app.register(cors, {
  origin: '*',
  credentials: true,
});
"""

ROUTE_CORS_WILDCARD_NO_CREDS = """\
import Fastify from 'fastify';
import cors from '@fastify/cors';
import helmet from '@fastify/helmet';
const app = Fastify();
app.register(helmet);
// Strict-Transport-Security set
app.register(cors, {
  origin: '*',
});
"""

ROUTE_COOKIE_MISSING_SAMESITE = """\
import Fastify from 'fastify';
import helmet from '@fastify/helmet';
const app = Fastify();
app.register(helmet);
// Strict-Transport-Security: max-age
app.setCookie('session', token, {
  Secure: true,
  HttpOnly: true,
});
"""

ENV_WITH_REAL_SECRET = """\
# App config
APP_NAME=vollx
APP_PORT=3000
JWT_SECRET=aB3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4Yz5Ab6Cd7Ef8Gh9
API_URL=https://api.vollx.com
"""

ENV_WITH_UUID_SECRET = """\
APP_NAME=vollx
TENANT_ID=a7f3c9b1-2e4d-4a6f-9b8c-1d2e3f4a5b6c
"""

ENV_WITH_PLACEHOLDERS = """\
APP_NAME=vollx
JWT_SECRET=your-jwt-secret-here
API_KEY=replace-me
STRIPE_KEY=sk_test_placeholder_xxx
DB_URL=postgresql://user:changeme@localhost:5432/db
"""

PACKAGE_JSON = """\
{
  "name": "vollx",
  "private": true,
  "dependencies": {
    "fastify": "^4.0.0"
  }
}
"""

LOCKFILE_CONTENT = """\
{
  "name": "vollx",
  "version": "0.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {}
}
"""


# ─────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────


def test_tls_12_ok_passes(tmp_path):
    """nginx.conf with TLSv1.2+1.3 should not trigger tls_outdated."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo, "deploy")
    out = _parse(r.stdout)
    assert "tls_outdated" not in _ev_types(out), (
        f"unexpected tls_outdated: {out}"
    )
    # Should PASS — good TLS, no outdated
    assert r.returncode == 0


def test_tls_10_explicit_blocks(tmp_path):
    """TLSv1.0 explicit in ssl_protocols → BLOCK."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": BAD_NGINX_TLS10,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "tls_outdated" in _ev_types(out)


def test_sslv3_explicit_blocks(tmp_path):
    """SSLv3 explicit → BLOCK."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": BAD_SSLV3,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "tls_outdated" in _ev_types(out)


def test_cors_wildcard_with_credentials_blocks(tmp_path):
    """origin: '*' + credentials: true → HARD BLOCK (critical vuln)."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": ROUTE_CORS_WILDCARD_CREDS,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "cors_wildcard_credentials" in _ev_types(out)


def test_cors_wildcard_no_credentials_does_not_block(tmp_path):
    """origin: '*' without credentials → no BLOCK."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": ROUTE_CORS_WILDCARD_NO_CREDS,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    # Should not block on CORS wildcard when no credentials
    assert r.returncode == 0
    assert "cors_wildcard_credentials" not in _ev_types(out)


def test_real_secret_in_env_example_blocks(tmp_path):
    """Real 32+ char base64-ish secret in .env.example → BLOCK."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
        ".env.example": ENV_WITH_REAL_SECRET,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "secret_in_example" in _ev_types(out)


def test_uuid_secret_in_env_example_blocks(tmp_path):
    """UUID v4 in .env.example → BLOCK."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
        ".env.example": ENV_WITH_UUID_SECRET,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "secret_in_example" in _ev_types(out)


def test_placeholder_in_env_example_passes(tmp_path):
    """your-jwt-secret-here / replace-me placeholders → PASS."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
        ".env.example": ENV_WITH_PLACEHOLDERS,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert "secret_in_example" not in _ev_types(out), (
        f"placeholder falsely flagged: {out}"
    )


def test_helmet_present_passes(tmp_path):
    """Route imports @fastify/helmet + registers → no headers_missing."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert "headers_missing" not in _ev_types(out), (
        f"helmet present but still flagged: {out}"
    )


def test_headers_missing_warns(tmp_path):
    """Route without helmet → WARN headers_missing."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": ROUTE_NO_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    # WARN, not BLOCK
    assert r.returncode == 0
    assert "headers_missing" in _ev_types(out)


def test_hsts_present_passes(tmp_path):
    """Route has Strict-Transport-Security → no hsts_missing."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert "hsts_missing" not in _ev_types(out)


def test_hsts_missing_warns(tmp_path):
    """Route without HSTS (require_hsts=true default) → WARN."""
    route_helmet_no_hsts = """\
import Fastify from 'fastify';
import helmet from '@fastify/helmet';
const app = Fastify();
app.register(helmet, { hsts: false });
app.register(cors, { origin: ['https://vollx.com'] });
app.setCookie('session', token, {
  Secure: true,
  HttpOnly: true,
  SameSite: 'Strict',
});
"""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": route_helmet_no_hsts,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    # WARN not BLOCK
    assert r.returncode == 0
    assert "hsts_missing" in _ev_types(out)


def test_cookie_samesite_missing_warns(tmp_path):
    """Cookie setup without SameSite → WARN cookie_flags_missing."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": ROUTE_COOKIE_MISSING_SAMESITE,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert "cookie_flags_missing" in _ev_types(out)


def test_lockfile_present_passes(tmp_path):
    """package-lock.json on disk → no lockfile_missing."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package-lock.json": LOCKFILE_CONTENT,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert "lockfile_missing" not in _ev_types(out)


def test_lockfile_missing_warns(tmp_path):
    """No lockfile anywhere → WARN."""
    repo = _setup(tmp_path, {
        "infra/nginx.conf": GOOD_NGINX,
        "apps/api/src/server.ts": GOOD_ROUTE_WITH_HELMET,
        "package.json": PACKAGE_JSON,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert "lockfile_missing" in _ev_types(out)
