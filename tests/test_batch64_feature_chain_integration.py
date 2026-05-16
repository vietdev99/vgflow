"""tests/test_batch64_feature_chain_integration.py — B64 end-to-end smoke.

Synthetic phase fixture exercising entire B62-pre + B62 + B63 chain.
Catches inter-layer drift: schema field rename, prompt-vs-validator
mismatch, scanner-to-enrich data shape regression, view-rename-stability.

Pipeline tested:
  1. Build synthetic LIFECYCLE-SPECS with goal_class=feature_chain
  2. Verify generate-lifecycle-specs emits FEATURE_CHAIN_STAGES
     (B62-pre dispatch)
  3. Synthetic scan-*.json with cross_view_propagation_observations
  4. enrich-test-goals consumes scan → emits feature_chain G-AUTO goals
     with chain_steps + stable goal-id (B63)
  5. Symmetry validator passes on healthy enables[]/Dependencies[]
     (B62-pre ID-2)
  6. Feature-chain coverage validator passes on full chain (B62 ID-3)
  7. Cross-view coverage validator passes (B63)
  8. seed-chain-status layer 8 reports both validators
  9. Real-prompt fixture: contracts-delegation.md AI instruction
     present (smoke against actual prompt — closes audit ID-8 gap)
  10. Goal-id stability across view rename (audit ID-6 regression test)
"""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
VALIDATORS = SCRIPTS / "validators"

LIFECYCLE = SCRIPTS / "generate-lifecycle-specs.py"
ENRICH = SCRIPTS / "enrich-test-goals.py"
STATUS = SCRIPTS / "seed-chain-status.py"

VAL_FEATURE_CHAIN = VALIDATORS / "verify-feature-chain-coverage.py"
VAL_CROSS_VIEW = VALIDATORS / "verify-cross-view-coverage.py"
VAL_SYMMETRY = VALIDATORS / "verify-enables-deps-symmetry.py"

DELEGATION = REPO / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _build_synthetic_phase(tmp_path: Path) -> Path:
    """Create phase fixture with CRUD-SURFACES + scans + initial TEST-GOALS."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)

    # CRUD resources
    (pd / "CRUD-SURFACES.md").write_text(
        '## site\n```json\n{"method": "POST", "path": "/api/sites"}\n```\n\n'
        '## order\n```json\n{"method": "POST", "path": "/api/orders"}\n```\n',
        encoding="utf-8",
    )

    # Scan with cross-view propagation for site CREATE
    (pd / "scan-sites.json").write_text(json.dumps({
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_id": "site-001",
                "entity_canonical_id": "site:create",
                "observed_in_target": "yes",
                "observed_count_delta": 1,
            },
            {
                "source_view": "/sites",
                "target_view": "/audit",
                "target_view_class": "audit_log",
                "action": "delete",
                "entity_canonical_id": "site:delete",
                "observed_in_target": "partial",
            },
        ],
    }), encoding="utf-8")
    # scan-orders.json with CREATE
    (pd / "scan-orders.json").write_text(json.dumps({
        "view": "/orders",
        "cross_view_propagation_observations": [
            {
                "source_view": "/orders",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_canonical_id": "order:create",
                "observed_in_target": "yes",
            },
        ],
    }), encoding="utf-8")

    # Full valid feature_chain goal for site (covers B62 validator)
    chain_block = """## Goal G-01: Site lifecycle
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

## Goal G-02: Order lifecycle
goal_class: feature_chain
chain_steps:
  - step_id: S1
    target_view_class: source_view
    expected_state: list_loaded
    downstream_effects: []
  - step_id: S2
    target_view_class: source_view_modal
    expected_state: form_open
    downstream_effects: []
  - step_id: S3
    target_view_class: source_view_modal
    expected_state: order_submitted
    downstream_effects:
      - order in queue
  - step_id: S4
    target_view_class: dashboard_summary
    expected_state: count_increment
    downstream_effects:
      - counter +1
  - step_id: S5
    target_view_class: sibling_list
    expected_state: detail_loaded
    downstream_effects: []
  - step_id: S6
    target_view_class: source_view
    expected_state: payment_recorded
    downstream_effects: []
  - step_id: S7
    target_view_class: source_view_modal
    expected_state: cancelled
    downstream_effects: []
  - step_id: S8
    target_view_class: audit_log
    expected_state: archived
    downstream_effects:
      - audit_log +1
