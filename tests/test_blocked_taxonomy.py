"""v2.67.0 #160 + v3.1.0 #173 — GOAL-COVERAGE-MATRIX BLOCKED 7-reason taxonomy.

Tests:
1. BlockedReason enum exposes all 7 reasons (APP_BLOCKED, WORKFLOW_BLOCKED,
   PREREQ_MISSING, EXTERNAL_REQUIRED, PROBE_INVALID, TEST_SPEC_MISSING,
   ENV_MISMATCH).
2. classify_blocked() distinguishes APP_BLOCKED from WORKFLOW_BLOCKED, plus
   TEST_SPEC_MISSING and ENV_MISMATCH (#173 additions).
3. commands/vg/review.md auto-fix routing references the BLOCKED reason taxonomy.
4. verify-matrix-evidence-link.py STATUSES_WITHOUT_RUNTIME includes the v3.1.0
   additions (TEST_SPEC_MISSING + ENV_MISMATCH) so a matrix row using one of
   them does not trigger matrix_status_without_runtime_sequence.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "challenge_coverage",
        REPO_ROOT / "scripts" / "challenge-coverage.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_blocked_reason_enum_defined():
    mod = _load()
    assert hasattr(mod, "BlockedReason"), "BlockedReason enum must be exported"
    expected = {
        "APP_BLOCKED",
        "WORKFLOW_BLOCKED",
        "PREREQ_MISSING",
        "EXTERNAL_REQUIRED",
        "PROBE_INVALID",
        "TEST_SPEC_MISSING",  # v3.1.0 #173
        "ENV_MISMATCH",       # v3.1.0 #173
    }
    actual = {e.name for e in mod.BlockedReason}
    missing = expected - actual
    assert not missing, f"Missing BLOCKED reasons: {missing}"


def test_classifier_distinguishes_app_vs_workflow():
    mod = _load()
    assert hasattr(mod, "classify_blocked"), "classify_blocked() must exist"

    # APP_BLOCKED: code shipped, runtime returns wrong response
    res = mod.classify_blocked(
        {"runtime_response_present": True, "matches_contract": False}
    )
    assert "APP_BLOCKED" in str(res), f"expected APP_BLOCKED, got {res}"

    # PROBE_INVALID: probe ran wrong (e.g., WS as GET)
    res = mod.classify_blocked(
        {"probe_error": "probe ran WS as GET", "runtime_response_present": False}
    )
    assert "PROBE_INVALID" in str(res), f"expected PROBE_INVALID, got {res}"

    # PREREQ_MISSING: upstream patch deferred
    res = mod.classify_blocked({"upstream_deferred": True})
    assert "PREREQ_MISSING" in str(res), f"expected PREREQ_MISSING, got {res}"

    # EXTERNAL_REQUIRED: needs OAuth/WS/reset
    res = mod.classify_blocked({"requires_external": True})
    assert "EXTERNAL_REQUIRED" in str(res), f"expected EXTERNAL_REQUIRED, got {res}"


def test_classifier_handles_test_spec_missing():
    """v3.1.0 #173 — TEST_SPEC_MISSING when no Playwright/lifecycle spec covers goal."""
    mod = _load()
    res = mod.classify_blocked({"missing_spec": True})
    assert "TEST_SPEC_MISSING" in str(res), f"expected TEST_SPEC_MISSING, got {res}"

    # missing_spec dominates other signals (otherwise route to /vg:test codegen)
    res = mod.classify_blocked(
        {"missing_spec": True, "runtime_response_present": True, "matches_contract": False}
    )
    assert "TEST_SPEC_MISSING" in str(res), (
        f"missing_spec must dominate APP_BLOCKED heuristic, got {res}"
    )


def test_classifier_handles_env_mismatch():
    """v3.1.0 #173 — ENV_MISMATCH for cookie/auth/host env-contract failures."""
    mod = _load()
    res = mod.classify_blocked({"env_mismatch": True})
    assert "ENV_MISMATCH" in str(res), f"expected ENV_MISMATCH, got {res}"

    # env_mismatch dominates everything (don't classify as APP_BLOCKED — it's not a code bug)
    res = mod.classify_blocked(
        {"env_mismatch": True, "missing_spec": True, "upstream_deferred": True}
    )
    assert "ENV_MISMATCH" in str(res), (
        f"env_mismatch must dominate other heuristics, got {res}"
    )


def _review_md_full_text() -> str:
    """Concatenate review.md + all _shared/review/*.md sub-files (v2.70.0 split)."""
    parts = [(REPO_ROOT / "commands" / "vg" / "review.md").read_text(encoding="utf-8")]
    shared_review = REPO_ROOT / "commands" / "vg" / "_shared" / "review"
    if shared_review.is_dir():
        for p in sorted(shared_review.glob("*.md")):
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_review_md_routes_by_blocked_reason():
    body = _review_md_full_text()
    # Auto-fix routing must reference BLOCKED reason taxonomy keywords
    assert re.search(
        r"APP_BLOCKED|WORKFLOW_BLOCKED|PREREQ_MISSING|EXTERNAL_REQUIRED|PROBE_INVALID",
        body,
    ), "review.md auto-fix routing must use BLOCKED reason taxonomy"


def test_review_md_routes_test_spec_missing_and_env_mismatch():
    """v3.1.0 #173 — review.md must surface routing for the two new reasons."""
    body = _review_md_full_text()
    assert "TEST_SPEC_MISSING" in body, (
        "review.md must reference TEST_SPEC_MISSING (route to /vg:test codegen)"
    )
    assert "ENV_MISMATCH" in body, (
        "review.md must reference ENV_MISMATCH (env-contract repair handling)"
    )


def test_matrix_evidence_link_skips_test_spec_missing_and_env_mismatch():
    """v3.1.0 #173 — STATUSES_WITHOUT_RUNTIME must include the new statuses
    so a matrix row with TEST_SPEC_MISSING / ENV_MISMATCH does not trigger
    matrix_status_without_runtime_sequence (no replay expected for either).
    """
    validator_path = REPO_ROOT / "scripts" / "validators" / "verify-matrix-evidence-link.py"
    assert validator_path.is_file(), "verify-matrix-evidence-link.py must exist"
    body = validator_path.read_text(encoding="utf-8")
    # The set literal must contain both new statuses
    assert '"TEST_SPEC_MISSING"' in body, (
        "STATUSES_WITHOUT_RUNTIME must include TEST_SPEC_MISSING"
    )
    assert '"ENV_MISMATCH"' in body, (
        "STATUSES_WITHOUT_RUNTIME must include ENV_MISMATCH"
    )


def test_validator_mirror_byte_identity():
    """v3.1.0 #173 — canonical/mirror byte identity for the matrix-evidence-link
    validator (.claude mirror used by orchestrator at runtime)."""
    canonical = (REPO_ROOT / "scripts" / "validators" / "verify-matrix-evidence-link.py").read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-matrix-evidence-link.py").read_bytes()
    assert canonical == mirror, "matrix-evidence-link canonical and .claude mirror must match"


def test_challenge_coverage_mirror_byte_identity():
    """v3.1.0 #173 — canonical/mirror byte identity for challenge-coverage.py."""
    canonical = (REPO_ROOT / "scripts" / "challenge-coverage.py").read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "challenge-coverage.py").read_bytes()
    assert canonical == mirror, "challenge-coverage canonical and .claude mirror must match"
