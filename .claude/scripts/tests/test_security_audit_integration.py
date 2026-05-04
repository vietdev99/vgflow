"""
SEC-2 (2026-04-23) — verify 5f_security_audit step in test.md invokes
B8 validators (Tier 0), not just grep prose from earlier versions.

Before SEC-2: step 5f_security_audit was 4-tier grep only. Users ran
/vg:test 7.13 → runtime evaluated grep patterns but never invoked
secrets-scan.py / verify-input-validation.py / verify-authz-declared.py,
even though those scripts existed on disk. That was the SEC-2 gap.

This test asserts the step body contains explicit Tier 0 invocations
so the gap cannot silently reopen via future edits.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "test.md"


@pytest.fixture(scope="module")
def step_5f_body() -> str:
    """Extract body of <step name="5f_security_audit"> block."""
    text = TEST_MD.read_text(encoding="utf-8")
    # Match from opening tag to next <step or closing </step>
    m = re.search(
        r'<step name="5f_security_audit">(.*?)(?=<step name="5f_mobile_security_audit")',
        text, re.DOTALL,
    )
    assert m, "5f_security_audit step not found in test.md"
    return m.group(1)


def test_tier0_header_present(step_5f_body):
    """Tier 0 section header signals structured validator invocation."""
    assert "Tier 0" in step_5f_body, (
        "5f missing Tier 0 section — B8 validators not wired into test pipeline"
    )


def test_secrets_scan_invoked(step_5f_body):
    """secrets-scan.py must be explicitly invoked with --phase."""
    assert "secrets-scan.py" in step_5f_body, "secrets-scan.py not invoked"
    # Sanity: --phase flag passed
    assert re.search(r"secrets-scan.*--phase|--phase.*secrets-scan",
                     step_5f_body, re.DOTALL) or \
           "for V in secrets-scan" in step_5f_body, \
        "secrets-scan invoked without --phase flag"


def test_input_validation_invoked(step_5f_body):
    assert "verify-input-validation" in step_5f_body, \
        "verify-input-validation.py not invoked in 5f"


def test_authz_declared_invoked(step_5f_body):
    assert "verify-authz-declared" in step_5f_body, \
        "verify-authz-declared.py not invoked in 5f"


def test_tier0_exit_tracked(step_5f_body):
    """Tier 0 must track exit code separately so it can block final verdict."""
    assert "SEC_TIER0_EXIT" in step_5f_body, (
        "Tier 0 exit code not tracked — verdict can't distinguish B8 block "
        "from grep advisory"
    )


def test_final_verdict_respects_tier0(step_5f_body):
    """Display section must reference Tier 0 in verdict rules."""
    assert "Tier 0" in step_5f_body.split("Display:")[-1], (
        "Tier 0 not surfaced in final verdict display/rules"
    )


def test_validator_scripts_exist_on_disk():
    """Scripts invoked by Tier 0 must exist (prevents drift)."""
    for name in ("secrets-scan.py", "verify-input-validation.py",
                 "verify-authz-declared.py"):
        path = REPO_ROOT / ".claude" / "scripts" / "validators" / name
        assert path.exists(), f"validator script missing: {path}"


def test_tier1_still_present(step_5f_body):
    """Tier 1 grep kept as advisory complement, not replaced."""
    assert "Tier 1: Built-in Security Grep" in step_5f_body, (
        "Tier 1 grep was dropped — intent was to ADD Tier 0, not replace."
    )
