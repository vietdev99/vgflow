"""B108 v4.70.2 — live route shape diff for FE consumers.

Codex postmortem rec #3: promote B95 advisory static heuristic to a
runtime probe. For each FE source file that consumes API data
(`response.data.foo`, `.rows[0].x`, etc.), issue a safe GET against the
configured live server and diff response envelope keys vs FE-dereferenced
field paths. Catches empty dropdown (failed XHR), wrong envelope key
(`.rows` vs `.data`), `_id` vs `id` drift — bug classes that B95 static
heuristics cannot detect.

Without `--base-url`, the validator scans FE source for consumer surface
but skips the live probe (advisory mode, CI-safe).

With `--base-url`, the validator hits the live server, parses JSON
response, and compares keys.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-fe-route-shape-live.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-fe-route-shape-live.py"


def _run(tmp_path: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(tmp_path), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed_fe(tmp_path: Path, files: dict[str, str], app: str = "admin") -> Path:
    src = tmp_path / "apps" / app / "src"
    src.mkdir(parents=True)
    for rel, body in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return src


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vd():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vd", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b108_flatten_keys_dict(vd) -> None:
    out = vd.flatten_keys({"data": {"items": [{"id": 1, "name": "x"}]}})
    assert ".data" in out
    assert ".data.items" in out
    assert ".data.items[0]" in out
    assert ".data.items[0].id" in out
    assert ".data.items[0].name" in out


def test_b108_flatten_keys_list_root(vd) -> None:
    out = vd.flatten_keys([{"id": 1}])
    assert "[0]" in out
    assert "[0].id" in out


def test_b108_diff_shape_detects_missing(vd) -> None:
    expected = [".data.rows", ".data.rows[0].id"]
    actual = [".data", ".data.items", ".data.items[0]", ".data.items[0].id"]
    drift = vd.diff_shape(expected, actual)
    assert ".data.rows" in drift
    assert ".data.rows[0].id" in drift


def test_b108_diff_shape_passes_when_present(vd) -> None:
    expected = [".data.items[0].id"]
    actual = [".data", ".data.items", ".data.items[0]", ".data.items[0].id"]
    drift = vd.diff_shape(expected, actual)
    assert drift == []


def test_b108_url_pattern_to_concrete_replaces_placeholders(vd) -> None:
    assert vd.url_pattern_to_concrete("/api/v1/users/:id") == "/api/v1/users/1"
    assert vd.url_pattern_to_concrete("/api/v1/users/{id}/posts/:postId") == "/api/v1/users/1/posts/1"


# ---------------------------------------------------------------------------
# FE consumer scan
# ---------------------------------------------------------------------------

def test_b108_scan_picks_up_axios_get_with_deref(tmp_path: Path) -> None:
    _seed_fe(tmp_path, {
        "TopupList.tsx": """
import axios from 'axios';
const fetchTopups = async () => {
  const response = await axios.get('/api/v1/admin/topups');
  return response.data.rows.map(r => r.id);
};
""",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"  # no --base-url → SCAN-ONLY
    assert out["consumers_found"] >= 1
    consumer = out.get("audits") or []
    # No audits without base-url, but the count tells us scan worked
    assert out["live_probe_skipped"] is True


def test_b108_scan_no_consumer_no_findings(tmp_path: Path) -> None:
    _seed_fe(tmp_path, {
        "PureUtil.tsx": "export const add = (a:number, b:number) => a + b;",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["consumers_found"] == 0


# ---------------------------------------------------------------------------
# Live probe — spin up tiny HTTP server, run live diff
# ---------------------------------------------------------------------------

class _FakeBE(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        if self.path.startswith("/api/v1/admin/topups"):
            payload = {"data": {"items": [{"id": 1, "name": "Alpha"}]}}
        elif self.path.startswith("/api/v1/admin/users"):
            payload = {"data": {"rows": [{"id": 1, "email": "x@y"}]}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def fake_be():
    server = HTTPServer(("127.0.0.1", 0), _FakeBE)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def test_b108_live_probe_flags_shape_drift(tmp_path: Path, fake_be: str) -> None:
    """FE expects `.data.rows` but BE returns `.data.items` → drift."""
    _seed_fe(tmp_path, {
        "TopupList.tsx": """
import axios from 'axios';
const fetchTopups = async () => {
  const response = await axios.get('/api/v1/admin/topups');
  return response.data.rows.map(r => r.id);  // BE actually returns .data.items
};
""",
    })
    proc = _run(tmp_path, "--base-url", fake_be)
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    assert out["total_drift_count"] >= 1


def test_b108_live_probe_passes_when_shape_matches(tmp_path: Path, fake_be: str) -> None:
    _seed_fe(tmp_path, {
        "UserList.tsx": """
import axios from 'axios';
const fetchUsers = async () => {
  const response = await axios.get('/api/v1/admin/users');
  return response.data.rows.map(r => r.email);
};
""",
    })
    proc = _run(tmp_path, "--base-url", fake_be)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"


def test_b108_severity_block_exits_one(tmp_path: Path, fake_be: str) -> None:
    _seed_fe(tmp_path, {
        "Drift.tsx": """
import axios from 'axios';
const f = async () => {
  const response = await axios.get('/api/v1/admin/topups');
  return response.data.rows;  // BE returns .data.items
};
""",
    })
    proc = _run(tmp_path, "--base-url", fake_be, "--severity", "block")
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# Registry + mirror
# ---------------------------------------------------------------------------

def test_b108_registry_entry_present() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")
    assert "id: fe-route-shape-live" in body
    idx = body.index("id: fe-route-shape-live")
    region = body[idx:idx + 1000]
    assert "severity: warn" in region
    assert "added_in: v4.70.2" in region


def test_b108_validator_mirror_parity() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()


def test_b108_registry_mirror_parity() -> None:
    a = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml").read_bytes()
    assert a == b
