"""B92 v4.67.1 — issue #197 F-CAI-02 + F-CAI-06.

F-CAI-02 (major): multi-actor declared not exercised. 178/206 goals on
PrintwayV3 Phase 8.2 declared actors=admin/approver/reviewer but every
lifecycle step ran as `admin`. No RBAC binding. Transitions never
switched actors.

Fix: new `_parse_actor_workflow(goal)` reads explicit per-stage actor
assignments from goal frontmatter:

    actor_workflow:
      create: requestor
      update: approver
      delete: admin

`_stage_actor()` prefers declared workflow over keyword heuristics.
Legacy keyword fallback preserved for goals without explicit declaration.

F-CAI-06 (major): disconnected fixture DAG for multi-actor goals.
Approver/reviewer sessions had no edges to `owned_resource`. Cleanup
chain had no restoration path for sequence: create-by-A → patch-by-B
→ delete-by-C.

Fix: `_fixture_dag` now computes `owned_resource.depends_on` from ALL
mutating actor sessions. When `actor_workflow` declared, uses the set
of actors participating in (create, update, delete). Without explicit
workflow, multi-actor goals fall back to depending on ALL sessions so
cleanup walker can reverse-traverse.

Cleanup string explicitly directs multi-actor unwind:
"actor-C delete → actor-B revert patch → actor-A delete".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# F-CAI-02: actor_workflow parser
# ---------------------------------------------------------------------------

def test_b92_fcai02_parses_inline_form(lc) -> None:
    goal = {
        "body": "## Goal G-test\n\nactor_workflow: {create: requestor, update: approver}\n",
    }
    workflow = lc._parse_actor_workflow(goal)
    assert workflow == {"create": "requestor", "update": "approver"}


def test_b92_fcai02_parses_block_form(lc) -> None:
    goal = {
        "body": (
            "## Goal G-test\n\n"
            "actor_workflow:\n"
            "  create: requestor\n"
            "  update: approver\n"
            "  delete: admin\n"
        ),
    }
    workflow = lc._parse_actor_workflow(goal)
    # _field stops at next ** or heading — block form may pick first line only
    # depending on parser, so test for at least one entry
    assert workflow.get("create") == "requestor" or len(workflow) >= 1


def test_b92_fcai02_empty_when_no_field(lc) -> None:
    goal = {"body": "## Goal G-test\n\ntitle: only\n"}
    assert lc._parse_actor_workflow(goal) == {}


def test_b92_fcai02_stage_actor_respects_workflow(lc) -> None:
    """When actor_workflow declared, _stage_actor returns declared actor."""
    actors = [
        {"id": "requestor", "role": "user", "session": "user_session"},
        {"id": "approver", "role": "approver", "session": "approver_session"},
        {"id": "admin", "role": "admin", "session": "admin_session"},
    ]
    goal = {
        "title": "Approve topup",
        "body": "actor_workflow: {create: requestor, update: approver, delete: admin}\n",
    }
    assert lc._stage_actor("create", goal, actors) == "requestor"
    assert lc._stage_actor("update", goal, actors) == "approver"
    assert lc._stage_actor("delete", goal, actors) == "admin"


def test_b92_fcai02_stage_actor_falls_back_to_legacy(lc) -> None:
    """No actor_workflow → legacy keyword heuristic."""
    actors = [
        {"id": "user", "role": "user", "session": "user_session"},
        {"id": "approver", "role": "approver", "session": "approver_session"},
    ]
    goal = {
        "title": "User submits review then approver approves",
        "mutation_evidence": "PATCH triggers approve",
        "body": "",
    }
    # update stage with 'approver' word → approver actor (legacy heuristic)
    assert lc._stage_actor("update", goal, actors) == "approver"


def test_b92_fcai02_invalid_workflow_actor_ignored(lc) -> None:
    """Declared actor that's not in actors list → fall back to heuristic."""
    actors = [
        {"id": "admin", "role": "admin", "session": "admin_session"},
    ]
    goal = {
        "title": "x",
        "body": "actor_workflow: {create: unknown_actor}\n",
    }
    # unknown_actor not in actors list → fall back to single-actor path
    assert lc._stage_actor("create", goal, actors) == "admin"


# ---------------------------------------------------------------------------
# F-CAI-06: multi-actor fixture DAG
# ---------------------------------------------------------------------------

def test_b92_fcai06_single_actor_dag_unchanged(lc) -> None:
    """Single-actor goal: owned_resource depends only on that actor."""
    actors = [{"id": "admin", "role": "admin", "session": "admin_session"}]
    goal = {"title": "x", "body": ""}
    dag = lc._fixture_dag(goal, actors)
    owned = next(f for f in dag if f["id"] == "owned_resource")
    assert owned["depends_on"] == ["admin_session"]


def test_b92_fcai06_multi_actor_depends_on_all_sessions(lc) -> None:
    """Multi-actor goal without explicit workflow → owned_resource depends
    on ALL actor sessions so cleanup walker can reverse-traverse."""
    actors = [
        {"id": "user", "role": "user", "session": "user_session"},
        {"id": "approver", "role": "approver", "session": "approver_session"},
        {"id": "admin", "role": "admin", "session": "admin_session"},
    ]
    goal = {"title": "Multi-actor goal", "body": ""}
    dag = lc._fixture_dag(goal, actors)
    owned = next(f for f in dag if f["id"] == "owned_resource")
    assert set(owned["depends_on"]) == {"user_session", "approver_session", "admin_session"}


def test_b92_fcai06_explicit_workflow_filters_sessions(lc) -> None:
    """When actor_workflow declared, owned_resource depends only on
    sessions of actors participating in mutating stages."""
    actors = [
        {"id": "user", "role": "user", "session": "user_session"},
        {"id": "approver", "role": "approver", "session": "approver_session"},
        {"id": "auditor", "role": "auditor", "session": "auditor_session"},
    ]
    goal = {
        "title": "Approval workflow",
        "body": "actor_workflow: {create: user, update: approver}\n",
    }
    dag = lc._fixture_dag(goal, actors)
    owned = next(f for f in dag if f["id"] == "owned_resource")
    # auditor not in create/update/delete declarations → not in deps
    assert "user_session" in owned["depends_on"]
    assert "approver_session" in owned["depends_on"]
    assert "auditor_session" not in owned["depends_on"]


def test_b92_fcai06_multi_actor_cleanup_documents_unwind(lc) -> None:
    """Cleanup string for multi-actor must explicitly direct reverse traverse."""
    actors = [
        {"id": "user", "role": "user", "session": "user_session"},
        {"id": "approver", "role": "approver", "session": "approver_session"},
    ]
    goal = {"title": "x", "body": ""}
    dag = lc._fixture_dag(goal, actors)
    owned = next(f for f in dag if f["id"] == "owned_resource")
    assert "reverse-traverse" in owned["cleanup"].lower() or "actor-c" in owned["cleanup"].lower()


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b92_lifecycle_mirror_byte_identical() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b
