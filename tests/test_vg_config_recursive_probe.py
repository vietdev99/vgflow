"""Verify vg.config.template.md ships review.recursive_probe + review.target_env
+ review.batch + review.prod_safety blocks with valid YAML.

Tasks 23 (recursive_probe) + 26f (target_env, batch, prod_safety).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "vg.config.template.md"


def _load_review_block() -> dict:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("\nreview:")
    end = text.index("\ndesign_system:")
    return yaml.safe_load(text[start + 1:end])


def test_template_exists():
    assert TEMPLATE.is_file()


def test_review_recursive_probe_block_present():
    data = _load_review_block()
    rp = data["review"]["recursive_probe"]
    for key in ("default_mode", "default_probe_mode", "worker_model",
                "worker_concurrency", "max_depth_overrides", "hybrid_routing"):
        assert key in rp, f"missing review.recursive_probe.{key}"


def test_recursive_probe_modes_exhaustive():
    data = _load_review_block()
    rp = data["review"]["recursive_probe"]
    assert rp["default_mode"] in {"light", "deep", "exhaustive"}
    assert rp["default_probe_mode"] in {"auto", "manual", "hybrid"}
    for k in ("light", "deep", "exhaustive"):
        assert k in rp["max_depth_overrides"]


def test_review_target_env_block_present():
    data = _load_review_block()
    assert data["review"]["target_env"] in {"local", "sandbox", "staging", "prod"}


def test_review_prod_safety_block_present():
    data = _load_review_block()
    ps = data["review"]["prod_safety"]
    assert ps["require_reason"] is True
    assert ps["read_only"] is True
    assert ps["mutation_budget"] == 0


def test_review_batch_block_present():
    data = _load_review_block()
    b = data["review"]["batch"]
    assert isinstance(b["parallelism"], int)
    assert b["continue_on_failure"] is True
    assert "{date}" in b["aggregate_findings_path"]


def test_hybrid_routing_lenses_disjoint():
    data = _load_review_block()
    rp = data["review"]["recursive_probe"]
    auto = set(rp["hybrid_routing"]["auto_lenses"])
    manual = set(rp["hybrid_routing"]["manual_lenses"])
    assert not (auto & manual), f"overlap: {auto & manual}"
