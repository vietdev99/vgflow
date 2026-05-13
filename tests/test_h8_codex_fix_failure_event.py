"""tests/test_h8_codex_fix_failure_event.py — H8 stderr-only codex failure."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "test" / "fix-loop-and-verdict.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_codex_spawn_failure_emits_event():
    body = _read(CANON)
    cx_idx = body.find("codex-spawn.sh")
    assert cx_idx > 0
    block = body[cx_idx:cx_idx + 2000]
    # Failure path must emit event
    assert "test.codex_fix_failed" in body or "codex_fix_failed" in body, (
        "H8: codex-spawn fix-agent failure must emit test.codex_fix_failed "
        "event (not just stderr echo)"
    )


def test_codex_failure_writes_to_phase_dir():
    body = _read(CANON)
    # Failure must persist to phase dir (not just stderr noise)
    assert "CODEX-FIX-FAILURES" in body or "REVIEW-FEEDBACK.md" in body, (
        "H8: codex fix-agent failure must persist to phase dir artifact "
        "(CODEX-FIX-FAILURES.json or REVIEW-FEEDBACK.md entry)"
    )
