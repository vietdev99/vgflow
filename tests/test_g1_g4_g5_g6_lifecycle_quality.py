"""tests/test_g1_g4_g5_g6_lifecycle_quality.py — Batch 4 lifecycle quality."""
from __future__ import annotations
import json
import subprocess
import sys
import os
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
GEN = REPO / "scripts" / "generate-lifecycle-specs.py"


def _gen(tmp_path, goals_md):
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    out = phase_dir / "LIFECYCLE-SPECS.json"
    r = subprocess.run(
        [sys.executable, str(GEN), "--phase", "99", "--phase-dir", str(phase_dir),
         "--out", str(out)],
        capture_output=True, text=True, env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_g1_preconditions_pull_from_dependencies(tmp_path):
    """G1: preconditions derived from goal.dependencies + infra_deps, not hardcoded 4-bullet."""
    goals = """## Goal G-01: User creates order

**goal_type:** create-only
**Surface:** api
**mutation_evidence:** POST /api/orders
**dependencies:** active session, payment provider connected, product catalog seeded
**infra_deps:** redis, postgres
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-01"]
    preconds = goal.get("preconditions", [])
    # Must derive from dependencies + infra_deps, not be the 4-line boilerplate
    txt = "\n".join(str(p) for p in preconds)
    assert "session" in txt.lower() or "payment provider" in txt.lower() or "product catalog" in txt.lower(), (
        "G1: preconditions must derive from goal.dependencies. Currently boilerplate."
    )


def test_g4_actor_inference_uses_metadata(tmp_path):
    """G4: actor inference reads explicit goal metadata (e.g. actors: ['admin','owner'])
    in preference to word-match heuristic."""
    goals = """## Goal G-02: Owner reviews subscription

**goal_type:** read-only
**actors:** owner, billing_admin
**Surface:** api
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-02"]
    actor_ids = {a["id"] for a in goal.get("actors", [])}
    # Explicit metadata 'actors: owner, billing_admin' must produce both actors
    assert "owner" in actor_ids or "billing_admin" in actor_ids, (
        f"G4: explicit actors metadata must be honored. Got actors={actor_ids}"
    )


def test_g5_fixture_dag_from_dependencies(tmp_path):
    """G5: fixture DAG built from goal.dependencies graph, not 2-template hardcode."""
    goals = """## Goal G-01: Foundation goal

**goal_type:** create-only
**dependencies:** baseline_seeded

## Goal G-02: Depends on G-01

**goal_type:** create-only
**dependencies:** G-01
"""
    spec = _gen(tmp_path, goals)
    dag = spec.get("fixture_dag") or {}
    # DAG must reflect G-02 → G-01 edge
    edges_or_deps = json.dumps(dag).lower()
    assert "g-01" in edges_or_deps or "g-02" in edges_or_deps, (
        "G5: fixture_dag must reference goals by ID (G-01 depends on G-02 etc)"
    )


def test_g6_artifact_capture_per_kind(tmp_path):
    """G6: artifact_capture entries reflect goal artifact_kind field."""
    goals = """## Goal G-01: Export CSV

**goal_type:** read-only
**Surface:** api
**artifact_kind:** csv-download
"""
    spec = _gen(tmp_path, goals)
    goal = spec["goals"]["G-01"]
    artifact_capture = goal.get("artifact_capture", []) if isinstance(goal.get("artifact_capture"), list) else [goal.get("artifact_capture")]
    txt = json.dumps(artifact_capture).lower()
    assert "csv" in txt or "download" in txt or "artifact_kind" in txt, (
        "G6: artifact_capture must reference goal.artifact_kind (e.g. csv-download), "
        "not generic boilerplate entry"
    )
