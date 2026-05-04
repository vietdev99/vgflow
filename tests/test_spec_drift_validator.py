"""Spec drift detector — compares executor SUMMARY.md returns vs API-CONTRACTS spec.

Heuristic: contract declares 'Response 201: { id: string }' (sync). Build
output (BUILD-LOG/task-NN.md) implements 'returns 202 with task_id' (async).
That mismatch flags as BLOCK.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-spec-drift.py"


def test_sync_vs_async_drift_blocks(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "API-CONTRACTS").mkdir(parents=True)
    (pd / "BUILD-LOG").mkdir()
    (pd / "API-CONTRACTS" / "post-api-invoices.md").write_text(textwrap.dedent("""
        # POST /api/invoices

        **Method:** POST
        **Path:** /api/invoices
        **Response 201:** { "id": "string" }
    """).strip(), encoding="utf-8")
    (pd / "BUILD-LOG" / "task-39.md").write_text(textwrap.dedent("""
        # task-39

        BE handler returns 202 with task_id (async worker enqueue).
        FE redirects to invoice list with merchant filter.
    """).strip(), encoding="utf-8")
    out = tmp_path / "evidence.json"
    result = subprocess.run(
        ["python3", str(GATE),
         "--phase-dir", str(pd),
         "--phase", "test-4.1",
         "--evidence-out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert ev["category"] == "spec_drift"
    assert "task-39" in ev["summary"]


def test_matching_status_passes(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "API-CONTRACTS").mkdir(parents=True)
    (pd / "BUILD-LOG").mkdir()
    (pd / "API-CONTRACTS" / "get-api-health.md").write_text(textwrap.dedent("""
        # GET /api/health

        **Method:** GET
        **Path:** /api/health
        **Response 200:** { "ok": true }
    """).strip(), encoding="utf-8")
    (pd / "BUILD-LOG" / "task-01.md").write_text(textwrap.dedent("""
        # task-01

        Implements GET /api/health returning 200 { ok: true }.
    """).strip(), encoding="utf-8")
    result = subprocess.run(
        ["python3", str(GATE),
         "--phase-dir", str(pd),
         "--phase", "test-1.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
