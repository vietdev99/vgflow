"""Tests for scripts/runtime/api_index.py — RFC v9 PR-C count_fn wiring."""
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

from runtime.api_index import (  # noqa: E402
    ApiIndexError,
    count_fn_factory,
    parse_api_index,
)
from runtime.recipe_executor import RecipeRunner  # noqa: E402


# ─── parse_api_index ──────────────────────────────────────────────────


def test_parse_api_index_yaml_block(tmp_path):
    pytest.importorskip("yaml")
    md = """
# ENV-CONTRACT

```yaml
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
    count_query_keys: [tier, status]
  withdraw:
    count_endpoint: /api/admin/withdraw
    count_jsonpath: $.data.length
    count_role: admin
```
""".lstrip()
    p = tmp_path / "ENV.md"
    p.write_text(md, encoding="utf-8")
    idx = parse_api_index(p)
    assert "topup" in idx
    assert idx["topup"].count_endpoint == "/api/admin/topup"
    assert idx["topup"].count_query_keys == ["tier", "status"]
    assert idx["withdraw"].count_jsonpath == "$.data.length"


def test_parse_api_index_missing_required_raises(tmp_path):
    pytest.importorskip("yaml")
    md = """
```yaml
api_index:
  topup:
    count_endpoint: /api/x
    # missing count_jsonpath
    count_role: admin
```
""".lstrip()
    p = tmp_path / "ENV.md"
    p.write_text(md, encoding="utf-8")
    with pytest.raises(ApiIndexError, match="count_jsonpath"):
        parse_api_index(p)


def test_parse_api_index_no_block_returns_empty(tmp_path):
    p = tmp_path / "ENV.md"
    p.write_text("No api_index here.\n", encoding="utf-8")
    assert parse_api_index(p) == {}


# ─── count_fn_factory — live HTTP ─────────────────────────────────────


class _CountHandler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    log: list = []
    log_message = lambda *a, **k: None

    def do_GET(self) -> None:  # noqa: N802
        self.log.append({"path": self.path, "headers": dict(self.headers)})
        # Match by method + path-prefix (drop query string for routing)
        path_only = self.path.split("?", 1)[0]
        route = self.routes.get(("GET", path_only))
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        # Allow per-request override based on full path (incl. query)
        full_route = self.routes.get(("GET", self.path), route)
        status = full_route.get("status", 200)
        body = full_route.get("body", {})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


@pytest.fixture
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    routes: dict = {}
    log: list = []

    class _H(_CountHandler):
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


def test_count_fn_extracts_scalar(server):
    base_url, routes, log = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"meta": {"total": 7}, "data": []},
    }
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"admin": {"kind": "api_key", "key": "k"}},
    )
    from runtime.api_index import ResourceCounter
    idx = {"topup": ResourceCounter(
        resource="topup",
        count_endpoint="/api/admin/topup",
        count_jsonpath="$.meta.total",
        count_role="admin",
        count_query_keys=["tier", "status"],
    )}
    count = count_fn_factory(idx, runner)
    n = count("topup", {"tier": 2, "status": "pending"})
    assert n == 7
    # Query string only includes count_query_keys
    paths = [e["path"] for e in log]
    assert any("tier=2" in p and "status=pending" in p for p in paths)


def test_count_fn_filters_unknown_query_keys(server):
    base_url, routes, log = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"data": [1, 2, 3]},
    }
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"admin": {"kind": "api_key", "key": "k"}},
    )
    from runtime.api_index import ResourceCounter
    idx = {"topup": ResourceCounter(
        resource="topup",
        count_endpoint="/api/admin/topup",
        count_jsonpath="$.data",  # array → length
        count_role="admin",
        count_query_keys=["tier"],  # ONLY tier passes through
    )}
    count = count_fn_factory(idx, runner)
    n = count("topup", {"tier": 2, "internal_flag": "secret"})
    assert n == 3
    assert all("internal_flag" not in e["path"] for e in log)


def test_count_fn_array_jsonpath_returns_len(server):
    base_url, routes, _ = server
    routes[("GET", "/api/admin/withdraw")] = {
        "status": 200, "body": {"data": [{"id": 1}, {"id": 2}]},
    }
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"admin": {"kind": "api_key", "key": "k"}},
    )
    from runtime.api_index import ResourceCounter
    idx = {"withdraw": ResourceCounter(
        resource="withdraw",
        count_endpoint="/api/admin/withdraw",
        count_jsonpath="$.data[*]",
        count_role="admin",
    )}
    count = count_fn_factory(idx, runner)
    assert count("withdraw", {}) == 2


def test_count_fn_string_int_coerced(server):
    base_url, routes, _ = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"meta": {"total": "42"}},
    }
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"admin": {"kind": "api_key", "key": "k"}},
    )
    from runtime.api_index import ResourceCounter
    idx = {"topup": ResourceCounter(
        resource="topup",
        count_endpoint="/api/admin/topup",
        count_jsonpath="$.meta.total",
        count_role="admin",
    )}
    count = count_fn_factory(idx, runner)
    assert count("topup", {}) == 42


def test_count_fn_unknown_resource_raises(server):
    base_url, _, _ = server
    runner = RecipeRunner(base_url=base_url, env="sandbox", credentials_map={})
    count = count_fn_factory({}, runner)
    with pytest.raises(ApiIndexError, match="no entry for resource"):
        count("missing", {})


def test_count_fn_500_raises(server):
    base_url, routes, _ = server
    routes[("GET", "/api/admin/topup")] = {"status": 500, "body": {"err": "oops"}}
    runner = RecipeRunner(
        base_url=base_url, env="sandbox",
        credentials_map={"admin": {"kind": "api_key", "key": "k"}},
    )
    from runtime.api_index import ResourceCounter
    idx = {"topup": ResourceCounter(
        resource="topup",
        count_endpoint="/api/admin/topup",
        count_jsonpath="$.meta.total",
        count_role="admin",
    )}
    count = count_fn_factory(idx, runner)
    with pytest.raises(ApiIndexError, match="500"):
        count("topup", {})
