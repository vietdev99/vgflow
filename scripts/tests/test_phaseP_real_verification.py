"""
OHOK Batch 2 B5 + C4 — review.md phaseP_delta + phaseP_regression real verification
+ contract expand to require the API precheck gate before discovery.

Before Batch 2:
- phaseP_delta wrote "Verdict: PASS" stub without re-checking parent failed goals
- phaseP_regression wrote "PASS (regression handled at /vg:test)" without verifying
  bug_ref, code changes, or test coverage
- Contract listed only 3 markers — 19 other steps could silent-skip

These tests lock the structural + behavioral contract so future refactor can't
regress back to performative stubs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))

import contracts  # type: ignore  # noqa: E402


REVIEW_MD = (Path(__file__).resolve().parents[2]
             / "commands" / "vg" / "review.md")


@pytest.fixture(scope="module")
def review_text() -> str:
    assert REVIEW_MD.exists(), f"review.md missing at {REVIEW_MD}"
    return REVIEW_MD.read_text(encoding="utf-8")


def _extract_step(text: str, name: str) -> str:
    match = re.search(
        rf'<step name="{re.escape(name)}"[^>]*>(.+?)</step>',
        text, re.DOTALL,
    )
    assert match, f'step "{name}" missing from review.md'
    return match.group(1)


# ═══════════════════════════ B5: phaseP_delta real verification ═══════════════

def test_phaseP_delta_requires_parent_phase_ref(review_text):
    block = _extract_step(review_text, "phaseP_delta")
    assert "PARENT_REF" in block
    # No parent phase in SPECS → exit 1 (hotfix must cite parent)
    assert re.search(r'\[\s*-z\s*"\$PARENT_REF"\s*\]', block), (
        "phaseP_delta: missing empty PARENT_REF guard"
    )
    assert re.search(r'exit 1', block), "phaseP_delta: no exit path"


def test_phaseP_delta_blocks_empty_hotfix(review_text):
    """Hotfix with 0 code files changed must BLOCK unless override flag."""
    block = _extract_step(review_text, "phaseP_delta")
    assert 'DELTA_COUNT' in block, "phaseP_delta: missing DELTA_COUNT accumulator"
    assert '--allow-empty-hotfix' in block, (
        "phaseP_delta: missing --allow-empty-hotfix escape hatch"
    )
    # Must have the empty-hotfix branch that exits 1 when flag absent
    assert re.search(
        r'DELTA_COUNT.*-eq 0.*allow-empty-hotfix',
        block, re.DOTALL,
    ), "phaseP_delta: missing empty-hotfix gate logic"


def test_phaseP_delta_checks_overlap_with_parent_files(review_text):
    """Real verification: hotfix must touch files parent worked on,
    else BLOCK as orthogonal."""
    block = _extract_step(review_text, "phaseP_delta")
    assert '.delta-coverage.json' in block
    assert 'overlap' in block.lower()
    assert '--allow-orthogonal-hotfix' in block, (
        "phaseP_delta: missing --allow-orthogonal-hotfix escape hatch"
    )


def test_phaseP_delta_writes_real_verdict_not_stub(review_text):
    """Verdict must reflect actual checks, not hardcoded PASS."""
    block = _extract_step(review_text, "phaseP_delta")
    # Must NOT have the old performative verdict
    assert "PASS (delta review — regression verification deferred to /vg:test)" not in block, (
        "phaseP_delta: regressed to old stub verdict"
    )
    # Must have conditional verdict based on overlap
    assert "orthogonal" in block.lower()
    assert "parent files" in block.lower()


def test_phaseP_delta_emits_verification_event(review_text):
    block = _extract_step(review_text, "phaseP_delta")
    assert 'review.phaseP_delta_verified' in block


# ═══════════════════════════ B5: phaseP_regression real verification ═══════════

def test_phaseP_regression_requires_bug_reference(review_text):
    block = _extract_step(review_text, "phaseP_regression")
    assert 'BUG_REF' in block
    # Empty BUG_REF → exit 1 unless override
    assert '--allow-no-bugref' in block, (
        "phaseP_regression: missing --allow-no-bugref escape hatch"
    )
    assert re.search(r'\[\s*-z\s*"\$BUG_REF"\s*\]', block), (
        "phaseP_regression: missing empty BUG_REF guard"
    )


def test_phaseP_regression_blocks_empty_bugfix(review_text):
    """Bugfix with 0 code files must BLOCK (else it's not a fix)."""
    block = _extract_step(review_text, "phaseP_regression")
    assert 'CODE_COUNT' in block
    assert '--allow-empty-bugfix' in block, (
        "phaseP_regression: missing --allow-empty-bugfix escape hatch"
    )
    assert re.search(
        r'CODE_COUNT.*-eq 0.*allow-empty-bugfix',
        block, re.DOTALL,
    ), "phaseP_regression: missing empty-bugfix gate logic"


def test_phaseP_regression_scans_for_test_coverage(review_text):
    block = _extract_step(review_text, "phaseP_regression")
    assert 'TEST_COUNT' in block
    assert 'TEST_MENTIONS_BUG' in block, (
        "phaseP_regression: missing test-bug-linkage detection"
    )
    # Should grep test files for bug ID
    assert re.search(r'grep.*BUG_ID_SAFE', block), (
        "phaseP_regression: not scanning test files for bug ID"
    )


def test_phaseP_regression_writes_real_verdict_not_stub(review_text):
    block = _extract_step(review_text, "phaseP_regression")
    # The old stub wrote `"**Verdict:** PASS (regression handled at /vg:test)"`
    # inside the Python write. Check there's no variable-free hardcoded verdict:
    # the verdict must be computed from code/test counts.
    # Strip documentation prose (before first ```bash) so we check only executable.
    bash_start = block.find("```bash")
    exec_block = block[bash_start:] if bash_start >= 0 else block
    # In executable portion, must have conditional verdict based on counts
    assert "code_count == 0" in exec_block, (
        "phaseP_regression: missing code_count conditional in verdict logic"
    )
    # Verdict must differ based on actual checks
    assert "BLOCK" in exec_block and "PASS-WARN" in exec_block


def test_phaseP_regression_emits_verification_event(review_text):
    block = _extract_step(review_text, "phaseP_regression")
    assert 'review.phaseP_regression_verified' in block


# ═══════════════════════════ C4: contract expand ═══════════════════════════

def test_review_contract_has_api_precheck_step(review_text):
    contract = contracts.parse("vg:review")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    names = {m["name"] for m in markers}

    expected = {
        # Hard gates
        "00_gate_integrity_precheck", "0_parse_and_validate",
        "0b_goal_coverage_gate", "complete",
        # Session / planning
        "00_session_lifecycle", "create_task_tracker", "phase_profile_branch",
        # phaseP_*
        "phaseP_infra_smoke", "phaseP_delta", "phaseP_regression",
        "phaseP_schema_verify", "phaseP_link_check",
        # Full-profile pipeline
        "phase1_code_scan", "phase1_5_ripple_and_god_node",
        "phase2a_api_contract_probe",
        "phase2_browser_discovery", "phase2_exploration_limits",
        "phase2_mobile_discovery", "phase2_5_visual_checks",
        "phase2_5_mobile_visual_checks", "phase3_fix_loop",
        "phase4_goal_comparison",
        # Post-discovery
        "unreachable_triage", "crossai_review", "write_artifacts",
        "bootstrap_reflection",
    }
    missing = expected - names
    assert not missing, (
        f"review contract missing {len(missing)} markers: {sorted(missing)}"
    )


def test_review_api_precheck_requires_fresh_artifact_and_telemetry(review_text):
    assert '${PHASE_DIR}/api-contract-precheck.txt' in review_text
    artifact_idx = review_text.index('${PHASE_DIR}/api-contract-precheck.txt')
    artifact_block = review_text[artifact_idx:artifact_idx + 260]
    assert 'must_be_created_in_run: true' in artifact_block
    assert 'check_provenance: true' in artifact_block
    assert 'required_unless_flag: "--skip-discovery"' in artifact_block

    assert 'event_type: "review.api_precheck_completed"' in review_text
    event_idx = review_text.index('event_type: "review.api_precheck_completed"')
    event_block = review_text[event_idx:event_idx + 220]
    assert 'required_unless_flag: "--skip-discovery"' in event_block


def test_review_hard_gates_are_block_severity(review_text):
    """Foundational steps must remain severity=block — can't relax."""
    contract = contracts.parse("vg:review")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    by_name = {m["name"]: m for m in markers}

    hard_gates = ["00_gate_integrity_precheck", "0_parse_and_validate",
                  "0b_goal_coverage_gate", "complete"]
    for g in hard_gates:
        m = by_name.get(g)
        assert m is not None, f"hard gate {g} missing"
        assert m["severity"] == "block", (
            f"hard gate {g} has severity={m['severity']}, must be 'block'"
        )


def test_review_crossai_waivable_by_skip_flag(review_text):
    """crossai_review marker must be waived when --skip-crossai in args."""
    contract = contracts.parse("vg:review")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    crossai = next((m for m in markers if m["name"] == "crossai_review"), None)
    assert crossai is not None
    assert crossai["required_unless_flag"] == "--skip-crossai"


def test_review_crossai_requires_artifact_and_telemetry(review_text):
    """Review CrossAI needs hard evidence, not just a marker touch."""
    assert '${PHASE_DIR}/crossai/review-check.xml' in review_text
    artifact_idx = review_text.index('${PHASE_DIR}/crossai/review-check.xml')
    artifact_block = review_text[artifact_idx:artifact_idx + 180]
    assert 'required_unless_flag: "--skip-crossai"' in artifact_block

    assert 'event_type: "crossai.verdict"' in review_text
    event_idx = review_text.index('event_type: "crossai.verdict"')
    event_block = review_text[event_idx:event_idx + 180]
    assert 'required_unless_flag: "--skip-crossai"' in event_block


def test_review_skip_crossai_requires_override(review_text):
    """Skipping objective review must leave override debt."""
    assert re.search(
        r"forbidden_without_override:.*-\s+\"--skip-crossai\"",
        review_text,
        re.DOTALL,
    )


def test_review_profile_specific_phases_are_warn(review_text):
    """Optional / profile-exclusive phases must be severity=warn to avoid
    blocking when REVIEW_MODE routes around them."""
    contract = contracts.parse("vg:review")
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    by_name = {m["name"]: m for m in markers}

    warn_expected = [
        "phaseP_infra_smoke", "phaseP_delta", "phaseP_regression",
        "phaseP_schema_verify", "phaseP_link_check",
        "phase2_mobile_discovery", "phase2_5_mobile_visual_checks",
    ]
    for s in warn_expected:
        m = by_name.get(s)
        assert m is not None, f"{s} missing from contract"
        assert m["severity"] == "warn", (
            f"{s} has severity={m['severity']}, must be 'warn' "
            f"(profile-exclusive / optional)"
        )


def test_review_new_override_flags_declared(review_text):
    """B5 introduced 4 new override flags — must be declared in
    forbidden_without_override so their use gets logged to debt."""
    contract = contracts.parse("vg:review")
    forbidden = contract.get("forbidden_without_override") or []
    for flag in ["--allow-empty-hotfix", "--allow-orthogonal-hotfix",
                 "--allow-no-bugref", "--allow-empty-bugfix"]:
        assert flag in forbidden, f"override flag {flag} missing from contract"
