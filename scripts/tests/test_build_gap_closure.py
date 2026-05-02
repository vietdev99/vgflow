"""
OHOK Batch 4 — build.md gap closure.

Before Batch 4:
- step 5_handle_branching had ZERO bash code, marker touched regardless of
  whether branch checkout succeeded / was attempted
- step 4c/4d/4e subprocess calls (find-siblings.py etc.) swallowed failures —
  executor got empty sibling context silently
- contract listed only 8 of 18 steps — 11 could silent-skip without detection

Batch 4 adds:
- B6: real branching bash with exit 1 on failure
- B7: wave-level exit 1 if ALL find-siblings calls fail
- C3: contract expand to 18 markers (13 block + 5 warn)

Smoke tests (extracted bash + mock env) in test_build_smoke.py. This file
locks structural expectations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))

import contracts  # type: ignore  # noqa: E402


BUILD_MD = (Path(__file__).resolve().parents[2]
            / "commands" / "vg" / "build.md")


@pytest.fixture(scope="module")
def build_text() -> str:
    return BUILD_MD.read_text(encoding="utf-8")


def _extract_step(text: str, name: str) -> str:
    match = re.search(
        rf'<step name="{re.escape(name)}"[^>]*>(.+?)</step>',
        text, re.DOTALL,
    )
    assert match, f'step "{name}" missing'
    return match.group(1)


# ═══════════════════════════ B6: step 5 real bash ═══════════════════════════

def test_step5_has_real_branching_bash(build_text):
    block = _extract_step(build_text, "5_handle_branching")
    # Must have bash code block (not just prose)
    assert "```bash" in block, "step 5 missing bash block"
    # Must reference git checkout
    assert "git checkout" in block
    # Must have BRANCH_STRATEGY read from config
    assert "BRANCH_STRATEGY" in block
    assert "vg_config_get branching_strategy" in block


def test_step5_exits_on_checkout_failure(build_text):
    """Failed git checkout must exit 1, not swallowed."""
    block = _extract_step(build_text, "5_handle_branching")
    # Must have exit 1 paths around git operations
    assert re.search(r'git checkout.*exit 1', block, re.DOTALL), (
        "step 5 missing exit 1 on checkout failure"
    )


def test_step5_handles_uncommitted_changes(build_text):
    """Uncommitted changes before branch switch must BLOCK."""
    block = _extract_step(build_text, "5_handle_branching")
    assert "git diff --quiet" in block, (
        "step 5 missing uncommitted-changes precheck"
    )
    assert "Uncommitted changes" in block


def test_step5_handles_all_strategy_values(build_text):
    """Must cover phase/milestone/none and emit warning for unknown."""
    block = _extract_step(build_text, "5_handle_branching")
    assert re.search(r'case\s+"\$BRANCH_STRATEGY"', block)
    for val in ["phase", "milestone", "none"]:
        assert val in block, f"step 5 missing strategy value: {val}"


def test_step5_idempotent_when_already_on_branch(build_text):
    """If already on target branch, no-op — don't re-checkout."""
    block = _extract_step(build_text, "5_handle_branching")
    assert "Already on" in block or "already on" in block.lower()


def test_step5_writes_marker(build_text):
    block = _extract_step(build_text, "5_handle_branching")
    assert "5_handle_branching.done" in block


# ═══════════════════════════ B7: step 4c subprocess error handling ═══════════

def test_step4c_tracks_failed_siblings(build_text):
    """find-siblings.py failures must be tracked, not swallowed."""
    # Extract only the 4c sub-section (from "### 4c:" to "### 4d:")
    match = re.search(
        r'### 4c:.*?(?=### 4d:)', build_text, re.DOTALL,
    )
    assert match, "4c section missing"
    block = match.group(0)

    assert "SIBLINGS_FAILED" in block, "4c missing failure tracker"
    # Must have fallback stub JSON so downstream doesn't crash
    assert "find-siblings-failed" in block


def test_step4c_blocks_if_all_tasks_fail(build_text):
    """If ALL tasks' find-siblings fail → systemic issue → exit 1."""
    match = re.search(r'### 4c:.*?(?=### 4d:)', build_text, re.DOTALL)
    block = match.group(0)

    # Must compare failure count against WAVE_TASKS count + exit 1
    assert re.search(
        r'SIBLINGS_FAILED.*WAVE_TASKS.*exit 1',
        block, re.DOTALL,
    ), "4c missing systemic-failure BLOCK path"


# ═══════════════════════════ C3: contract expand ═══════════════════════════

def test_build_contract_has_all_18_markers(build_text):
    contract = contracts.parse("vg:build")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    names = {m["name"] for m in markers}

    expected = {
        # Hard gates
        "0_gate_integrity_precheck",
        "1_parse_args", "1a_build_queue_preflight", "1b_recon_gate",
        "3_validate_blueprint",
        "4_load_contracts_and_context",
        "5_handle_branching",
        "7_discover_plans", "8_execute_waves",
        "9_post_execution", "10_postmortem_sanity",
        "11_crossai_build_verify_loop", "12_run_complete",
        # Warn
        "0_session_lifecycle", "create_task_tracker", "2_initialize",
        "6_validate_phase", "8_5_bootstrap_reflection_per_wave",
    }
    missing = expected - names
    assert not missing, f"contract missing markers: {sorted(missing)}"


