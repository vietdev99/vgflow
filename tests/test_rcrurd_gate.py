"""Tests for scripts/runtime/rcrurd_gate.py — RFC v9 PR-D2 Layer 0 lifecycle gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.rcrurd_gate import (  # noqa: E402
    LifecycleGateError,
    run_post_state_with_retry,
    run_pre_state,
)


def _stub_get(responses: dict[tuple[str, str], dict | Exception]):
    """Returns a get_fn over a (role, endpoint) → response mapping."""
    def get_fn(role: str, endpoint: str):
        r = responses.get((role, endpoint))
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise KeyError(f"no stub for ({role}, {endpoint})")
        return r
    return get_fn


def test_pre_state_passes_when_assertion_matches():
    lifecycle = {
        "pre_state": {
            "role": "u",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 0}],
        },
    }
    res = run_pre_state("G-1", lifecycle, _stub_get({
        ("u", "/api/topup/pending"): {"count": 0},
    }))
    assert res.pre_state_passed
    assert not res.pre_state_failures


def test_pre_state_fails_when_assertion_does_not_match():
    lifecycle = {
        "pre_state": {
            "role": "u",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 0}],
        },
    }
    res = run_pre_state("G-1", lifecycle, _stub_get({
        ("u", "/api/topup/pending"): {"count": 5},  # WRONG
    }))
    assert not res.pre_state_passed
    assert any("count" in f for f in res.pre_state_failures)


def test_pre_state_no_lifecycle_skips():
    res = run_pre_state("G-1", {}, _stub_get({}))
    assert res.skipped_reason


def test_pre_state_get_raises_recorded():
    lifecycle = {
        "pre_state": {
            "role": "u", "endpoint": "/api/x",
            "assert_jsonpath": [{"path": "$", "not_null": True}],
        },
    }
    res = run_pre_state("G-1", lifecycle, _stub_get({
        ("u", "/api/x"): RuntimeError("network"),
    }))
    assert any("raised" in f for f in res.pre_state_failures)


def test_post_state_passes_first_attempt():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 1}],
        },
    }
    res = run_post_state_with_retry("G-1", lifecycle, _stub_get({
        ("u", "/api/topup/pending"): {"count": 1},
    }))
    assert res.post_state_passed


def test_post_state_eventually_passes_with_retry():
    """Eventual consistency: first attempt sees count=0, second sees count=1."""
    attempt_state = {"n": 0}

    def get_fn(role: str, endpoint: str):
        attempt_state["n"] += 1
        return {"count": 0 if attempt_state["n"] < 3 else 1}

    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 1}],
            "retry": {"max_attempts": 5, "delay_ms": 1, "until_assertion_pass": True},
        },
    }
    res = run_post_state_with_retry("G-1", lifecycle, get_fn)
    assert res.post_state_passed
    assert attempt_state["n"] == 3


def test_post_state_max_attempts_exhausted():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/topup/pending",
            "assert_jsonpath": [{"path": "$.count", "equals": 1}],
            "retry": {"max_attempts": 3, "delay_ms": 1, "until_assertion_pass": True},
        },
    }
    res = run_post_state_with_retry("G-1", lifecycle, _stub_get({
        ("u", "/api/topup/pending"): {"count": 0},
    }))
    assert not res.post_state_passed
    assert any("attempt 3" in f for f in res.post_state_failures)


def test_post_state_increased_by_at_least():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/balance",
            "assert_jsonpath": [{"path": "$.balance", "increased_by_at_least": 100}],
        },
    }
    res = run_post_state_with_retry(
        "G-1",
        lifecycle,
        _stub_get({("u", "/api/balance"): {"balance": 1100}}),
        pre_payload={"balance": 1000},
    )
    assert res.post_state_passed


def test_post_state_increased_by_at_least_below_threshold():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/balance",
            "assert_jsonpath": [{"path": "$.balance", "increased_by_at_least": 100}],
        },
    }
    res = run_post_state_with_retry(
        "G-1",
        lifecycle,
        _stub_get({("u", "/api/balance"): {"balance": 1050}}),
        pre_payload={"balance": 1000},
    )
    assert not res.post_state_passed
    assert any("delta=50.0" in f or "threshold=100" in f for f in res.post_state_failures)


def test_post_state_cardinality_assertion():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/items",
            "assert_jsonpath": [{"path": "$.items[*]", "cardinality": ">=3"}],
        },
    }
    payload = {"items": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]}
    res = run_post_state_with_retry("G-1", lifecycle, _stub_get({
        ("u", "/api/items"): payload,
    }))
    assert res.post_state_passed


def test_post_state_not_null():
    lifecycle = {
        "post_state": {
            "role": "u",
            "endpoint": "/api/last",
            "assert_jsonpath": [{"path": "$.confirmed_at", "not_null": True}],
        },
    }
    res = run_post_state_with_retry("G-1", lifecycle, _stub_get({
        ("u", "/api/last"): {"confirmed_at": "2026-05-02T10:00:00Z"},
    }))
    assert res.post_state_passed


def test_post_state_no_retry_block_runs_once():
    """retry omitted → max_attempts=1, no until_pass loop."""
    attempts = {"n": 0}

    def get_fn(role: str, endpoint: str):
        attempts["n"] += 1
        return {"count": 0}  # always fails

    lifecycle = {
        "post_state": {
            "role": "u", "endpoint": "/api/x",
            "assert_jsonpath": [{"path": "$.count", "equals": 1}],
        },
    }
    run_post_state_with_retry("G-1", lifecycle, get_fn)
    assert attempts["n"] == 1
