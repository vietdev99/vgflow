"""tests/test_batch63_cross_view_propagation.py — B63 bottom-up.

Scanner cross-view propagation observation + enrich-test-goals consumer
emits feature_chain goals from observed data.

Coverage:
  1. Scanner SKILL.md schema declares cross_view_propagation_observations
  2. Scanner workflow documents budget cap + sample mode
  3. Scanner documents heuristic priority + dedup key
  4. Scanner documents limitations[] field
  5. enrich consumes create observation → emits visibility goal
  6. enrich consumes update observation → emits status-cascade goal
  7. enrich consumes delete observation → emits archive goal
  8. enrich goal has goal_class=feature_chain + ≥4 chain_steps
  9. enrich emits stable goal-id from entity_canonical_id (view rename safe)
  10. Validator PASS when observation covers CRUD resource
  11. Validator FAIL strict when CRUD resource has no observation
  12. Validator PASS with skip_cross_view override
  13. Validator PASS with global cross_view_scan=disabled
  14. Back-compat: scan without field still works
  15. enrich idempotent (re-run no duplicates)
  16. seed-chain-status reports layer 8
  17. Mirror parity
"""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "vg-haiku-scanner" / "SKILL.md"
SKILL_MIRROR = REPO / ".claude" / "skills" / "vg-haiku-scanner" / "SKILL.md"
ENRICH = REPO / "scripts" / "enrich-test-goals.py"
ENRICH_MIRROR = REPO / ".claude" / "scripts" / "enrich-test-goals.py"
VAL = REPO / "scripts" / "validators" / "verify-cross-view-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-cross-view-coverage.py"
STATUS = REPO / "scripts" / "seed-chain-status.py"
STATUS_MIRROR = REPO / ".claude" / "scripts" / "seed-chain-status.py"


def _load_enrich_module():
    spec = importlib.util.spec_from_file_location("enrich", ENRICH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["enrich_test_b63"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_scanner_skill_declares_cross_view_field():
    body = SKILL.read_text(encoding="utf-8")
    assert "cross_view_propagation_observations" in body
    assert "target_view_class" in body
    assert "entity_canonical_id" in body
    assert "observed_in_target" in body


def test_scanner_skill_documents_budget_and_sample_mode():
    body = SKILL.read_text(encoding="utf-8")
    assert "VG_CROSS_VIEW_TOTAL_BUDGET_S" in body
    assert "VG_CROSS_VIEW_MODE" in body or "sample|enabled|disabled" in body
    assert "60s" in body or "60 s" in body


def test_scanner_skill_documents_heuristic_priority():
    body = SKILL.read_text(encoding="utf-8")
    # Heuristic priority documented
    assert "shared entity slug" in body or "shared slug" in body
    assert "dashboard" in body.lower()
    # Dedup key
    assert "entity_slug_family" in body or "Dedup" in body or "dedup" in body


def test_scanner_skill_documents_limitations():
    body = SKILL.read_text(encoding="utf-8")
    assert "single_role_scan" in body
    assert "no_delayed_propagation" in body


def test_enrich_emits_visibility_goal_on_create():
    mod = _load_enrich_module()
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_id": "site-001",
                "entity_canonical_id": "sites:create",
                "observed_in_target": "yes",
                "observed_count_delta": 1,
            }
        ],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    chain_goals = [s for s in stubs if s.get("goal_class") == "feature_chain"]
    assert chain_goals, "expected feature_chain goal from create observation"
    visibility_goals = [g for g in chain_goals if "visibility" in g["id"]]
    assert visibility_goals
    assert "dashboard_summary" in visibility_goals[0]["id"]


def test_enrich_emits_status_cascade_on_update():
    mod = _load_enrich_module()
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "update",
                "entity_canonical_id": "sites:update",
                "observed_in_target": "yes",
            }
        ],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    status_goals = [s for s in stubs if "status-cascade" in s.get("id", "")]
    assert status_goals


def test_enrich_emits_archive_on_delete():
    mod = _load_enrich_module()
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/audit",
                "target_view_class": "audit_log",
                "action": "delete",
                "entity_canonical_id": "sites:delete",
                "observed_in_target": "partial",
            }
        ],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    archive_goals = [s for s in stubs if "archive" in s.get("id", "")]
    assert archive_goals


def test_enrich_goal_has_chain_steps_and_class():
    mod = _load_enrich_module()
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_canonical_id": "sites:create",
                "observed_in_target": "yes",
            }
        ],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    chain_goals = [s for s in stubs if s.get("goal_class") == "feature_chain"]
    assert chain_goals
    goal = chain_goals[0]
    assert "chain_steps" in goal
    assert len(goal["chain_steps"]) >= 4
    # Has target_view_class on each step
    for step in goal["chain_steps"]:
        assert "target_view_class" in step
        assert "expected_state" in step


