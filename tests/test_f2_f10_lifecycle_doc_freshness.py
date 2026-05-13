"""tests/test_f2_f10_lifecycle_doc_freshness.py — F2 + F10 LIFECYCLE doc."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO / "commands" / "vg" / "LIFECYCLE.md"


def test_lifecycle_test_artifact_is_sandbox_test_md():
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "SANDBOX-TEST.md" in body, (
        "F2: LIFECYCLE.md must reference SANDBOX-TEST.md as the test phase output "
        "(the actual artifact written by test/close.md)"
    )
    # The stale TEST-RESULTS.json reference must be either removed or annotated
    # as deprecated. Tolerate if it's in a deprecation note.
    if "TEST-RESULTS.json" in body:
        # Must be in a context that marks it as deprecated/historical
        idx = body.index("TEST-RESULTS.json")
        ctx = body[max(0, idx-200):idx+200]
        assert "deprecated" in ctx.lower() or "historical" in ctx.lower() or "renamed" in ctx.lower(), (
            f"F2: LIFECYCLE.md still references TEST-RESULTS.json without "
            f"marking it deprecated. Context: ...{ctx[150:250]}..."
        )


def test_lifecycle_documents_batch_artifacts():
    body = LIFECYCLE.read_text(encoding="utf-8")
    # F10: must reference key artifacts introduced in Batches 1-9 + H13
    required = [
        ".test-step-status.json",       # Batch 9 C5 ledger
        "LIFECYCLE-SPECS.json",          # Batch 1
        "DEEP-TEST-SPECS.md",            # test-spec lane
        "evidence-manifest",             # Issue #175 provenance
        "TEST-FAILURE-REPORT.md",        # H13 v4.12.0
    ]
    missing = [r for r in required if r not in body]
    assert not missing, (
        f"F10: LIFECYCLE.md must document Batch 1-9 + H13 artifacts. "
        f"Missing references: {missing}"
    )


def test_lifecycle_documents_strict_marker_gate():
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "verify_all_markers_strict_runid" in body or "run_id" in body or "strict marker" in body.lower(), (
        "F10: LIFECYCLE.md must document the strict marker gate introduced in "
        "Batch 9 (C9 verdict integrity)"
    )
