"""v2.67.0 #158 — Lens artifacts must_write strict + Codex telemetry parity.

Three checks:
1. LENS-DISPATCH-PLAN.json must_write entry has stricter content guards
   (content_min_bytes ≥ 500 + content_required_sections present), so a
   stub artifact (200 bytes, no sections) cannot satisfy the gate.
2. LENS-COVERAGE-MATRIX.md must_write entry similarly tightened
   (content_min_bytes ≥ 300 + content_required_sections present).
3. codex-skills/vg-review/SKILL.md emits lens marker(s) per v2.65.0 A9
   pattern — `mark-step review <2b3_lens_*>` so Codex hits the same
   marker telemetry as Claude (which gets it via PostToolUse hook).
"""
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"
CODEX_SKILL = REPO_ROOT / "codex-skills" / "vg-review" / "SKILL.md"


def _extract_must_write_entry(body: str, artifact_name: str) -> str:
    """Pull the YAML stanza that follows `path: "${PHASE_DIR}/<artifact_name>"`
    until the next `- path:` / `must_*:` / top-level key boundary.
    """
    pattern = re.compile(
        r'-\s+path:\s+"\$\{PHASE_DIR\}/' + re.escape(artifact_name) + r'"'
        r'(?P<body>.*?)(?=\n\s*-\s+path:|\n\s{2,4}must_[a-z_]+:|\nargument_schema|\nphases:|\Z)',
        re.DOTALL,
    )
    m = pattern.search(body)
    assert m, f"must_write entry for {artifact_name} not found"
    return m.group("body")


def test_lens_dispatch_plan_strict_guards():
    """LENS-DISPATCH-PLAN.json must enforce content_min_bytes ≥ 500
    AND declare content_required_sections so a stub plan can't slip past."""
    body = REVIEW_MD.read_text(encoding="utf-8")
    block = _extract_must_write_entry(body, "LENS-DISPATCH-PLAN.json")

    m = re.search(r"content_min_bytes:\s*(\d+)", block)
    assert m, "LENS-DISPATCH-PLAN.json missing content_min_bytes"
    bytes_n = int(m.group(1))
    assert bytes_n >= 500, (
        f"LENS-DISPATCH-PLAN.json content_min_bytes={bytes_n} too low; "
        "must be ≥500 to reject stub plans (v2.67.0 #158)"
    )

    assert "content_required_sections:" in block, (
        "LENS-DISPATCH-PLAN.json missing content_required_sections — "
        "structural enforcement required (v2.67.0 #158)"
    )


def test_lens_coverage_matrix_strict_guards():
    """LENS-COVERAGE-MATRIX.md must enforce content_min_bytes ≥ 300
    AND declare content_required_sections."""
    body = REVIEW_MD.read_text(encoding="utf-8")
    block = _extract_must_write_entry(body, "LENS-COVERAGE-MATRIX.md")

    m = re.search(r"content_min_bytes:\s*(\d+)", block)
    assert m, "LENS-COVERAGE-MATRIX.md missing content_min_bytes"
    bytes_n = int(m.group(1))
    assert bytes_n >= 300, (
        f"LENS-COVERAGE-MATRIX.md content_min_bytes={bytes_n} too low; "
        "must be ≥300 to reject empty matrix (v2.67.0 #158)"
    )

    assert "content_required_sections:" in block, (
        "LENS-COVERAGE-MATRIX.md missing content_required_sections — "
        "structural enforcement required (v2.67.0 #158)"
    )


def test_codex_review_emits_lens_marker():
    """codex-skills/vg-review/SKILL.md must emit lens-related mark-step
    calls so Codex hits the same marker telemetry Claude gets via hook
    (v2.65.0 A9 pattern, applied to lens dispatch + matrix render)."""
    body = CODEX_SKILL.read_text(encoding="utf-8")

    # Pattern: "mark-step review <something>lens<something>" or vice-versa.
    # Match either "vg-orchestrator mark-step review <marker_with_lens>" or
    # the generic "<marker_with_lens>" appearing anywhere as a marker arg.
    matches = re.findall(
        r"mark-step\s+review\s+\S*lens\S*|\S*lens\S*\s*\".*mark-step",
        body,
        re.IGNORECASE,
    )
    assert matches, (
        "codex-skills/vg-review/SKILL.md must emit at least one "
        "`vg-orchestrator mark-step review <lens-related-marker>` so "
        "Codex matches Claude PostToolUse hook telemetry parity "
        "(v2.67.0 #158, v2.65.0 A9 pattern)"
    )
