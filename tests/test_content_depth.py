"""Tests for scripts/runtime/content_depth.py — RFC v9 D27."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.content_depth import (  # noqa: E402
    aggregate_failures,
    cross_reference,
    edge_case_substance,
    instruction_repetition,
    llm_judge_sample,
    word_count,
)


# ─── word_count ───────────────────────────────────────────────────────


def test_word_count_passes():
    ok, msg = word_count("alpha beta gamma delta epsilon zeta", min_words=5)
    assert ok and msg is None


def test_word_count_fails():
    ok, msg = word_count("only three words now", min_words=10)
    assert not ok
    assert "word_count=4" in msg


def test_word_count_handles_unicode():
    ok, _ = word_count("một hai ba bốn năm", min_words=5)
    assert ok


# ─── cross_reference ─────────────────────────────────────────────────


def test_cross_reference_all_present():
    text = "We discuss D-01, D-02, D-03, and decision G-10."
    ok, msg = cross_reference(text, required_anchors=["D-01", "D-02", "G-10"])
    assert ok and msg is None


def test_cross_reference_missing():
    text = "Only D-01 here."
    ok, msg = cross_reference(text, required_anchors=["D-01", "D-02", "G-10"])
    assert not ok
    assert "D-02" in msg


def test_cross_reference_min_unique_enforced():
    text = "D-01 D-01 D-01"
    ok, msg = cross_reference(
        text, required_anchors=["D-01"], min_unique=2,
    )
    assert not ok
    assert "1 unique" in msg


# ─── edge_case_substance ─────────────────────────────────────────────


def test_edge_case_substance_passes_when_substantive():
    text = """
- API rejects with 422 when amount exceeds tier limit; client must show
- Rate limiter trips after 5 requests in 10 seconds and surfaces 429
- Concurrent admin clicks cause race; idempotency-key prevents double charge
- Network timeout after 30s rolls back transaction; user sees retry option
""".strip()
    ok, msg = edge_case_substance(text)
    assert ok, msg


def test_edge_case_substance_fails_on_tbd():
    text = """
- TBD
- TODO: think about this
- N/A
""".strip()
    ok, msg = edge_case_substance(text)
    assert not ok
    assert "placeholder" in msg


def test_edge_case_substance_fails_on_thin_bullets():
    text = """
- Short
- Tiny one
- Brief
- Yes
""".strip()
    ok, msg = edge_case_substance(text, bullet_min_words=10)
    assert not ok
    assert "substantive bullets" in msg


def test_edge_case_substance_fails_on_too_few_bullets():
    text = """
- This is a substantive edge case with sufficient detail to satisfy threshold
""".strip()
    ok, msg = edge_case_substance(text, min_bullets_with_body=3)
    assert not ok


def test_edge_case_substance_vietnamese_placeholder():
    text = "- chưa\n- cần bổ sung\n- TBD\n"
    ok, msg = edge_case_substance(text)
    assert not ok
    assert "placeholder" in msg


# ─── instruction_repetition ──────────────────────────────────────────


def test_instruction_repetition_passes():
    text = "STEP 1: do X. Later: REMEMBER, do X. Final: do X again."
    ok, msg = instruction_repetition(text, key_phrase="do X", min_occurrences=3)
    assert ok


def test_instruction_repetition_fails():
    text = "Do X once at the top. Then never again."
    ok, msg = instruction_repetition(text, key_phrase="do X", min_occurrences=3)
    assert not ok
    assert "1×" in msg


def test_instruction_repetition_case_insensitive_default():
    text = "Do X. DO X. do x."
    ok, _ = instruction_repetition(text, key_phrase="do x", min_occurrences=3)
    assert ok


def test_instruction_repetition_case_sensitive():
    text = "Do X. DO X."
    ok, msg = instruction_repetition(
        text, key_phrase="do X", min_occurrences=2, case_insensitive=False,
    )
    assert not ok


# ─── llm_judge_sample ────────────────────────────────────────────────


def test_llm_judge_sample_returns_all_when_few_sections():
    sections = {"a": "X", "b": "Y"}
    out = llm_judge_sample(sections, sample_size=3)
    assert out == sections


def test_llm_judge_sample_deterministic():
    sections = {f"s{i}": f"text-{i}" for i in range(10)}
    out_a = llm_judge_sample(sections, sample_size=3, rng_seed=42)
    out_b = llm_judge_sample(sections, sample_size=3, rng_seed=42)
    assert out_a == out_b
    assert len(out_a) == 3


def test_llm_judge_sample_different_seed_different_picks():
    sections = {f"s{i}": f"text-{i}" for i in range(20)}
    out_a = llm_judge_sample(sections, sample_size=5, rng_seed=1)
    out_b = llm_judge_sample(sections, sample_size=5, rng_seed=2)
    assert out_a != out_b


# ─── aggregate_failures ──────────────────────────────────────────────


def test_aggregate_passes_when_all_ok():
    results = [(True, None), (True, None)]
    out = aggregate_failures(results, name="test-validator")
    assert out["verdict"] == "PASS"
    assert out["failures"] == []
    assert out["checks_run"] == 2
    assert out["checks_passed"] == 2


def test_aggregate_blocks_with_partial_failures():
    results = [(True, None), (False, "issue-A"), (False, "issue-B")]
    out = aggregate_failures(results, name="test")
    assert out["verdict"] == "BLOCK"
    assert "issue-A" in out["failures"]
    assert out["checks_passed"] == 1
