"""B91 v4.67.0 — issue #197 F-CAI-01 + F-CAI-03 + F-CAI-04 + F-CAI-10.

Generator correctness bundle. Closes 4 of remaining 8 architectural gaps
from issue #197. Continues from B90 (F-CAI-05 + F-CAI-08 shipped).

  F-CAI-01 (critical): RCRURDR semantic anchoring.
    Drop unconstrained verb-fallback in `_bind_endpoint`. Replace with
    entity-slug anchored filter. Goals whose entity slugs don't overlap
    any candidate path return None (with `_b91_endpoint_unmatched_count`
    tag). New `_extract_entity_slugs(goal)` helper derives slugs from
    primary_endpoints paths + title fallback.

  F-CAI-04 (major): endpoint declarations fresh.
    Tolerant path normalization. New `_normalize_contract_path()` resolves
    bare /admin/X ↔ /api/v1/admin/X mismatches. goal.primary_endpoints
    paths missing the /api/v1 prefix now match contracts that include it.

  F-CAI-10 (minor): endpoint=null pass-through.
    When `contracts` list empty (API-CONTRACTS.md unparseable), fall back
    to goal.primary_endpoints[stage_verb_match] instead of returning None
    for every step. Preserves declared endpoints across the binding gap.

  F-CAI-03 (major): empty source assertions audit.
    New `_audit_source_assertions(goals)` scans mutation goals for empty
    mutation_evidence + persistence_check. Summary surfaces counts +
    goal IDs. main() emits stderr warning. Read-only goals excluded.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# F-CAI-01: entity-anchored binding (no cross-resource pollution)
# ---------------------------------------------------------------------------

def test_b91_fcai01_drops_unrelated_resource_pollution(lc) -> None:
    """G-001 topup review — must NOT bind to payment-gateway / bank-account."""
    goal = {
        "id": "G-001",
        "title": "List + filter pending topups for admin review",
        "primary_endpoints": [
            {"method": "GET", "path": "/api/v1/admin/topups"},
        ],
        "mutation_evidence": "",
        "persistence_check": "",
        "dependencies": "",
    }
    # Contracts contain unrelated mutations — pre-B91 fallback would bind
    contracts = [
        {"method": "PATCH", "path": "/api/v1/admin/payment-gateways/{id}"},
        {"method": "DELETE", "path": "/api/v1/admin/legal-entities/{id}/bank-accounts/{bankId}"},
        {"method": "POST", "path": "/api/v1/admin/topups/{id}/approve"},
        {"method": "GET", "path": "/api/v1/admin/topups"},
    ]
    # update stage on a topup review goal — must NOT bind /payment-gateways
    result = lc._bind_endpoint("update", goal, contracts)
    if result is not None:
        assert "topup" in result["path"], (
            f"update stage bound to unrelated resource: {result}"
        )
    # delete stage same: must NOT bind /bank-accounts
    result = lc._bind_endpoint("delete", goal, contracts)
    if result is not None:
        assert "topup" in result["path"], (
            f"delete stage bound to unrelated resource: {result}"
        )


def test_b91_fcai01_entity_slug_extractor(lc) -> None:
    goal = {
        "title": "Approve topup",
        "primary_endpoints": [
            {"method": "POST", "path": "/api/v1/admin/topups/{id}/approve"},
        ],
    }
    slugs = lc._extract_entity_slugs(goal)
    # Should NOT include api, v1, admin (filtered) or placeholder {id}
    assert "api" not in slugs
    assert "v1" not in slugs
    assert "admin" not in slugs
    assert "{id}" not in slugs
    # Should include `topups` + `approve`
    assert "topups" in slugs


def test_b91_fcai01_title_fallback_when_no_primary_endpoints(lc) -> None:
    goal = {"title": "Display merchant dashboard"}
    slugs = lc._extract_entity_slugs(goal)
    # Common stopwords filtered
    assert "display" not in slugs
    # Domain words kept
    assert "merchant" in slugs or "dashboard" in slugs


# ---------------------------------------------------------------------------
# F-CAI-04: path normalization
# ---------------------------------------------------------------------------

def test_b91_fcai04_bare_admin_path_normalizes(lc) -> None:
    contract_paths = {"/api/v1/admin/credits"}
    result = lc._normalize_contract_path("/admin/credits", contract_paths)
    assert result == "/api/v1/admin/credits"


def test_b91_fcai04_already_canonical_unchanged(lc) -> None:
    contract_paths = {"/api/v1/admin/credits"}
    result = lc._normalize_contract_path("/api/v1/admin/credits", contract_paths)
    assert result == "/api/v1/admin/credits"


def test_b91_fcai04_unmatched_unchanged(lc) -> None:
    contract_paths = {"/api/v1/admin/credits"}
    result = lc._normalize_contract_path("/admin/unknown", contract_paths)
    # No match → return original
    assert result == "/admin/unknown"


def test_b91_fcai04_versioned_to_bare(lc) -> None:
    """Reverse: contract list uses bare /admin during dev."""
    contract_paths = {"/admin/credits"}
    result = lc._normalize_contract_path("/api/v1/admin/credits", contract_paths)
    assert result == "/admin/credits"


def test_b91_fcai04_normalized_path_used_in_binding(lc) -> None:
    """End-to-end: stale primary_endpoints `/admin/X` matches contract `/api/v1/admin/X`."""
    goal = {
        "id": "G-test",
        "title": "Create topup",
        "primary_endpoints": [
            {"method": "POST", "path": "/admin/topups"},  # stale bare prefix
        ],
        "mutation_evidence": "",
        "persistence_check": "",
        "dependencies": "",
    }
    contracts = [
        {"method": "POST", "path": "/api/v1/admin/topups"},  # canonical
    ]
    result = lc._bind_endpoint("create", goal, contracts)
    assert result == {"method": "POST", "path": "/api/v1/admin/topups"}


# ---------------------------------------------------------------------------
# F-CAI-10: endpoint=null pass-through
# ---------------------------------------------------------------------------

def test_b91_fcai10_empty_contracts_uses_goal_primary_endpoints(lc) -> None:
    """When API-CONTRACTS.md unparseable (contracts=[]), preserve declared endpoints."""
    goal = {
        "id": "G-001",
        "title": "Create topup",
        "primary_endpoints": [
            {"method": "POST", "path": "/api/v1/admin/topups"},
        ],
    }
    result = lc._bind_endpoint("create", goal, [])  # empty contracts
    assert result == {"method": "POST", "path": "/api/v1/admin/topups"}
    assert goal.get("_b91_endpoint_contracts_empty_count", 0) == 1


def test_b91_fcai10_empty_contracts_no_primary_returns_none(lc) -> None:
    """When contracts AND primary_endpoints both empty → None (correct)."""
    goal = {"id": "G-x", "title": "x"}
    result = lc._bind_endpoint("create", goal, [])
    assert result is None


# ---------------------------------------------------------------------------
# F-CAI-03: source assertion audit
# ---------------------------------------------------------------------------

def test_b91_fcai03_audit_function_exposed(lc) -> None:
    assert hasattr(lc, "_audit_source_assertions")


def test_b91_fcai03_empty_evidence_flagged(lc) -> None:
    goals = [
        {
            "id": "G-good",
            "title": "Good mutation goal",
            "goal_type": "mutation",
            "mutation_evidence": "POST /api/v1/admin/topups returns 201",
            "persistence_check": "GET returns inserted row",
        },
        {
            "id": "G-bad",
            "title": "Bad mutation goal",
            "goal_type": "mutation",
            "mutation_evidence": "",
            "persistence_check": "",
        },
        {
            "id": "G-readonly",
            "title": "Read-only goal",
            "goal_type": "read-only",
            "mutation_evidence": "",
            "persistence_check": "",
        },
    ]
    audit = lc._audit_source_assertions(goals)
    assert audit["empty_mutation_evidence_count"] == 1
    assert audit["empty_persistence_check_count"] == 1
    assert "G-bad" in audit["empty_mutation_evidence_goals"]
    assert "G-bad" in audit["empty_persistence_check_goals"]
    # Read-only excluded
    assert "G-readonly" not in audit["empty_mutation_evidence_goals"]


def test_b91_fcai03_summary_includes_audit(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: Bad goal\n\ngoal_type: mutation\n\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir)
    sa = payload["summary"]["source_assertion_audit"]
    assert sa["empty_mutation_evidence_count"] == 1


# ---------------------------------------------------------------------------
# End-to-end summary includes new diagnostic fields
# ---------------------------------------------------------------------------

def test_b91_summary_endpoint_binding_audit_fields(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: Create topup\n\n"
        "goal_type: mutation\n"
        "mutation_evidence: POST /api/v1/admin/topups\n"
        "persistence_check: GET returns row\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir)
    eba = payload["summary"]["endpoint_binding_audit"]
    assert "slug_fallback_total" in eba
    assert "unmatched_total" in eba
    assert "contracts_empty_fallback_total" in eba


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b91_lifecycle_mirror_byte_identical() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b
