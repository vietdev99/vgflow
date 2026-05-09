"""v2.66.1 #153 — Findings clustered by API endpoint shape."""
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_derive():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "derive_findings",
        repo_root / "scripts" / "derive-findings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_findings_with_same_endpoint_clustered():
    """3 findings on different views all hitting POST /api/v1/orders/:id/pay -> 1 ROOT + 3 child refs."""
    mod = _load_derive()
    findings = [
        {"resource": "/orders", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/123/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
        {"resource": "/orders/views", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/456/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
        {"resource": "/checkout", "role": "ALL", "step_ref": "smoke",
         "title": "400 /api/v1/orders/789/pay",
         "api_endpoint": "POST /api/v1/orders/:id/pay",
         "severity": "MINOR"},
    ]
    clustered = mod.cluster_by_api_endpoint(findings)

    # Expect 1 ROOT (escalated severity) + 3 child references in metadata
    roots = [f for f in clustered if f.get("cluster_role") == "root"]
    assert len(roots) == 1, f"Expected 1 root, got {len(roots)}"

    root = roots[0]
    assert root["api_endpoint"] == "POST /api/v1/orders/:id/pay"
    assert root["severity"] in ("MAJOR", "CRITICAL"), \
        f"Root must escalate severity, got {root['severity']}"
    assert root.get("affected_views_count") == 3 or len(root.get("affected_views", [])) == 3


def test_findings_without_api_endpoint_passthrough():
    """Findings without api_endpoint key pass through dedup unchanged (back-compat)."""
    mod = _load_derive()
    findings = [
        {"resource": "/x", "role": "ALL", "step_ref": "ssim",
         "title": "Pixel diff", "severity": "MINOR"},
    ]
    out = mod.cluster_by_api_endpoint(findings)
    assert len(out) == 1
    assert out[0].get("cluster_role") in (None, "standalone")


def test_dedupe_still_runs_after_clustering():
    """Existing dedupe by view + title still applies AFTER clustering (orthogonal)."""
    mod = _load_derive()
    # 2 findings on same view, same title - dedup to 1
    findings = [
        {"resource": "/x", "role": "ALL", "step_ref": "smoke", "title": "Console error A"},
        {"resource": "/x", "role": "ALL", "step_ref": "smoke", "title": "Console error A"},
    ]
    out = mod.dedupe(findings)
    assert len(out) == 1


def test_normalize_api_endpoint_strips_query_and_ids():
    """api_endpoint shape extraction must replace numeric IDs with :id, strip query."""
    mod = _load_derive()
    cases = [
        ("POST /api/v1/orders/123/pay", "POST /api/v1/orders/:id/pay"),
        ("GET /api/v1/users/abc-uuid?include=profile", "GET /api/v1/users/:id"),
        ("DELETE /api/v1/items/42", "DELETE /api/v1/items/:id"),
    ]
    for raw, expected in cases:
        got = mod.normalize_api_endpoint(raw)
        assert got == expected, f"normalize({raw!r}) = {got!r}, want {expected!r}"
