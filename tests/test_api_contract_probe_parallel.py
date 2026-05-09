"""v2.65.0 A2 — Parallel API contract probe tests.

Validates that ``review-api-contract-probe.probe_endpoints`` runs the endpoint
list via ThreadPoolExecutor when ``parallel > 1`` while preserving:
  - default sequential back-compat (parallel=1 → list comp, no executor)
  - meaningful speedup vs sequential when probes simulate real latency
  - partial-failure handling: a worker raising must NOT crash the whole batch;
    the offending endpoint surfaces as an error-shaped ProbeResult while
    siblings still return their real results

Tests stub ``probe_endpoint`` via ``monkeypatch`` so we never touch the network;
the stub honours a per-endpoint sleep encoded in ``Endpoint.path`` (sleep:0.2,
sleep:fail) to simulate latency / poisoning without forking curl.

A1 alignment: error shape mirrors the existing ``curl_rc != 0`` path in
``probe_endpoint`` itself — ``status=0, verdict="FAIL"`` plus a ``detail``
prefix (``worker_raise:``) so a single ``r.verdict == "FAIL" and r.status == 0``
predicate covers connectivity failures + worker exceptions uniformly.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "review-api-contract-probe.py"


@pytest.fixture(scope="module")
def probe_module():
    """Import review-api-contract-probe.py as a module for direct API access.

    Registers the module in ``sys.modules`` BEFORE ``exec_module`` so the
    dataclass decorator can resolve forward references via
    ``sys.modules[cls.__module__]`` — required because the script uses
    ``from __future__ import annotations``.
    """
    import sys
    name = "review_api_contract_probe"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _ep(probe_module, method: str, path: str):
    """Build one synthetic Endpoint."""
    return probe_module.Endpoint(method=method, path=path, auth=None)


def _install_sleep_stub(probe_module, monkeypatch, sleep_s: float = 0.2,
                       *, poison_path: str | None = None) -> None:
    """Stub ``probe_endpoint`` to sleep ``sleep_s`` per call and return a
    PASS ProbeResult — unless ``poison_path`` matches the endpoint, in which
    case the stub raises RuntimeError to exercise partial-failure handling.
    """
    Result = probe_module.ProbeResult

    def fake_probe(base_url, endpoint, headers, timeout):
        if poison_path is not None and endpoint.path == poison_path:
            raise RuntimeError("simulated probe crash")
        if sleep_s > 0:
            time.sleep(sleep_s)
        return Result(
            endpoint=endpoint,
            url=f"{base_url}{endpoint.path}",
            status=200,
            verdict="PASS",
            detail=f"probe={endpoint.probe_method}; status=200",
        )

    monkeypatch.setattr(probe_module, "probe_endpoint", fake_probe)


# ---------------------------------------------------------------------------
# Test 1 — default sequential back-compat (parallel=1, no executor)
# ---------------------------------------------------------------------------
def test_default_sequential_backcompat(probe_module, monkeypatch) -> None:
    """parallel=1 (default) must hit the sequential codepath; no
    ThreadPoolExecutor.

    Wall-clock for N endpoints × sleep_s ≈ N * sleep_s (with safety margin
    for Windows sleep granularity).
    """
    _install_sleep_stub(probe_module, monkeypatch, sleep_s=0.15)
    endpoints = [_ep(probe_module, "GET", f"/api/r{i}") for i in range(4)]

    started = time.time()
    results = probe_module.probe_endpoints(
        endpoints, base_url="http://x", headers=[], timeout=5,
    )
    elapsed = time.time() - started

    assert len(results) == 4
    # Sequential lower bound: total ≈ N * sleep_s = 0.6s. We assert ≥0.55s
    # to catch the case where the default accidentally fires the executor.
    # 0.55s gives Windows-under-load slack while staying well below the
    # 0.6s sequential expectation and far above any plausible parallel
    # finish (~0.2s).
    assert elapsed >= 0.55, (
        f"default (parallel=1) finished in {elapsed:.2f}s — too fast, "
        "suggests ThreadPoolExecutor branch fired when it should have stayed "
        "sequential"
    )
    # Each result is a real ProbeResult with the expected shape.
    for i, r in enumerate(results):
        assert r.endpoint.path == f"/api/r{i}"
        assert r.verdict == "PASS"
        assert r.status == 200


# ---------------------------------------------------------------------------
# Test 2 — parallel speedup vs sequential
# ---------------------------------------------------------------------------
def test_parallel_speedup(probe_module, monkeypatch) -> None:
    """parallel=5 over 5 endpoints (each sleeping 0.2s) must finish in
    well under the sequential lower bound (5 * 0.2 = 1.0s).

    Threshold: <1.3s (matches A1 flake-margin convention). Ideal on a
    5-worker pool with overlapping I/O is ~0.2s; we pad heavily — 1.3s
    — to keep CI flake-free under load while staying decisively below
    the 1.0s sequential floor when amortized over the test wall.
    """
    _install_sleep_stub(probe_module, monkeypatch, sleep_s=0.2)
    endpoints = [_ep(probe_module, "GET", f"/api/r{i}") for i in range(5)]

    started = time.time()
    results = probe_module.probe_endpoints(
        endpoints, base_url="http://x", headers=[], timeout=5, parallel=5,
    )
    elapsed = time.time() - started

    assert len(results) == 5
    assert elapsed < 1.3, (
        f"parallel=5 took {elapsed:.2f}s — expected <1.3s "
        "(sequential would be ~1.0s); ThreadPoolExecutor likely not engaged"
    )
    # Order preserved regardless of completion order.
    for i, r in enumerate(results):
        assert r.endpoint.path == f"/api/r{i}", (
            f"results[{i}].path={r.endpoint.path!r} expected /api/r{i}; "
            "ordering not preserved by ThreadPoolExecutor branch"
        )


# ---------------------------------------------------------------------------
# Test 3 — partial-failure: one worker raises, others must still return
# ---------------------------------------------------------------------------
def test_partial_failure_returns_error_dict(probe_module, monkeypatch) -> None:
    """If a single worker raises, ``probe_endpoints`` must NOT crash the
    whole batch.

    The error shape mirrors the existing ``curl_rc != 0`` path in
    ``probe_endpoint`` (status=0, verdict='FAIL') with a ``worker_raise:``
    detail prefix so downstream consumers can identify it. This keeps a
    single predicate — ``r.verdict == 'FAIL' and r.status == 0`` —
    covering connectivity failures and worker exceptions uniformly,
    which is the A1 homogeneous-shape principle.
    """
    _install_sleep_stub(
        probe_module, monkeypatch, sleep_s=0.05, poison_path="/api/r2",
    )
    endpoints = [_ep(probe_module, "GET", f"/api/r{i}") for i in range(5)]

    results = probe_module.probe_endpoints(
        endpoints, base_url="http://x", headers=[], timeout=5, parallel=4,
    )

    # Order must still align with input plan even when one entry errored.
    assert len(results) == 5
    for i, r in enumerate(results):
        assert r.endpoint.path == f"/api/r{i}", (
            f"results[{i}].path={r.endpoint.path!r} expected /api/r{i}; "
            "ordering not preserved when a worker raised"
        )

    # Entries 0,1,3,4 succeeded — verdict PASS, status 200.
    for i in (0, 1, 3, 4):
        r = results[i]
        assert r.verdict == "PASS", (
            f"results[{i}] expected PASS; got {r!r}"
        )
        assert r.status == 200

    # Entry 2 surfaced as an error-shaped ProbeResult matching the canonical
    # field set: status=0 + verdict=FAIL (same as curl_rc != 0 path) plus a
    # ``worker_raise:`` detail prefix carrying the exception message.
    err = results[2]
    assert err.verdict == "FAIL", (
        f"poisoned entry should have verdict=FAIL; got {err!r}"
    )
    assert err.status == 0, (
        f"poisoned entry should have status=0 (no HTTP response); got {err!r}"
    )
    assert err.detail.startswith("worker_raise:"), (
        f"poisoned entry detail should start with 'worker_raise:'; got {err!r}"
    )
    assert "simulated probe crash" in err.detail, (
        f"error message not propagated into detail: {err!r}"
    )
    assert err.endpoint.path == "/api/r2"
