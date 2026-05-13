"""tests/test_h7_skip_substitute_audit.py — H7 HARD-GATE skip audit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"
REGSEC = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"
ACCEPT = REPO / "commands" / "vg" / "_shared" / "accept" / "audit.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_test_runtime_emits_skip_event():
    body = _read(RUNTIME)
    # When step is skipped by HARD-GATE, must emit test.step_skipped_by_profile event
    assert "test.step_skipped_by_profile" in body, (
        "H7: runtime.md HARD-GATE skip directives must emit "
        "test.step_skipped_by_profile event with step + profile + substitute"
    )


def test_regression_security_emits_skip_event():
    body = _read(REGSEC)
    assert "test.step_skipped_by_profile" in body, (
        "H7: regression-security.md HARD-GATE skip directives must emit "
        "test.step_skipped_by_profile event"
    )


def test_accept_audit_reads_skip_events():
    body = _read(ACCEPT)
    # accept/audit.md must reference skip events or skip-manifest verification
    assert ("test.step_skipped_by_profile" in body or
            "skip_substitute" in body or
            "skip-manifest" in body), (
        "H7: accept/audit.md must verify each test step skipped by profile "
        "has the substitute step's event present"
    )
