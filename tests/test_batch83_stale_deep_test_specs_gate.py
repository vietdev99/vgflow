"""B83 v4.64.0 — Remove stale v3.6.6 deep-test-specs preflight gate.

Conflict surfaced by user (RTB phase 8.1 dogfood, 2026-05-18) after B81
PIPELINE-STATE flip shipped:

  - `build/close.md:838` emits `next_command=/vg:review`
  - But `review/preflight.md:281-307` (v3.6.6 gate) fired immediately
    BLOCKing review with "run /vg:test-spec first"
  - test-spec then required `RUNTIME-MAP.json` produced ONLY by review
    → unresolvable deadlock

Canonical pipeline per B69 + LIFECYCLE.md:64-65:
    build → review → test-spec → test → accept

review produces RUNTIME-MAP.json (lens-and-findings.md:371).
test-spec requires it (test-spec.md:178 Step 1 gate).
Therefore review MUST run before test-spec.

The v3.6.6 gate was a stale design that the B69 reorganization in
test-spec.md superseded but never cleaned up. B83 removes it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "preflight.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "preflight.md"


def test_b83_v366_gate_removed() -> None:
    """The v3.6.6 deep-test-specs gate must no longer be active code.

    Allowed: explanatory comment block referencing v3.6.6 (audit trail).
    Disallowed: any active bash that calls `verify-deep-test-specs.py`
    OR exits with "/vg:test-spec ... before /vg:review".
    """
    body = PREFLIGHT.read_text(encoding="utf-8")
    # Disallowed phrase from old gate (BLOCK message)
    assert "Deep test specs missing or shallow" not in body, (
        "v3.6.6 gate block message still present"
    )
    assert "DEEP_SPEC_REQUIRED" not in body, (
        "v3.6.6 gate variable still present"
    )
    assert "DEEP_SPEC_VALIDATOR" not in body, (
        "v3.6.6 gate validator invocation still present"
    )
    assert "review.deep_test_spec_blocked" not in body, (
        "v3.6.6 gate event emit still present"
    )


def test_b83_audit_comment_explains_removal() -> None:
    """A B83 audit comment must justify the removal so future readers
    don't reintroduce the gate without considering the deadlock.
    """
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "B83" in body, "B83 audit-trail comment missing"
    assert "B69" in body, "removal must reference B69 canonical pipeline"
    assert "build → review → test-spec" in body, (
        "canonical pipeline order must be documented in the removal comment"
    )
    assert "deadlock" in body.lower() or "RUNTIME-MAP" in body, (
        "removal rationale (deadlock OR RUNTIME-MAP dependency) must be documented"
    )


def test_b83_mirror_byte_identical() -> None:
    assert PREFLIGHT.read_bytes() == MIRROR.read_bytes(), (
        "review/preflight.md mirror drift"
    )
