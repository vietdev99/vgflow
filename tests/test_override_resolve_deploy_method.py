"""tests/test_override_resolve_deploy_method.py — Batch 20 deploy method override."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OR_MD = REPO / "commands" / "vg" / "override-resolve.md"


def test_override_resolve_documents_deploy_method():
    body = OR_MD.read_text(encoding="utf-8")
    assert "--deploy-method" in body, (
        "Batch 20: override-resolve.md must document --deploy-method flag "
        "for changing locked deploy contract method"
    )
    # Must mention contract file
    assert "DEPLOY-CONTRACT.json" in body, (
        "Batch 20: must reference the contract file the override modifies"
    )
