"""tests/test_f9_blueprint_override_emit.py — F9 blueprint override emit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_blueprint_skip_flags_emit_override():
    """When --skip-form-api-map or --skip-ui-spec branches are taken,
    blueprint shell must emit 'vg-orchestrator override --flag=... --reason=...'
    so forbidden_without_override contract validator sees the override.used event.
    """
    candidates = [
        REPO / "commands/vg/_shared/blueprint/plan-overview.md",
        REPO / "commands/vg/_shared/blueprint/design.md",
        REPO / "commands/vg/_shared/blueprint/fe-contracts-overview.md",
        REPO / "commands/vg/_shared/blueprint/contracts-overview.md",
    ]
    found_emit = False
    for p in candidates:
        if not p.is_file():
            continue
        body = p.read_text(encoding="utf-8")
        # Look for a branch that handles a --skip-* flag AND calls vg-orchestrator override
        if "--skip-form-api-map" in body or "--skip-ui-spec" in body:
            # In the SAME file, must invoke 'vg-orchestrator override'
            if "vg-orchestrator override" in body and "--reason" in body:
                found_emit = True
                break
    assert found_emit, (
        "F9: blueprint --skip-form-api-map / --skip-ui-spec branches must "
        "call 'vg-orchestrator override --flag=... --reason=...' so the "
        "forbidden_without_override contract validator can enforce reasoned skips."
    )


def test_skip_ui_spec_requires_override_reason():
    """The --skip-ui-spec branch in design.md must block if --override-reason is absent."""
    design = REPO / "commands/vg/_shared/blueprint/design.md"
    body = design.read_text(encoding="utf-8")
    assert "--skip-ui-spec" in body, "F9: design.md must handle --skip-ui-spec flag"
    # Must block if empty
    idx = body.find("--skip-ui-spec")
    block = body[idx:idx + 800]
    assert "OVERRIDE_REASON" in block or "override-reason" in block.lower(), (
        "F9: design.md --skip-ui-spec branch must require --override-reason"
    )


def test_skip_form_api_map_requires_override_reason():
    """The --skip-form-api-map branch must exist in blueprint files and require override-reason."""
    candidates = [
        REPO / "commands/vg/_shared/blueprint/fe-contracts-overview.md",
        REPO / "commands/vg/_shared/blueprint/design.md",
        REPO / "commands/vg/_shared/blueprint/contracts-overview.md",
    ]
    found = False
    for p in candidates:
        if not p.is_file():
            continue
        body = p.read_text(encoding="utf-8")
        if "--skip-form-api-map" in body:
            idx = body.find("--skip-form-api-map")
            block = body[idx:idx + 800]
            if "OVERRIDE_REASON" in block or "override-reason" in block.lower():
                found = True
                break
    assert found, (
        "F9: --skip-form-api-map branch must exist in a blueprint sub-step file "
        "and require --override-reason"
    )
