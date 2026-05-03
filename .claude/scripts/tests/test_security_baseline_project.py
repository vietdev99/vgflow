"""
Tests for verify-security-baseline-project.py — Phase M Batch 1 of v2.5.2.

Orchestrator integration tests: run against a mock HTTP server (serving
canonical security headers + a good session cookie) and verify the
sub-validators aggregate properly.

Covers:
  - No target URL + no --only → orchestrator still runs non-target subs (exit 0)
  - All sub-validators pass → exit 0
  - One critical sub-validator blocks → exit 1
  - Low-risk sub-validator blocks → exit 0 (warn only)
  - Waiver downgrades block to warn
  - --only filters to single sub-validator
  - JSON output parseable
  - Missing SECURITY-TEST-PLAN config → defaults used (no error)
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
    "verify-security-baseline-project.py"


def _run(args: list[str], cwd: Path | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace",
        cwd=str(cwd) if cwd else None,
    )


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


FULL_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=()",
}
GOOD_COOKIE = "sessionid=xyz; HttpOnly; SameSite=Strict; Path=/"


def _make_handler(headers: dict, cookies: list):
    class H(http.server.BaseHTTPRequestHandler):
        def _emit(self):
            self.send_response(200)
            for k, v in headers.items():
                self.send_header(k, v)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_GET(self):  # noqa: N802
            self._emit()

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            self._emit()

        def log_message(self, *a, **kw):
            return
    return H


@contextmanager
def mock_server(headers: dict, cookies: list):
    port = _free_port()
    server = socketserver.TCPServer(("127.0.0.1", port),
                                     _make_handler(headers, cookies))
    server.allow_reuse_address = True
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


class TestBaselineOrchestrator:
    def test_no_target_runs_non_target_subs(self, tmp_path):
        # Without target, container_hardening + dep_vuln can still run.
        # With --only container_hardening + no Dockerfile → exit 0
        r = _run(["--project-root", str(tmp_path),
                  "--only", "container_hardening", "--quiet"])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_all_subs_pass(self, tmp_path):
        with mock_server(FULL_HEADERS, [GOOD_COOKIE]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "cookie_flags,security_headers,container_hardening",
                "--quiet",
            ])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def test_critical_block_fails_orchestrator(self, tmp_path):
        # Missing HttpOnly → cookie_flags blocks (critical)
        bad_cookie = "sessionid=x; Secure; SameSite=Strict"
        with mock_server(FULL_HEADERS, [bad_cookie]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "cookie_flags",
            ])
        assert r.returncode == 1

    def test_low_risk_block_does_not_fail_orchestrator(self, tmp_path):
        # container_hardening is marked risk_profile=low in the orchestrator.
        # Create a Dockerfile that blocks (USER root + latest), run only it.
        df = tmp_path / "Dockerfile"
        df.write_text("FROM node:latest\nCMD node server.js\n",
                      encoding="utf-8")
        r = _run([
            "--project-root", str(tmp_path),
            "--only", "container_hardening",
        ])
        # Sub-validator exits 1, but orchestrator treats low-risk as warn
        assert r.returncode == 0

    def test_waiver_downgrades_block_to_warn(self, tmp_path):
        bad_cookie = "sessionid=x; Secure; SameSite=Strict"  # no HttpOnly
        # Write waiver file at default location
        (tmp_path / ".vg").mkdir(exist_ok=True)
        (tmp_path / ".vg" / "security-runtime-waivers.yml").write_text(
            "- validator: cookie_flags\n"
            "  reason: legacy-cookie-migration\n",
            encoding="utf-8",
        )
        with mock_server(FULL_HEADERS, [bad_cookie]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "cookie_flags",
            ])
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "WAIVED" in r.stdout or "waived" in r.stdout.lower()

    def test_only_filter_runs_single_sub(self, tmp_path):
        with mock_server(FULL_HEADERS, [GOOD_COOKIE]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "security_headers", "--json",
            ])
        data = json.loads(r.stdout)
        ran = [s for s in data["sub_validators"]
               if s.get("status") == "ran"]
        assert len(ran) == 1
        assert ran[0]["name"] == "security_headers"

    def test_json_output_parseable(self, tmp_path):
        with mock_server(FULL_HEADERS, [GOOD_COOKIE]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "cookie_flags,security_headers",
                "--json",
            ])
        data = json.loads(r.stdout)
        assert "aggregate_block_count" in data
        assert "sub_validators" in data
        assert len(data["sub_validators"]) >= 2

    def test_missing_config_uses_defaults(self, tmp_path):
        # No SECURITY-TEST-PLAN.md; orchestrator should still run with
        # its built-in defaults.
        with mock_server(FULL_HEADERS, [GOOD_COOKIE]) as url:
            r = _run([
                "--target-url", url,
                "--project-root", str(tmp_path),
                "--only", "cookie_flags", "--quiet",
            ])
        assert r.returncode == 0
