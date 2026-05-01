"""Tests for scripts/preflight-invariants.py — standalone runner."""
from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "preflight-invariants.py"

requests = pytest.importorskip("requests")


def _run(repo: Path, *args: str, env_extra: dict | None = None
         ) -> subprocess.CompletedProcess:
    env = {
        "VG_REPO_ROOT": str(repo),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(REPO_ROOT / "scripts"),
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    log_message = lambda *a, **k: None

    def do_GET(self) -> None:
        path_only = self.path.split("?", 1)[0]
        route = self.routes.get(("GET", path_only))
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(route.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(route.get("body", {})).encode())


@pytest.fixture
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    routes: dict = {}

    class _H(_Handler):
        pass
    _H.routes = routes
    srv = http.server.HTTPServer(("127.0.0.1", port), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}", routes
    finally:
        srv.shutdown()
        srv.server_close()


def _phase(tmp_path: Path, env_contract_md: str) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "01.0-preflight"
    phase_dir.mkdir(parents=True)
    (phase_dir / "ENV-CONTRACT.md").write_text(env_contract_md, encoding="utf-8")
    return phase_dir


def test_no_env_contract_passes(tmp_path):
    """No ENV-CONTRACT.md — preflight is opt-in, so trivial PASS."""
    phase_dir = tmp_path / ".vg" / "phases" / "01.0-x"
    phase_dir.mkdir(parents=True)
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "PASS"


def test_no_invariants_passes(tmp_path):
    _phase(tmp_path, "# ENV-CONTRACT\n\nNo invariants here.\n")
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "PASS"


def test_dry_run_emits_planned_checks(tmp_path):
    pytest.importorskip("yaml")
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: tier2_topup
    resource: topup
    where: {tier: 2}
    consumers:
      - {goal: G-10, recipe: G-10, consume_semantics: destructive}
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
```
""".strip())
    result = _run(tmp_path, "--phase", "1.0", "--dry-run")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "DRY_RUN"
    assert out["invariants"] == 1
    assert "topup" in out["api_index_resources"]


def test_live_run_pass_when_count_meets_required(tmp_path, server):
    pytest.importorskip("yaml")
    base_url, routes = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"meta": {"total": 5}},
    }
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: tier2_topup
    resource: topup
    where: {tier: 2}
    consumers:
      - {goal: G-10, recipe: G-10, consume_semantics: destructive}
      - {goal: G-11, recipe: G-11, consume_semantics: destructive}
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
    count_query_keys: [tier]
```
""".strip())
    creds = json.dumps({"admin": {"kind": "api_key", "key": "test"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["verdict"] == "PASS"


def test_live_run_blocks_when_count_short(tmp_path, server):
    pytest.importorskip("yaml")
    base_url, routes = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"meta": {"total": 1}},  # need 3, have 1
    }
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: tier2_topup
    resource: topup
    where: {tier: 2}
    consumers:
      - {goal: G-10, recipe: G-10, consume_semantics: destructive}
      - {goal: G-11, recipe: G-11, consume_semantics: destructive}
      - {goal: G-12, recipe: G-12, consume_semantics: destructive}
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
    count_query_keys: [tier]
```
""".strip())
    creds = json.dumps({"admin": {"kind": "api_key", "key": "test"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out["verdict"] == "BLOCK"
    assert len(out["gaps"]) == 1
    assert out["gaps"][0]["required"] == 3
    assert out["gaps"][0]["actual"] == 1
    assert "fix_hint" in out["gaps"][0]


def test_severity_warn_does_not_block(tmp_path, server):
    pytest.importorskip("yaml")
    base_url, routes = server
    routes[("GET", "/api/admin/topup")] = {
        "status": 200, "body": {"meta": {"total": 0}},
    }
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: tier2_topup
    resource: topup
    where: {tier: 2}
    consumers:
      - {goal: G-10, recipe: G-10, consume_semantics: destructive}
api_index:
  topup:
    count_endpoint: /api/admin/topup
    count_jsonpath: $.meta.total
    count_role: admin
```
""".strip())
    creds = json.dumps({"admin": {"kind": "api_key", "key": "test"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   "--severity", "warn",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "WARN"


def test_missing_credentials_errors(tmp_path):
    pytest.importorskip("yaml")
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: i
    resource: r
    where: {x: 1}
    consumers:
      - {goal: G-1, recipe: G-1, consume_semantics: destructive}
api_index:
  r:
    count_endpoint: /api/r
    count_jsonpath: $.n
    count_role: admin
```
""".strip())
    result = _run(tmp_path, "--phase", "1.0", "--base-url", "http://localhost")
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert out["verdict"] == "ERROR"
    assert "credentials" in out["error"].lower()


def test_missing_base_url_errors(tmp_path):
    pytest.importorskip("yaml")
    _phase(tmp_path, """
```yaml
data_invariants:
  - id: i
    resource: r
    where: {x: 1}
    consumers:
      - {goal: G-1, recipe: G-1, consume_semantics: destructive}
api_index:
  r:
    count_endpoint: /api/r
    count_jsonpath: $.n
    count_role: admin
```
""".strip())
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert "base-url" in out["error"].lower() or "base_url" in out["error"].lower()


def test_phase_not_found_errors(tmp_path):
    (tmp_path / ".vg" / "phases").mkdir(parents=True)
    result = _run(tmp_path, "--phase", "99.99")
    assert result.returncode == 2
