"""Layer 2 Diagnostic UX — universal Type-B BLOCK resolver (RFC v9 D11+D26+PR-D3).

Layer 0 deterministic gate fails on a Type-B BLOCK (semantic, needs
reasoning) → Layer 1 cheap auto-fix candidates fail too → Layer 2
spawns a Diagnostic AI subagent in an isolated context window to:
1. Survey the gate evidence + nearby files.
2. Propose a fix with audit trail (layer2_proposal_id).
3. Surface to user via SINGLE-ADVISORY (not 3-option menu — D26).

D26 single-advisory pattern: when the right answer is clear, advise it
straight: "Recommend: <fix>. Apply? [Y/n]". Don't fabricate alternatives
just to feel democratic.

This module owns the proposal lifecycle (open → applied|rejected) and
emits the audit trail that the matrix-staleness validator and the
evidence-provenance validator both consume to decide if a SUSPECTED →
READY promotion is trustworthy.

Storage: .vg/phases/{phase}/.l2-proposals/{proposal_id}.json
Format:
  {
    "schema_version": "1.0",
    "proposal_id": "l2-{epoch}-{rand6}",
    "gate_id": "...",
    "block_family": "missing-evidence|content-depth|...",
    "evidence_in": {...},
    "diagnosis": "...",
    "proposed_fix": "...",
    "confidence": 0.85,
    "spawned_at": "2026-05-02T10:00:00Z",
    "decided_at": null,
    "decision": null,        # accepted | rejected | applied
    "applied_artifacts": []  # paths touched during fix
  }
"""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"


@dataclass
class L2Proposal:
    proposal_id: str
    gate_id: str
    block_family: str
    evidence_in: dict[str, Any]
    diagnosis: str
    proposed_fix: str
    confidence: float
    spawned_at: str
    schema_version: str = SCHEMA_VERSION
    decided_at: str | None = None
    decision: str | None = None  # accepted | rejected | applied
    applied_artifacts: list[str] = field(default_factory=list)


def proposal_dir(phase_dir: Path) -> Path:
    return phase_dir / ".l2-proposals"


def new_proposal_id() -> str:
    epoch = int(time.time())
    rand6 = secrets.token_hex(3)
    return f"l2-{epoch}-{rand6}"


def render_single_advisory(
    proposal: L2Proposal,
    *,
    locale: str = "vi",
) -> str:
    """Render a tight Vietnamese-default advisory body for AskUserQuestion.

    D26 anti-pattern: don't list 3 fake options when one fix is clearly
    correct. Lead with the recommendation, explain why, ask Y/n.
    """
    if locale == "vi":
        return (
            f"⚠ {proposal.gate_id}\n\n"
            f"Chẩn đoán: {proposal.diagnosis}\n\n"
            f"Đề xuất sửa (confidence={proposal.confidence:.0%}):\n"
            f"  {proposal.proposed_fix}\n\n"
            f"Áp dụng đề xuất này? [Y]es / [n]o / [d]etails"
        )
    return (
        f"⚠ {proposal.gate_id}\n\n"
        f"Diagnosis: {proposal.diagnosis}\n\n"
        f"Recommended fix (confidence={proposal.confidence:.0%}):\n"
        f"  {proposal.proposed_fix}\n\n"
        f"Apply? [Y]es / [n]o / [d]etails"
    )


def write_proposal(phase_dir: Path, proposal: L2Proposal) -> Path:
    pdir = proposal_dir(phase_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    target = pdir / f"{proposal.proposal_id}.json"
    target.write_text(
        json.dumps(asdict(proposal), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def load_proposal(phase_dir: Path, proposal_id: str) -> L2Proposal:
    path = proposal_dir(phase_dir) / f"{proposal_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return L2Proposal(**data)


def record_decision(
    phase_dir: Path,
    proposal_id: str,
    decision: str,
    *,
    applied_artifacts: list[str] | None = None,
) -> L2Proposal:
    """Mark proposal accepted | rejected | applied. Returns updated proposal."""
    if decision not in {"accepted", "rejected", "applied"}:
        raise ValueError(f"unknown decision: {decision}")
    proposal = load_proposal(phase_dir, proposal_id)
    proposal.decision = decision
    proposal.decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if applied_artifacts:
        proposal.applied_artifacts = list(applied_artifacts)
    write_proposal(phase_dir, proposal)
    return proposal


def list_open_proposals(phase_dir: Path) -> list[L2Proposal]:
    """Return proposals without a decision (still pending user/system)."""
    pdir = proposal_dir(phase_dir)
    if not pdir.exists():
        return []
    out: list[L2Proposal] = []
    for f in sorted(pdir.glob("l2-*.json")):
        try:
            p = L2Proposal(**json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            continue
        if p.decision is None:
            out.append(p)
    return out


def make_proposal(
    *,
    gate_id: str,
    block_family: str,
    evidence_in: dict[str, Any],
    diagnosis: str,
    proposed_fix: str,
    confidence: float,
) -> L2Proposal:
    """Construct a new proposal (NOT yet persisted — caller invokes write_proposal)."""
    return L2Proposal(
        proposal_id=new_proposal_id(),
        gate_id=gate_id,
        block_family=block_family,
        evidence_in=evidence_in,
        diagnosis=diagnosis,
        proposed_fix=proposed_fix,
        confidence=max(0.0, min(1.0, confidence)),
        spawned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
