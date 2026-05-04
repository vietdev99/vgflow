"""
OHOK Batch 3 B4 — accept.md UAT quorum gate.

Before Batch 3: accept.md step 5 was pure theatre — AskUserQuestion offered
[s] Skip on every critical item, user could skip decisions + goals + designs
+ ripples, phase ships with "DEFERRED" verdict, next phase proceeded. No
mechanism prevented minimum due diligence bypass.

Batch 3 adds:
- Response persistence requirement: AI must write .uat-responses.json
- Step 5_uat_quorum_gate: count critical skips, BLOCK if > threshold
- Config: accept.max_uat_skips_critical (default 0)
- Override flags: --allow-uat-skips, --allow-empty-uat (log to debt)
- Telemetry: accept.uat_quorum_blocked / accept.uat_quorum_passed events
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))

import contracts  # type: ignore  # noqa: E402


ACCEPT_MD = (Path(__file__).resolve().parents[2]
             / "commands" / "vg" / "accept.md")


@pytest.fixture(scope="module")
def accept_text() -> str:
    assert ACCEPT_MD.exists(), f"accept.md missing at {ACCEPT_MD}"
    return ACCEPT_MD.read_text(encoding="utf-8")


def _extract_step(text: str, name: str) -> str:
    match = re.search(
        rf'<step name="{re.escape(name)}"[^>]*>(.+?)</step>',
        text, re.DOTALL,
    )
    assert match, f'step "{name}" missing from accept.md'
    return match.group(1)


# ═══════════════════════════ B4: quorum gate step exists ═══════════════════════════

def test_quorum_gate_step_exists(accept_text):
    """New step 5_uat_quorum_gate must exist between 5_interactive_uat and 6_write_uat_md."""
    assert '<step name="5_uat_quorum_gate">' in accept_text, (
        "5_uat_quorum_gate step missing"
    )


def test_quorum_gate_between_uat_and_write(accept_text):
    """Order matters: quorum gate must come AFTER 5_interactive_uat, BEFORE 6_write_uat_md."""
    idx_uat = accept_text.find('<step name="5_interactive_uat">')
    idx_quorum = accept_text.find('<step name="5_uat_quorum_gate">')
    idx_write = accept_text.find('<step name="6_write_uat_md">')
    assert 0 < idx_uat < idx_quorum < idx_write, (
        f"step order wrong: uat={idx_uat}, quorum={idx_quorum}, write={idx_write}"
    )


def test_quorum_gate_reads_response_json(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert ".uat-responses.json" in block, (
        "quorum gate doesn't reference .uat-responses.json"
    )


def test_quorum_gate_blocks_missing_response_file(accept_text):
    """If AI doesn't persist responses, gate BLOCKs (prevents theatre)."""
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    # Must check file exists / non-empty
    assert re.search(r'\[\s*!\s*-s\s+"\$RESP_JSON"\s*\]', block), (
        "quorum gate doesn't check empty response JSON"
    )
    # Must have --allow-empty-uat escape hatch
    assert "--allow-empty-uat" in block