def test_build_contract_hard_gates_are_block_severity(build_text):
    """Critical path steps must keep severity=block."""
    contract = contracts.parse("vg:build")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    by_name = {m["name"]: m for m in markers}

    hard_gates = [
        "0_gate_integrity_precheck", "1_parse_args",
        "1a_build_queue_preflight", "1b_recon_gate",
        "3_validate_blueprint", "4_load_contracts_and_context",
        "5_handle_branching", "7_discover_plans", "8_execute_waves",
        "9_post_execution", "10_postmortem_sanity",
        "11_crossai_build_verify_loop", "12_run_complete",
    ]
    for g in hard_gates:
        m = by_name.get(g)
        assert m is not None, f"hard gate {g} missing"
        assert m["severity"] == "block", (
            f"hard gate {g} has severity={m['severity']}, must be 'block'"
        )


def test_build_contract_optional_steps_are_warn(build_text):
    """Advisory/cosmetic steps should be warn so they don't block."""
    contract = contracts.parse("vg:build")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    by_name = {m["name"]: m for m in markers}

    warn_expected = [
        "0_session_lifecycle", "create_task_tracker",
        "2_initialize", "6_validate_phase",
        "8_5_bootstrap_reflection_per_wave",
    ]
    for s in warn_expected:
        m = by_name.get(s)
        assert m is not None, f"warn step {s} missing"
        assert m["severity"] == "warn", (
            f"{s} severity={m['severity']}, must be 'warn'"
        )


def test_build_preserved_existing_forbidden_flags(build_text):
    """Batch 4 shouldn't regress prior contract (existing flags intact)."""
    contract = contracts.parse("vg:build")
    forbidden = contract.get("forbidden_without_override") or []
    for flag in ["--override-reason", "--allow-missing-commits",
                 "--allow-r5-violation", "--force"]:
        assert flag in forbidden, f"pre-Batch-4 flag {flag} regressed"


def test_build_contract_summary_still_required(build_text):
    """Must_write SUMMARY.md unchanged — critical artifact."""
    contract = contracts.parse("vg:build")
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    paths = [item["path"] for item in must_write]
    assert any("SUMMARY.md" in p for p in paths), (
        f"SUMMARY.md missing from must_write: {paths}"
    )


def test_build_contract_requires_api_docs(build_text):
    contract = contracts.parse("vg:build")
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    paths = [item["path"] for item in must_write]
    assert any("API-DOCS.md" in p for p in paths), (
        f"API-DOCS.md missing from must_write: {paths}"
    )
    assert any("INTERFACE-STANDARDS.md" in p for p in paths), (
        f"INTERFACE-STANDARDS.md missing from must_write: {paths}"
    )
    assert any("INTERFACE-STANDARDS.json" in p for p in paths), (
        f"INTERFACE-STANDARDS.json missing from must_write: {paths}"
    )


def test_build_does_not_claim_complete_before_crossai(build_text):
    """Step 9 must not tell users the build is complete before CrossAI runs."""
    step9 = _extract_step(build_text, "9_post_execution")
    assert "Code execution complete for Phase" in step9
    assert "build is NOT complete yet" in step9
    assert "Do not claim /vg:build PASS until step 12 run-complete succeeds" in step9
    assert "Build complete for Phase" not in step9


def test_step9_generates_and_verifies_api_docs(build_text):
    step9 = _extract_step(build_text, "9_post_execution")
    assert "generate-api-docs.py" in step9
    assert "verify-api-docs-coverage.py" in step9
    assert "API-DOCS.md" in step9
    assert "--interface-standards" in step9
    assert "INTERFACE-STANDARDS.json" in step9


def test_build_validates_interface_standards(build_text):
    assert "generate-interface-standards.py" in build_text
    assert "verify-interface-standards.py" in build_text
    assert "<interface_standards_context>" in build_text


def test_build_completed_event_emitted_after_crossai_step(build_text):
    """build.completed is the final build signal, not a pre-CrossAI signal."""
    crossai_idx = build_text.index('<step name="11_crossai_build_verify_loop">')
    completed_idx = build_text.index('emit-event "build.completed"')
    assert completed_idx > crossai_idx
    assert '\\"after_crossai\\":true' in build_text


def test_build_pipeline_state_pending_until_run_complete(build_text):
    """Progress must show build in-progress until run-complete passes."""
    step9 = _extract_step(build_text, "9_post_execution")
    step12 = _extract_step(build_text, "12_run_complete")
    assert "build-crossai-pending" in step9
    assert "'status': 'in_progress'" in step9
    assert "build-complete" in step12
    assert "'status': 'done'" in step12
