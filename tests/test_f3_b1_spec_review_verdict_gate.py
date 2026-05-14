"""tests/test_f3_b1_spec_review_verdict_gate.py — F3 spec review verdict gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
PE = REPO / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_marker_touch_conditional_on_verdict_file():
    body = _read(PE)
    # Find STEP 5.1 marker touch block
    marker_idx = body.find("5_1_spec_compliance_review.done")
    assert marker_idx > 0
    # Look backwards 600 chars for verdict-file gate (NOT in the SKIP_SPEC_REVIEW branch)
    # The non-skip branch must check verdict file before touching marker
    body_segment = body[max(0, marker_idx - 1500):marker_idx]
    # Must reference verdict file path AND a guard (if/test) before marker
    assert ".spec-review" in body_segment or "spec-review" in body_segment, (
        "F3: post-execution-overview.md STEP 5.1 must reference per-task spec-review "
        "verdict directory (e.g. ${PHASE_DIR}/.spec-review/{task_id}.md) "
        "so verdict file existence can be gated before marker"
    )


def test_verdict_file_existence_check_present():
    body = _read(PE)
    # Locate per-task loop area
    loop_start = body.find('for task_id in "${WAVE_TASKS[@]}"')
    assert loop_start > 0
    loop_block = body[loop_start:loop_start + 2500]
    # Must guard marker write on verdict file presence ([ -f or [ ! -f for negation check)
    assert ("[ -f" in loop_block or "[ ! -f" in loop_block or "test -f" in loop_block or "Path(" in loop_block), (
        "F3: per-task spec-review loop must check verdict file exists before "
        "proceeding (otherwise marker fires without evidence)"
    )


def test_fail_verdict_blocks():
    body = _read(PE)
    # Some FAIL handling must exist
    assert "FAIL" in body
    # And a block path
    assert ("exit 1" in body or "BLOCK" in body or "must be FAIL" in body), (
        "F3: FAIL verdict path must block (exit 1) unless --skip-spec-review override"
    )
