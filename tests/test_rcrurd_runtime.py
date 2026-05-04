"""Tests for verify-rcrurd-runtime.py — review-side mandatory gate."""
from __future__ import annotations

import json
import subprocess
import textwrap
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-rcrurd-runtime.py"


class FakeAPIHandler(BaseHTTPRequestHandler):
    """Stateful in-memory API stub for runtime tests.

    Behaviors driven by class attributes set in tests:
      - PATCH /api/users/U → 200 (mode: PERSIST | LIE | ERROR_500)
      - GET /api/users/U  → reflects in-memory state
    """
    state = {"U": {"id": "U", "roles": []}}
    write_mode = "PERSIST"

    def log_message(self, format: str, *args) -> None:
        return

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/users/"):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            uid = path.rsplit("/", 1)[-1]
            if FakeAPIHandler.write_mode == "PERSIST":
                FakeAPIHandler.state.setdefault(uid, {"id": uid, "roles": []})
                FakeAPIHandler.state[uid]["roles"] = body.get("roles", [])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            elif FakeAPIHandler.write_mode == "LIE":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            else:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/users/"):
            uid = path.rsplit("/", 1)[-1]
            entity = FakeAPIHandler.state.get(uid, {"id": uid, "roles": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(entity).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fake_api():
    server = HTTPServer(("127.0.0.1", 0), FakeAPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    FakeAPIHandler.state = {"U": {"id": "U", "roles": []}}
    FakeAPIHandler.write_mode = "PERSIST"
    yield base
    server.shutdown()


def _make_invariant(tmp_path: Path, base_url: str) -> Path:
    """Write a TEST-GOAL.md fixture with structured invariant."""
    goal = tmp_path / "G-04.md"
    goal.write_text(textwrap.dedent(f"""
        # G-04: Admin grants role

        **goal_type:** mutation

        **Persistence check:** After PATCH role, GET user must show new role.

        ## Read-after-write invariant

        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: PATCH
            endpoint: {base_url}/api/users/U
          read:
            method: GET
            endpoint: {base_url}/api/users/U
            cache_policy: no_store
            settle: {{mode: immediate}}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")
    return goal


def test_runtime_passes_when_state_actually_persists(tmp_path: Path, fake_api: str) -> None:
    goal = _make_invariant(tmp_path, fake_api)
    out = tmp_path / "evidence.json"

    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
        "--action-payload", json.dumps({"new_role": "admin", "roles": ["admin"]}),
        "--evidence-out", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "ADVISORY"
    assert ev["category"] == "rcrurd_runtime"


def test_runtime_blocks_on_lying_success(tmp_path: Path, fake_api: str) -> None:
    """The user's bug: PATCH 200, but state NOT mutated. Must BLOCK."""
    FakeAPIHandler.write_mode = "LIE"
    goal = _make_invariant(tmp_path, fake_api)
    out = tmp_path / "evidence.json"

    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
        "--action-payload", json.dumps({"new_role": "admin", "roles": ["admin"]}),
        "--evidence-out", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert "R8" in ev["summary"] or "did_not_apply" in ev["summary"].lower()


def test_non_mutation_goal_skipped(tmp_path: Path, fake_api: str) -> None:
    """Read-only goal has no invariant — gate must SKIP, not fail."""
    goal = tmp_path / "G-99.md"
    goal.write_text(textwrap.dedent("""
        # G-99: Health check

        **goal_type:** read_only

        ## (no invariant block — not a mutation)
    """).strip(), encoding="utf-8")
    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "skipped" in result.stdout.lower() or "non-mutation" in result.stdout.lower()
