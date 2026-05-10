"""v2.67.0 #160 — GOAL-COVERAGE-MATRIX BLOCKED 5-reason taxonomy.

Tests:
1. BlockedReason enum exposes all 5 reasons (APP_BLOCKED, WORKFLOW_BLOCKED,
   PREREQ_MISSING, EXTERNAL_REQUIRED, PROBE_INVALID).
2. classify_blocked() distinguishes APP_BLOCKED from WORKFLOW_BLOCKED.
3. commands/vg/review.md auto-fix routing references the BLOCKED reason taxonomy.
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