def test_quorum_gate_counts_critical_skips(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "CRITICAL_SKIPS" in block
    # Should read decisions.skip + goals.skip (READY goals)
    assert "decisions" in block.lower()
    assert "READY" in block, (
        "quorum gate doesn't filter goal skips by status_before=READY"
    )


def test_quorum_gate_config_driven_threshold(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "MAX_CRIT_SKIPS" in block
    assert "max_uat_skips_critical" in block, (
        "quorum gate must read config.accept.max_uat_skips_critical"
    )


def test_quorum_gate_blocks_on_threshold_breach(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "--allow-uat-skips" in block, (
        "quorum gate missing --allow-uat-skips escape hatch"
    )
    # Block path: exit 1 when over threshold + flag absent
    assert re.search(
        r'CRITICAL_SKIPS.*-gt.*MAX_CRIT_SKIPS',
        block, re.DOTALL,
    ), "quorum gate missing threshold comparison"
    assert "exit 1" in block


def test_quorum_gate_forces_DEFER_on_override(accept_text):
    """When user overrides with --allow-uat-skips, verdict forced to DEFER
    (not ACCEPT) so /vg:next still blocks."""
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert re.search(r'forced_by.*uat_quorum_override', block, re.DOTALL), (
        "quorum override must force verdict=DEFER with forced_by field"
    )


def test_quorum_gate_emits_block_event(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "accept.uat_quorum_blocked" in block, (
        "missing accept.uat_quorum_blocked telemetry event"
    )


def test_quorum_gate_emits_pass_event(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "accept.uat_quorum_passed" in block, (
        "missing accept.uat_quorum_passed telemetry event"
    )


def test_quorum_gate_writes_marker(accept_text):
    block = _extract_step(accept_text, "5_uat_quorum_gate")
    assert "5_uat_quorum_gate.done" in block


# ═══════════════════════════ Contract expand ═══════════════════════════

def test_accept_contract_requires_response_json(accept_text):
    """Contract must_write includes .uat-responses.json so missing = BLOCK."""
    contract = contracts.parse("vg:accept")
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    paths = [item["path"] for item in must_write]
    assert any(".uat-responses.json" in p for p in paths), (
        f"must_write missing .uat-responses.json: {paths}"
    )


def test_accept_contract_lists_quorum_gate_marker(accept_text):
    contract = contracts.parse("vg:accept")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    names = {m["name"] for m in markers}
    assert "5_uat_quorum_gate" in names, (
        f"contract missing 5_uat_quorum_gate marker: {sorted(names)}"
    )


def test_accept_contract_expanded_to_all_critical_steps(accept_text):
    """Previously only 3 hard markers — now all 9 critical steps declared."""
    contract = contracts.parse("vg:accept")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    names = {m["name"] for m in markers}

    critical_expected = {
        "0_gate_integrity_precheck",
        "1_artifact_precheck", "2_marker_precheck",
        "3_sandbox_verdict_gate", "3b_unreachable_triage_gate",
        "3c_override_resolution_gate",
        "5_interactive_uat", "5_uat_quorum_gate", "6_write_uat_md",
        "7_post_accept_actions",
    }
    missing = critical_expected - names
    assert not missing, f"contract missing critical markers: {missing}"


def test_accept_contract_quorum_gate_is_block_severity(accept_text):
    """UAT quorum gate MUST be severity=block (no waiver) so theatre can't bypass."""
    contract = contracts.parse("vg:accept")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    quorum = next((m for m in markers if m["name"] == "5_uat_quorum_gate"), None)
    assert quorum is not None
    assert quorum["severity"] == "block", (
        f"5_uat_quorum_gate severity={quorum['severity']}, must be 'block' "
        f"(otherwise theatre can skip via severity=warn path)"
    )


def test_accept_contract_new_override_flags_declared(accept_text):
    contract = contracts.parse("vg:accept")
    forbidden = contract.get("forbidden_without_override") or []
    for flag in ["--allow-uat-skips", "--allow-empty-uat"]:
        assert flag in forbidden, f"override flag {flag} missing from forbidden list"


# ═══════════════════════════ Step 5 persistence instruction ═══════════════════════════

def test_step5_instructs_ai_to_persist_responses(accept_text):
    """Step 5_interactive_uat must instruct AI to write .uat-responses.json."""
    block = _extract_step(accept_text, "5_interactive_uat")
    # Must reference response JSON so AI knows what to write
    assert ".uat-responses.json" in block, (
        "step 5_interactive_uat doesn't mention .uat-responses.json"
    )
    # Must make it MANDATORY not optional
    assert re.search(r'(MUST|REQUIRED)', block), (
        "step 5 persistence instruction too weak (no MUST/REQUIRED keyword)"
    )
