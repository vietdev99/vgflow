"""Contract shape validator — ensure FE call shape matches BE contract shape.

Reads API-CONTRACTS.md (per-endpoint files preferred) for declared method/path/
request/response/auth/status. Compares against actual FE call site (header,
body shape) + BE handler signature. Flags mismatches as BLOCK.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-contract-shape.py"


def test_method_mismatch_blocks(tmp_path: Path) -> None:
    contract = tmp_path / "API-CONTRACTS"
    contract.mkdir()
    (contract / "post-api-orders.md").write_text(textwrap.dedent("""
        # POST /api/orders

        **Method:** POST
        **Path:** /api/orders
        **Request body:** { "items": [...] }
        **Response 201:** { "id": "string" }
        **Auth:** required (Bearer)
    """).strip(), encoding="utf-8")
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "Page.tsx").write_text("axios.get('/api/orders');\n", encoding="utf-8")
    out = tmp_path / "evidence.json"
    result = subprocess.run(
        ["python3", str(GATE),
         "--contracts-dir", str(contract),
         "--fe-root", str(fe),
         "--phase", "test",
         "--evidence-out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert ev["category"] == "contract_shape_mismatch"
    assert "method" in ev["summary"].lower()


def test_matching_call_passes(tmp_path: Path) -> None:
    contract = tmp_path / "API-CONTRACTS"
    contract.mkdir()
    (contract / "get-api-health.md").write_text(textwrap.dedent("""
        # GET /api/health

        **Method:** GET
        **Path:** /api/health
        **Response 200:** { "ok": true }
    """).strip(), encoding="utf-8")
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "Page.tsx").write_text("axios.get('/api/health');\n", encoding="utf-8")
    result = subprocess.run(
        ["python3", str(GATE),
         "--contracts-dir", str(contract),
         "--fe-root", str(fe),
         "--phase", "test"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