def test_enrich_goal_id_stable_across_view_renames():
    """Goal-id derives from entity_canonical_id + target_view_class, NOT
    raw view path. So rename /sites → /properties keeps same goal-id."""
    mod = _load_enrich_module()
    scan1 = {
        "view": "/sites",
        "cross_view_propagation_observations": [{
            "source_view": "/sites",
            "target_view": "/dashboard",
            "target_view_class": "dashboard_summary",
            "action": "create",
            "entity_canonical_id": "sites:create",
            "observed_in_target": "yes",
        }],
    }
    scan2 = {
        "view": "/properties",
        "cross_view_propagation_observations": [{
            "source_view": "/properties",
            "target_view": "/dashboard",
            "target_view_class": "dashboard_summary",
            "action": "create",
            "entity_canonical_id": "sites:create",  # canonical id stable
            "observed_in_target": "yes",
        }],
    }
    stubs1 = mod.classify_elements("/sites", scan1, {}, [])
    stubs2 = mod.classify_elements("/properties", scan2, {}, [])
    ids1 = {s["id"] for s in stubs1 if s.get("goal_class") == "feature_chain"}
    ids2 = {s["id"] for s in stubs2 if s.get("goal_class") == "feature_chain"}
    # Same goal id despite view rename
    assert ids1 == ids2


def test_validator_passes_when_resource_covered(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(
        '## site\n```json\n{"method": "POST"}\n```\n', encoding="utf-8"
    )
    (pd / "scan-sites.json").write_text(json.dumps({
        "view": "/sites",
        "cross_view_propagation_observations": [{
            "source_view": "/sites",
            "target_view": "/dashboard",
            "target_view_class": "dashboard_summary",
            "action": "create",
            "entity_canonical_id": "site:create",
            "observed_in_target": "yes",
        }],
    }), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_validator_fails_strict_when_no_observation(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(
        '## site\n```json\n{"method": "POST"}\n```\n', encoding="utf-8"
    )
    (pd / "scan-sites.json").write_text(json.dumps({
        "view": "/sites",
        # NO cross_view_propagation_observations field
    }), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode != 0


def test_validator_passes_with_skip_cross_view_override(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(
        '## site\n```json\n{"method": "POST"}\n```\n', encoding="utf-8"
    )
    (pd / "scan-sites.json").write_text(json.dumps({"view": "/sites"}), encoding="utf-8")
    vg_dir = pd / ".vg"
    vg_dir.mkdir()
    (vg_dir / "scanner-overrides.yaml").write_text(
        "skip_cross_view[site]: true\n", encoding="utf-8"
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0


def test_validator_passes_with_global_disabled(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "CRUD-SURFACES.md").write_text(
        '## site\n```json\n{"method": "POST"}\n```\n', encoding="utf-8"
    )
    vg_dir = pd / ".vg"
    vg_dir.mkdir()
    (vg_dir / "scanner-overrides.yaml").write_text(
        "cross_view_scan: disabled\n", encoding="utf-8"
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0


def test_back_compat_scan_without_field():
    """Legacy scan with no cross_view_propagation_observations field
    should not crash enrich."""
    mod = _load_enrich_module()
    scan = {"view": "/sites", "forms": []}
    stubs = mod.classify_elements("/sites", scan, {}, [])
    # No crash, no feature_chain goals from missing field
    chain_goals = [s for s in stubs if s.get("goal_class") == "feature_chain"]
    assert chain_goals == []


def test_enrich_dedup_no_duplicate_goals():
    mod = _load_enrich_module()
    scan = {
        "view": "/sites",
        "cross_view_propagation_observations": [
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_canonical_id": "sites:create",
                "observed_in_target": "yes",
            },
            # Same goal-id pair → dedup
            {
                "source_view": "/sites",
                "target_view": "/dashboard",
                "target_view_class": "dashboard_summary",
                "action": "create",
                "entity_canonical_id": "sites:create",
                "observed_in_target": "yes",
            },
        ],
    }
    stubs = mod.classify_elements("/sites", scan, {}, [])
    chain_goals = [s for s in stubs if s.get("goal_class") == "feature_chain"]
    ids = [g["id"] for g in chain_goals]
    assert len(ids) == len(set(ids)), f"duplicate goal-ids: {ids}"


def test_seed_chain_status_includes_layer_8():
    body = STATUS.read_text(encoding="utf-8")
    assert "_check_layer_8_feature_chain" in body
    assert "feature_chain coverage" in body or "feature_chain" in body
    assert "B62-63" in body


def test_mirrors_in_sync():
    assert SKILL.read_text(encoding="utf-8") == SKILL_MIRROR.read_text(encoding="utf-8")
    assert ENRICH.read_text(encoding="utf-8") == ENRICH_MIRROR.read_text(encoding="utf-8")
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    assert STATUS.read_text(encoding="utf-8") == STATUS_MIRROR.read_text(encoding="utf-8")
