"""tests/test_h12_crossai_runs_consumed.py — H12 stranded CrossAI output."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "test" / "preflight.md"


def test_test_preflight_scans_crossai_runs():
    body = PREFLIGHT.read_text(encoding="utf-8")
    # Test preflight must reference review/runs/ scanning
    assert "review/runs" in body or "crossai/runs" in body or "review-runs" in body, (
        "H12: test/preflight.md must scan .vg/phases/{phase}/review/runs/{tool}/ "
        "(or equivalent path) and surface CrossAI findings to downstream codegen"
    )


def test_codegen_overview_includes_crossai_context():
    overview = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"
    body = overview.read_text(encoding="utf-8")
    # Codegen prompt context must include CrossAI findings when present
    assert ("CROSSAI_FINDINGS" in body or
            "crossai" in body.lower() or
            "review/runs" in body), (
        "H12: codegen/overview.md must include CrossAI runs findings in "
        "subagent prompt context when present (env var or context file)"
    )
