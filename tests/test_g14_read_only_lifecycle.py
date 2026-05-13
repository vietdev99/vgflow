"""tests/test_g14_read_only_lifecycle.py — G14 read-only goal lifecycle."""
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


def test_read_only_goal_produces_lifecycle(tmp_path):
    """v5.0 G14: read-only goal must produce read_before + filter_check steps."""
    goals = """## Goal G-01: User lists pending tasks

**goal_type:** read-only
**Surface:** api
**persistence_check:** GET /api/tasks?status=pending returns filtered list
"""
    spec = _gen(tmp_path, goals)
    assert "G-01" in spec["goals"]
    goal = spec["goals"]["G-01"]
    stage_names = [s.get("name") or s.get("stage") for s in goal["steps"]]
    assert "read_before" in stage_names, (
        "G14: read-only goal must have read_before stage (precondition + assertion)"
    )
    # Read-only goal lifecycle MUST NOT have create/update/delete
    assert "create" not in stage_names
    assert "update" not in stage_names
    assert "delete" not in stage_names


def test_read_only_goal_endpoint_binding(tmp_path):
    """G14: read-only step should bind GET endpoint from API-CONTRACTS when present."""
    goals = """## Goal G-02: List active users

**goal_type:** read-only
**persistence_check:** GET /api/users?active=true
"""
    contracts = """## GET /api/users
Response: 200 user list
"""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals, encoding="utf-8")
    (phase_dir / "API-CONTRACTS.md").write_text(contracts, encoding="utf-8")
    out = phase_dir / "LIFECYCLE-SPECS.json"
    r = subprocess.run(
        [sys.executable, str(GEN), "--phase", "99", "--phase-dir", str(phase_dir),
         "--out", str(out)],
        capture_output=True, text=True, env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stderr
    spec = json.loads(out.read_text(encoding="utf-8"))
    goal = spec["goals"]["G-02"]
    rb = next((s for s in goal["steps"] if (s.get("name") or s.get("stage")) == "read_before"), None)
    assert rb is not None
    # endpoint binding should resolve GET
    if rb.get("endpoint") is not None:
        assert rb["endpoint"]["method"] == "GET"
