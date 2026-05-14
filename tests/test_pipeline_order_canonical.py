"""tests/test_pipeline_order_canonical.py — guard against pipeline order drift.

Canonical v4.0: specs → scope → blueprint → build → review → test-spec → test → accept
"""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

# Files exempt from canonical check (intentional drift — e.g. skip-review prose)
EXEMPT_LINES = [
    # phase.md:218 — "Bỏ qua /vg:review" prose (skip-review option, not canonical claim)
]


def test_no_4step_skip_test_spec():
    """No file in commands/vg/ should claim pipeline 'build → review → test → accept'
    (4-step missing test-spec). Use 5-step v4.0 canonical."""
    bad = re.compile(r"build\s*[→>-]+\s*review\s*[→>-]+\s*test\s*[→>-]+\s*accept(?!\s*[-→]+\s*test-spec)")
    misses = []
    for p in (REPO / "commands" / "vg").rglob("*.md"):
        try:
            body = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(body.splitlines(), 1):
            if bad.search(line) and "test-spec" not in line:
                # Exempt skip-review prose
                if "Bỏ qua /vg:review" in line or "skip-review" in line.lower():
                    continue
                misses.append(f"{p.relative_to(REPO)}:{ln}: {line.strip()[:120]}")
    assert not misses, (
        "Pipeline drift: old 4-step references must include test-spec:\n  " +
        "\n  ".join(misses)
    )


def test_no_wrong_order_test_spec_before_review():
    """No file should claim 'test-spec → review' or 'test-spec **→ review**' — that's
    v3.x backwards. v4.0 is 'review → test-spec'."""
    bad = re.compile(r"test-spec\s*[→>-]+\s*(?:\*\*)?review")
    misses = []
    for p in (REPO / "commands" / "vg").rglob("*.md"):
        try:
            body = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(body.splitlines(), 1):
            if bad.search(line):
                # Exempt scope-review or doc-history comments
                if "scope-review" in line or "v3.x" in line or "legacy" in line.lower():
                    continue
                # Exempt filename/label/glob patterns like "test-spec-review.md",
                # LABEL="test-spec-review", result-*test-spec-review*.xml
                # These are CrossAI artifact names, not pipeline order claims
                if re.search(r"test-spec-review[.\"\*]", line) or '"test-spec-review"' in line:
                    continue
                misses.append(f"{p.relative_to(REPO)}:{ln}: {line.strip()[:120]}")
    assert not misses, (
        "Pipeline drift: 'test-spec → review' is v3.x backwards order. "
        "v4.0 canonical is 'review → test-spec':\n  " + "\n  ".join(misses)
    )


def test_phase_recon_canonical():
    """phase-recon.py PIPELINE_STEPS must have review before test-spec."""
    body = (REPO / ".claude/scripts/phase-recon.py").read_text(encoding="utf-8")
    m = re.search(r"PIPELINE_STEPS\s*=\s*\[([^\]]+)\]", body)
    assert m
    steps = m.group(1)
    review_pos = steps.find('"review"')
    ts_pos = steps.find('"test-spec"')
    assert 0 < review_pos < ts_pos, (
        f"phase-recon.py PIPELINE_STEPS must have review BEFORE test-spec. "
        f"Got: {steps}"
    )
