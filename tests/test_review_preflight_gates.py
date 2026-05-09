"""v2.67.0 #161 — review.md Phase 0.5 preflight 3 hard gates.

Tests assert that commands/vg/review.md (and its .claude mirror) declare
three additional BLOCK gates in the Phase 0.5 RFC v9 preflight section:

  P1. routes-static.json validity — gate when file missing or empty array.
  P2. ENV-CONTRACT.preflight_checks — gate when ENV-CONTRACT.md present but
      lacks the preflight_checks: section.
  P3. OpenAPI schema validity — gate when openapi-generation.log shows
      FST_ERR_INVALID_SCHEMA or HTTP 500.

These gates run BEFORE the scanner so we fail fast on broken sandbox state
instead of running a full review pass on artifacts that cannot be trusted.

Tests inspect markdown source for the gate language because review.md is a
shell-flavored runbook — the bash blocks execute under /vg:review at runtime,
not under pytest. Source-level assertions are the contract.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / "commands" / "vg" / "review.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "review.md"


@pytest.fixture(scope="module")
def review_md() -> str:
    """Canonical review.md text content."""
    assert CANONICAL.exists(), f"missing {CANONICAL}"
    return CANONICAL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Gate P1 — routes-static.json validity
# ---------------------------------------------------------------------------

def test_preflight_routes_static_gate(review_md: str):
    """A BLOCK gate must exist that checks routes-static.json existence
    AND non-empty .routes array. Without either, the review run cannot
    validate route-level coverage and must abort."""
    # Look for the marker phrase + a guard combining file existence and
    # array length in close proximity.
    assert re.search(r"routes-static\.json", review_md), (
        "review.md must reference routes-static.json"
    )
    # The block gate must be present — search for routes-static.json
    # mentioned alongside a BLOCK / exit guard within the same section.
    pattern = re.compile(
        r"routes-static\.json[\s\S]{0,800}(?:BLOCK|exit\s+1|preflight\s+P1)",
        re.IGNORECASE,
    )
    assert pattern.search(review_md), (
        "routes-static.json BLOCK gate (Preflight P1) missing in review.md"
    )


# ---------------------------------------------------------------------------
# Gate P2 — ENV-CONTRACT.preflight_checks section
# ---------------------------------------------------------------------------

def test_preflight_env_contract_section_gate(review_md: str):
    """A BLOCK gate must verify the preflight_checks: section is present
    in ENV-CONTRACT.md when ENV-CONTRACT.md exists. Existing prior gates
    only confirm the file's presence, not the required section content."""
    # Match "preflight_checks" in close proximity to ENV-CONTRACT and a
    # BLOCK/exit guard.
    pattern = re.compile(
        r"ENV-CONTRACT[\s\S]{0,400}preflight_checks[\s\S]{0,400}(?:BLOCK|exit\s+1|preflight\s+P2)",
        re.IGNORECASE,
    )
    assert pattern.search(review_md), (
        "ENV-CONTRACT.preflight_checks section BLOCK gate (P2) missing"
    )


# ---------------------------------------------------------------------------
# Gate P3 — OpenAPI schema validity (log scan)
# ---------------------------------------------------------------------------

def test_preflight_openapi_validity_gate(review_md: str):
    """A BLOCK gate must scan openapi-generation.log for FST_ERR_INVALID_SCHEMA
    or HTTP 500 and abort the run when found. Mirrors the in-script
    _openapi_schema_valid helper added in #157 — review.md needs the
    equivalent gate at preflight time."""
    pattern = re.compile(
        r"openapi-generation\.log[\s\S]{0,500}(?:FST_ERR_INVALID_SCHEMA|HTTP/[\d.]+\s+500)[\s\S]{0,200}(?:BLOCK|exit\s+1|preflight\s+P3)",
        re.IGNORECASE,
    )
    assert pattern.search(review_md), (
        "OpenAPI schema validity BLOCK gate (P3) missing in review.md "
        "— must scan openapi-generation.log for FST_ERR_INVALID_SCHEMA / 500"
    )


# ---------------------------------------------------------------------------
# Mirror parity — .claude/commands/vg/review.md must match canonical bytes
# ---------------------------------------------------------------------------

def test_canonical_and_mirror_byte_identical():
    """commands/vg/review.md and .claude/commands/vg/review.md must be
    byte-identical so /vg:review behaves the same regardless of which path
    the runtime resolves first."""
    assert CANONICAL.exists(), f"missing canonical {CANONICAL}"
    assert MIRROR.exists(), f"missing mirror {MIRROR}"
    assert CANONICAL.read_bytes() == MIRROR.read_bytes(), (
        "canonical commands/vg/review.md and .claude/commands/vg/review.md "
        "must be byte-identical mirrors — drift detected"
    )
