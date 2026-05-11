"""tests/test_build_close_contract_runtime_gate.py — Codex-recommended wiring fix.

Verifies that verify-contract-runtime.py is hard-wired as a BLOCK gate at
build-close, before PR-E truthcheck. Closes the 'phantom endpoints declared
in contract, never implemented' gap that previously surfaced only at review
step 5b — too late.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOSE_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "close.md"
CLOSE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "close.md"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"
REGISTRY_MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"
BUILD_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "build.md"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-contract-runtime.py"


def test_validator_exists():
    """The validator script itself must exist — Codex verified this."""
    assert VALIDATOR.is_file()


def test_registry_severity_block_not_warn():
    """v3.7.1: contract-runtime registry severity promoted warn → block.

    Codex finding: registry.yaml:530 listed severity 'warn' but the validator
    is designed to BLOCK on declared-but-not-implemented endpoints. Promotion
    aligns config with intent.
    """
    body = REGISTRY.read_text(encoding="utf-8")
    # Find the contract-runtime block — stop before the next "- id:" entry
    m = re.search(
        r"- id: contract-runtime\b.*?(?=\n\s*- id:|\Z)",
        body,
        re.DOTALL,
    )
    assert m, "contract-runtime entry missing from registry.yaml"
    block = m.group(0)
    assert "severity: block" in block, (
        "contract-runtime must declare severity: block per Codex wiring fix"
    )
    assert "severity: warn" not in block, (
        "old warn-severity must be replaced, not appended"
    )


def test_close_invokes_verify_contract_runtime():
    """v3.7.1: build close.md must invoke verify-contract-runtime.py BEFORE PR-E truthcheck.

    Codex finding: validator existed (378 lines) but was never invoked in any
    build phase — pure dead code at the harness level. Wiring fix inserts the
    invocation right before the RFC v9 PR-E API truthcheck section.
    """
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "verify-contract-runtime.py" in body, (
        "close.md must invoke verify-contract-runtime.py"
    )
    # Must appear BEFORE the PR-E truthcheck section header
    contract_runtime_idx = body.index("verify-contract-runtime.py")
    pr_e_idx = body.find("PR-E — API truthcheck loop")
    assert pr_e_idx > 0, "PR-E section marker missing"
    assert contract_runtime_idx < pr_e_idx, (
        "verify-contract-runtime invocation must precede PR-E truthcheck "
        "(static check before runtime probe)"
    )


def test_close_treats_contract_runtime_as_block_unless_override():
    """The new invocation must BLOCK on non-zero exit (matches business-rule
    + interface-standards + route-schema-coverage pattern), unless explicit
    --skip-contract-runtime override flag is present with --override-reason."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    # Look for the block-exit pattern around the verify-contract-runtime invocation
    m = re.search(
        r"verify-contract-runtime\.py.*?exit 1",
        body, re.DOTALL,
    )
    assert m, "contract-runtime gate must include `exit 1` block-fail path"
    assert "--skip-contract-runtime" in body, (
        "Skip flag must exist for emergency operator override (debt-emitting)"
    )


def test_build_md_lists_skip_contract_runtime_as_forbidden_without_override():
    """v3.7.1: --skip-contract-runtime is operator-controllable but
    must require --override-reason (joins --skip-truthcheck convention)."""
    body = BUILD_MD.read_text(encoding="utf-8")
    assert "--skip-contract-runtime" in body, (
        "build.md must list --skip-contract-runtime in skill argument surface"
    )
    # Ensure it lives in forbidden_without_override block alongside --skip-truthcheck
    m = re.search(
        r"forbidden_without_override:.*?(?=\n\w+:|\n---|\Z)",
        body, re.DOTALL,
    )
    assert m, "build.md must have forbidden_without_override block"
    block = m.group(0)
    assert "--skip-contract-runtime" in block, (
        "--skip-contract-runtime must require override-reason"
    )


def test_mirrors_byte_identical():
    """Both close.md and registry.yaml + build.md must mirror to .claude/."""
    assert CLOSE_MD.read_bytes() == CLOSE_MIRROR.read_bytes(), \
        "commands/vg/_shared/build/close.md diverged from .claude/ mirror"
    assert REGISTRY.read_bytes() == REGISTRY_MIRROR.read_bytes(), \
        "scripts/validators/registry.yaml diverged from .claude/ mirror"
    assert BUILD_MD.read_bytes() == BUILD_MIRROR.read_bytes(), \
        "commands/vg/build.md diverged from .claude/ mirror"
