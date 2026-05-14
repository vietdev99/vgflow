"""tests/test_batch28_filter_validator_wired.py — F14 bash invoke gate.

User dogfood PrintwayV3: "filter gần như không được tạo, không được test".
Audit: verify-filter-test-coverage.py exists with D-16 matrix logic but
never bash-invoked. Only mentioned in delegation.md:216 + agents SKILL
prose ("Validate with..."). Rigor pack unenforced.

This test suite asserts that codegen/overview.md actually shells out to
the validator with rc capture + fail-on-shortfall, not just prose
suggestion.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODEGEN_OVERVIEW = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"
CODEGEN_OVERVIEW_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"


def test_overview_invokes_filter_coverage_validator():
    """codegen/overview.md must bash-invoke verify-filter-test-coverage.py
    (not just mention in prose). Bash may split path + --phase across
    line-continuations, so check both tokens + rc capture marker."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8")
    assert "verify-filter-test-coverage.py" in body, (
        "F14 Batch 28: codegen/overview.md must reference the validator"
    )
    # Must have --phase arg passed AND rc capture (proves actual bash invoke,
    # not just prose mention).
    assert "--phase " in body or '--phase "' in body, (
        "F14 Batch 28: validator must be invoked with --phase arg"
    )
    assert "FILTER_RC=$?" in body, (
        "F14 Batch 28: must capture validator rc into FILTER_RC=$? "
        "(currently only prose 'Validate with...')"
    )
    assert "FILTER_COVERAGE_STATUS" in body, (
        "F14 Batch 28: must set FILTER_COVERAGE_STATUS based on rc"
    )


def test_filter_validator_exit_on_fail_or_block_emit():
    """Validator non-zero rc must either exit-on-fail OR emit
    test.filter_coverage_failed event so step-status-ledger records FAIL."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8")
    assert (
        "test.filter_coverage_failed" in body
        or 'FILTER_COVERAGE_STATUS="FAIL"' in body
        or "FILTER_COVERAGE_STATUS=FAIL" in body
    ), (
        "F14: filter validator FAIL must emit event or set status FAIL "
        "(currently silent — rigor pack shortfall passes through)"
    )


def test_filter_validator_legacy_escape_hatch():
    """Allow --allow-filter-shortfall for legacy phases without
    interactive_controls frontmatter. Without escape hatch, batch breaks
    every existing phase."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8")
    assert "--allow-filter-shortfall" in body, (
        "F14: must support --allow-filter-shortfall arg so legacy phases "
        "(pre-Batch 28) can still complete /vg:test without the rigor pack"
    )


def test_mirror_in_sync():
    """Mirror at .claude/commands/... must byte-identical for same field."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8")
    mirror = CODEGEN_OVERVIEW_MIRROR.read_text(encoding="utf-8")
    assert body == mirror, (
        "Mirror drift: .claude/commands/vg/_shared/test/codegen/overview.md "
        "differs from commands/... — re-run mirror cp"
    )
    # Both must have the validator invoke + rc capture
    assert "verify-filter-test-coverage.py" in mirror
    assert "FILTER_RC=$?" in mirror
