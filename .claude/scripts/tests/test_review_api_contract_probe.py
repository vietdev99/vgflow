from __future__ import annotations

import http.server
import socketserver
import subprocess
import sys
import textwrap
import threading
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "review-api-contract-probe.py"


def _serve():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/health":
                body = b'{"ok":true,"version":"1"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_OPTIONS(self):
            if self.path == "/api/items":
                self.send_response(204)
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_probe_passes_for_get_and_mutation_options(tmp_path):
    server, thread = _serve()
    try:
        contracts = tmp_path / "API-CONTRACTS.md"
        contracts.write_text(
            textwrap.dedent(
                """\
                # API Contracts

                ## GET /api/health
                **Auth:** Public

                ## POST /api/items
                **Auth:** Authenticated
                """
            ),
            encoding="utf-8",
        )
        out = tmp_path / "report.txt"
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--contracts",
                str(contracts),
                "--base-url",
                base_url,
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        report = out.read_text(encoding="utf-8")
        assert "PASS" in report
        assert "/api/health" in report
        assert "/api/items" in report
        assert "json_keys=ok,version" in report
        assert "FAIL: 0" in report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_probe_fails_when_endpoint_missing(tmp_path):
    server, thread = _serve()
    try:
        contracts = tmp_path / "API-CONTRACTS.md"
        contracts.write_text(
            textwrap.dedent(
                """\
                # API Contracts

                ## GET /api/missing
                **Auth:** Public
                """
            ),
            encoding="utf-8",
        )
        out = tmp_path / "report.txt"
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--contracts",
                str(contracts),
                "--base-url",
                base_url,
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 1
        report = out.read_text(encoding="utf-8")
        assert "FAIL" in report
        assert "Failing endpoints:" in report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
