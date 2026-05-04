"""Task 41 — verify capsule extension for actor + workflow + write_phase awareness.

Pin: build_task_context_capsule() returns capsule_version='2' with
actor_role / workflow_id / workflow_step / write_phase fields. Missing
PLAN tags = None (graceful, backward-compat).

execution_contract gains must_match_workflow_state + actor_role_hint.
anti_lazy_read_rules gains 2 workflow-aware entries.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_pre_executor_check():
    """Load scripts/pre-executor-check.py (hyphen in name prevents direct import)."""
    spec = importlib.util.spec_from_file_location(
        "pre_executor_check",
        REPO / "scripts" / "pre-executor-check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_executor_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)
    return phase_dir


def _import_helpers():
    mod = _load_pre_executor_check()
    return (
        mod.build_task_context_capsule,
        mod.extract_actor_role,
        mod.extract_workflow_id,
        mod.extract_workflow_step,
        mod.extract_write_phase,
    )


def test_extract_actor_role_present() -> None:
    _, extract_actor_role, *_ = _import_helpers()
    body = "## Task 03: Add POST /api/sites handler\n<actor>user</actor>\n"
    assert extract_actor_role(body) == "user"


def test_extract_actor_role_missing_returns_none() -> None:
    _, extract_actor_role, *_ = _import_helpers()
    body = "## Task 03: Add POST /api/sites handler\n"
    assert extract_actor_role(body) is None


def test_extract_workflow_id_and_step() -> None:
    _, _, extract_workflow_id, extract_workflow_step, _ = _import_helpers()
    body = "<workflow>WF-001</workflow>\n<workflow-step>2</workflow-step>\n"
    assert extract_workflow_id(body) == "WF-001"
    assert extract_workflow_step(body) == 2


def test_extract_write_phase_create() -> None:
    *_, extract_write_phase = _import_helpers()
    assert extract_write_phase("<write-phase>create</write-phase>\n") == "create"


def test_extract_write_phase_invalid_returns_none() -> None:
    *_, extract_write_phase = _import_helpers()
    # Only create|update|delete|null are accepted
    assert extract_write_phase("<write-phase>banana</write-phase>\n") is None


def test_capsule_v2_includes_workflow_fields_when_tags_present(synthetic_phase: Path) -> None:
    build_task_context_capsule, *_ = _import_helpers()
    task_body = (
        "## Task 03: Add POST /api/sites handler\n"
        "<file-path>apps/api/src/sites/routes.ts</file-path>\n"
        "<actor>user</actor>\n"
        "<workflow>WF-001</workflow>\n"
        "<workflow-step>2</workflow-step>\n"
        "<write-phase>create</write-phase>\n"
    )
    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=3,
        task_context=task_body,
        contract_context="POST /api/sites\n",
        goals_context="G-04",
        crud_surface_context="sites",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    assert capsule["capsule_version"] == "2"
    assert capsule["actor_role"] == "user"
    assert capsule["workflow_id"] == "WF-001"
    assert capsule["workflow_step"] == 2
    assert capsule["write_phase"] == "create"
    # execution_contract additions
    assert capsule["execution_contract"]["must_match_workflow_state"] is True
    assert capsule["execution_contract"]["actor_role_hint"] == "user"
    # anti_lazy_read_rules — 2 new entries
    rules = capsule["anti_lazy_read_rules"]
    assert any("WORKFLOW-SPECS" in r for r in rules), \
        "anti_lazy_read_rules must add workflow-spec read rule"
    assert any("state_machine.states" in r for r in rules), \
        "anti_lazy_read_rules must enforce state-name discipline"


def test_capsule_v2_null_fields_when_tags_absent(synthetic_phase: Path) -> None:
    build_task_context_capsule, *_ = _import_helpers()
    task_body = (
        "## Task 99: Migration script\n"
        "<file-path>scripts/migrate-2026.sql</file-path>\n"
    )
    capsule = build_task_context_capsule(
        phase_dir=synthetic_phase,
        task_num=99,
        task_context=task_body,
        contract_context="",
        goals_context="",
        crud_surface_context="none",
        sibling_context="none",
        downstream_callers="none",
        design_context="none",
        build_config={"phase": "N1"},
    )
    assert capsule["capsule_version"] == "2"
    assert capsule["actor_role"] is None
    assert capsule["workflow_id"] is None
    assert capsule["workflow_step"] is None
    assert capsule["write_phase"] is None
    assert capsule["execution_contract"]["must_match_workflow_state"] is False
    assert capsule["execution_contract"]["actor_role_hint"] in ("", None)


def test_plan_delegation_md_documents_tag_conventions() -> None:
    plan_del = REPO / "commands/vg/_shared/blueprint/plan-delegation.md"
    text = plan_del.read_text(encoding="utf-8")
    for tag in ("<actor>", "<workflow>", "<workflow-step>", "<write-phase>"):
        assert tag in text, f"plan-delegation.md must document tag: {tag}"
    # Must enumerate valid actor + write_phase values
    assert "user" in text and "admin" in text
    assert "create" in text and "update" in text and "delete" in text
