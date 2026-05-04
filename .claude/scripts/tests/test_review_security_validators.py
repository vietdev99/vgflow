"""
SEC-1 (2026-04-23) — verify B8 security validators are wired into
vg:review and vg:test dispatchers. Previously they only ran at build
run-complete + pre-push, so users running /vg:review or /vg:test saw
zero security signal from hundreds of LOC of validators we shipped.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def orchestrator_main():
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


# ─────────────────────────────────────────────────────────────────────────
# vg:review — security wire-in

def test_secrets_scan_registered_for_review(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:review", [])
    assert "secrets-scan" in validators, (
        f"secrets-scan not in vg:review. Current: {validators}"
    )


def test_input_validation_registered_for_review(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:review", [])
    assert "verify-input-validation" in validators, (
        f"verify-input-validation not in vg:review. Current: {validators}"
    )


def test_authz_declared_registered_for_review(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:review", [])
    assert "verify-authz-declared" in validators, (
        f"verify-authz-declared not in vg:review. Current: {validators}"
    )


# ─────────────────────────────────────────────────────────────────────────
# vg:test — security wire-in (defense-in-depth)

def test_secrets_scan_registered_for_test(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:test", [])
    assert "secrets-scan" in validators, (
        f"secrets-scan not in vg:test. Current: {validators}"
    )


def test_input_validation_registered_for_test(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:test", [])
    assert "verify-input-validation" in validators, (
        f"verify-input-validation not in vg:test. Current: {validators}"
    )


def test_authz_declared_registered_for_test(orchestrator_main):
    validators = orchestrator_main.COMMAND_VALIDATORS.get("vg:test", [])
    assert "verify-authz-declared" in validators, (
        f"verify-authz-declared not in vg:test. Current: {validators}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Back-compat — existing review/test validators not removed

def test_review_prior_validators_unchanged(orchestrator_main):
    validators = set(orchestrator_main.COMMAND_VALIDATORS.get("vg:review", []))
    required_prior = {"phase-exists", "runtime-evidence", "review-skip-guard"}
    missing = required_prior - validators
    assert not missing, f"prior review validators dropped: {missing}"


def test_test_prior_validators_unchanged(orchestrator_main):
    validators = set(orchestrator_main.COMMAND_VALIDATORS.get("vg:test", []))
    required_prior = {"phase-exists", "goal-coverage", "runtime-evidence",
                      "deferred-evidence"}
    missing = required_prior - validators
    assert not missing, f"prior test validators dropped: {missing}"


# ─────────────────────────────────────────────────────────────────────────
# Validator files exist

@pytest.mark.parametrize("name", [
    "secrets-scan.py",
    "verify-input-validation.py",
    "verify-authz-declared.py",
])
def test_validator_file_exists(name):
    path = REPO_ROOT / ".claude" / "scripts" / "validators" / name
    assert path.exists(), f"validator script missing: {path}"
    text = path.read_text(encoding="utf-8")
    assert "from _common import" in text, f"{name} missing _common contract"
