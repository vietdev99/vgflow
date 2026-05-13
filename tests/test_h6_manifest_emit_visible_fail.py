"""tests/test_h6_manifest_emit_visible_fail.py — H6 silent manifest emit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "test" / "fix-loop-and-verdict.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_manifest_emit_drops_quiet_for_runtime_map():
    body = _read(CANON)
    rt_idx = body.find('--path "${PHASE_DIR}/RUNTIME-MAP.json"')
    assert rt_idx > 0
    # Look in next 500 chars for the emit block
    block = body[rt_idx:rt_idx + 500]
    # New behavior: must NOT use --quiet || true silent pattern
    assert "--quiet || true" not in block, (
        "H6: RUNTIME-MAP.json manifest emit must NOT swallow output via "
        "'--quiet || true'. On failure, partial emit fails silently → "
        "run-complete blocks with 'manifest missing for X' but user has "
        "no idea which emit failed."
    )


def test_manifest_emit_drops_quiet_for_goal_coverage():
    body = _read(CANON)
    gc_idx = body.find('--path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"')
    assert gc_idx > 0
    block = body[gc_idx:gc_idx + 500]
    assert "--quiet || true" not in block, (
        "H6: GOAL-COVERAGE-MATRIX.md manifest emit must NOT use "
        "'--quiet || true' silent pattern."
    )


def test_manifest_emit_fail_surfaces_warning():
    body = _read(CANON)
    # Failure path must emit a visible warning + event
    assert "review.manifest_emit_failed" in body or "manifest_emit_fail" in body or "manifest emit failed" in body, (
        "H6: failure path must emit review.manifest_emit_failed event + "
        "visible echo so user sees which path failed."
    )
