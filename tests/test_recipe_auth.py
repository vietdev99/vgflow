"""Tests for scripts/runtime/recipe_auth.py — RFC v9 PR-A2 4 auth handlers."""
from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

requests = pytest.importorskip("requests")

from runtime.recipe_auth import (  # noqa: E402
    AuthError,
    auth_api_key,
    auth_bearer_jwt,
    auth_command,
    auth_cookie_login,
    authenticate,
)


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    log: list = []
    log_message = lambda *a, **k: None

    def _serve(self, method: str) -> None:
        body_len = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(body_len) if body_len else b""
        try:
            parsed = json.loads(body) if body else None
        except (json.JSONDecodeError, ValueError):
            parsed = body
        self.log.append({"method": method, "path": self.path, "body": parsed})
        route = self.routes.get((method, self.path))
        if not route:
            self.send_response(404)
            self.end_headers()
            return
        cookies = route.get("set_cookies")
        status = route.get("status", 200)
        payload = route.get("body", {})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if cookies:
            for name, val in cookies.items():
                self.send_header("Set-Cookie", f"{name}={val}; Path=/")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self): self._serve("GET")
    def do_POST(self): self._serve("POST")


@pytest.fixture
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    routes: dict = {}
    log: list = []

    class _H(_Handler):
        pass
    _H.routes = routes
    _H.log = log
    srv = http.server.HTTPServer(("127.0.0.1", port), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}", routes, log
    finally:
        srv.shutdown()
        srv.server_close()


# ─── api_key ──────────────────────────────────────────────────────────


def test_api_key_default_header():
    ctx = auth_api_key("http://x", {"key": "secret-1"}, sandbox=True)
    assert ctx.session.headers["Authorization"] == "ApiKey secret-1"
    assert ctx.session.headers["X-VGFlow-Sandbox"] == "true"


def test_api_key_custom_header_and_scheme():
    ctx = auth_api_key("http://x", {
        "key": "k",
        "header_name": "X-Api-Token",
        "scheme": "",
    }, sandbox=False)
    assert ctx.session.headers["X-Api-Token"] == "k"
    assert "X-VGFlow-Sandbox" not in ctx.session.headers


def test_api_key_missing_key_raises():
    with pytest.raises(AuthError, match="creds.key"):
        auth_api_key("http://x", {}, sandbox=True)


# ─── cookie_login ─────────────────────────────────────────────────────


def test_cookie_login_attaches_session_cookie(server):
    base_url, routes, log = server
    routes[("POST", "/login")] = {
        "status": 200,
        "set_cookies": {"session_id": "sess-123"},
        "body": {"ok": True},
    }
    ctx = auth_cookie_login(
        base_url,
        {"endpoint": "/login", "body": {"u": "alice", "p": "pw"}},
        sandbox=True,
    )
    assert ctx.session.cookies.get("session_id") == "sess-123"
    assert log[0]["body"] == {"u": "alice", "p": "pw"}


def test_cookie_login_4xx_raises(server):
    base_url, routes, _ = server
    routes[("POST", "/login")] = {"status": 401, "body": {"err": "bad"}}
    with pytest.raises(AuthError, match="401"):
        auth_cookie_login(base_url, {"endpoint": "/login", "body": {}}, sandbox=True)


def test_cookie_login_no_set_cookie_raises(server):
    base_url, routes, _ = server
    routes[("POST", "/login")] = {"status": 200, "body": {"ok": True}}  # no Set-Cookie
    with pytest.raises(AuthError, match="Set-Cookie"):
        auth_cookie_login(base_url, {"endpoint": "/login", "body": {}}, sandbox=True)


# ─── bearer_jwt ───────────────────────────────────────────────────────


def test_bearer_jwt_captures_token(server):
    base_url, routes, log = server
    routes[("POST", "/auth/token")] = {
        "status": 200,
        "body": {"access_token": "jwt-xyz", "expires_in": 3600},
    }
    ctx = auth_bearer_jwt(
        base_url,
        {"endpoint": "/auth/token", "body": {"u": "alice"}},
        sandbox=True,
    )
    assert ctx.session.headers["Authorization"] == "Bearer jwt-xyz"
    assert ctx.refresh_callable is not None


