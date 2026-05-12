"""tests/test_review_preflight_fe_be_advisory.py — Codex deferred Item 2."""
from __future__ import annotations
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "preflight.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "preflight.md"


def test_preflight_invokes_fe_be_call_graph_advisory():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "verify-fe-be-call-graph.py" in body, (
        "review preflight must invoke verify-fe-be-call-graph.py as advisory probe"
    )
    # Must be advisory — NOT exit 1 on rc
    pattern = re.compile(r"verify-fe-be-call-graph\.py.*?(?:\|\| true|--severity warn|advisory|no-exit-on-fail)", re.DOTALL)
    assert pattern.search(body), (
        "must be advisory — false positives on dynamic routes / generated clients"
    )


def test_preflight_documents_advisory_rationale():
    body = PREFLIGHT.read_text(encoding="utf-8")
    pattern = re.compile(r"verify-fe-be-call-graph.{0,400}(?:dynamic|false positive|advisory|discovery-only|warn)", re.DOTALL | re.IGNORECASE)
    assert pattern.search(body), (
        "comment must explain advisory rationale: dynamic routes / framework prefix / discovery-only fit"
    )


def test_preflight_emits_telemetry_event():
    body = PREFLIGHT.read_text(encoding="utf-8")
    assert "review.fe_be_drift_warn" in body or "fe_be_call_graph" in body, (
        "must emit review.fe_be_drift_warn (or similar) event on drift hit"
    )


def test_mirror_byte_identical():
    assert PREFLIGHT.read_bytes() == MIRROR.read_bytes()