"""
    (pd / "TEST-GOALS.md").write_text(chain_block, encoding="utf-8")
    return pd


def _run(script: Path, *args: str):
    cmd = ["python", str(script), *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def test_lifecycle_stages_for_feature_chain():
    """B62-pre dispatch — goal_class=feature_chain → FEATURE_CHAIN_STAGES."""
    mod = _load_module(LIFECYCLE, "gls_b64")
    stages = mod._stages_for_goal({"goal_class": "feature_chain"})
    assert "visibility_check" in stages
    assert "interaction_chain" in stages
    assert "cascade_check" in stages
    assert "archive_visibility_check" in stages


def test_enrich_emits_chain_goals_from_scan(tmp_path):
    """Scan with cross_view obs → enrich emits feature_chain G-AUTO goals."""
    mod = _load_module(ENRICH, "enrich_b64")
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [{
            "source_view": "/sites",
            "target_view": "/dashboard",
            "target_view_class": "dashboard_summary",
            "action": "create",
            "entity_canonical_id": "site:create",
            "observed_in_target": "yes",
        }],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    chain_goals = [s for s in stubs if s.get("goal_class") == "feature_chain"]
    assert chain_goals
    g = chain_goals[0]
    assert "visibility" in g["id"]
    assert len(g["chain_steps"]) >= 4
    assert all("target_view_class" in s for s in g["chain_steps"])


def test_symmetry_validator_clean_chain_passes(tmp_path):
    """B62-pre symmetry: clean chain with no enables[] passes."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01\n- **Dependencies:** []\n\n"
        "## G-02\n- **Dependencies:** [G-01]\n",
        encoding="utf-8",
    )
    r = _run(VAL_SYMMETRY, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode == 0


def test_feature_chain_coverage_passes_full_chain(tmp_path):
    """B62 validator passes on synthetic phase with full feature_chain goals."""
    pd = _build_synthetic_phase(tmp_path)
    r = _run(VAL_FEATURE_CHAIN, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_cross_view_coverage_passes_with_observations(tmp_path):
    """B63 validator passes when scan provides cross_view observations."""
    pd = _build_synthetic_phase(tmp_path)
    r = _run(VAL_CROSS_VIEW, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_seed_chain_status_reports_layer_8(tmp_path):
    """B63 added layer 8. Status report should run feature_chain + cross_view checks."""
    pd = _build_synthetic_phase(tmp_path)
    r = _run(STATUS, "--phase", "7", "--phase-dir", str(pd))
    assert r.returncode == 0
    assert "8. feature_chain coverage" in r.stdout


def test_real_prompt_has_b62_instructions():
    """Audit ID-8 mitigation: assert contracts-delegation.md has feature_chain
    instruction in the actual file AI will read. Closes synthetic-vs-real-AI gap."""
    body = DELEGATION.read_text(encoding="utf-8")
    body_lower = body.lower()
    # Hard assertion on actual prompt surface AI sees
    assert "feature_chain" in body
    assert "closed-loop" in body_lower or "closed loop" in body_lower
    assert "B62" in body
    assert "chain_steps" in body
    # Anti-cheat: prompt must mention NOT renaming
    assert "rename" in body_lower
    # Must mention CRUD-creating
    assert "crud" in body_lower or "POST" in body


def test_goal_id_stable_across_view_rename(tmp_path):
    """Audit ID-6: rename /sites → /properties keeps same goal-id when
    entity_canonical_id stable."""
    mod = _load_module(ENRICH, "enrich_b64_rename")
    base_obs = {
        "target_view": "/dashboard",
        "target_view_class": "dashboard_summary",
        "action": "create",
        "entity_canonical_id": "site:create",
        "observed_in_target": "yes",
    }
    scan_sites = {"view": "/sites",
                  "cross_view_propagation_observations": [
                      {**base_obs, "source_view": "/sites"}
                  ]}
    scan_renamed = {"view": "/properties",
                    "cross_view_propagation_observations": [
                        {**base_obs, "source_view": "/properties"}
                    ]}
    stubs1 = mod.classify_elements("/sites", scan_sites, {}, [])
    stubs2 = mod.classify_elements("/properties", scan_renamed, {}, [])
    ids1 = {s["id"] for s in stubs1 if s.get("goal_class") == "feature_chain"}
    ids2 = {s["id"] for s in stubs2 if s.get("goal_class") == "feature_chain"}
    assert ids1 == ids2, f"goal-id drift after view rename: {ids1} vs {ids2}"


def test_end_to_end_synthetic_phase(tmp_path):
    """B64 end-to-end: build phase → run ALL validators → assert green."""
    pd = _build_synthetic_phase(tmp_path)
    # B62-pre symmetry
    r1 = _run(VAL_SYMMETRY, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r1.returncode == 0, f"symmetry: {r1.stdout}\n{r1.stderr}"
    # B62 top-down
    r2 = _run(VAL_FEATURE_CHAIN, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r2.returncode == 0, f"feature_chain: {r2.stdout}\n{r2.stderr}"
    # B63 bottom-up
    r3 = _run(VAL_CROSS_VIEW, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r3.returncode == 0, f"cross_view: {r3.stdout}\n{r3.stderr}"
    # Seed-chain status (informational, never fails)
    r4 = _run(STATUS, "--phase", "7", "--phase-dir", str(pd))
    assert r4.returncode == 0


def test_legacy_phase_no_regression(tmp_path):
    """Phase with NO feature_chain goals + NO CRUD resources passes without
    forcing the new gate."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    # No CRUD-SURFACES, no TEST-GOALS → validator skips gracefully
    r = _run(VAL_FEATURE_CHAIN, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode == 0
    r2 = _run(VAL_CROSS_VIEW, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r2.returncode == 0
    r3 = _run(VAL_SYMMETRY, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r3.returncode == 0


def test_audit_nf2_yaml_block_list_dependencies(tmp_path):
    """NF-2: symmetry validator must parse YAML block-list Dependencies.

      ## G-02
      Dependencies:
        - G-01
    """
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01\nenables:\n  - G-02\n\n"
        "## G-02\nDependencies:\n  - G-01\n",
        encoding="utf-8",
    )
    r = _run(VAL_SYMMETRY, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode == 0, f"YAML block-list should parse cleanly: {r.stdout}\n{r.stderr}"


def test_audit_nf2_yaml_block_list_asymmetric_detected(tmp_path):
    """NF-2: block-list with missing back-edge still flagged."""
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01\nenables:\n  - G-02\n\n"
        "## G-02\nDependencies:\n  - G-99\n",  # G-99 not G-01
        encoding="utf-8",
    )
    r = _run(VAL_SYMMETRY, "--phase", "7", "--phase-dir", str(pd), "--strict")
    assert r.returncode != 0


def test_audit_id9_vg_feature_chain_mode_env_documented():
    """Audit ID-9: VG_FEATURE_CHAIN_MODE env added to close.md gate logic."""
    close_md = REPO / "commands" / "vg" / "_shared" / "blueprint" / "close.md"
    body = close_md.read_text(encoding="utf-8")
    assert "VG_FEATURE_CHAIN_MODE" in body
    assert "FC_MODE" in body
    # warn mode bypass present
    assert "warn" in body.lower()
    # mirror sync
    close_mirror = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "close.md"
    assert body == close_mirror.read_text(encoding="utf-8")


def test_audit_nf1_symmetry_wired_in_close_md():
    """NF-1: verify-enables-deps-symmetry.py invoked from close.md."""
    close_md = REPO / "commands" / "vg" / "_shared" / "blueprint" / "close.md"
    body = close_md.read_text(encoding="utf-8")
    assert "verify-enables-deps-symmetry.py" in body
    assert "--allow-symmetry-gaps" in body
    # 3-tier fallback present
    assert "SYM_VAL" in body
