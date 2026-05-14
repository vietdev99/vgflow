"""tests/test_f6_ui_runtime_contract_gate.py — F6 UI-RUNTIME-CONTRACT gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
BLUEPRINT = REPO / "commands" / "vg" / "blueprint.md"


def test_blueprint_contract_lists_ui_runtime_contract():
    body = BLUEPRINT.read_text(encoding="utf-8")
    # must_write block must reference UI-RUNTIME-CONTRACT.json or .md
    assert "UI-RUNTIME-CONTRACT" in body, (
        "F6: blueprint.md must_write must list UI-RUNTIME-CONTRACT.{md,json} "
        "with required_unless_flag for non-legacy FE phases"
    )


def test_emitter_failure_no_longer_silent():
    body = DESIGN.read_text(encoding="utf-8")
    # The line that says 'continuing (contract is informational at Stage 2; Stages 3-4 will harden)'
    # must be replaced or guarded by FE-phase check
    if "emit-ui-runtime-contract.py exit=" in body:
        # If we still continue silently, it must be guarded by a backend-only check
        idx = body.find("emit-ui-runtime-contract.py exit=")
        ctx = body[max(0, idx-200):idx+400]
        assert ("FE_TASKS" in ctx or "PHASE_PROFILE" in ctx or "exit 1" in ctx), (
            "F6: emitter non-zero exit must escalate for FE phases — current "
            "'continuing' wording masks failures"
        )
