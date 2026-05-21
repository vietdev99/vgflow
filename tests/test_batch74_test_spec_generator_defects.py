"""tests/test_batch74_test_spec_generator_defects.py — B74 issue #191 fix.

Closes 4/8 defects from issue #191:
  - C-M2: 2FA entrypoint contamination (every goal got top-10 surface routes).
  - C-M5: API contract path validation in _bind_endpoint primary_endpoints path.
  - C-M6: YAML fence pollution in `_field()` regex (Dependencies value bled).
  - C-M1: endpoint=null surface — fallback-binding marked on goal for caller warning.

Deferred to follow-up (require deeper refactor; tracked in #191):
  - C-M3 actor mapping reads canonical role list.
  - C-M4 RCRURDR per-goal coverage.
  - C-M7 mutation_evidence vs success_status cross-validation.
  - C-M8 TEST-GOALS source unification.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIFECYCLE_GEN = REPO / "scripts" / "generate-lifecycle-specs.py"
AI_EXPANDER = REPO / "scripts" / "test_spec_ai_expander.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lifecycle_mod():
    return _load(LIFECYCLE_GEN, "lifecycle_gen")


@pytest.fixture(scope="module")
def expander_mod():
    return _load(AI_EXPANDER, "ai_expander")


# ---------------------------------------------------------------------------
# C-M2: 2FA contamination — _entrypoint_hints filters by goal relevance.
# ---------------------------------------------------------------------------


def test_b74_cm2_finance_goal_excludes_2fa_routes(expander_mod):
    """A finance/topup goal should NOT receive /2fa/* routes from surfaces."""
    spec = {
        "title": "Finance topup adjustment cycle",
        "mutation_evidence": "POST /api/v1/admin/finance/topup returns 201",
        "persistence_check": "/api/v1/admin/finance/topup/{id} GET returns 200",
        "dependencies": "admin-finance role; topup ledger schema",
        "primary_endpoints": [{"method": "POST", "path": "/api/v1/admin/finance/topup"}],
    }
    surfaces = {"routes": [
        {"route": "/2fa/challenge"},
        {"route": "/2fa/setup-totp"},
        {"route": "/2fa/verify-email"},
        {"route": "/api/v1/admin/finance/topup"},
        {"route": "/admin/finance/topup"},
    ]}
    hints = expander_mod._entrypoint_hints(spec, surfaces, "web-fullstack")
    has_2fa = any("/2fa" in h for h in hints)
    has_finance = any("/finance/topup" in h or "topup" in h for h in hints)
    assert not has_2fa, f"2FA route polluted finance goal hints: {hints}"
    assert has_finance, f"finance route absent from hints: {hints}"


def test_b74_cm2_auth_goal_includes_2fa_when_relevant(expander_mod):
    """An auth/2FA goal SHOULD still receive /2fa/* routes (relevance signal hit)."""
    spec = {
        "title": "User enables 2FA via TOTP setup",
        "mutation_evidence": "POST /2fa/setup-totp returns 200 with secret",
        "persistence_check": "/2fa/verify-totp confirms 2fa_enabled=true",
        "dependencies": "totp library; otp config",
        "primary_endpoints": [{"method": "POST", "path": "/2fa/setup-totp"}],
    }
    surfaces = {"routes": [
        {"route": "/2fa/setup-totp"},
        {"route": "/2fa/verify-totp"},
        {"route": "/api/v1/admin/finance/topup"},  # unrelated
    ]}
    hints = expander_mod._entrypoint_hints(spec, surfaces, "web-fullstack")
    has_2fa = any("/2fa" in h for h in hints)
    has_unrelated = any("/finance" in h for h in hints)
    assert has_2fa, f"2FA route stripped from auth goal: {hints}"
    assert not has_unrelated, f"unrelated finance route polluted auth goal: {hints}"


def test_b74_cm2_empty_haystack_keeps_prior_top_10_behavior(expander_mod):
    """When spec has no signal text, fall through to original top-10 behavior (compat)."""
    spec = {}
    surfaces = {"routes": [{"route": f"/r{i}"} for i in range(15)]}
    hints = expander_mod._entrypoint_hints(spec, surfaces, "web-fullstack")
    # Empty haystack falls through → top-10.
    assert sum(1 for h in hints if h.startswith("/r")) == 10


def test_b74_cm2_route_cap_at_10(expander_mod):
    """Even with relevance hits, route count caps at 10."""
    spec = {"title": "alpha", "mutation_evidence": "alpha", "persistence_check": "alpha",
            "dependencies": "alpha"}
    surfaces = {"routes": [{"route": f"/alpha/{i}"} for i in range(20)]}
    hints = expander_mod._entrypoint_hints(spec, surfaces, "web-fullstack")
    matched = [h for h in hints if h.startswith("/alpha")]
    assert len(matched) <= 10


# ---------------------------------------------------------------------------
# C-M6: YAML fence pollution — _field strips ```yaml ... ``` before extract.
# ---------------------------------------------------------------------------


def test_b74_cm6_dependencies_no_yaml_block_leak(lifecycle_mod):
    body = """## Goal G-007: Pay invoice

**Dependencies:** invoice schema; payment provider stub

```yaml
rcrurdr:
  resource: invoice
  api_endpoint: /api/v1/invoices/{id}/pay
  expectations:
    - status returns 200
    - audit log entry added
```

**Surface:** finance
**Priority:** critical
"""
    deps = lifecycle_mod._field(body, "Dependencies")
    assert "rcrurdr" not in deps.lower()
    assert "expectations" not in deps.lower()
    assert "invoice schema" in deps
    assert "payment provider stub" in deps


def test_b74_cm6_field_after_yaml_block_still_extractable(lifecycle_mod):
    body = """## Goal G-008: Create site

```yaml
rcrurdr:
  resource: site
```

**Surface:** publisher
**Mutation evidence:** POST /api/v1/sites returns 201
"""
    surface = lifecycle_mod._field(body, "Surface")
    mut = lifecycle_mod._field(body, "Mutation evidence")
    assert "publisher" in surface.lower()
    assert "/api/v1/sites" in mut


def test_b74_cm6_no_yaml_block_unchanged_behavior(lifecycle_mod):
    """Goals without yaml blocks parse identically to pre-B74."""
    body = """## Goal G-001: Topup

**Dependencies:** finance role
**Priority:** critical
"""
    assert lifecycle_mod._field(body, "Dependencies") == "finance role"
    assert lifecycle_mod._field(body, "Priority") == "critical"


# ---------------------------------------------------------------------------
# C-M5: API contract path validation + C-M1 fallback warning surface.
# ---------------------------------------------------------------------------


def test_b74_cm5_primary_endpoint_in_contracts_used(lifecycle_mod):
    """When goal.primary_endpoints[i].path is present AND in contracts → that path wins over fallback."""
    goal = {
        "title": "Topup adjustment",
        "primary_endpoints": [{"method": "POST", "path": "/api/v1/admin/finance/topup"}],
    }
    contracts = [
        {"method": "POST", "path": "/api/v1/auth/login"},  # would be fallback (wrong)
        {"method": "POST", "path": "/api/v1/admin/finance/topup"},
        {"method": "GET", "path": "/api/v1/admin/finance/topup/{id}"},
    ]
    result = lifecycle_mod._bind_endpoint("create", goal, contracts)
    assert result == {"method": "POST", "path": "/api/v1/admin/finance/topup"}


def test_b74_cm5_primary_endpoint_not_in_contracts_skipped(lifecycle_mod):
    """If goal claims a path NOT in contracts (stale/drifted), don't propagate phantom.

    B91 v4.67.0 (issue #197 F-CAI-01) update: previously fell through to
    verb-fallback (first POST in contracts) — which is the cross-resource
    pollution pattern. B91 entity-anchor invariant: when goal.primary_endpoints
    have no contract match AND no other goal slug overlaps any contract path,
    return None instead of binding to unrelated resource.
    """
    goal = {
        "title": "Drifted-OLD_PATH",
        "primary_endpoints": [{"method": "POST", "path": "/api/v1/OLD_PATH"}],
    }
    contracts = [
        {"method": "POST", "path": "/api/v1/auth/login"},
        {"method": "POST", "path": "/api/v1/admin/finance/topup"},
    ]
    result = lifecycle_mod._bind_endpoint("create", goal, contracts)
    # B91: entity slugs from title (drifted, old_path) don't overlap any
    # contract path → unmatched, returns None. Diagnostic tag captures gap.
    assert result is None
    assert goal.get("_b91_endpoint_unmatched_count", 0) >= 1


def test_b74_cm1_fallback_path_records_diagnostic(lifecycle_mod):
    """When haystack + primary_endpoints both miss, B91 returns None instead
    of unconstrained verb-fallback. Diagnostic counter still records gap.

    B91 v4.67.0 (issue #197 F-CAI-01) update: previously emitted first
    POST in contracts (auth/login) for sparse goal "Sparse goal" wanting
    "create" — that's exactly the cross-resource pollution F-CAI-01 reports.
    Now: no slug overlap → None. _b91_endpoint_unmatched_count counts.
    """
    goal = {"title": "Sparse goal", "mutation_evidence": "", "persistence_check": "",
            "dependencies": ""}
    contracts = [
        {"method": "POST", "path": "/api/v1/auth/login"},
    ]
    result = lifecycle_mod._bind_endpoint("create", goal, contracts)
    # Title "sparse goal" → entity slug "sparse" → not in /api/v1/auth/login
    assert result is None
    assert goal.get("_b91_endpoint_unmatched_count") == 1


def test_b74_cm5_no_contracts_returns_none(lifecycle_mod):
    """Backward compat: empty contracts → None (no fallback magic)."""
    goal = {"title": "x"}
    result = lifecycle_mod._bind_endpoint("create", goal, [])
    assert result is None


def test_b74_cm5_unknown_stage_returns_none(lifecycle_mod):
    """Unknown stage (not in verb_map) → None (no false bind)."""
    goal = {"title": "x"}
    contracts = [{"method": "POST", "path": "/x"}]
    result = lifecycle_mod._bind_endpoint("unknown_stage", goal, contracts)
    assert result is None


# ---------------------------------------------------------------------------
# Marker presence — verifies B74 fix block in source files.
# ---------------------------------------------------------------------------


def test_b74_marker_in_lifecycle_gen():
    body = LIFECYCLE_GEN.read_text(encoding="utf-8")
    assert "B74 v4.63.6" in body
    assert "C-M6" in body or "issue #191" in body
    assert "C-M5" in body or "C-M1" in body


def test_b74_marker_in_ai_expander():
    body = AI_EXPANDER.read_text(encoding="utf-8")
    assert "B74 v4.63.6" in body
    assert "C-M2" in body or "2FA" in body
