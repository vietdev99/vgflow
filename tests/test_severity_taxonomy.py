"""Severity taxonomy enum + machine-readable evidence shape."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_severity_enum_has_4_tiers() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import Severity  # type: ignore

    assert {s.value for s in Severity} == {
        "BLOCK", "TRIAGE_REQUIRED", "FORWARD_DEP", "ADVISORY",
    }


def test_severity_ordering() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import Severity  # type: ignore

    # BLOCK is most severe; ADVISORY least.
    assert Severity.BLOCK.weight > Severity.TRIAGE_REQUIRED.weight
    assert Severity.TRIAGE_REQUIRED.weight > Severity.FORWARD_DEP.weight
    assert Severity.FORWARD_DEP.weight > Severity.ADVISORY.weight


def test_evidence_schema_validates_minimal_doc() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import validate_evidence  # type: ignore

    doc = {
        "warning_id": "fe-be-gap-1",
        "severity": "BLOCK",
        "category": "fe_be_call_graph",
        "phase": "4.1",
        "evidence_refs": [{"file": "apps/web/src/pages/InvoiceDetailPage.tsx", "line": 42}],
        "summary": "FE calls GET /api/v1/admin/invoices/:id/payments — BE has no GET handler",
        "detected_by": "verify-fe-be-call-graph.py",
        "detected_at": "2026-05-03T10:00:00Z",
    }
    validate_evidence(doc)  # raises on schema violation


def test_evidence_schema_rejects_missing_severity() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import validate_evidence  # type: ignore

    doc = {"warning_id": "x", "category": "y", "phase": "1.0",
           "evidence_refs": [], "summary": "x", "detected_by": "x",
           "detected_at": "2026-01-01T00:00:00Z"}
    with pytest.raises(Exception, match="severity"):
        validate_evidence(doc)
