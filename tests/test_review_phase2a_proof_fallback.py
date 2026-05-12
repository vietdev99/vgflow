"""tests/test_review_phase2a_proof_fallback.py — Codex deferred Item 3."""
from __future__ import annotations
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOSE_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "close.md"
API_DISCOVERY = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "api-and-discovery.md"
CLOSE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "close.md"
API_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "api-and-discovery.md"


def test_close_emits_contract_runtime_proof_artifact():
    """v4.0.x Item 3: build close must write .contract-runtime-report.json
    after successful contract-runtime validator run, so review phase2a can
    consume it as proof instead of re-probing."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert ".contract-runtime-report.json" in body, (
        "close.md must write proof artifact .contract-runtime-report.json"
    )
    # Must emit evidence-manifest entry pointing to it (for freshness check)
    pattern = re.compile(
        r"emit-evidence-manifest.*?contract-runtime-report\.json",
        re.DOTALL,
    )
    assert pattern.search(body), (
        "close.md must emit evidence-manifest entry for proof artifact"
    )


def test_phase2a_checks_proof_artifact_before_fresh_probe():
    """v4.0.x Item 3: phase2a step must check .contract-runtime-report.json
    BEFORE invoking review-api-contract-probe.py. Fresh proof → skip probe."""
    body = API_DISCOVERY.read_text(encoding="utf-8")
    assert ".contract-runtime-report.json" in body, (
        "phase2a must reference .contract-runtime-report.json proof artifact"
    )
    # Look for fallback pattern: if proof exists → reuse, else fresh probe
    pattern = re.compile(
        r"contract-runtime-report\.json.{0,300}(?:exists|is_file|fresh|reuse|skip|fall.?back)",
        re.DOTALL | re.IGNORECASE,
    )
    assert pattern.search(body), (
        "phase2a must implement proof-artifact fallback (consume if fresh)"
    )


def test_phase2a_freshness_via_evidence_manifest():
    """Freshness check must use evidence-manifest (not just file mtime)
    to verify proof was created by current run, not stale from earlier."""
    body = API_DISCOVERY.read_text(encoding="utf-8")
    pattern = re.compile(
        r"contract-runtime-report\.json.{0,500}(?:verify-artifact-freshness|evidence-manifest|creator_run_id|current-run)",
        re.DOTALL,
    )
    assert pattern.search(body), (
        "freshness check must use evidence-manifest infrastructure, not just file existence"
    )


def test_mirrors_byte_identical():
    assert CLOSE_MD.read_bytes() == CLOSE_MIRROR.read_bytes()
    assert API_DISCOVERY.read_bytes() == API_MIRROR.read_bytes()
