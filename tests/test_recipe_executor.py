"""Tests for scripts/runtime/recipe_executor.py — RFC v9 PR-A2.

Uses a stdlib HTTP server fixture (no external mock dep). Each test spins
up an http.server.HTTPServer in a thread, runs the recipe against it, and
shuts down. Server records request log for assertions.
"""
from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Skip everything if requests not available
requests = pytest.importorskip("requests")

from runtime.recipe_executor import (  # noqa: E402
    AuthDegradedError, RecipeRunner, RecipeExecutionError,
)


class RecordingHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that records requests + serves canned responses."""

    routes: dict[tuple[str, str], dict] = {}
    log: list[dict] = []

    def log_message(self, *_args, **_kwargs):  # silence stderr noise
        return

    def _record(self, method: str, body: bytes | None) -> None:
        try:
            parsed_body = json.loads(body) if body else None
        except (json.JSONDecodeError, ValueError):
            parsed_body = body.decode("utf-8", errors="replace") if body else None
        self.log.append({
            "method": method,
            "path": self.path,
            "headers": dict(self.headers),
            "body": parsed_body,
        })

    def _serve(self, method: str) -> None:
        body_len = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(body_len) if body_len else b""
        self._record(method, body)
        route = self.routes.get((method, self.path)) or self.routes.get((method, "*"))
        if not route:
            self.send_response(404)
            self.end_headers()
            return
        status = route.get("status", 200)
        payload = route.get("body", {})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self): self._serve("GET")
    def do_POST(self): self._serve("POST")
    def do_PUT(self): self._serve("PUT")
    def do_PATCH(self): self._serve("PATCH")
    def do_DELETE(self): self._serve("DELETE")


@pytest.fixture
def http_server():
    """Spin up a localhost HTTP server with shared route map. Yield (base_url, routes, log)."""
    # Pick a free port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    routes: dict = {}
    log: list = []

    class _H(RecordingHandler):
        pass
    _H.routes = routes
    _H.log = log

    server = http.server.HTTPServer(("127.0.0.1", port), _H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", routes, log
    finally:
        server.shutdown()
        server.server_close()


def test_simple_get_step(http_server):
    base_url, routes, log = http_server
    routes[("GET", "/api/me")] = {"status": 200, "body": {"name": "alice"}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "test-key"}},
    )
    runner.run({
        "schema_version": "1.0",
        "goal": "G-X",
        "steps": [
            {"id": "fetch", "kind": "api_call", "role": "u",
             "method": "GET", "endpoint": "/api/me"},
        ],
    })
    assert log[0]["method"] == "GET"
    headers_ci = {k.lower(): v for k, v in log[0]["headers"].items()}
    assert headers_ci.get("authorization") == "ApiKey test-key"
    assert headers_ci.get("x-vgflow-sandbox") == "true"


def test_post_with_idempotency_key(http_server):
    base_url, routes, log = http_server
    routes[("POST", "/api/topup")] = {"status": 201, "body": {"id": "p7"}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "test-key"}},
    )
    runner.run({
        "schema_version": "1.0",
        "goal": "G-X",
        "steps": [{
            "id": "create",
            "kind": "api_call",
            "role": "u",
            "method": "POST",
            "endpoint": "/api/topup",
            "idempotency_key": "k-001",
            "body": {"amount": 0.01},
        }],
    })
    headers_ci = {k.lower(): v for k, v in log[0]["headers"].items()}
    assert headers_ci.get("idempotency-key") == "k-001"


def test_capture_into_store_and_interpolation(http_server):
    base_url, routes, log = http_server
    routes[("POST", "/api/topup")] = {"status": 201, "body": {"data": {"id": "p99"}}}
    routes[("GET", "*")] = {"status": 200, "body": {"ok": True}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0",
        "goal": "G-X",
        "steps": [
            {"id": "create", "kind": "api_call", "role": "u",
             "method": "POST", "endpoint": "/api/topup",
             "idempotency_key": "k-001",
             "body": {"amount": 0.01},
             "capture": {"pid": {"path": "$.data.id"}}},
            {"id": "fetch", "kind": "api_call", "role": "u",
             "method": "GET", "endpoint": "/api/topup/${pid}"},
        ],
    })
    assert runner.store["pid"] == "p99"
    # 2nd request hit /api/topup/p99
    paths = [e["path"] for e in log]
    assert "/api/topup/p99" in paths


def test_4xx_response_raises(http_server):
    base_url, routes, _ = http_server
    routes[("GET", "/api/x")] = {"status": 404, "body": {"err": "nope"}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    with pytest.raises(RecipeExecutionError, match="404"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/api/x"}],
        })


def test_expect_status_strict(http_server):
    base_url, routes, _ = http_server
    routes[("GET", "/api/x")] = {"status": 200, "body": {}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    with pytest.raises(RecipeExecutionError, match="expected 201"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/api/x",
                       "expect_status": 201}],
        })


def test_validate_after_runs_get(http_server):
    base_url, routes, log = http_server
    routes[("POST", "/api/topup")] = {"status": 201, "body": {"id": "p1"}}
    routes[("GET", "/api/topup/p1")] = {
        "status": 200, "body": {"data": {"status": "pending"}}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0", "goal": "G-X",
        "steps": [{
            "id": "create", "kind": "api_call", "role": "u",
            "method": "POST", "endpoint": "/api/topup",
            "idempotency_key": "k1", "body": {"amount": 0.01},
            "capture": {"pid": {"path": "$.id"}},
            "validate_after": {
                "kind": "api_call", "method": "GET",
                "endpoint": "/api/topup/${pid}",
                "expect_status": 200,
                "assert_jsonpath": [
                    {"path": "$.data.status", "equals": "pending"},
                ],
            },
        }],
    })
    paths = [e["path"] for e in log]
    assert "/api/topup/p1" in paths


def test_validate_after_assertion_fails(http_server):
    base_url, routes, _ = http_server
    routes[("POST", "/api/topup")] = {"status": 201, "body": {"id": "p1"}}
    routes[("GET", "/api/topup/p1")] = {
        "status": 200, "body": {"data": {"status": "approved"}}}  # WRONG status

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    with pytest.raises(RecipeExecutionError, match="status"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{
                "id": "create", "kind": "api_call", "role": "u",
                "method": "POST", "endpoint": "/api/topup",
                "idempotency_key": "k1", "body": {"amount": 0.01},
                "capture": {"pid": {"path": "$.id"}},
                "validate_after": {
                    "kind": "api_call", "method": "GET",
                    "endpoint": "/api/topup/${pid}",
                    "assert_jsonpath": [
                        {"path": "$.data.status", "equals": "pending"},
                    ],
                },
            }],
        })


def test_loop_step_iterates(http_server):
    base_url, routes, log = http_server
    routes[("POST", "*")] = {"status": 200, "body": {"id": "x"}}

    runner = RecipeRunner(
        base_url=base_url,
        env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0", "goal": "G-X",
        "steps": [{
            "id": "loop", "kind": "loop",
            "over": 3,
            "each": {
                "id": "create", "kind": "api_call", "role": "u",
                "method": "POST", "endpoint": "/api/x",
                "idempotency_key": "iter-${_index}",
                "body": {"amount": 0.01},
            },
        }],
    })
    posts = [e for e in log if e["method"] == "POST"]
    assert len(posts) == 3
    idem_keys = {
        next((v for k, v in e["headers"].items() if k.lower() == "idempotency-key"), None)
        for e in posts
    }
    assert idem_keys == {"iter-0", "iter-1", "iter-2"}


def test_unknown_role_raises(http_server):
    base_url, _, _ = http_server
    runner = RecipeRunner(
        base_url=base_url, env="sandbox", credentials_map={},
    )
    with pytest.raises(RecipeExecutionError, match="unknown_role"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{"id": "x", "kind": "api_call", "role": "unknown_role",
                       "method": "GET", "endpoint": "/api/x"}],
        })


def test_sandbox_safety_blocks_money_without_sentinel(http_server):
    base_url, _, _ = http_server
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    with pytest.raises(RecipeExecutionError, match="sentinel"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{
                "id": "topup", "kind": "api_call", "role": "u",
                "method": "POST", "endpoint": "/api/topup",
                "idempotency_key": "k1",
                "body": {"amount": 1000, "merchant": "real-merchant"},
            }],
        })


# ─── Codex-HIGH-7: URL allowlist + response echo ─────────────────────


def test_runner_rejects_url_outside_allowlist(http_server):
    base_url, _, _ = http_server
    with pytest.raises(RecipeExecutionError, match="NOT in sandbox_url_allowlist"):
        RecipeRunner(
            base_url=base_url, env="sandbox",
            credentials_map={"u": {"kind": "api_key", "key": "k"}},
            sandbox_url_allowlist=["sandbox.example.com"],  # base_url is 127.0.0.1
        )


def test_runner_accepts_url_in_allowlist(http_server):
    base_url, _, _ = http_server
    # base_url is http://127.0.0.1:PORT — allowlist permits 127.0.0.1
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
        sandbox_url_allowlist=["127.0.0.1"],
    )
    assert runner.base_url == base_url


def test_runner_response_echo_check_blocks_when_header_missing(http_server):
    base_url, routes, _ = http_server
    routes[("GET", "/api/x")] = {"status": 200, "body": {"ok": True}}
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
        response_echo_check=True,
    )
    with pytest.raises(RecipeExecutionError, match="echo handshake"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/api/x"}],
        })


# ─── Codex-B-MEDIUM: PATCH/DELETE idempotency-key ────────────────────


def test_patch_carries_idempotency_key(http_server):
    base_url, routes, log = http_server
    routes[("PATCH", "/api/x")] = {"status": 200, "body": {}}
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0", "goal": "G-X",
        "steps": [{
            "id": "patch", "kind": "api_call", "role": "u",
            "method": "PATCH", "endpoint": "/api/x",
            "idempotency_key": "patch-k1",
            "body": {"x": 1},
        }],
    })
    headers_ci = {k.lower(): v for k, v in log[0]["headers"].items()}
    assert headers_ci.get("idempotency-key") == "patch-k1"


def test_delete_carries_idempotency_key(http_server):
    base_url, routes, log = http_server
    routes[("DELETE", "/api/x/1")] = {"status": 204, "body": {}}
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0", "goal": "G-X",
        "steps": [{
            "id": "del", "kind": "api_call", "role": "u",
            "method": "DELETE", "endpoint": "/api/x/1",
            "idempotency_key": "del-k1",
        }],
    })
    headers_ci = {k.lower(): v for k, v in log[0]["headers"].items()}
    assert headers_ci.get("idempotency-key") == "del-k1"


# ─── Codex-A-MEDIUM: AuthDegradedError typed exception ──────────────


def test_loop_validate_after_sees_per_iteration_capture(http_server):
    """Codex-R5-HIGH-2: with from_each: true, the loop iteration's
    captured value used to skip self.store. validate_after couldn't
    interpolate it. Now per-iteration value is exposed in store."""
    base_url, routes, log = http_server
    routes[("POST", "/api/x")] = {"status": 200, "body": {"id": "x-1"}}
    # validate_after path matches whichever id was just captured
    routes[("GET", "/api/x/x-1")] = {"status": 200, "body": {"verified": True}}
    routes[("GET", "/api/x/x-2")] = {"status": 200, "body": {"verified": True}}

    routes[("POST", "/api/iter1")] = {"status": 200, "body": {"id": "x-1"}}
    routes[("POST", "/api/iter2")] = {"status": 200, "body": {"id": "x-2"}}

    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {"kind": "api_key", "key": "k"}},
    )
    runner.run({
        "schema_version": "1.0", "goal": "G-X",
        "steps": [{
            "id": "loop", "kind": "loop",
            "over": ["iter1", "iter2"],
            "each": {
                "id": "create", "kind": "api_call", "role": "u",
                "method": "POST", "endpoint": "/api/${_value}",
                "idempotency_key": "k-${_index}",
                "body": {"amount": 0.01},
                "capture": {
                    "current_id": {"path": "$.id", "from_each": True},
                },
                "validate_after": {
                    "kind": "api_call", "method": "GET",
                    "endpoint": "/api/x/${current_id}",
                    "expect_status": 200,
                    "assert_jsonpath": [
                        {"path": "$.verified", "equals": True},
                    ],
                },
            },
        }],
    })
    # After loop: current_id is the accumulated array
    assert runner.store["current_id"] == ["x-1", "x-2"]
    # Both validate_after GETs hit the right per-iteration URLs
    paths = [e["path"] for e in log if e["method"] == "GET"]
    assert "/api/x/x-1" in paths
    assert "/api/x/x-2" in paths


def test_auth_degraded_when_refresh_then_401(http_server):
    """Bearer JWT: refresh succeeds but second response is also 401 →
    refresh-token expired, surface as AuthDegradedError so caller can
    re-prompt for credentials."""
    base_url, routes, _ = http_server
    routes[("POST", "/auth/token")] = {
        "status": 200, "body": {"access_token": "jwt-1"},
    }
    routes[("GET", "/api/me")] = {"status": 401, "body": {}}
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"u": {
            "kind": "bearer_jwt",
            "endpoint": "/auth/token",
            "body": {"u": "alice"},
        }},
    )
    with pytest.raises(AuthDegradedError, match="refresh succeeded"):
        runner.run({
            "schema_version": "1.0", "goal": "G-X",
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/api/me"}],
        })
