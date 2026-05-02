"""
B7.3 — verify orchestrator dispatcher wires verify-contract-runtime for
vg:build so missing endpoints BLOCK at run-complete instead of surfacing
1+ hour later in review/test.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".claude" / "scripts" / "vg-orchestrator").exists():
            return candidate
    raise RuntimeError("repo root not found")


REPO_ROOT = _repo_root()


@pytest.fixture(scope="module")
def orchestrator_main():
    """Import orchestrator module via importlib (dash in dir name)."""
    # Dir name has a hyphen so `import vg-orchestrator` won't parse.
    # Use importlib.util to load __main__.py directly.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader, "orchestrator __main__.py not loadable"
    mod = importlib.util.module_from_spec(spec)
    # Avoid running if-main block — tests load it as module only
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        # Some orchestrator top-level code may call sys.exit on bad args,
        # but for importing the module, we suppress.
        pass
    return mod


def test_verify_contract_runtime_registered_for_vg_build(orchestrator_main):
    """vg:build must list verify-contract-runtime in its validator chain."""
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:build", [])
    assert "verify-contract-runtime" in validators, (
        f"verify-contract-runtime not registered for vg:build. "
        f"Current: {validators}"
    )


def test_validator_file_exists():
    """Registry pointer must resolve to an actual script."""
    path = (REPO_ROOT / ".claude" / "scripts" / "validators"
            / "verify-contract-runtime.py")
    assert path.exists(), f"validator file missing at {path}"
    text = path.read_text(encoding="utf-8")
    # Sanity: implements the shared Output/Evidence contract
    assert "from _common import" in text
    assert "emit_and_exit" in text


def test_verify_input_validation_registered_for_vg_build(orchestrator_main):
    """B8.2: input validation dormant-schema gate registered for vg:build."""
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:build", [])
    assert "verify-input-validation" in validators, (
        f"verify-input-validation not registered for vg:build. "
        f"Current: {validators}"
    )


def test_build_command_validators_unchanged_except_addition(orchestrator_main):
    """Back-compat: all prior vg:build validators still present — only
    addition, no deletion. Catches accidental registry drift."""
    validators = set(orchestrator_main.COMMAND_VALIDATORS.get("vg:build", []))
    required_prior = {
        "phase-exists", "commit-attribution", "task-goal-binding",
        "plan-granularity", "override-debt-balance", "test-first",
        "build-crossai-required",
    }
    missing = required_prior - validators
    assert not missing, f"prior validators dropped: {missing}"
