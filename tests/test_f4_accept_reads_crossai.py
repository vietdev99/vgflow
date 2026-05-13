"""tests/test_f4_accept_reads_crossai.py — F4 accept consumes CrossAI findings."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "commands" / "vg" / "_shared" / "accept" / "audit.md"
GATES = REPO / "commands" / "vg" / "_shared" / "accept" / "gates.md"


def test_accept_reads_crossai_findings():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Must reference CrossAI artifact paths
    assert ("crossai/review-check" in combined or
            "review-check.report.json" in combined or
            "crossai_findings" in combined), (
        "F4: accept/audit.md or gates.md must read CrossAI findings from "
        "${PHASE_DIR}/crossai/review-check.{xml,report.json} OR ${PHASE_DIR}/crossai/"
    )


def test_accept_blocks_on_unacknowledged_high_findings():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Must have BLOCK semantics on HIGH+ unacknowledged
    assert ("HIGH" in combined and ("BLOCK" in combined or "exit 1" in combined)) or "crossai_findings_block" in combined, (
        "F4: must BLOCK accept when CrossAI HIGH findings count > 0 unless "
        "--allow-crossai-findings override with debt logged"
    )


def test_accept_supports_crossai_override_flag():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Override flag for cases where findings are reviewed + accepted
    assert "--allow-crossai-findings" in combined or "skip-crossai" in combined or "ack-crossai" in combined, (
        "F4: accept must support an override flag (--allow-crossai-findings or "
        "similar) so reviewer-acknowledged findings can pass + log to debt"
    )
