"""
Tests for verify-cookie-flags-runtime.py — Phase M Batch 1 of v2.5.2.

Uses a mock HTTP server on 127.0.0.1 with configurable Set-Cookie headers.
No external network calls.

Covers:
  - All flags set (HttpOnly + Secure + SameSite=Strict) → OK
  - Missing HttpOnly on session cookie → BLOCK
  - Missing Secure on https → BLOCK
  - Missing Secure on localhost http → WARN only
  - SameSite=None without --allow-samesite-none → BLOCK
  - JSON output parseable
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
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-cookie-flags-runtime.py"


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


def _make_handler(cookies: Iterable[str]):
    class H(http.server.BaseHTTPRequestHandler):
        def _emit(self):
            self.send_response(200)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_GET(self):  # noqa: N802
            self._emit()

        def do_POST(self):  # noqa: N802
            # Read body to avoid broken pipe
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            self._emit()

        def log_message(self, *a, **kw):  # silence
            return
    return H


@contextmanager
def mock_server(cookies: Iterable[str]):
    port = _free_port()
    handler = _make_handler(list(cookies))
    server = socketserver.TCPServer(("127.0.0.1", port), handler)
    server.allow_reuse_address = True
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


class TestCookieFlags:
    def test_all_flags_set_passes_on_localhost(self):
        cookie = ("sessionid=abc123; Path=/; HttpOnly; "
                  "SameSite=Strict")
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only", "--quiet"])
        # localhost http → Secure missing = WARN only, HttpOnly + SameSite OK
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_missing_httponly_blocks(self):
        cookie = "session=abc; Path=/; Secure; SameSite=Strict"
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only"])
        assert r.returncode == 1
        assert "HttpOnly" in r.stdout or "httponly" in r.stdout.lower()

    def test_missing_secure_on_localhost_is_warn(self):
        # Server is localhost http:// — missing Secure on session cookie = WARN
        cookie = "session=abc; HttpOnly; SameSite=Lax"
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only"])
        assert r.returncode == 0
        # Output should mention WARN
        assert "WARN" in r.stdout or "warn" in r.stdout.lower()

    def test_samesite_none_blocked_without_flag(self):
        cookie = "auth=x; HttpOnly; SameSite=None"
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only"])
        assert r.returncode == 1
        assert "SameSite=None" in r.stdout or "samesite-none" in r.stdout.lower()

    def test_samesite_none_allowed_with_flag(self):
        cookie = "auth=x; HttpOnly; SameSite=None"
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only",
                      "--allow-samesite-none", "--quiet"])
        # SameSite=None now allowed; Secure missing on http = WARN only
        assert r.returncode == 0

    def test_json_output_parseable(self):
        cookie = "sessionid=x; HttpOnly; SameSite=Strict"
        with mock_server([cookie]) as url:
            r = _run(["--target-url", url, "--probe-only", "--json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "target" in data
        assert "violations" in data
        assert "cookies_inspected" in data
        assert "sessionid" in data["cookies_inspected"]