def test_bearer_jwt_custom_token_path(server):
    base_url, routes, _ = server
    routes[("POST", "/auth/token")] = {
        "status": 200,
        "body": {"data": {"token": {"value": "deep-jwt"}}},
    }
    ctx = auth_bearer_jwt(
        base_url,
        {
            "endpoint": "/auth/token",
            "body": {},
            "token_path": "data.token.value",
        },
        sandbox=True,
    )
    assert ctx.session.headers["Authorization"] == "Bearer deep-jwt"


def test_bearer_jwt_refresh_re_calls_login(server):
    base_url, routes, log = server
    routes[("POST", "/auth/token")] = {
        "status": 200,
        "body": {"access_token": "jwt-1"},
    }
    ctx = auth_bearer_jwt(base_url, {"endpoint": "/auth/token", "body": {}}, sandbox=True)
    assert ctx.session.headers["Authorization"] == "Bearer jwt-1"
    # Swap response → refresh should pick up new token
    routes[("POST", "/auth/token")] = {
        "status": 200,
        "body": {"access_token": "jwt-2"},
    }
    ctx.refresh_callable()
    assert ctx.session.headers["Authorization"] == "Bearer jwt-2"


def test_bearer_jwt_token_path_not_found_raises(server):
    base_url, routes, _ = server
    routes[("POST", "/auth/token")] = {
        "status": 200,
        "body": {"foo": "bar"},  # no access_token
    }
    with pytest.raises(AuthError, match="token_path"):
        auth_bearer_jwt(base_url, {"endpoint": "/auth/token", "body": {}}, sandbox=True)


def test_bearer_jwt_login_4xx_raises(server):
    base_url, routes, _ = server
    routes[("POST", "/auth/token")] = {"status": 403, "body": {}}
    with pytest.raises(AuthError, match="403"):
        auth_bearer_jwt(base_url, {"endpoint": "/auth/token", "body": {}}, sandbox=True)


# ─── command ──────────────────────────────────────────────────────────


def test_command_auth_blocked_outside_sandbox():
    with pytest.raises(AuthError, match="sandbox-only"):
        auth_command("http://x", {"command": "echo {}"}, sandbox=False)


def test_command_auth_invokes_script_and_sets_headers(tmp_path):
    """Use a small Python script that emits JSON on stdout."""
    script = tmp_path / "auth.py"
    script.write_text(
        "import json, sys\n"
        "print(json.dumps({'kind': 'header', "
        "'headers': {'X-Custom': 'value-from-cmd'}}))\n"
    )
    ctx = auth_command(
        "http://x",
        {"command": f"{sys.executable} {script}"},
        sandbox=True,
    )
    assert ctx.session.headers["X-Custom"] == "value-from-cmd"
    assert ctx.session.headers["X-VGFlow-Sandbox"] == "true"


def test_command_auth_cookies_kind(tmp_path):
    script = tmp_path / "auth_cookie.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({'kind': 'cookies', 'cookies': {'sid': 'cmd-sid'}}))\n"
    )
    ctx = auth_command(
        "http://x",
        {"command": f"{sys.executable} {script}"},
        sandbox=True,
    )
    assert ctx.session.cookies.get("sid") == "cmd-sid"


def test_command_auth_non_zero_exit_raises(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys; print('boom', file=sys.stderr); sys.exit(1)\n")
    with pytest.raises(AuthError, match="exited 1"):
        auth_command(
            "http://x", {"command": f"{sys.executable} {script}"}, sandbox=True,
        )


def test_command_auth_invalid_json_raises(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("print('not json')\n")
    with pytest.raises(AuthError, match="not JSON"):
        auth_command(
            "http://x", {"command": f"{sys.executable} {script}"}, sandbox=True,
        )


# ─── dispatcher ───────────────────────────────────────────────────────


def test_authenticate_dispatcher_unknown_kind_raises():
    with pytest.raises(AuthError, match="Unknown auth kind"):
        authenticate("magic", "http://x", {}, sandbox=True)


def test_authenticate_dispatcher_routes_api_key():
    ctx = authenticate("api_key", "http://x", {"key": "k"}, sandbox=True)
    assert ctx.session.headers.get("Authorization") == "ApiKey k"
