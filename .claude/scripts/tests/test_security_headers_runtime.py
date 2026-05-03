"""
Tests for verify-security-headers-runtime.py — Phase M Batch 1 of v2.5.2.

Mock HTTP server emits configurable response headers; validator probes
and asserts on required + recommended headers.

Covers:
  - All required headers present → OK
  - HSTS max-age below threshold → BLOCK
  - Missing CSP → BLOCK
  - X-Frame-Options ALLOWALL → WARN
  - Multiple paths checked
  - JSON output parseable
  - --require-recommended turns Referrer/Permissions missing into BLOCK
  - localhost http + missing HSTS → WARN only
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
    "verify-security-headers-runtime.py"


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


def _make_handler(headers: dict):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a, **kw):
            return
    return H


@contextmanager
def mock_server(headers: dict):
    port = _free_port()
    server = socketserver.TCPServer(("127.0.0.1", port), _make_handler(headers))
    server.allow_reuse_address = True
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


FULL_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=()",
}


class TestSecurityHeaders:
    def test_all_required_present_passes(self):
        with mock_server(FULL_HEADERS) as url:
            r = _run(["--target-url", url, "--quiet"])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_hsts_too_short_blocks(self):
        h = dict(FULL_HEADERS)
        h["Strict-Transport-Security"] = "max-age=3600"
        with mock_server(h) as url:
            r = _run(["--target-url", url])
        assert r.returncode == 1
        assert "max-age" in r.stdout.lower()

    def test_missing_csp_blocks(self):
        h = dict(FULL_HEADERS)
        del h["Content-Security-Policy"]
        with mock_server(h) as url:
            r = _run(["--target-url", url])
        assert r.returncode == 1
        assert "Content-Security-Policy" in r.stdout or "CSP" in r.stdout

    def test_xframe_allowall_warns(self):
        h = dict(FULL_HEADERS)
        h["X-Frame-Options"] = "ALLOWALL"
        with mock_server(h) as url:
            r = _run(["--target-url", url])
        # ALLOWALL is WARN severity, not BLOCK
        assert r.returncode == 0
        assert "WARN" in r.stdout or "warn" in r.stdout.lower()

    def test_multiple_paths_all_checked(self):
        with mock_server(FULL_HEADERS) as url:
            r = _run(["--target-url", url, "--paths", "/,/api/health,/foo",
                      "--json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["results"]) == 3

    def test_json_output_parseable(self):
        with mock_server(FULL_HEADERS) as url:
            r = _run(["--target-url", url, "--json"])
        data = json.loads(r.stdout)
        assert "target" in data
        assert "block_count" in data
        assert data["block_count"] == 0

    def test_require_recommended_escalates_warns(self):
        h = dict(FULL_HEADERS)
        del h["Referrer-Policy"]
        del h["Permissions-Policy"]
        with mock_server(h) as url:
            r = _run(["--target-url", url, "--require-recommended"])
        assert r.returncode == 1
        assert "Referrer-Policy" in r.stdout or "Permissions-Policy" in r.stdout

    def test_localhost_http_missing_hsts_warns_only(self):
        h = dict(FULL_HEADERS)
        del h["Strict-Transport-Security"]
        with mock_server(h) as url:
            # url is http://127.0.0.1:... — HSTS missing = WARN only
            r = _run(["--target-url", url])
        assert r.returncode == 0
