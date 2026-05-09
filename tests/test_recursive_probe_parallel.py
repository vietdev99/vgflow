"""v2.65.0 A1 — Parallel lens probe dispatch tests.

Validates that ``spawn_recursive_probe.dispatch_auto`` runs the plan via
ThreadPoolExecutor when ``parallel > 1`` while preserving:
  - default sequential back-compat (parallel=1 → no executor)
  - result ordering matches input plan order (deterministic indexing)
  - meaningful speedup vs sequential when entries simulate real work

Tests use ``mock_mode=True`` so we never spawn a real Gemini subprocess; the
mock honors a per-entry ``mock_sleep_s`` to simulate latency without forking.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"


@pytest.fixture(scope="module")
def probe_module():
    """Import spawn_recursive_probe.py as a module for direct API access."""
    spec = importlib.util.spec_from_file_location(
        "spawn_recursive_probe", SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _mock_entry(i: int, sleep_s: float) -> dict:
    """Build one synthetic plan entry whose mock worker sleeps ``sleep_s``."""
    return {
        "element": {
            "element_class": "mutation_button",
            "selector": f"btn-{i}",
            "view": "/admin",
            "resource": f"res-{i}",
            "role": "admin",
            "selector_hash": f"h{i:04d}",
        },
        "lens": "lens-authz-negative",
        "scope_key": (f"res-{i}", "admin", "lens-authz-negative"),
        "mock_sleep_s": sleep_s,
    }


def _mock_plan(n: int, sleep_s: float = 0.2) -> list[dict]:
    """Build a synthetic plan with uniform sleep_s per entry."""
    return [_mock_entry(i, sleep_s) for i in range(n)]


# ---------------------------------------------------------------------------
# Test 1 — default sequential back-compat (parallel=1, no executor)
# ---------------------------------------------------------------------------
def test_default_sequential_backcompat(probe_module, tmp_path: Path) -> None:
    """parallel=1 must hit the sequential codepath; no ThreadPoolExecutor.

    Wall-clock for N entries × sleep_s ≈ N * sleep_s (with safety margin
    for Windows sleep granularity).
    """
    plan = _mock_plan(n=4, sleep_s=0.15)
    started = time.time()
    results = probe_module.dispatch_auto(
        plan, tmp_path, parallel=1, mock_mode=True,
    )
    elapsed = time.time() - started

    assert len(results) == 4
    # Sequential lower bound: total ≈ N * sleep_s = 0.6s. We assert ≥0.5s
    # to catch the case where parallel=1 accidentally fires the executor.
    assert elapsed >= 0.5, (
        f"parallel=1 finished in {elapsed:.2f}s — too fast, suggests "
        "ThreadPoolExecutor branch fired when it should have stayed sequential"
    )
    # Each result carries the canonical fields dispatch_auto returns today.
    for r in results:
        assert "exit_code" in r
        assert "lens" in r
        assert "selector" in r


# ---------------------------------------------------------------------------
# Test 2 — parallel speedup vs sequential
# ---------------------------------------------------------------------------
def test_parallel_speedup(probe_module, tmp_path: Path) -> None:
    """parallel=4 over 8 entries (each sleeping 0.2s) must be measurably
    faster than the sequential lower bound (8 * 0.2 = 1.6s).

    Threshold: <1.0s (≥38% reduction). Ideal on a 4-worker pool is ~0.4s;
    we pad heavily to keep CI flake-free.
    """
    plan = _mock_plan(n=8, sleep_s=0.2)
    started = time.time()
    results = probe_module.dispatch_auto(
        plan, tmp_path, parallel=4, mock_mode=True,
    )
    elapsed = time.time() - started

    assert len(results) == 8
    assert elapsed < 1.0, (
        f"parallel=4 took {elapsed:.2f}s — expected <1.0s "
        "(sequential would be ~1.6s); ThreadPoolExecutor likely not engaged"
    )


# ---------------------------------------------------------------------------
# Test 3 — output order preserved (parallel results align with input plan)
# ---------------------------------------------------------------------------
def test_parallel_output_order_preserved(probe_module, tmp_path: Path) -> None:
    """Even when workers complete out of order, results[i] must correspond
    to plan[i]. Reverse-order sleep ensures naive ``as_completed`` would
    scramble the order — only an indexed-future collection survives.
    """
    plan = [
        _mock_entry(i, 0.1 + (4 - i) * 0.1)  # 0.5, 0.4, 0.3, 0.2
        for i in range(4)
    ]
    results = probe_module.dispatch_auto(
        plan, tmp_path, parallel=4, mock_mode=True,
    )
    assert len(results) == 4
    for i, r in enumerate(results):
        assert r["selector"] == f"btn-{i}", (
            f"results[{i}].selector={r['selector']!r} expected btn-{i}; "
            "ordering not preserved by ThreadPoolExecutor branch"
        )
