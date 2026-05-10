"""v3.5.0 — #173 Stage 5: auto-routing TEST_SPEC_MISSING to /vg:test codegen.

Coverage:
1. review close.md prints exact /vg:test command when TEST_SPEC_MISSING goals exist
2. close.md emits review.test_spec_missing_routed telemetry
3. vg-test-codegen delegation references UI-RUNTIME-CONTRACT.json
4. delegation declares test_spec_missing_filter section
5. canonical/mirror byte-identity for close.md + delegation.md
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLOSE_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "close.md"
CLOSE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "close.md"
DELEGATION_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
DELEGATION_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


def test_close_md_surfaces_test_spec_missing():
    body = CLOSE_CANON.read_text(encoding="utf-8")
    assert "TEST_SPEC_MISSING" in body, (
        "close.md must reference TEST_SPEC_MISSING for v3.5.0 auto-routing"
    )
    assert "--codegen-from-goals" in body, (
        "close.md must print /vg:test --codegen-from-goals flag"
    )
    assert "--filter=test-spec-missing" in body, (
        "close.md must print --filter=test-spec-missing arg"
    )


def test_close_md_emits_routed_telemetry():
    body = CLOSE_CANON.read_text(encoding="utf-8")
    assert "review.test_spec_missing_routed" in body, (
        "close.md must emit review.test_spec_missing_routed telemetry event"
    )


def test_close_md_lists_codegen_inputs():
    body = CLOSE_CANON.read_text(encoding="utf-8")
    # The hint block should mention the canonical inputs the codegen consumes
    for ref in ["TEST-GOALS.md", "CRUD-SURFACES.md", "UI-RUNTIME-CONTRACT.json", "RUNTIME-MAP.json"]:
        assert ref in body, f"close.md must list {ref} as codegen input in hint"


def test_close_md_mirror_byte_identity():
    assert CLOSE_CANON.read_bytes() == CLOSE_MIRROR.read_bytes()


def test_delegation_references_ui_runtime_contract():
    body = DELEGATION_CANON.read_text(encoding="utf-8")
    assert "UI-RUNTIME-CONTRACT.json" in body, (
        "test codegen delegation.md must list UI-RUNTIME-CONTRACT.json as input"
    )
    assert "route_inventory" in body, (
        "delegation must instruct subagent to cover route_inventory"
    )
    assert "first_viewport_surfaces" in body, (
        "delegation must instruct subagent to assert first-viewport surfaces"
    )
    assert "min_spec_count" in body, (
        "delegation must reference min_spec_count target"
    )


def test_delegation_declares_test_spec_missing_filter():
    body = DELEGATION_CANON.read_text(encoding="utf-8")
    assert "test_spec_missing_filter" in body, (
        "delegation must declare the --filter=test-spec-missing semantics"
    )
    assert "--filter=test-spec-missing" in body


def test_delegation_mirror_byte_identity():
    assert DELEGATION_CANON.read_bytes() == DELEGATION_MIRROR.read_bytes()
