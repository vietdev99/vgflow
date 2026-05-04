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


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-static-assets-runtime.py"
ORCHESTRATOR = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("VG_TARGET_URL", None)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        timeout=15,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _handler(routes: dict[str, tuple[int, str, bytes]]):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            status, content_type, body = routes.get(
                self.path,
                (404, "text/plain", b"not found"),
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return

    return Handler


@contextmanager
def mock_server(routes: dict[str, tuple[int, str, bytes]]):
    port = _free_port()
    server = socketserver.TCPServer(("127.0.0.1", port), _handler(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_static_css_asset_passes() -> None:
    routes = {
        "/": (
            200,
            "text/html",
            b'<html><head><link rel="stylesheet" href="/assets/app.css"></head></html>',
        ),
        "/assets/app.css": (
            200,
            "text/css; charset=utf-8",
            b":root{--fg:#111}.button{display:flex}",
        ),
    }
    with mock_server(routes) as url:
        result = _run(["--target-url", url])
    assert result.returncode == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["verdict"] == "PASS"


def test_stylesheet_wrong_content_type_blocks() -> None:
    routes = {
        "/": (
            200,
            "text/html",
            b'<html><head><link rel="stylesheet" href="/assets/app.css"></head></html>',
        ),
        "/assets/app.css": (
            200,
            "text/plain",
            b":root{--fg:#111}",
        ),
    }
    with mock_server(routes) as url:
        result = _run(["--target-url", url])
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["verdict"] == "BLOCK"
    assert any(e["type"] == "stylesheet_wrong_content_type" for e in data["evidence"])


def test_stylesheet_source_body_blocks_even_with_css_content_type() -> None:
    routes = {
        "/": (
            200,
            "text/html",
            b'<html><head><link rel="stylesheet" href="/assets/app.css"></head></html>',
        ),
        "/assets/app.css": (
            200,
            "text/css",
            b"import React from 'react';\nexport default function App(){return null}",
        ),
    }
    with mock_server(routes) as url:
        result = _run(["--target-url", url])
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(e["type"] == "stylesheet_body_not_css" for e in data["evidence"])


def test_missing_target_url_self_skips() -> None:
    result = _run(["--phase", "1"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["verdict"] == "PASS"
    assert data["evidence"][0]["type"] == "runtime_probe_skipped"


def test_static_asset_validator_is_wired() -> None:
    orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
    registry = REGISTRY.read_text(encoding="utf-8")
    assert '"verify-static-assets-runtime"' in orchestrator
    assert "verify-static-assets-runtime" in orchestrator
    assert "static-assets-runtime" in registry
    assert "verify-static-assets-runtime.py" in registry
