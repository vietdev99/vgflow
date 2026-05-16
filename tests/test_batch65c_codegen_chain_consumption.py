"""tests/test_batch65c_codegen_chain_consumption.py — B65c (codex BLOCKERs #1 + #4).

Codex audit (dev-phases/test-flow-hardening/CODEX-AUDIT.md):

BLOCKER #1: chain_steps belongs to TEST-GOAL frontmatter, NOT VARIANTS.json.
  Original B65 plan stuffed chain metadata into wrong schema source.

BLOCKER #4: "one test() per chain_step" proposed in original plan breaks
  the existing seed/variant contract from Batch 52. Correct shape:
    test.each(variants) OUTER + test.step() INNER per chain_step.

Fix: extend codegen delegation.md with <feature_chain_emission> section
documenting correct shape + per-step assertion contract + cross_view
hookup to B63 scan data.

Coverage:
  1. delegation.md inputs include LIFECYCLE-SPECS.json
  2. delegation.md inputs include scan-*.json (B63 cross_view)
  3. feature_chain_emission section present
  4. Section cites TEST-GOAL frontmatter as chain_steps source (NOT
     VARIANTS.json — codex BLOCKER #1 fix)
  5. Section mandates test.each(variants) OUTER + test.step() INNER
     shape (codex BLOCKER #4 fix)
  6. Section explicitly forbids "test() per chain_step" alternative
  7. Per-step assertion contract documented (target_view, expected_state,
     downstream_effects)
  8. Cross-view propagation hookup to scan data documented
  9. Chain_steps source priority (LIFECYCLE-SPECS > frontmatter > fallback)
  10. Sample emission has runSeedRecipe + cleanup wrap (Batch 52 contract
      preserved)
  11. Mirror parity (.claude/)
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DELEGATION = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
DELEGATION_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_inputs_include_lifecycle_specs():
    body = _read(DELEGATION)
    # B65a artifact wired into codegen inputs
    assert "@${PHASE_DIR}/LIFECYCLE-SPECS.json" in body
    assert "B65a" in body


def test_inputs_include_scan_files():
    body = _read(DELEGATION)
    # B63 cross_view data wired into codegen inputs
    assert "@${PHASE_DIR}/scan-*.json" in body
    assert "B63" in body
    assert "cross_view_propagation_observations" in body


def test_feature_chain_emission_section_present():
    body = _read(DELEGATION)
    assert "<feature_chain_emission>" in body
    assert "</feature_chain_emission>" in body


def test_chain_steps_source_is_test_goal_frontmatter():
    """Codex BLOCKER #1: chain_steps lives in TEST-GOAL frontmatter,
    NOT VARIANTS.json. delegation.md must say this explicitly."""
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    assert section_start > 0 < section_end
    section = body[section_start:section_end]
    # Must reference TEST-GOAL template frontmatter
    assert "TEST-GOAL-enriched-template.md" in section
    assert "frontmatter" in section.lower()
    # Must explicitly NOT use VARIANTS.json for chain_steps
    assert "NOT VARIANTS.json" in section or "not VARIANTS.json" in section


def test_test_each_outer_test_step_inner_shape():
    """Codex BLOCKER #4: correct shape is test.each(variants) OUTER +
    test.step() INNER per chain step."""
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    assert "test.each(variants)" in section
    assert "test.step(" in section
    assert "OUTER" in section
    assert "INNER" in section


def test_forbids_test_per_chain_step():
    """Validator anti-pattern: must not emit one test() per chain_step."""
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    # Should mention rejection of "one test() per chain_step" pattern
    assert "NOT one test() per chain_step" in section or "not one test() per chain_step" in section.lower()


def test_per_step_assertion_contract_documented():
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    # Must reference all 3 per-step assertion types
    assert "target_view" in section.lower()
    assert "expected_state" in section.lower()
    assert "downstream_effects" in section.lower()
    # Must mandate ≥1 expect() per assertion type
    assert "expect()" in section or "expect(" in section


def test_cross_view_b63_hookup_documented():
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    # B63 cross-view hookup
    assert "cross-view" in section.lower() or "Cross-view" in section
    assert "B63" in section
    assert "entity_id" in section or "entity_canonical_id" in section


def test_chain_steps_source_priority():
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    # Priority order: LIFECYCLE-SPECS > frontmatter > fallback
    assert "source priority" in section.lower() or "LIFECYCLE-SPECS.json" in section
    assert "frontmatter" in section.lower()
    assert "fallback" in section.lower() or "absent" in section.lower()


def test_sample_emission_preserves_seed_contract():
    """Batch 52 contract: every test.each variant wrapped in
    runSeedRecipe / cleanup. B65c section MUST keep this."""
    body = _read(DELEGATION)
    section_start = body.find("<feature_chain_emission>")
    section_end = body.find("</feature_chain_emission>")
    section = body[section_start:section_end]
    assert "runSeedRecipe" in section
    assert "cleanup" in section
    assert "afterEach" in section.lower() or "finally" in section.lower()


def test_mirror_in_sync():
    assert _read(DELEGATION) == _read(DELEGATION_MIRROR)
