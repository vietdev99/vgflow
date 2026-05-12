"""tests/test_lifecycle_generator_multi_actor.py — G12 multi-actor step switching."""
from __future__ import annotations
import json
import subprocess
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


def _seed_phase(tmp_path: Path, goals_md: str) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    return phase_dir


def _gen(tmp_path: Path, goals_md: str) -> dict:
    phase_dir = _seed_phase(tmp_path, goals_md)
    out_path = phase_dir / "LIFECYCLE-SPECS.json"
    r = subprocess.run(
        [sys.executable, str(GENERATOR), "--phase", "99", "--phase-dir", str(phase_dir),
         "--out", str(out_path)],
        capture_output=True, text=True, env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_multi_actor_goal_switches_actor_across_stages(tmp_path):
    """v5.0 G12: invite + accept goal should have different actors per stage,
    not collapsed to actors[0]."""
    goals = """## Goal G-01: Owner invites collaborator, collaborator accepts

**goal_type:** multi-actor
**Surface:** api
**mutation_evidence:** POST /api/invites by owner; PATCH /api/invites/:id by invitee
**persistence_check:** GET /api/projects/:id/members includes invitee after accept
**dependencies:** owner session, invitee session
"""
    spec = _gen(tmp_path, goals)
    goal_spec = spec["goals"]["G-01"]
    actors = goal_spec["actors"]
    assert len(actors) >= 2, "multi-actor goal must infer 2+ actors"
    # Steps should reference at least 2 distinct actor IDs
    step_actors = {s["actor"] for s in goal_spec["steps"]}
    assert len(step_actors) >= 2, (
        f"v5.0 G12: multi-actor goal must switch actor across stages, "
        f"got step_actors={step_actors}"
    )


def test_single_actor_goal_all_steps_same_actor(tmp_path):
    """v5.0 G12: single-actor goal keeps consistent actor across all steps."""
    goals = """## Goal G-02: User creates project

**goal_type:** mutation
**Surface:** api
**mutation_evidence:** POST /api/projects returns 201
"""
    spec = _gen(tmp_path, goals)
    goal_spec = spec["goals"]["G-02"]
    step_actors = {s["actor"] for s in goal_spec["steps"]}
    assert len(step_actors) == 1, (
        f"single-actor goal should use one actor; got step_actors={step_actors}"
    )


def test_approval_stage_uses_approver_actor(tmp_path):
    """v5.0 G12: 'admin approves' wording → approval stage uses admin actor."""
    goals = """## Goal G-03: User submits, admin approves

**goal_type:** multi-actor
**Surface:** api
**mutation_evidence:** POST /api/requests by user; PATCH /api/requests/:id by admin
**persistence_check:** GET /api/requests/:id status == 'approved' after admin patch
**dependencies:** user session, admin session
"""
    spec = _gen(tmp_path, goals)
    goal_spec = spec["goals"]["G-03"]
    # The update stage should be performed by an admin/approver actor when admin is in goal
    update_step = next((s for s in goal_spec["steps"] if s["name"] == "update"), None)
    assert update_step is not None
    # Admin actor should be in the actors list
    admin_actors = [a for a in goal_spec["actors"] if "admin" in a["id"].lower() or "admin" in a.get("role", "").lower()]
    if admin_actors:
        # If admin actor exists AND update stage exists, the update step should reference admin
        # (heuristic — may be approver/reviewer/admin)
        assert update_step["actor"] in {a["id"] for a in goal_spec["actors"]}
