"""v2.86.0 Tier 1 from agent-skills audit — content docs structure tests.

Verifies 4 new reference docs exist with required structure + cross-links.
Inspired by addyosmani/agent-skills lifecycle taxonomy + anti-rationalization
tables pattern.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS = {
    "rationalization_tables": REPO_ROOT / "commands" / "vg" / "_shared" / "rationalization-tables.md",
    "eng_principles":         REPO_ROOT / "commands" / "vg" / "_shared" / "eng-principles.md",
    "discovery_flowchart":    REPO_ROOT / "commands" / "vg" / "_shared" / "discovery-flowchart.md",
    "lifecycle":              REPO_ROOT / "commands" / "vg" / "LIFECYCLE.md",
}

MIRRORS = {
    "rationalization_tables": REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "rationalization-tables.md",
    "eng_principles":         REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "eng-principles.md",
    "discovery_flowchart":    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "discovery-flowchart.md",
    "lifecycle":              REPO_ROOT / ".claude" / "commands" / "vg" / "LIFECYCLE.md",
}


# ── existence ───────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(DOCS.keys()))
def test_canonical_doc_exists(name):
    assert DOCS[name].exists(), f"missing {DOCS[name]}"


@pytest.mark.parametrize("name", list(DOCS.keys()))
def test_mirror_byte_identity(name):
    assert DOCS[name].read_bytes() == MIRRORS[name].read_bytes(), (
        f"{name}: canonical and .claude mirror differ"
    )


# ── frontmatter ─────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(DOCS.keys()))
def test_doc_starts_with_frontmatter(name):
    body = DOCS[name].read_text(encoding="utf-8")
    assert body.startswith("---\n"), f"{name}: must start with YAML frontmatter"
    assert "\n---\n" in body, f"{name}: frontmatter must close"


@pytest.mark.parametrize("name", list(DOCS.keys()))
def test_doc_has_name_and_description(name):
    body = DOCS[name].read_text(encoding="utf-8")
    fm_end = body.index("\n---\n", 4)
    fm = body[:fm_end]
    assert "name:" in fm
    assert "description:" in fm


# ── rationalization-tables specifics ────────────────────────────────


def test_rationalization_tables_has_six_categories():
    body = DOCS["rationalization_tables"].read_text(encoding="utf-8")
    expected = [
        "Test / verification skips",
        "Gate / contract skips",
        "Code change skips",
        "Migration / breaking change skips",
        "Deploy / production skips",
        "Documentation skips",
    ]
    for cat in expected:
        assert cat in body, f"rationalization-tables missing category: {cat}"


def test_rationalization_tables_uses_excuse_reality_columns():
    body = DOCS["rationalization_tables"].read_text(encoding="utf-8")
    # Markdown table header pattern
    assert "| Excuse | Reality |" in body
    # At least 6 separator rows (one per category min)
    assert body.count("|---|---|") >= 6


def test_rationalization_tables_links_to_runtime_guard():
    body = DOCS["rationalization_tables"].read_text(encoding="utf-8")
    assert "_shared/rationalization-guard.md" in body, (
        "static tables must reference the runtime adjudicator"
    )


# ── eng-principles specifics ────────────────────────────────────────


def test_eng_principles_cites_core_concepts():
    body = DOCS["eng_principles"].read_text(encoding="utf-8")
    expected = [
        "Hyrum's Law",
        "Beyonce Rule",
        "Shift Left",
        "Test Pyramid",
        "Trunk-Based Development",
        "Fail-Closed",
        "Provenance Binding",
        "Idempotency",
    ]
    for principle in expected:
        assert principle in body, f"eng-principles missing: {principle}"


def test_eng_principles_links_to_other_docs():
    body = DOCS["eng_principles"].read_text(encoding="utf-8")
    for ref in [
        "rationalization-guard.md",
        "rationalization-tables.md",
        "discovery-flowchart.md",
        "LIFECYCLE.md",
    ]:
        assert ref in body, f"eng-principles missing cross-ref: {ref}"


# ── discovery-flowchart specifics ──────────────────────────────────


def test_discovery_flowchart_has_mermaid_block():
    body = DOCS["discovery_flowchart"].read_text(encoding="utf-8")
    assert "```mermaid" in body, "discovery-flowchart must contain mermaid diagram"
    assert "flowchart" in body or "graph" in body


def test_discovery_flowchart_lists_main_commands():
    body = DOCS["discovery_flowchart"].read_text(encoding="utf-8")
    main_cmds = [
        "/vg:project", "/vg:specs", "/vg:scope", "/vg:blueprint",
        "/vg:build", "/vg:review", "/vg:test", "/vg:accept", "/vg:deploy",
    ]
    for cmd in main_cmds:
        assert cmd in body, f"discovery-flowchart missing: {cmd}"


# ── LIFECYCLE specifics ────────────────────────────────────────────


def test_lifecycle_has_eight_phases():
    body = DOCS["lifecycle"].read_text(encoding="utf-8")
    phases = [
        "0. Init", "1. Define", "2. Scope", "3. Plan",
        "4. Build", "5. Verify", "6. Test", "7. Accept",
    ]
    for p in phases:
        assert p in body, f"LIFECYCLE missing phase: {p}"


def test_lifecycle_documents_phase_contracts():
    body = DOCS["lifecycle"].read_text(encoding="utf-8")
    # Contract table headers
    assert "Required output" in body or "required output" in body.lower()
    assert "Gates next phase reads" in body or "gates next phase" in body.lower()


def test_lifecycle_documents_5_scope_rounds():
    body = DOCS["lifecycle"].read_text(encoding="utf-8")
    for r in ("Domain", "Technical", "API", "UI", "Tests", "Deep probe"):
        assert r in body, f"LIFECYCLE Phase 2 sub-phase missing: {r}"
