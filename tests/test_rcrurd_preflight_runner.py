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


# ─── Codex-HIGH-1: --mode post wires post_state into workflow ────────


def test_mode_post_runs_post_state_assertions(tmp_path, server):
    """Codex-HIGH-1: post-state must actually execute, not just be defined."""
    base_url, routes = server
    routes[("GET", "/api/topup/pending")] = {
        "status": 200, "body": {"count": 1},  # post-state expects 1
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
                   "--mode", "post",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["verdict"] == "PASS"
    assert out["mode"] == "post"


def test_mode_post_blocks_when_post_state_wrong(tmp_path, server):
    """Action did not produce expected post-state — must BLOCK."""
    base_url, routes = server
    # Both endpoints return count=0 — pre-state OK, post-state WRONG
    routes[("GET", "/api/topup/pending")] = {
        "status": 200, "body": {"count": 0},
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
                   "--mode", "post", "--severity", "block",
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out["verdict"] == "BLOCK"
    assert out["mode"] == "post"


def test_mode_post_dry_run_lists_post_state_endpoints(tmp_path):
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET",
                              "endpoint": "/api/pre",
                              "assert_jsonpath": [{"path": "$.x", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/post",
                               "assert_jsonpath": [{"path": "$.x", "equals": 1}]},
            },
        },
    })
    result = _run(tmp_path, "--phase", "1.0", "--mode", "post", "--dry-run")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    # Should list /api/post (post_state endpoint), not /api/pre
    assert any("/api/post" in p["endpoint"] for p in out["would_check"])
    assert not any("/api/pre" in p["endpoint"] for p in out["would_check"])


def test_capture_and_reuse_snapshot_for_increased_by_delta(tmp_path, server):
    """Codex-HIGH-1-bis: post_state must use REAL pre-action snapshot for
    increased_by_at_least, not a fresh post-action GET."""
    base_url, routes = server
    # Stage 1: pre_state runs against count=0
    routes[("GET", "/api/balance")] = {
        "status": 200, "body": {"balance": 100},
    }
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {
                    "role": "u", "method": "GET",
                    "endpoint": "/api/balance",
                    "assert_jsonpath": [{"path": "$.balance", "not_null": True}],
                },
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/topup",
                                                  "status_range": [200, 299]}},
                "post_state": {
                    "role": "u", "method": "GET",
                    "endpoint": "/api/balance",
                    "assert_jsonpath": [
                        {"path": "$.balance", "increased_by_at_least": 50},
                    ],
                },
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    snap = tmp_path / "pre-snapshot.json"

    # Stage 1: --mode pre with --capture-snapshot
    r1 = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
               "--mode", "pre", "--capture-snapshot", str(snap),
               env_extra={"VG_CREDENTIALS_JSON": creds})
    assert r1.returncode == 0, f"stdout={r1.stdout}\nstderr={r1.stderr}"
    assert snap.exists()
    snap_data = json.loads(snap.read_text())
    assert snap_data["G-10"] == {"balance": 100}

    # Stage 2: simulate action — balance increases to 200
    routes[("GET", "/api/balance")] = {
        "status": 200, "body": {"balance": 200},
    }

    # Stage 3: --mode post with --pre-snapshot — delta = 200-100 = 100 >= 50 → PASS
    r2 = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
               "--mode", "post", "--pre-snapshot", str(snap),
               env_extra={"VG_CREDENTIALS_JSON": creds})
    assert r2.returncode == 0, f"stdout={r2.stdout}\nstderr={r2.stderr}"
    out2 = json.loads(r2.stdout)
    assert out2["verdict"] == "PASS"
    assert out2.get("pre_snapshot_loaded") is True


def test_post_without_snapshot_fails_delta_assertions(tmp_path, server):
    """Without snapshot, post mode samples pre + post post-action — delta=0."""
    base_url, routes = server
    routes[("GET", "/api/balance")] = {
        "status": 200, "body": {"balance": 200},
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
                              "endpoint": "/api/balance",
                              "assert_jsonpath": [{"path": "$.balance", "not_null": True}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/topup",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET",
                               "endpoint": "/api/balance",
                               "assert_jsonpath": [
                                   {"path": "$.balance", "increased_by_at_least": 50},
                               ]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    # No --pre-snapshot → fallback fetch reads same payload → delta=0
    r = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
              "--mode", "post",
              env_extra={"VG_CREDENTIALS_JSON": creds})
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["verdict"] == "BLOCK"


def test_default_severity_is_now_block(tmp_path, server):
    """Codex-HIGH-4: default severity changed from warn to block."""
    base_url, routes = server
    routes[("GET", "/api/x")] = {"status": 200, "body": {"count": 99}}  # wrong
    _phase(tmp_path, {
        "G-10": {
            "schema_version": "1.0", "goal": "G-10",
            "description": "x" * 50,
            "fixture_intent": {"declared_in": "x", "validates": "x" * 25},
            "steps": [{"id": "x", "kind": "api_call", "role": "u",
                       "method": "GET", "endpoint": "/x"}],
            "lifecycle": {
                "pre_state": {"role": "u", "method": "GET", "endpoint": "/api/x",
                              "assert_jsonpath": [{"path": "$.count", "equals": 0}]},
                "action": {"surface": "ui_click",
                           "expected_network": {"method": "POST",
                                                  "endpoint": "/api/x",
                                                  "status_range": [200, 299]}},
                "post_state": {"role": "u", "method": "GET", "endpoint": "/api/x",
                               "assert_jsonpath": [{"path": "$.count", "equals": 1}]},
            },
        },
    })
    creds = json.dumps({"u": {"kind": "api_key", "key": "k"}})
    # NO --severity flag → should default to block, exit 1
    result = _run(tmp_path, "--phase", "1.0", "--base-url", base_url,
                   env_extra={"VG_CREDENTIALS_JSON": creds})
    assert result.returncode == 1
    assert json.loads(result.stdout)["verdict"] == "BLOCK"


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
