"""v2.67.0 #162 — envelope_drift finding_type + always-route classifier.

The conservative gate (severity≥HIGH + confidence=high) filters out
envelope drift findings (typically MEDIUM severity), so they never
route to AUTO-FIX-TASKS.md despite being a real bug. Add an
ALWAYS_ROUTE_FINDING_TYPES set with should_route() helper that bypasses
the severity floor for known-actionable finding types.

Tests:
1. envelope_drift findings (MEDIUM severity) route via filter_findings.
2. Source references envelope_drift in the classifier set (not just doc).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_router():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "route_findings_to_build",
        REPO_ROOT / "scripts" / "route-findings-to-build.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_envelope_drift_routed_to_fix_task():
    mod = _load_router()
    findings = [
        {
            "finding_type": "envelope_drift",
            "severity": "medium",  # below severity floor
            "confidence": "high",
            "title": "Envelope drift: contract ok/request_id, runtime success/requestId",
            "evidence": "...",
        }
    ]
    # Use should_route() if exposed, else filter_findings()
    if hasattr(mod, "should_route"):
        routed = [f for f in findings if mod.should_route(f, include_medium=False)]
    else:
        routed = mod.filter_findings(findings, include_medium=False)
    assert len(routed) >= 1, (
        "envelope_drift must route to fix task even at MEDIUM severity"
    )


def test_envelope_drift_in_always_route_set():
    """Source must define envelope_drift in ALWAYS_ROUTE_FINDING_TYPES set."""
    mod = _load_router()
    assert hasattr(mod, "ALWAYS_ROUTE_FINDING_TYPES"), (
        "router must expose ALWAYS_ROUTE_FINDING_TYPES set"
    )
    assert "envelope_drift" in mod.ALWAYS_ROUTE_FINDING_TYPES, (
        "envelope_drift must be in ALWAYS_ROUTE_FINDING_TYPES"
    )


def test_low_severity_random_type_still_filtered():
    """Sanity: a random low-severity finding without always-route type still gets filtered."""
    mod = _load_router()
    findings = [
        {
            "finding_type": "noise_finding",
            "severity": "low",
            "confidence": "low",
            "title": "noisy",
        }
    ]
    if hasattr(mod, "should_route"):
        routed = [f for f in findings if mod.should_route(f, include_medium=False)]
    else:
        routed = mod.filter_findings(findings, include_medium=False)
    assert len(routed) == 0, (
        "low severity / low confidence non-always-route findings must still be filtered"
    )
