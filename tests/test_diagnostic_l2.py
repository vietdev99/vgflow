"""Tests for scripts/runtime/diagnostic_l2.py — RFC v9 PR-D3."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.diagnostic_l2 import (  # noqa: E402
    L2Proposal,
    list_open_proposals,
    load_proposal,
    make_proposal,
    new_proposal_id,
    proposal_dir,
    record_decision,
    render_single_advisory,
    write_proposal,
)


def _stub_proposal(**overrides) -> L2Proposal:
    base = dict(
        gate_id="missing-evidence",
        block_family="provenance",
        evidence_in={"goal": "G-10"},
        diagnosis="Mutation step at G-10/step[2] missing evidence.source",
        proposed_fix="Re-run scanner: /vg:review {phase} --re-scan-goals=G-10",
        confidence=0.85,
    )
    base.update(overrides)
    return make_proposal(**base)


def test_new_proposal_id_format():
    pid = new_proposal_id()
    assert pid.startswith("l2-")
    parts = pid.split("-")
    assert len(parts) == 3
    int(parts[1])  # epoch is numeric
    assert len(parts[2]) == 6  # rand6


def test_make_proposal_clamps_confidence():
    p = _stub_proposal(confidence=1.5)
    assert p.confidence == 1.0
    p = _stub_proposal(confidence=-0.2)
    assert p.confidence == 0.0


def test_write_then_load_roundtrip(tmp_path):
    p = _stub_proposal()
    write_proposal(tmp_path, p)
    loaded = load_proposal(tmp_path, p.proposal_id)
    assert loaded.proposal_id == p.proposal_id
    assert loaded.diagnosis == p.diagnosis
    assert loaded.evidence_in == p.evidence_in


def test_render_single_advisory_vietnamese():
    p = _stub_proposal()
    text = render_single_advisory(p, locale="vi")
    assert "Chẩn đoán" in text
    assert "Áp dụng đề xuất này?" in text
    assert "85%" in text  # confidence


def test_render_single_advisory_english():
    p = _stub_proposal()
    text = render_single_advisory(p, locale="en")
    assert "Diagnosis:" in text
    assert "Apply?" in text


def test_render_single_advisory_no_3_options_anti_pattern():
    """D26: do NOT show A/B/C menu — single advisory only."""
    p = _stub_proposal()
    text = render_single_advisory(p, locale="vi")
    # Must not have "Option A:" / "(a)" / "1." / etc.
    assert "Option A" not in text
    assert "Lựa chọn 1" not in text
    assert "(a)" not in text
    # Must have the single decision: Y/n/d
    assert "[Y]" in text


def test_record_decision_accepted(tmp_path):
    p = _stub_proposal()
    write_proposal(tmp_path, p)
    updated = record_decision(tmp_path, p.proposal_id, "accepted")
    assert updated.decision == "accepted"
    assert updated.decided_at is not None


def test_record_decision_applied_with_artifacts(tmp_path):
    p = _stub_proposal()
    write_proposal(tmp_path, p)
    updated = record_decision(
        tmp_path, p.proposal_id, "applied",
        applied_artifacts=["RUNTIME-MAP.json", "GOAL-COVERAGE-MATRIX.md"],
    )
    assert updated.decision == "applied"
    assert "RUNTIME-MAP.json" in updated.applied_artifacts


def test_record_decision_rejected(tmp_path):
    p = _stub_proposal()
    write_proposal(tmp_path, p)
    updated = record_decision(tmp_path, p.proposal_id, "rejected")
    assert updated.decision == "rejected"


def test_record_decision_invalid_raises(tmp_path):
    p = _stub_proposal()
    write_proposal(tmp_path, p)
    with pytest.raises(ValueError, match="unknown decision"):
        record_decision(tmp_path, p.proposal_id, "maybe-later")


def test_list_open_proposals_returns_only_undecided(tmp_path):
    p1 = _stub_proposal()
    p2 = _stub_proposal()
    p3 = _stub_proposal()
    write_proposal(tmp_path, p1)
    write_proposal(tmp_path, p2)
    write_proposal(tmp_path, p3)
    record_decision(tmp_path, p1.proposal_id, "applied")
    record_decision(tmp_path, p2.proposal_id, "rejected")
    open_props = list_open_proposals(tmp_path)
    assert len(open_props) == 1
    assert open_props[0].proposal_id == p3.proposal_id


def test_list_open_proposals_handles_missing_dir(tmp_path):
    assert list_open_proposals(tmp_path / "missing") == []


def test_persisted_file_includes_layer2_proposal_id(tmp_path):
    """Audit trail: matrix-staleness/evidence-provenance check this ID exists."""
    p = _stub_proposal()
    target = write_proposal(tmp_path, p)
    data = json.loads(target.read_text())
    assert data["proposal_id"] == p.proposal_id
    assert data["schema_version"] == "1.0"


def test_proposal_dir_path(tmp_path):
    assert proposal_dir(tmp_path).name == ".l2-proposals"


def test_two_proposals_have_unique_ids():
    p1 = _stub_proposal()
    p2 = _stub_proposal()
    assert p1.proposal_id != p2.proposal_id
