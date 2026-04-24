"""
Tests for verify-authz-negative-paths.py — Phase M Batch 1 of v2.5.2.

Mock HTTP server checks Authorization header against embedded tenant→token
map; returns 200 for owner, 403 for non-owner (properly) OR 200
for everyone (leak).

Covers:
  - Proper 403 on cross-tenant access → OK
  - Cross-tenant leak (200 returned to non-owner) → BLOCK
  - Fixtures file missing → exit 2
  - Role escalation (user accessing admin route) → BLOCK
  - Multiple resources probed
  - JSON output parseable
  - --allow-status overrides default
  - Empty fixtures → WARN exit 0
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-authz-negative-paths.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace",
    )


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make_handler(token_map: dict, leak: bool = False,
                  admin_routes: set | None = None):
    """token_map: {token: tenant_or_role}. leak=True = always 200."""
    admin_routes = admin_routes or set()

    class H(http.server.BaseHTTPRequestHandler):
        def _respond(self, code: int, body: bytes = b"{}"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            auth = self.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "").strip() if auth else ""
            identity = token_map.get(token)

            if leak:
                return self._respond(200, b'{"data":"leaked"}')

            path = self.path

            # Admin-route: require role=admin
            if path in admin_routes:
                if identity == "admin":
                    return self._respond(200)
                return self._respond(403)

            # Resource path: /api/res/{id}, tenant owner determined by
            # path prefix — /api/res-A/* owned by tenant A, etc.
            if path.startswith("/api/res-A/"):
                if identity == "A":
                    return self._respond(200)
                return self._respond(403)
            if path.startswith("/api/res-B/"):
                if identity == "B":
                    return self._respond(200)
                return self._respond(403)

            return self._respond(404)

        def log_message(self, *a, **kw):
            return
    return H


@contextmanager
def mock_server(token_map: dict, leak: bool = False,
                admin_routes=None):
    port = _free_port()
    server = socketserver.TCPServer(("127.0.0.1", port),
                                     _make_handler(token_map, leak,
                                                   admin_routes))
    server.allow_reuse_address = True
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _write_fixtures(path: Path, users: list, resources: list) -> None:
    path.write_text(json.dumps({
        "users": users, "resources": resources,
    }), encoding="utf-8")


class TestAuthzNegativePaths:
    def test_proper_403_passes(self, tmp_path):
        token_map = {"tokA": "A", "tokB": "B"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokA", "tenant": "A", "role": "user"},
            {"token": "tokB", "tenant": "B", "role": "user"},
        ], [
            {"path": "/api/res-A/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET"},
        ])
        with mock_server(token_map) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures),
                      "--quiet"])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_cross_tenant_leak_blocks(self, tmp_path):
        token_map = {"tokA": "A", "tokB": "B"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokA", "tenant": "A", "role": "user"},
            {"token": "tokB", "tenant": "B", "role": "user"},
        ], [
            {"path": "/api/res-A/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET"},
        ])
        # leak=True: server returns 200 to everyone
        with mock_server(token_map, leak=True) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures)])
        assert r.returncode == 1
        assert "leak" in r.stdout.lower() or "cross" in r.stdout.lower()

    def test_fixtures_missing_returns_2(self, tmp_path):
        r = _run(["--target-url", "http://127.0.0.1:1",
                  "--fixtures", str(tmp_path / "nope.json")])
        assert r.returncode == 2

    def test_role_escalation_detected(self, tmp_path):
        # user token trying admin route → server returns 403
        # user token treating admin route as resource → should 403
        # If server broken (leak), non-admin gets 200 = escalation
        token_map = {"tokUser": "user", "tokAdmin": "admin"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokAdmin", "tenant": "A", "role": "admin"},
            {"token": "tokUser", "tenant": "A", "role": "user"},
        ], [
            {"path": "/api/res-A/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET", "role_required": "admin"},
        ])
        # leak=True: user gets 200 on admin-gated resource
        with mock_server(token_map, leak=True) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures)])
        assert r.returncode == 1

    def test_multiple_resources_probed(self, tmp_path):
        token_map = {"tokA": "A", "tokB": "B"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokA", "tenant": "A", "role": "user"},
            {"token": "tokB", "tenant": "B", "role": "user"},
        ], [
            {"path": "/api/res-A/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET"},
            {"path": "/api/res-B/{id}", "owned_by_tenant": "B",
             "id": "r2", "method": "GET"},
        ])
        with mock_server(token_map) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures),
                      "--json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["resources"] == 2
        assert data["probes_count"] >= 2

    def test_json_output_parseable(self, tmp_path):
        token_map = {"tokA": "A"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokA", "tenant": "A", "role": "user"},
        ], [
            {"path": "/api/res-A/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET"},
        ])
        with mock_server(token_map) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures),
                      "--json"])
        data = json.loads(r.stdout)
        assert "target" in data
        assert "violations" in data

    def test_allow_status_404_accepted(self, tmp_path):
        # fixtures point to resource server doesn't own at all (404)
        # default allow_status includes 404 already, so OK
        token_map = {"tokA": "A"}
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [
            {"token": "tokA", "tenant": "A", "role": "user"},
            {"token": "tokB", "tenant": "B", "role": "user"},
        ], [
            {"path": "/api/unknown/{id}", "owned_by_tenant": "A",
             "id": "r1", "method": "GET"},
        ])
        with mock_server(token_map) as url:
            # Server returns 404 for this path; --allow-status 404 = OK for
            # non-owner. But owner also gets 404 → warn but no block.
            r = _run(["--target-url", url, "--fixtures", str(fixtures),
                      "--allow-status", "403,404"])
        # No BLOCK (404 = acceptable denial + no leak)
        assert r.returncode == 0

    def test_empty_fixtures_warns(self, tmp_path):
        fixtures = tmp_path / "fix.json"
        _write_fixtures(fixtures, [], [])
        with mock_server({}) as url:
            r = _run(["--target-url", url, "--fixtures", str(fixtures)])
        assert r.returncode == 0
