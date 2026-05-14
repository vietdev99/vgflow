"""tests/test_batch32_blueprint_scaffold_gates.py — Batch 32.

Audit: docs/plans/2026-05-15-codex-blueprint-scaffold-audit.md identified
4 SCAFFOLD blueprint markers (no bash, no mark-step).

- 2b5e_a_lens_walk: source drift — file existed in .claude/ mirror but
  NOT in commands/ source tree. FIXED via cp (separate change).
- 2b6d_fe_contracts: fe-contracts-overview.md prose only.
- 2b8_rcrurdr_invariants: blueprint.md:166 declares marker, no owner file.
- 2b9_workflows: workflows-overview.md prose only.

Fix: add real bash with step-active + validator invoke + mark-step gate.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FE = REPO / "commands" / "vg" / "_shared" / "blueprint" / "fe-contracts-overview.md"
WF = REPO / "commands" / "vg" / "_shared" / "blueprint" / "workflows-overview.md"
LENS = REPO / "commands" / "vg" / "_shared" / "blueprint" / "lens-walk.md"
BLUEPRINT = REPO / "commands" / "vg" / "blueprint.md"


def test_lens_walk_source_drift_fixed():
    """lens-walk.md must exist in commands/ source tree (was only in .claude/)."""
    assert LENS.exists(), (
        "Batch 32 gap #1: lens-walk.md source drift. File existed in "
        ".claude/commands/vg/_shared/blueprint/ but not in commands/. "
        "Reference in blueprint.md:338 broke."
    )
    mirror = REPO / ".claude" / LENS.relative_to(REPO)
    assert LENS.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8")


def test_2b6d_fe_contracts_has_bash_gate():
    """2b6d_fe_contracts must have step-active + validator bash + mark-step.
    Currently prose only."""
    body = FE.read_text(encoding="utf-8")
    assert "vg-orchestrator step-active 2b6d_fe_contracts" in body or \
           "step-active 2b6d_fe_contracts" in body, (
        "Batch 32 gap #2b6d: fe-contracts-overview.md must invoke "
        "step-active 2b6d_fe_contracts before any work"
    )
    assert "verify-fe-contract-block5.py" in body, "must invoke validator"
    assert "mark-step blueprint 2b6d_fe_contracts" in body, (
        "Batch 32: must mark-step on validator pass"
    )


def test_2b9_workflows_has_bash_gate():
    """2b9_workflows must have step-active + validator bash + mark-step."""
    body = WF.read_text(encoding="utf-8")
    assert "step-active 2b9_workflows" in body, (
        "Batch 32 gap #2b9: workflows-overview.md must invoke step-active"
    )
    assert "verify-workflow-specs.py" in body, "must invoke validator"
    assert "mark-step blueprint 2b9_workflows" in body, (
        "Batch 32: must mark-step on validator pass"
    )


def test_2b8_rcrurdr_has_owner_or_referenced():
    """2b8_rcrurdr_invariants declared in blueprint.md must_mark — must
    have a bash invocation site somewhere. Either inline in blueprint.md
    or owned _shared file."""
    bp = BLUEPRINT.read_text(encoding="utf-8")
    has_2b8_bash = "step-active 2b8_rcrurdr_invariants" in bp
    # Or check _shared file owner
    owner = REPO / "commands" / "vg" / "_shared" / "blueprint" / "rcrurdr-invariants.md"
    if not has_2b8_bash:
        assert owner.exists(), (
            "Batch 32 gap #2b8: rcrurdr-invariants must have owner file "
            "commands/vg/_shared/blueprint/rcrurdr-invariants.md OR inline "
            "bash in blueprint.md. Currently neither."
        )
        owner_body = owner.read_text(encoding="utf-8")
        assert "step-active 2b8_rcrurdr_invariants" in owner_body
        assert "mark-step blueprint 2b8_rcrurdr_invariants" in owner_body


def test_mirrors_in_sync():
    for src in [FE, WF, LENS]:
        mirror = REPO / ".claude" / src.relative_to(REPO)
        assert src.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8"), (
            f"Mirror drift: {mirror.relative_to(REPO)}"
        )
    owner = REPO / "commands" / "vg" / "_shared" / "blueprint" / "rcrurdr-invariants.md"
    if owner.exists():
        mirror = REPO / ".claude" / owner.relative_to(REPO)
        assert mirror.exists() and \
            owner.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8")
