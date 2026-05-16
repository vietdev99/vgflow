"""tests/test_batch62_feature_chain.py — B62 top-down feature_chain.

Top-down enforcement of feature_chain goal class:
  - TEST-GOAL-enriched-template.md extends goal_class enum
  - contracts-delegation.md prompt instructs AI to emit closed-loop goals
  - close.md wires verify-feature-chain-coverage.py gate
  - Validator enforces audit ID-3 anti-cheat: chain_steps ≥ 8, distinct
    expected_state, ≥1 step out-of-source-view-family, ≥2 steps with
    downstream_effects
  - feature_chain stages dispatch via B62-pre (goal_class precedence)

Coverage:
  1. Template enum contains feature_chain + post_create_cascade alias
  2. Template documents new frontmatter fields (enables, chain_*_state,
     chain_steps, target_view_class)
  3. min_steps[feature_chain] = 8 documented
  4. contracts-delegation prompt has closed-loop instruction
  5. close.md wires verify-feature-chain-coverage.py with 3-tier fallback
  6. close.md uses ORCH_BIN 3-tier for emit-event
  7. Validator PASS on resource with valid feature_chain goal
  8. Validator FAIL strict on CRUD resource without chain
  9. Validator FAIL strict on chain_steps < 8 (audit ID-3)
  10. Validator FAIL strict when chain stays in source view family
  11. Validator FAIL strict on <2 steps with downstream_effects
  12. Validator PASS with feature_chain_waiver in CONTEXT.md
  13. Validator PASS with --allow-feature-chain-shortfall flag
  14. OUT-OF-SCOPE.md documents deferred items
  15. Mirror parity
"""
from __future__ import annotations
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "commands" / "vg" / "_shared" / "templates" / "TEST-GOAL-enriched-template.md"
TEMPLATE_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "templates" / "TEST-GOAL-enriched-template.md"
DELEGATION = REPO / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md"
DELEGATION_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md"
CLOSE = REPO / "commands" / "vg" / "_shared" / "blueprint" / "close.md"
CLOSE_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "close.md"
VAL = REPO / "scripts" / "validators" / "verify-feature-chain-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-feature-chain-coverage.py"
OUT_OF_SCOPE = REPO / "dev-phases" / "feature-chain-design" / "OUT-OF-SCOPE.md"


def _valid_chain_block() -> str:
    """8-step valid chain content used in tests."""
    return """
## Goal G-01: Site lifecycle
goal_class: feature_chain
chain_steps:
  - step_id: S1
    target_view_class: source_view
    expected_state: list_loaded
    downstream_effects: []
  - step_id: S2
    target_view_class: source_view_modal
    expected_state: form_visible
    downstream_effects: []
  - step_id: S3
    target_view_class: source_view_modal
    expected_state: submit_ok
    downstream_effects:
      - row_count +1
  - step_id: S4
    target_view_class: dashboard_summary
    expected_state: visible_dash
    downstream_effects:
      - counter +1
  - step_id: S5
    target_view_class: sibling_list
    expected_state: detail_loaded
    downstream_effects: []
  - step_id: S6
    target_view_class: source_view
    expected_state: edit_saved
    downstream_effects: []
  - step_id: S7
    target_view_class: source_view_modal
    expected_state: deleted
    downstream_effects: []
  - step_id: S8
    target_view_class: audit_log
    expected_state: archived
    downstream_effects:
      - archive +1
"""


def _crud_surfaces() -> str:
    return """## site
```json
{"method": "POST", "path": "/api/sites"}
```
"""


def _run_validator(pd: Path, *extra: str):
    return subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_template_enum_contains_feature_chain():
    body = TEMPLATE.read_text(encoding="utf-8")
    assert "feature_chain" in body
    assert "post_create_cascade" in body


def test_template_documents_new_frontmatter():
    body = TEMPLATE.read_text(encoding="utf-8")
    assert "chain_steps" in body
    assert "chain_consumes_state" in body
    assert "chain_produces_state" in body
    assert "target_view_class" in body
    assert "downstream_effects" in body
    assert "enables:" in body


def test_template_documents_min_steps_8():
    body = TEMPLATE.read_text(encoding="utf-8")
    # docs feature_chain min_steps threshold
    assert "feature_chain:" in body
    # ≥8 mentioned per the new docs block
    assert "≥8" in body or "≥ 8" in body or "MIN 8" in body or "min 8" in body.lower()


def test_delegation_prompt_has_closed_loop_instruction():
    body = DELEGATION.read_text(encoding="utf-8")
    body_lower = body.lower()
    assert "B62" in body
    assert "feature_chain" in body
    assert "closed-loop" in body_lower or "closed loop" in body_lower
    assert "rename" in body_lower


def test_close_md_wires_validator_3tier():
    body = CLOSE.read_text(encoding="utf-8")
    assert "verify-feature-chain-coverage.py" in body
    # 3-tier fallback present
    assert "VG_SCRIPT_ROOT" in body
    assert "VG_HOME" in body
    assert "blueprint.feature_chain_blocked" in body


def test_close_md_uses_orch_bin_3tier():
    body = CLOSE.read_text(encoding="utf-8")
    # ORCH_BIN var with 3-tier
    assert 'ORCH_BIN=' in body
    assert "feature_chain_blocked" in body


