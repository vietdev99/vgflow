"""tests/test_batch75_test_spec_generator_remaining.py — B75 closes issue #191.

Remaining 4/8 defects from issue #191 (after v4.63.6 B74 shipped 4/8):
  - C-M3 actor canonical-role lookup + generic placeholder replacement.
  - C-M4 `immutable: true` flag → stage filter (skip update/delete).
  - C-M7 mutation_evidence vs success_status cross-validation helper.
  - C-M8 TEST-GOALS source merge (split-dir + flat-file dedup).
"""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIFECYCLE_GEN = REPO / "scripts" / "generate-lifecycle-specs.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("lifecycle_gen", LIFECYCLE_GEN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# C-M4: immutable flag.
# ---------------------------------------------------------------------------


def test_b75_cm4_immutable_true_returns_create_only_stages(mod):
    """Goal with `immutable: true` → no update/delete stages."""
    goal = {"immutable": True, "goal_type": "mutation"}
    stages = mod._stages_for_goal(goal)
    assert "update" not in stages
    assert "delete" not in stages
    assert "read_after_update" not in stages
    assert "read_after_delete" not in stages
    assert "create" in stages
    assert "read_before" in stages


def test_b75_cm4_immutable_false_keeps_full_rcrurdr(mod):
    """Default immutable=false → full RCRURDR sequence."""
    goal = {"immutable": False, "goal_type": "mutation"}
    stages = mod._stages_for_goal(goal)
    assert "update" in stages or "delete" in stages or len(stages) >= 5


def test_b75_cm4_immutable_field_parsed_from_frontmatter(mod):
    body = textwrap.dedent("""
        ## Goal G-100: Audit log entry

        **immutable:** true
        **Surface:** audit
        **Priority:** critical
    """).strip()
    goal = mod._parse_goal_block(body, Path("/tmp/G-100.md"))
    assert goal is not None
    assert goal["immutable"] is True


def test_b75_cm4_immutable_absent_defaults_false(mod):
    body = textwrap.dedent("""
        ## Goal G-101: Topup

        **Surface:** finance
    """).strip()
    goal = mod._parse_goal_block(body, Path("/tmp/G-101.md"))
    assert goal is not None
    assert goal["immutable"] is False


# ---------------------------------------------------------------------------
# C-M7: success_status vs mutation_evidence cross-validation.
# ---------------------------------------------------------------------------


def test_b75_cm7_consistent_status_returns_none(mod):
    """success_status=201 + mutation_evidence mentions 201 → no drift."""
    goal = {"success_status": "201", "mutation_evidence": "POST returns 201 Created"}
    drift = mod._validate_success_status_consistency(goal)
    assert drift is None


def test_b75_cm7_drift_detected(mod):
    """G-048 pattern: success=200 vs evidence=201."""
    goal = {"success_status": "200", "mutation_evidence": "POST returns 201"}
    drift = mod._validate_success_status_consistency(goal)
    assert drift is not None
    assert drift["declared"] == "200"
    assert drift["observed"] == "201"


def test_b75_cm7_missing_fields_no_validation(mod):
    """No success_status or no evidence → skip validation (no false flag)."""
    assert mod._validate_success_status_consistency({"mutation_evidence": "x"}) is None
    assert mod._validate_success_status_consistency({"success_status": "200"}) is None
    assert mod._validate_success_status_consistency({}) is None


def test_b75_cm7_success_status_parsed_from_frontmatter(mod):
    body = textwrap.dedent("""
        ## Goal G-200: Create topup

        **success_status:** 201
        **Mutation evidence:** POST returns 201 with topup id
    """).strip()
    goal = mod._parse_goal_block(body, Path("/tmp/G-200.md"))
    assert goal is not None
    assert goal["success_status"] == "201"


def test_b75_cm7_multiple_evidence_codes_takes_first(mod):
    """When evidence has multiple codes and none match declared, return first."""
    goal = {"success_status": "200", "mutation_evidence": "POST returns 201; rollback 500"}
    drift = mod._validate_success_status_consistency(goal)
    assert drift is not None
    assert drift["declared"] == "200"
    assert drift["observed"] == "201"


# ---------------------------------------------------------------------------
# C-M8: TEST-GOALS source merge (split + flat).
# ---------------------------------------------------------------------------


def test_b75_cm8_split_only_returns_split_goals(mod, tmp_path: Path):
    phase_dir = tmp_path / "phase"
    split = phase_dir / "TEST-GOALS"
    split.mkdir(parents=True)
    (split / "G-001.md").write_text(
        "## Goal G-001: Topup\n\n**Surface:** finance\n", encoding="utf-8"
    )
    (split / "G-002.md").write_text(
        "## Goal G-002: Refund\n\n**Surface:** finance\n", encoding="utf-8"
    )
    goals = mod._parse_goals(phase_dir)
    ids = [g["id"] for g in goals]
    assert ids == ["G-001", "G-002"]


def test_b75_cm8_flat_only_returns_flat_goals(mod, tmp_path: Path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-001: A\n\n## Goal G-002: B\n", encoding="utf-8"
    )
    goals = mod._parse_goals(phase_dir)
    ids = [g["id"] for g in goals]
    assert ids == ["G-001", "G-002"]


