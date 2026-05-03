"""Tests for FE call extractor + BE route registry extractor."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-fe-api-calls.py"
BE_EXTRACTOR = REPO / "scripts" / "extractors" / "extract-be-route-registry.py"


def _run(script: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(script), *args],
        capture_output=True, text=True, check=False,
    )


def test_fe_extractor_finds_axios_get(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text(textwrap.dedent("""
        import axios from 'axios';
        export function Page() {
          axios.get('/api/v1/admin/invoices/' + id + '/payments');
          return <div/>;
        }
    """).strip(), encoding="utf-8")
    result = _run(FE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)["calls"]
    assert any(c["method"] == "GET" and "/api/v1/admin/invoices" in c["path_template"] for c in calls)


def test_fe_extractor_finds_fetch(tmp_path: Path) -> None:
    f = tmp_path / "hook.ts"
    f.write_text(textwrap.dedent("""
        export async function fetchPayments(id: string) {
          return fetch(`/api/v1/admin/invoices/${id}/payments`, { method: 'GET' });
        }
    """).strip(), encoding="utf-8")
    result = _run(FE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    calls = json.loads(result.stdout)["calls"]
    assert any(c["method"] == "GET" and "payments" in c["path_template"] for c in calls)


def test_be_extractor_finds_express_route(tmp_path: Path) -> None:
    f = tmp_path / "router.ts"
    f.write_text(textwrap.dedent("""
        import { Router } from 'express';
        const r = Router();
        r.post('/api/v1/admin/invoices/:id/payments', handler);
        r.post('/api/v1/admin/invoices/:id/payments/:pid/approve', approve);
        export default r;
    """).strip(), encoding="utf-8")
    result = _run(BE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    routes = json.loads(result.stdout)["routes"]
    methods = {(r["method"], r["path_template"]) for r in routes}
    assert ("POST", "/api/v1/admin/invoices/:id/payments") in methods
    # No GET present — required for L4a-i gap detection downstream.
    assert not any(r["method"] == "GET" for r in routes)


def test_be_extractor_finds_fastify(tmp_path: Path) -> None:
    f = tmp_path / "fastify.ts"
    f.write_text(textwrap.dedent("""
        export async function plugin(app) {
          app.get('/api/v1/health', healthHandler);
          app.post('/api/v1/orders', createOrder);
        }
    """).strip(), encoding="utf-8")
    result = _run(BE_EXTRACTOR, ["--root", str(tmp_path), "--format", "json"])
    assert result.returncode == 0
    routes = json.loads(result.stdout)["routes"]
    assert any(r["method"] == "GET" and r["path_template"] == "/api/v1/health" for r in routes)


def test_gap_detector_finds_fe_call_with_no_be_route(tmp_path: Path) -> None:
    fe = tmp_path / "fe"
    be = tmp_path / "be"
    fe.mkdir()
    be.mkdir()
    (fe / "Page.tsx").write_text(
        "axios.get('/api/v1/admin/invoices/' + id + '/payments');\n",
        encoding="utf-8",
    )
    (be / "router.ts").write_text(
        "router.post('/api/v1/admin/invoices/:id/payments', h);\n",
        encoding="utf-8",
    )
    gate = REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = subprocess.run(
        ["python3", str(gate),
         "--fe-root", str(fe), "--be-root", str(be),
         "--phase", "test-1.0",
         "--evidence-out", str(out_dir / "evidence.json")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, f"expected BLOCK, got {result.returncode}: {result.stderr}"
    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["severity"] == "BLOCK"
    assert evidence["category"] == "fe_be_call_graph"
    assert "GET" in evidence["summary"]
    assert "/api/v1/admin/invoices/:param/payments" in evidence["summary"]


def test_gap_detector_passes_when_all_fe_calls_have_routes(tmp_path: Path) -> None:
    fe = tmp_path / "fe"
    be = tmp_path / "be"
    fe.mkdir()
    be.mkdir()
    (fe / "Page.tsx").write_text(
        "axios.get('/api/v1/health');\n",
        encoding="utf-8",
    )
    (be / "router.ts").write_text(
        "router.get('/api/v1/health', h);\n",
        encoding="utf-8",
    )
    gate = REPO / "scripts" / "validators" / "verify-fe-be-call-graph.py"
    result = subprocess.run(
        ["python3", str(gate),
         "--fe-root", str(fe), "--be-root", str(be),
         "--phase", "test-1.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_fe_extractor_handles_trailing_concat_variable(tmp_path: Path) -> None:
    """Bug fix Task 3.5: axios.get('/api/users/' + userId) must produce /api/users/:param,
    not /api/users/ (under-detection of gaps when URL ends with variable)."""
    f = tmp_path / "Page.tsx"
    f.write_text(
        "axios.get('/api/users/' + userId);\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["python3", str(FE_EXTRACTOR), "--root", str(tmp_path), "--format", "json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)["calls"]
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    # Bug was: path_template == '/api/users/' (trailing variable dropped)
    # Fix: append :param for trailing identifier
    assert calls[0]["path_template"] == "/api/users/:param", \
        f"expected '/api/users/:param', got {calls[0]['path_template']!r}"
