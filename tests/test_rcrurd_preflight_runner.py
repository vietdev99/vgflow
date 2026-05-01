"""Tests for scripts/rcrurd-preflight.py — RCRURD live runner."""
from __future__ import annotations

import http.server
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rcrurd-preflight.py"

requests = pytest.importorskip("requests")
yaml = pytest.importorskip("yaml")


def _run(repo: Path, *args: str, env_extra: dict | None = None
         ) -> subprocess.CompletedProcess:
    env = {"VG_REPO_ROOT": str(repo), "PATH": "/usr/bin:/bin",
           "PYTHONPATH": str(REPO_ROOT / "scripts")}
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


def _phase(tmp_path: Path, fixtures: dict[str, dict]) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "01.0-rcrurd"
    fixtures_dir = phase_dir / "FIXTURES"
    fixtures_dir.mkdir(parents=True)
    for gid, recipe in fixtures.items():
        (fixtures_dir / f"{gid}.yaml").write_text(
            yaml.safe_dump(recipe, sort_keys=False), encoding="utf-8",
        )
    return phase_dir


def test_no_fixtures_dir_passes(tmp_path):
    phase_dir = tmp_path / ".vg" / "phases" / "01.0-x"
    phase_dir.mkdir(parents=True)
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode == 0
    assert json.loads(result.stdout)["verdict"] == "PASS"


def test_no_lifecycle_blocks_passes(tmp_path):
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50, "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
        },
    })
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode == 0
    assert json.loads(result.stdout)["verdict"] == "PASS"


def test_dry_run_lists_planned_checks(tmp_path):
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/topup/pending",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/topup/pending",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    result = _run(tmp_path, "--phase", "1.0", "--dry-run")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "DRY_RUN"
    assert any("/api/topup/pending" in p["endpoint"] for p in out["would_check"])


def test_live_pre_state_passes(tmp_path, server):
    base_url, routes = server
    routes[("GET", "/api/topup/pending")] = {
        "status": 200, "body": {"count": 0},  # matches expected
    }
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/topup/pending",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/topup/pending",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["verdict"] == "PASS"


def test_live_pre_state_block_when_count_wrong(tmp_path, server):
    base_url, routes = server
    routes[("GET", "/api/topup/pending")] = {
        "status": 200, "body": {"count": 5},  # WRONG (expected 0)
    }
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/topup/pending",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/topup/pending",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   "--severity", "block",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out["verdict"] == "BLOCK"
    assert out["failed"] == 1
    assert any("count" in str(r.get("errors", "")) for r in out["results"])


def test_only_filter_targets_specific_goal(tmp_path, server):
    base_url, routes = server
    routes[("GET", "/api/x/0")] = {"status": 200, "body": {"count": 0}}
    routes[("GET", "/api/y/0")] = {"status": 200, "body": {"count": 0}}
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/x/0",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/x/0",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
        "G-11": {
            "schema_version": "1.0", "goal": "G-11",
            "description": "y" * 50,
            "fixture_intent": {"declared_in": "y", "validates": "y" * 25},
            "steps": [{"id": "y", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/y"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/y/0",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/y",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/y/0",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   "--only", "G-10",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["checked"] == 1


def test_warn_severity_does_not_block(tmp_path, server):
    base_url, routes = server
    routes[("GET", "/api/x")] = {
        "status": 200, "body": {"count": 99},  # wrong
    }
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/x",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/x",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   "--severity", "warn",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["verdict"] == "WARN"


def test_missing_credentials_errors(tmp_path):
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET", "endpoint": "/x",
                              "assert_jsonpath": [{"path": "$.x", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET", "endpoint": "/x",
                               "assert_jsonpath": [{"path": "$.x", "equals": 1}]},
            },
        },
    })
    result = _run(tmp_path, "--phase", "1.0", "--base-url", "http://localhost")
    assert result.returncode == 2
    assert "credentials" in json.loads(result.stdout)["error"].lower()