def test_b75_cm8_split_and_flat_merge_with_split_winning(mod, tmp_path: Path):
    """The Phase 8.2 dogfood scenario: split has G-001..G-005, flat has
    G-001..G-007. Result: 7 goals, G-006 + G-007 from flat, rest from split.
    """
    phase_dir = tmp_path / "phase"
    split = phase_dir / "TEST-GOALS"
    split.mkdir(parents=True)
    for i in range(1, 6):
        (split / f"G-00{i}.md").write_text(
            f"## Goal G-00{i}: Split version\n\n**Surface:** split\n",
            encoding="utf-8",
        )
    flat_body = ""
    for i in range(1, 8):
        flat_body += f"## Goal G-00{i}: Flat version\n\n**Surface:** flat\n\n"
    (phase_dir / "TEST-GOALS.md").write_text(flat_body, encoding="utf-8")
    goals = mod._parse_goals(phase_dir)
    ids = [g["id"] for g in goals]
    # All 7 distinct IDs present.
    assert sorted(ids) == [f"G-00{i}" for i in range(1, 8)]
    # G-001..G-005 from split (Surface=split), G-006/G-007 from flat (Surface=flat).
    by_id = {g["id"]: g for g in goals}
    assert by_id["G-001"]["surface"] == "split"
    assert by_id["G-005"]["surface"] == "split"
    assert by_id["G-006"]["surface"] == "flat"
    assert by_id["G-007"]["surface"] == "flat"


def test_b75_cm8_empty_phase_dir_returns_empty(mod, tmp_path: Path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    goals = mod._parse_goals(phase_dir)
    assert goals == []


# ---------------------------------------------------------------------------
# C-M3: canonical role lookup + generic placeholder replacement.
# ---------------------------------------------------------------------------


def test_b75_cm3_foundation_roles_parsed(mod, tmp_path: Path):
    """Roles parsed from FOUNDATION.md ## Roles block."""
    (tmp_path / "FOUNDATION.md").write_text(textwrap.dedent("""
        # Project Foundation

        ## Roles

        - super_admin: top-level operator
        - admin_finance: finance team admin
        - publisher: external publisher partner
        - advertiser: external advertiser partner

        ## Other

        Body.
    """).strip(), encoding="utf-8")
    phase_dir = tmp_path / "phases" / "P1"
    phase_dir.mkdir(parents=True)
    roles = mod._load_foundation_roles(phase_dir)
    assert "super_admin" in roles
    assert "admin_finance" in roles
    assert "publisher" in roles
    assert "advertiser" in roles


def test_b75_cm3_no_foundation_returns_empty(mod, tmp_path: Path):
    phase_dir = tmp_path / "P1"
    phase_dir.mkdir()
    assert mod._load_foundation_roles(phase_dir) == []


def test_b75_cm3_generic_placeholder_replaced_when_canonical_available(mod, tmp_path: Path):
    (tmp_path / "FOUNDATION.md").write_text(textwrap.dedent("""
        ## Roles

        - admin_finance: operator
    """).strip(), encoding="utf-8")
    phase_dir = tmp_path / "phases" / "P1"
    phase_dir.mkdir(parents=True)
    goal = {"actors": "secondary_user_or_external_system", "title": "x"}
    actors = mod._infer_actors_v2(goal, phase_dir)
    # No generic placeholder in output.
    for a in actors:
        assert a["role"] != "secondary_user_or_external_system"
    # Diagnostic count recorded on goal.
    assert goal.get("_b75_generic_actor_replaced", 0) >= 1


def test_b75_cm3_explicit_canonical_role_passes_through(mod, tmp_path: Path):
    (tmp_path / "FOUNDATION.md").write_text("## Roles\n\n- admin_finance: op\n",
                                            encoding="utf-8")
    phase_dir = tmp_path / "phases" / "P1"
    phase_dir.mkdir(parents=True)
    goal = {"actors": "admin_finance", "title": "x"}
    actors = mod._infer_actors_v2(goal, phase_dir)
    assert any(a["role"] == "admin_finance" for a in actors)
    assert goal.get("_b75_generic_actor_replaced", 0) == 0


def test_b75_cm3_no_canonical_keeps_generic_back_compat(mod, tmp_path: Path):
    """When no FOUNDATION.md, keep generic placeholder (back-compat)."""
    phase_dir = tmp_path / "phases" / "P1"
    phase_dir.mkdir(parents=True)
    goal = {"actors": "secondary_user_or_external_system", "title": "x"}
    actors = mod._infer_actors_v2(goal, phase_dir)
    assert any(a["role"] == "secondary_user_or_external_system" for a in actors)


# ---------------------------------------------------------------------------
# Marker presence.
# ---------------------------------------------------------------------------


def test_b75_marker_present_in_lifecycle_gen():
    body = LIFECYCLE_GEN.read_text(encoding="utf-8")
    assert "B75 v4.63.7" in body
    assert "C-M3" in body and "C-M4" in body and "C-M7" in body and "C-M8" in body
