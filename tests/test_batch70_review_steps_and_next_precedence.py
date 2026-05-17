"""tests/test_batch70_review_steps_and_next_precedence.py

B70a + B70b — root-cause fix for the user-reported "review xong không thấy
đề xuất /vg:test-spec mà là /vg:test" bug on RTB phase 7.16.

Codex adversarial audit on initial B70 plan returned FAIL with 6 BLOCKERS.
Root cause was NOT missing PIPELINE-STATE.json (file existed and contained
`next_command="/vg:test 7.16"` correctly written by test-spec/close after
user manually ran /vg:test-spec). Root cause was B69 oversight: review/close
emitted top-level `next_command` but never wrote `steps.review` subkey, so
downstream consumers (test-spec/close merge, /vg:next routing precedence,
accept gate) could not read the review verdict from PIPELINE-STATE.json.

This file covers B70a (review/close writes steps.review with parsed verdict
from GOAL-COVERAGE-MATRIX) and B70b (/vg:next prefers PIPELINE-STATE
next_command over recon-state next_command when pipeline-state is newer).

The migration backfill (B70c → v4.62.0) lives in a separate test module.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

REVIEW_CLOSE = REPO / "commands" / "vg" / "_shared" / "review" / "close.md"
REVIEW_CLOSE_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "close.md"
NEXT_MD = REPO / "commands" / "vg" / "next.md"
NEXT_MD_MIRROR = REPO / ".claude" / "commands" / "vg" / "next.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# B70a — review/close.md writes steps.review + verdict-aware next_command
# ---------------------------------------------------------------------------


def test_b70a_review_close_writes_steps_review():
    """B70a: review/close.md MUST write steps.review subkey."""
    body = _read(REVIEW_CLOSE)
    # The fix block sets steps.review with status, verdict, finished_at.
    assert "s.setdefault('steps', {})['review']" in body, (
        "B70a — review/close.md must call s.setdefault('steps',{})['review']"
    )
    assert "'status': 'done'" in body
    assert "'verdict': verdict" in body
    assert "'finished_at': now" in body


def test_b70a_review_close_parses_matrix_json_first():
    """B70a: prefer GOAL-COVERAGE-MATRIX.json (canonical) over .md."""
    body = _read(REVIEW_CLOSE)
    assert "matrix_json = Path('${PHASE_DIR}/GOAL-COVERAGE-MATRIX.json')" in body
    assert "if matrix_json.exists():" in body
    assert "elif matrix_md.exists():" in body


def test_b70a_review_close_fallback_md_regex_handles_legacy_verdicts():
    """B70a: .md fallback maps STATIC-READY/BROWSER-PENDING/READY/FAIL to canonical."""
    body = _read(REVIEW_CLOSE)
    assert "'STATIC-READY':'TEST_PENDING'" in body
    assert "'BROWSER-PENDING':'TEST_PENDING'" in body
    assert "'READY':'PASS'" in body
    assert "'FAIL':'BLOCK'" in body


def test_b70a_verdict_aware_next_command_block_on_block_or_fail():
    """B70a: BLOCK / FAIL verdict → next_command=None + reason recorded."""
    body = _read(REVIEW_CLOSE)
    assert "if verdict in ('BLOCK','FAIL'):" in body
    assert "s['next_command'] = None" in body
    assert "next_command_blocked_reason" in body


def test_b70a_verdict_pass_or_unknown_keeps_test_spec_routing():
    """B70a: PASS / PASS-WITH-FLAGS / TEST_PENDING / UNKNOWN → /vg:test-spec.

    UNKNOWN errs toward forward motion since absence of matrix verdict is
    not a BLOCK signal (matches B69 intent).
    """
    body = _read(REVIEW_CLOSE)
    # The else-branch sets /vg:test-spec for any non-BLOCK/FAIL verdict.
    assert "else:" in body
    assert "s['next_command'] = '/vg:test-spec ${PHASE_NUMBER}'" in body
    assert "s['steps']['review']['next_command'] = '/vg:test-spec ${PHASE_NUMBER}'" in body


def test_b70a_marker_present_for_grep():
    """B70a: 'B70a' tag present in close.md for codex audit grep + history."""
    body = _read(REVIEW_CLOSE)
    assert "B70a" in body


def test_b70a_b69_top_level_next_command_preserved_for_back_compat():
    """B70a does not delete B69's top-level next_command — it ALSO emits steps.review.

    Top-level next_command remains the canonical /vg:next signal (and B70b
    reads it). steps.review.next_command is a secondary surface for
    consumers that read per-step routing.
    """
    body = _read(REVIEW_CLOSE)
    # B69 fix marker still present.
    assert "B69 fix" in body
    # Top-level next_command set in BOTH branches.
    matches = re.findall(r"s\['next_command'\]\s*=", body)
    assert len(matches) >= 2, (
        f"expected >=2 top-level next_command assignments (BLOCK branch + PASS branch); "
        f"found {len(matches)}"
    )


def test_b70a_verdict_parser_simulation_pass():
    """Simulate the verdict parser body against a sample PASS matrix.md."""
    sample = textwrap.dedent(
        """
        # Phase 7.16 — GOAL-COVERAGE-MATRIX
        ## INTENT verdict
        **Phase 7.16 review verdict: PASS**
        """
    )
    # Mirror the regex from close.md.
    m = re.search(
        r"(?im)^\s*(?:\*\*)?(?:Phase\s+[\w.-]+\s+)?(?:review\s+)?verdict\s*:?\s*\*?\*?\s*"
        r"(PASS-WITH-FLAGS|PASS|TEST_PENDING|BLOCK|FAIL|STATIC-READY|READY|BROWSER-PENDING)",
        sample,
    )
    assert m is not None
    assert m.group(1).upper() == "PASS"


def test_b70a_verdict_parser_simulation_static_ready_maps_to_test_pending():
    """STATIC-READY in matrix.md → normalized to TEST_PENDING (browser-dependent)."""
    sample = "**Phase 7.16 review verdict: STATIC-READY / BROWSER-PENDING**"
    m = re.search(
        r"(?im)^\s*(?:\*\*)?(?:Phase\s+[\w.-]+\s+)?(?:review\s+)?verdict\s*:?\s*\*?\*?\s*"
        r"(PASS-WITH-FLAGS|PASS|TEST_PENDING|BLOCK|FAIL|STATIC-READY|READY|BROWSER-PENDING)",
        sample,
    )
    assert m is not None
    raw = m.group(1).upper()
    mapped = {
        "STATIC-READY": "TEST_PENDING",
        "BROWSER-PENDING": "TEST_PENDING",
        "READY": "PASS",
        "FAIL": "BLOCK",
    }.get(raw, raw)
    assert mapped == "TEST_PENDING"


# ---------------------------------------------------------------------------
# B70b — /vg:next prefers PIPELINE-STATE.next_command over recon-state when newer
# ---------------------------------------------------------------------------


def test_b70b_next_md_has_route_0a_precedence_block():
    """B70b: next.md must have Route 0a block declaring precedence."""
    body = _read(NEXT_MD)
    assert "Route 0a (B70b — pipeline-state precedence)" in body
    assert "PIPELINE-STATE.next_command" in body
    assert "recon-state" in body or ".recon-state" in body


def test_b70b_pipeline_state_read_invokes_python():
    """B70b: precedence check uses python json read (not bash grep)."""
    body = _read(NEXT_MD)
    # Anchor: the PIPELINE_NEXT assignment block.
    idx = body.find("PIPELINE_NEXT=$(")
    assert idx > 0, "PIPELINE_NEXT command-substitution missing"
    block = body[idx : idx + 1200]
    assert "json.loads(ps.read_text" in block
    assert "p.get('next_command')" in block


def test_b70b_timestamp_comparison_pipeline_vs_recon():
    """B70b: only override when pipeline-state.updated_at >= recon.classified_at.

    Audit BLOCKER B-2 said recon re-derives on every run — newer-wins logic
    prevents stale recon from masking a fresh PIPELINE-STATE.next_command.
    """
    body = _read(NEXT_MD)
    assert "classified_at" in body
    # Conservative comparison: only emit PIPELINE-STATE when newer-or-equal.
    assert "p_ts >= r_ts" in body


def test_b70b_non_empty_pipeline_next_invokes_directly():
    """B70b: non-empty $PIPELINE_NEXT → echo + handoff (skip recon routes)."""
    body = _read(NEXT_MD)
    assert 'if [ -n "$PIPELINE_NEXT" ];' in body
    assert "Invoke:" in body


def test_b70b_route_0_legacy_label_present():
    """B70b: original Route 0 relabeled 'legacy resume' so Route 0a precedes it."""
    body = _read(NEXT_MD)
    assert "**Route 0 (legacy resume):**" in body


def test_b70b_b70b_marker_present():
    body = _read(NEXT_MD)
    assert "B70b" in body


# ---------------------------------------------------------------------------
# Mirror parity — every B70a/B70b edit must land in .claude/ copies too.
# ---------------------------------------------------------------------------


def test_b70_mirror_parity_review_close():
    assert _read(REVIEW_CLOSE) == _read(REVIEW_CLOSE_MIRROR)


def test_b70_mirror_parity_next_md():
    assert _read(NEXT_MD) == _read(NEXT_MD_MIRROR)


# ---------------------------------------------------------------------------
# Goal-coverage-matrix.json schema (Batch 34 F2 canonical) compatibility.
# ---------------------------------------------------------------------------


def test_b70a_matrix_json_gate_key_or_verdict_key():
    """B70a: parser checks both `gate` and `verdict` keys in matrix.json.

    Batch 34 F2 canonical key is `gate`; older synthesizers may emit `verdict`.
    Parser uses (gate or verdict or 'UNKNOWN').
    """
    body = _read(REVIEW_CLOSE)
    assert "mj.get('gate') or mj.get('verdict')" in body
