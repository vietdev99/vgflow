"""
harness-v2.7-fixup-C2 — orchestrator-dispatch smoke test for blueprint
validators.

Audit finding (crossai-build-audit/sonnet.out, C2):
  blueprint.md sub-step bodies only run grep — no Python validator dispatch
  calls. Auditor could not verify whether the orchestrator's mark-step hook
  actually dispatches manifest-listed validators.

Investigation (this fixup):
  cmd_mark_step (.claude/scripts/vg-orchestrator/__main__.py:901-925) is
  ONLY a marker recorder — emits a `step.marked` event, no manifest read,
  no validator dispatch.

  Validators are dispatched at run-complete via _verify_contract →
  _run_validators (line 3013), keyed by COMMAND_VALIDATORS[command].
  The `triggers.steps` field in dispatch-manifest.json is informational —
  orchestrator dispatches by command match only.

Conclusion: C2 is paperwork — validators ARE firing at run-complete. This
test asserts that the 3 manifest-declared blueprint validators stay
registered + manifest entries stay in sync, so future drift is caught.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def orchestrator_main():
    """Import orchestrator __main__.py via importlib (dir name has hyphen)."""
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader, "orchestrator __main__.py not loadable"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


@pytest.fixture(scope="module")
def dispatch_manifest():
    path = (REPO_ROOT / ".claude" / "scripts" / "validators"
            / "dispatch-manifest.json")
    assert path.exists(), f"dispatch-manifest.json missing at {path}"
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


# --- Case 1: verify-blueprint-completeness wired ---------------------------

def test_blueprint_completeness_registered_for_vg_blueprint(orchestrator_main):
    """verify-blueprint-completeness MUST be in COMMAND_VALIDATORS[vg:blueprint].
    Manifest declares triggers.steps=['2c_verify'] but orchestrator dispatches
    by command — so registration must exist or the BLOCK validator never fires.
    """
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:blueprint", [])
    assert "verify-blueprint-completeness" in validators, (
        f"verify-blueprint-completeness NOT registered for vg:blueprint. "
        f"Audit C2 risk REOPENED. Current: {validators}"
    )


def test_blueprint_completeness_manifest_consistent(dispatch_manifest):
    """Manifest entry must list vg:blueprint command + 2c_verify step."""
    entry = dispatch_manifest.get("validators", {}).get(
        "verify-blueprint-completeness")
    assert entry is not None, "manifest missing verify-blueprint-completeness"
    triggers = entry.get("triggers", {})
    assert "vg:blueprint" in triggers.get("commands", [])
    assert "2c_verify" in triggers.get("steps", [])


# --- Case 2: verify-test-goals-platform-essentials wired -------------------

def test_test_goals_platform_essentials_registered(orchestrator_main):
    """verify-test-goals-platform-essentials MUST be in COMMAND_VALIDATORS
    for vg:blueprint. Manifest steps=['2b5_test_goals'] is informational."""
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:blueprint", [])
    assert "verify-test-goals-platform-essentials" in validators, (
        f"verify-test-goals-platform-essentials NOT registered for vg:blueprint. "
        f"Audit C2 risk REOPENED. Current: {validators}"
    )


# --- Case 3: verify-context-refs wired (wildcard step) ---------------------

def test_context_refs_registered_for_vg_blueprint(orchestrator_main):
    """verify-context-refs (wildcard '*' step) registers via command match."""
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:blueprint", [])
    assert "verify-context-refs" in validators, (
        f"verify-context-refs NOT registered for vg:blueprint. "
        f"Current: {validators}"
    )


def test_context_refs_manifest_wildcard(dispatch_manifest):
    """context-refs uses wildcard step '*' — informational only, but
    documented intent must persist in manifest."""
    entry = dispatch_manifest.get("validators", {}).get("verify-context-refs")
    assert entry is not None, "manifest missing verify-context-refs"
    steps = entry.get("triggers", {}).get("steps", [])
    assert "*" in steps, f"verify-context-refs lost wildcard step: {steps}"


# --- Case 4: dispatch is keyed by COMMAND, not step name -------------------

def test_dispatch_keyed_by_command_not_step(orchestrator_main):
    """Smoke-assert orchestrator dispatch model: _run_validators reads
    COMMAND_VALIDATORS[command], not manifest steps. This is the architectural
    invariant the C2 audit could not verify by code reading alone."""
    src = (REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
           / "__main__.py").read_text(encoding="utf-8")
    # Dispatch must lookup by command
    assert "COMMAND_VALIDATORS.get(command" in src, (
        "_run_validators no longer keys by command — invariant broken"
    )
    # Dispatch must NOT consult manifest steps array (would change semantics)
    # We assert dispatch site does not import dispatch-manifest.json
    assert "dispatch-manifest.json" not in src.split("def _run_validators")[1].split("def ")[0], (
        "_run_validators body referenced dispatch-manifest.json — "
        "step-based dispatch landed; update this test"
    )


# --- Case 5: validator scripts exist ---------------------------------------

@pytest.mark.parametrize("validator_name", [
    "verify-blueprint-completeness",
    "verify-test-goals-platform-essentials",
    "verify-context-refs",
])
def test_validator_scripts_exist(validator_name):
    """Registry pointer must resolve to actual validator script — otherwise
    _run_validators silently skips (line 3029: `if not v_path.exists(): continue`)."""
    path = (REPO_ROOT / ".claude" / "scripts" / "validators"
            / f"{validator_name}.py")
    assert path.exists(), f"{validator_name}.py missing at {path}"


# --- Case 6: dispatch fires at run-complete (not mark-step) ---------------

def test_dispatch_site_is_run_complete(orchestrator_main):
    """Audit asked: does mark-step trigger dispatch? Answer: NO. Dispatch
    fires at cmd_run_complete via _verify_contract. cmd_mark_step is a pure
    marker recorder. This test pins that architectural choice."""
    src = (REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
           / "__main__.py").read_text(encoding="utf-8")
    mark_step_body = src.split("def cmd_mark_step")[1].split("\ndef ")[0]
    # mark-step must not call validator dispatch
    assert "_run_validators" not in mark_step_body, (
        "cmd_mark_step grew validator dispatch — semantic change. "
        "Either intentional (update this test) or accidental (revert)."
    )
    assert "_verify_contract" not in mark_step_body, (
        "cmd_mark_step grew _verify_contract — same risk."
    )
    # run-complete must call _verify_contract (which calls _run_validators)
    run_complete_body = src.split("def cmd_run_complete")[1].split("\ndef ")[0]
    assert "_verify_contract" in run_complete_body, (
        "cmd_run_complete no longer calls _verify_contract — "
        "validators dispatch site moved or deleted"
    )
