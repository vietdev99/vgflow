"""tests/test_batch43_accessibility_scan.py — Batch 43.

Read-only spec accessibility stage (Batch 36 R2) prose-only. No scanner
evidence → spec body uses generic axe-core boilerplate.

Fix: scanner runs axe-core via browser_evaluate, emits
accessibility_findings[] with rule + selector + severity.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "vg-haiku-scanner" / "SKILL.md"
SKILL_MIRROR = REPO / ".claude" / "skills" / "vg-haiku-scanner" / "SKILL.md"
ENRICH = REPO / "scripts" / "enrich-test-goals.py"


def test_schema_declares_accessibility_findings():
    body = SKILL.read_text(encoding="utf-8")
    schema_idx = body.find('"view": "{VIEW_URL}"')
    block = body[schema_idx:schema_idx + 8000]
    assert '"accessibility_findings"' in block, (
        "Batch 43: schema must declare accessibility_findings[]"
    )
    for key in ('"rule"', '"selector"', '"severity"'):
        assert key in block, f"Batch 43: a11y entry missing {key}"


def test_workflow_runs_axe_core():
    body = SKILL.read_text(encoding="utf-8")
    assert "axe-core" in body or "axe.run" in body or "Batch 43" in body, (
        "Batch 43: workflow must invoke axe-core via browser_evaluate"
    )


def test_enrich_emits_a11y_stub():
    body = ENRICH.read_text(encoding="utf-8")
    assert "accessibility_findings" in body or "a11y" in body, (
        "Batch 43: enrich-test-goals must consume scan.accessibility_findings[]"
    )


def test_mirror_in_sync():
    assert SKILL.read_text(encoding="utf-8") == SKILL_MIRROR.read_text(encoding="utf-8")
