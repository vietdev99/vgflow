"""B76 v4.63.8 regression — issue #191 C-M1/C-M5/C-M8 real root cause.

B75 v4.63.7 claimed "8/8 complete" but consumer measurement showed:
- 1218/1218 lifecycle step endpoints null (C-M1)
- 114/185 primary_endpoints mismatched API-CONTRACTS (C-M5)
- 206/206 goals with empty decision_refs (C-M8)

Root cause: ENDPOINT_HEADER_RE only matched `### GET /path` headers;
3-layer split API-CONTRACTS.md uses TOC links → 0 contracts loaded.
DECISION_HEADER_RE required bare `D-XX`; CONTEXT.md uses `P8.D-XX`
prefix → 0 decisions parsed.

These tests assert non-zero counts via the public regex/parser surface
so future B-batches cannot stub-pass.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate-lifecycle-specs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lcs_b76", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── C-M1 / C-M5: endpoint binding from 3-layer split API-CONTRACTS ──────────


def test_endpoint_toc_link_re_matches_index_format() -> None:
    """3-layer split index `- [GET /path](file.md)` must match."""
    mod = _load_module()
    text = "- [GET /api/v1/admin/credits](get-credits.md)\n- [POST /api/v1/foo/bar](post-foo.md)\n"
    matches = list(mod.ENDPOINT_TOC_LINK_RE.finditer(text))
    assert len(matches) == 2
    assert (matches[0].group(1), matches[0].group(2)) == ("GET", "/api/v1/admin/credits")
    assert (matches[1].group(1), matches[1].group(2)) == ("POST", "/api/v1/foo/bar")


def test_endpoint_header_re_still_matches_flat_format() -> None:
    """Legacy flat `### GET /path` must still match (backward compat)."""
    mod = _load_module()
    text = "### GET /api/v1/foo\n### POST /api/v1/bar\n"
    matches = list(mod.ENDPOINT_HEADER_RE.finditer(text))
    assert len(matches) == 2


def test_parse_api_contracts_combines_both_formats(tmp_path: Path) -> None:
    """_parse_api_contracts must merge header + index-link + sub-file results."""
    mod = _load_module()
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "API-CONTRACTS.md").write_text(
        "## TOC\n"
        "- [GET /api/v1/admin/topups](get-topups.md)\n"
        "- [POST /api/v1/admin/topups/:id/approve](post-approve.md)\n"
        "### GET /api/v1/admin/legacy\n",
        encoding="utf-8",
    )
    # Plus a per-endpoint file for the 3-layer split layout.
    split_dir = phase_dir / "API-CONTRACTS"
    split_dir.mkdir()
    (split_dir / "patch-foo.md").write_text("### PATCH /api/v1/admin/foo\n", encoding="utf-8")

    contracts = mod._parse_api_contracts(phase_dir)
    paths = {(c["method"], c["path"]) for c in contracts}
    assert ("GET", "/api/v1/admin/topups") in paths
    assert ("POST", "/api/v1/admin/topups/:id/approve") in paths
    assert ("GET", "/api/v1/admin/legacy") in paths
    assert ("PATCH", "/api/v1/admin/foo") in paths
    assert len(contracts) >= 4


def test_parse_api_contracts_nonzero_on_phase_82_fixture() -> None:
    """B75 falsified: consumer reported 0 contracts on P8.2-style index.
    Synthetic regression — mirrors the real failing input.
    """
    mod = _load_module()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        phase = Path(td)
        (phase / "API-CONTRACTS.md").write_text(
            "---\nphase: 8.2\ntotal_endpoints: 123\n---\n\n"
            "## TOC\n\n"
            "### Finance — Billing\n\n"
            "- [GET /api/v1/admin/finance/billing/topup-reviews](get-topup-reviews.md)\n"
            "- [POST /api/v1/admin/topups/:id/approve](post-approve.md)\n",
            encoding="utf-8",
        )
        contracts = mod._parse_api_contracts(phase)
        assert len(contracts) >= 2, "B75 regression: index format must load contracts"


# ─── C-M8: decision_refs resolution across P\d+. prefix variants ──────────────


def test_decision_header_re_matches_prefixed_form() -> None:
    """`### P8.D-67:` must capture full `P8.D-67`."""
    mod = _load_module()
    text = "### P8.D-67: 4 tiers\n### D-200: plain form\n"
    matches = list(mod.DECISION_HEADER_RE.finditer(text))
    ids = [m.group(1) for m in matches]
    assert "P8.D-67" in ids
    assert "D-200" in ids


def test_decision_ref_re_matches_prefixed_form() -> None:
    """Goal text like `(P8.D-84, P8.D-214)` must capture both."""
    mod = _load_module()
    text = "Goal (P8.D-84, P8.D-214, D-200)"
    matches = list(mod.DECISION_REF_RE.finditer(text))
    ids = [m.group(1) for m in matches]
    assert "P8.D-84" in ids
    assert "P8.D-214" in ids
    assert "D-200" in ids


def test_parse_context_decisions_nonzero_on_prefixed_form(tmp_path: Path) -> None:
    """Phase-prefixed `### P8.D-67:` headers must populate decisions dict."""
    mod = _load_module()
    phase = tmp_path / "phase"
    phase.mkdir()
    (phase / "CONTEXT.md").write_text(
        "### P8.D-67: 4 tiers\nDetail.\n\n"
        "### P8.D-68: Upgrade rules\nDetail.\n\n"
        "### D-200: Plain decision\nDetail.\n",
        encoding="utf-8",
    )
    decisions = mod._parse_context_decisions(phase)
    assert "P8.D-67" in decisions, "B75 regression: prefixed header must parse"
    assert "P8.D-68" in decisions
    assert "D-200" in decisions
    assert len(decisions) >= 3


def test_goal_decision_refs_resolves_prefixed_ref_to_prefixed_decision() -> None:
    """End-to-end: goal mentions P8.D-84 → decisions has P8.D-84 → ref returned."""
    mod = _load_module()
    decisions = {"P8.D-84": {"title": "billing tabs"}, "P8.D-214": {"title": "topup branching"}}
    goal = {"title": "topup review", "dependencies": "P8.D-84 P8.D-214"}
    refs = mod._goal_decision_refs(goal, decisions)
    assert "P8.D-84" in refs
    assert "P8.D-214" in refs


# ─── Measurable counter assertions (suggested in #191 follow-up) ──────────────


def test_endpoint_binding_nonzero_rate_threshold() -> None:
    """After parser fix, _bind_endpoint must return non-None for ≥50% steps.
    Pre-B76 the rate was 0% (1218/1218 null). Assert improvement contract.
    """
    mod = _load_module()
    contracts = [
        {"method": "GET", "path": "/api/v1/admin/topups"},
        {"method": "POST", "path": "/api/v1/admin/topups/:id/approve"},
        {"method": "PUT", "path": "/api/v1/admin/foo/:id"},
        {"method": "DELETE", "path": "/api/v1/admin/foo/:id"},
    ]
    goal = {
        "title": "topup approve flow",
        "mutation_evidence": "POST /api/v1/admin/topups/:id/approve returns 200",
        "primary_endpoints": [{"method": "POST", "path": "/api/v1/admin/topups/:id/approve"}],
    }
    stages = ["read_before", "create", "read_after_create"]
    bindings = [mod._bind_endpoint(s, goal, contracts) for s in stages]
    bound = sum(1 for b in bindings if b is not None)
    assert bound == len(stages), f"all 3 stages should bind given valid contract, got {bound}"
