"""
Regression test for issue #175 — vg:review must auto-record evidence-manifest
entries for BOTH RUNTIME-MAP.json and GOAL-COVERAGE-MATRIX.md.

Original gap: review fix-loop emitted manifest for GOAL-COVERAGE-MATRIX.md only.
RUNTIME-MAP.json was written by step 2b-3 but never recorded → run-complete
blocked because must_write artifacts existed on disk without manifest entries.

Fix: fix-loop-and-goals.md now emits manifest entries for both files at Phase 4.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "fix-loop-and-goals.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "fix-loop-and-goals.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_canonical_emits_manifest_for_runtime_map():
    body = _read(CANONICAL)
    # The emit block must reference RUNTIME-MAP.json as --path
    assert '--path "${PHASE_DIR}/RUNTIME-MAP.json"' in body, (
        "Issue #175: canonical review skill must call emit-evidence-manifest "
        "with RUNTIME-MAP.json as --path so run-complete can verify provenance."
    )


def test_canonical_emits_manifest_for_goal_coverage_matrix():
    body = _read(CANONICAL)
    assert '--path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"' in body, (
        "Existing emit for GOAL-COVERAGE-MATRIX.md must remain — fix should add "
        "RUNTIME-MAP.json alongside, not replace."
    )


def test_canonical_runtime_map_emit_has_producer_tag():
    body = _read(CANONICAL)
    # Producer must distinguish from goal_comparison so run-complete maps each
    # artifact back to the step that wrote it.
    assert "phase2b3_runtime_map" in body, (
        "RUNTIME-MAP.json emit must carry --producer 'vg:review phase2b3_runtime_map' "
        "so freshness checks attribute the write to the correct step."
    )


def test_canonical_runtime_map_source_inputs_include_nav_discovery():
    body = _read(CANONICAL)
    # RUNTIME-MAP.json is derived from nav-discovery.json + TEST-GOALS.md.
    # Provenance chain must record those so upstream drift is detected.
    runtime_map_block_start = body.index('--path "${PHASE_DIR}/RUNTIME-MAP.json"')
    runtime_map_block = body[runtime_map_block_start:runtime_map_block_start + 600]
    assert "nav-discovery.json" in runtime_map_block, (
        "RUNTIME-MAP.json --source-inputs must include nav-discovery.json"
    )
    assert "TEST-GOALS.md" in runtime_map_block, (
        "RUNTIME-MAP.json --source-inputs must include TEST-GOALS.md"
    )


def test_mirror_matches_canonical_for_runtime_map_emit():
    """v3.6.3 byte-identity rule: .claude/ mirror must match canonical."""
    if not MIRROR.exists():
        # Mirror only exists in installed projects, not always in source repo.
        return
    canonical = _read(CANONICAL)
    mirror = _read(MIRROR)
    # Both must have the RUNTIME-MAP.json emit call.
    assert ('--path "${PHASE_DIR}/RUNTIME-MAP.json"' in canonical) == (
        '--path "${PHASE_DIR}/RUNTIME-MAP.json"' in mirror
    ), "Canonical + .claude/ mirror diverged for RUNTIME-MAP.json manifest emit."


def test_emit_block_guards_file_existence():
    """Emit block must check file exists before calling emitter — review may
    legitimately skip RUNTIME-MAP.json on backend-only phases."""
    body = _read(CANONICAL)
    # Both files must be wrapped in [ -f ... ] guards.
    rt_idx = body.index('--path "${PHASE_DIR}/RUNTIME-MAP.json"')
    gc_idx = body.index('--path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"')
    # Look backwards 200 chars for an `if [ -f` guard.
    pre_rt = body[max(0, rt_idx - 300):rt_idx]
    pre_gc = body[max(0, gc_idx - 300):gc_idx]
    assert 'if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]' in pre_rt, (
        "RUNTIME-MAP.json emit must be guarded by file-existence check"
    )
    assert 'if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]' in pre_gc, (
        "GOAL-COVERAGE-MATRIX.md emit must remain guarded"
    )