def test_validator_passes_on_valid_chain(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    (pd / "TEST-GOALS.md").write_text(_valid_chain_block(), encoding="utf-8")
    r = _run_validator(pd, "--strict")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_validator_fails_strict_when_no_chain(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    (pd / "TEST-GOALS.md").write_text(
        "## Goal G-01: Create site\ngoal_class: mutation\n", encoding="utf-8"
    )
    r = _run_validator(pd, "--strict")
    assert r.returncode != 0
    assert "UNCOVERED" in (r.stderr + r.stdout)


def test_validator_fails_strict_when_chain_too_short(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    # Only 4 steps
    short_chain = """
## Goal G-01: Short chain
goal_class: feature_chain
chain_steps:
  - step_id: S1
    target_view_class: source_view
    expected_state: a
    downstream_effects: []
  - step_id: S2
    target_view_class: source_view_modal
    expected_state: b
    downstream_effects: []
  - step_id: S3
    target_view_class: dashboard_summary
    expected_state: c
    downstream_effects:
      - effect1
  - step_id: S4
    target_view_class: source_view
    expected_state: d
    downstream_effects:
      - effect2
"""
    (pd / "TEST-GOALS.md").write_text(short_chain, encoding="utf-8")
    r = _run_validator(pd, "--strict")
    assert r.returncode != 0
    assert "chain_steps len 4 < 8" in (r.stderr + r.stdout)


def test_validator_fails_strict_when_chain_stays_in_source_family(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    # 8 steps but all in source family
    in_source_chain = """
## Goal G-01: All source family
goal_class: feature_chain
chain_steps:
  - step_id: S1
    target_view_class: source_view
    expected_state: a
    downstream_effects:
      - x
  - step_id: S2
    target_view_class: source_view_modal
    expected_state: b
    downstream_effects:
      - y
  - step_id: S3
    target_view_class: source_view_form
    expected_state: c
    downstream_effects: []
  - step_id: S4
    target_view_class: source_view
    expected_state: d
    downstream_effects: []
  - step_id: S5
    target_view_class: source_view_modal
    expected_state: e
    downstream_effects: []
  - step_id: S6
    target_view_class: source_view
    expected_state: f
    downstream_effects: []
  - step_id: S7
    target_view_class: source_view_modal
    expected_state: g
    downstream_effects: []
  - step_id: S8
    target_view_class: source_view
    expected_state: h
    downstream_effects: []
"""
    (pd / "TEST-GOALS.md").write_text(in_source_chain, encoding="utf-8")
    r = _run_validator(pd, "--strict")
    assert r.returncode != 0
    assert "stays in source view family" in (r.stderr + r.stdout)


def test_validator_fails_strict_when_insufficient_downstream_effects(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    # 8 steps, traverses out, but only 1 step with downstream_effects
    no_effects = """
## Goal G-01: Insufficient effects
goal_class: feature_chain
chain_steps:
  - step_id: S1
    target_view_class: source_view
    expected_state: a
    downstream_effects: []
  - step_id: S2
    target_view_class: source_view_modal
    expected_state: b
    downstream_effects: []
  - step_id: S3
    target_view_class: dashboard_summary
    expected_state: c
    downstream_effects:
      - effect1
  - step_id: S4
    target_view_class: sibling_list
    expected_state: d
    downstream_effects: []
  - step_id: S5
    target_view_class: source_view
    expected_state: e
    downstream_effects: []
  - step_id: S6
    target_view_class: source_view_modal
    expected_state: f
    downstream_effects: []
  - step_id: S7
    target_view_class: source_view
    expected_state: g
    downstream_effects: []
  - step_id: S8
    target_view_class: audit_log
    expected_state: h
    downstream_effects: []
"""
    (pd / "TEST-GOALS.md").write_text(no_effects, encoding="utf-8")
    r = _run_validator(pd, "--strict")
    assert r.returncode != 0
    assert "downstream_effects" in (r.stderr + r.stdout)


def test_validator_passes_with_resource_waiver(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    (pd / "TEST-GOALS.md").write_text(
        "## Goal G-01: Site mutation\ngoal_class: mutation\n", encoding="utf-8"
    )
    (pd / "CONTEXT.md").write_text(
        "feature_chain_waiver[site]: internal admin only, no cross-view effect\n",
        encoding="utf-8",
    )
    r = _run_validator(pd, "--strict")
    assert r.returncode == 0


def test_validator_passes_with_allow_shortfall_flag(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(_crud_surfaces(), encoding="utf-8")
    (pd / "TEST-GOALS.md").write_text(
        "## Goal G-01: Site mutation\ngoal_class: mutation\n", encoding="utf-8"
    )
    r = _run_validator(pd, "--strict", "--allow-feature-chain-shortfall")
    assert r.returncode == 0


def test_out_of_scope_doc_exists():
    assert OUT_OF_SCOPE.is_file()
    body = OUT_OF_SCOPE.read_text(encoding="utf-8")
    assert "Multi-tenant" in body
    assert "Async" in body or "async" in body
    assert "ID-7" in body


def test_mirrors_in_sync():
    assert TEMPLATE.read_text(encoding="utf-8") == TEMPLATE_MIRROR.read_text(encoding="utf-8")
    assert DELEGATION.read_text(encoding="utf-8") == DELEGATION_MIRROR.read_text(encoding="utf-8")
    assert CLOSE.read_text(encoding="utf-8") == CLOSE_MIRROR.read_text(encoding="utf-8")
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
