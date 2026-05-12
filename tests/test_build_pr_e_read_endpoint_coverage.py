"""tests/test_build_pr_e_read_endpoint_coverage.py — Codex deferred Item 4."""
from __future__ import annotations
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOSE_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "close.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "close.md"


def test_pr_e_extends_to_read_endpoints():
    """v4.0.x Item 4: PR-E must light-probe READ endpoints (GET), not just
    mutation goals with FIXTURES. Closes coverage gap where GET endpoints
    declared in API-CONTRACTS but not mapped to a goal slip through to
    review step 5b runtime fail."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    # Must mention read / GET endpoint light-probe path
    pattern = re.compile(
        r"PR-E.{0,2000}(?:read endpoint|GET endpoint|light.probe|non-mutation|read-only)",
        re.DOTALL | re.IGNORECASE,
    )
    assert pattern.search(body), (
        "PR-E must extend coverage to read/GET endpoints with light probe"
    )


def test_pr_e_light_probe_per_endpoint_invariant():
    """Light probe: single curl -i per declared endpoint, no D18 coverage,
    no idempotency replay. Just 'does endpoint exist + respond reasonably'."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?:light.probe|read.endpoint.probe).{0,800}(?:curl|requests\.get|http_probe|404)",
        re.DOTALL | re.IGNORECASE,
    )
    assert pattern.search(body), (
        "light probe must invoke curl/requests against each declared endpoint"
    )


def test_pr_e_emits_extended_coverage_event():
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "build.pr_e_read_probe_completed" in body or "pr_e_read_probe" in body or "read_endpoint_coverage" in body, (
        "PR-E extension must emit telemetry for read endpoint coverage"
    )


def test_pr_e_read_probe_advisory_not_block():
    """Read probe is ADVISORY — light coverage shouldn't block on 4xx/5xx
    (could be auth-required endpoint). 404 is the SIGNAL for phantom endpoint."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?:light.probe|read.probe).{0,1000}(?:404|missing|advisory|\|\| true|warn)",
        re.DOTALL | re.IGNORECASE,
    )
    assert pattern.search(body), (
        "light probe must specifically check for 404 (phantom signal), not block on 4xx/5xx generally"
    )


def test_mirror_byte_identical():
    assert CLOSE_MD.read_bytes() == MIRROR.read_bytes()
