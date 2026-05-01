"""Tests for scripts/runtime/pattern_catalog.py — RFC v9 D25."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.pattern_catalog import (  # noqa: E402
    Pattern,
    load_catalog,
    load_pattern,
    match_patterns,
    needs_web_augment,
)

CATALOG_DIR = REPO_ROOT / "catalog" / "edge-cases"


def test_seed_catalog_loads():
    """The 5 seed patterns must load without errors."""
    patterns = load_catalog(CATALOG_DIR)
    assert len(patterns) >= 5
    ids = {p.id for p in patterns}
    assert "payments-idempotency-collision" in ids
    assert "auth-session-fixation" in ids
    assert "ui-double-submit" in ids


def test_match_by_surface(tmp_path):
    catalog = load_catalog(CATALOG_DIR)
    api_only = match_patterns(catalog, surface="api")
    assert all(p.surface == "api" for p in api_only)
    assert any(p.id == "payments-idempotency-collision" for p in api_only)

    ui_only = match_patterns(catalog, surface="ui")
    assert all(p.surface == "ui" for p in ui_only)


def test_match_by_tags_overlap():
    catalog = load_catalog(CATALOG_DIR)
    payments = match_patterns(catalog, tags=["payments"])
    assert any(p.id == "payments-idempotency-collision" for p in payments)
    assert all("payments" in p.tags for p in payments)


def test_match_require_all_tags():
    catalog = load_catalog(CATALOG_DIR)
    # idempotency AND payments — payments-idempotency-collision is the seed
    # pattern carrying both tags
    matches = match_patterns(
        catalog, tags=["payments", "idempotency"], require_all_tags=True,
    )
    assert any(p.id == "payments-idempotency-collision" for p in matches)
    # something with only payments would miss when require_all_tags=True
    only_payments_match = match_patterns(
        catalog, tags=["payments", "no_such_tag"], require_all_tags=True,
    )
    assert only_payments_match == []


def test_severity_floor():
    catalog = load_catalog(CATALOG_DIR)
    high_only = match_patterns(catalog, severity_min="high")
    assert all(p.severity in ("high", "critical") for p in high_only)
    crit_only = match_patterns(catalog, severity_min="critical")
    assert all(p.severity == "critical" for p in crit_only)


def test_results_sorted_by_severity_desc():
    catalog = load_catalog(CATALOG_DIR)
    out = match_patterns(catalog)
    sev_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    ranks = [sev_rank.get(p.severity, 2) for p in out]
    assert ranks == sorted(ranks, reverse=True)


def test_load_pattern_missing_id_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nsurface: api\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing id"):
        load_pattern(bad)


def test_load_pattern_missing_surface_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing surface"):
        load_pattern(bad)


def test_needs_web_augment_threshold():
    assert needs_web_augment([], min_matches=1)
    assert needs_web_augment([Pattern("x", "api")], min_matches=2)
    assert not needs_web_augment(
        [Pattern("a", "api"), Pattern("b", "api")], min_matches=2,
    )


def test_load_catalog_empty_dir(tmp_path):
    assert load_catalog(tmp_path) == []


def test_load_catalog_nonexistent_dir(tmp_path):
    assert load_catalog(tmp_path / "missing") == []


def test_load_catalog_skips_malformed(tmp_path):
    (tmp_path / "good.md").write_text(
        "---\nid: g\nsurface: api\n---\nbody\n", encoding="utf-8",
    )
    (tmp_path / "bad.md").write_text(
        "---\nid: b\n---\nno surface\n", encoding="utf-8",
    )
    out = load_catalog(tmp_path)
    assert len(out) == 1
    assert out[0].id == "g"
