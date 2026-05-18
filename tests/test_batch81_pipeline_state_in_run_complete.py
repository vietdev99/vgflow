"""B81 v4.63.13 — orchestrator-owned PIPELINE-STATE flip in cmd_run_complete.

Dogfood report (RTB Phase 8.1 Flow 9 Admin Reports, 2026-05-18 dataset):
build session 4ea0f060 emitted `build.completed` + `run.completed` events,
all build steps marked done in events.db, but PIPELINE-STATE.json was NEVER
updated. Forensics showed:

  - RTB is global install (`.vg/.install-target=global`).
  - `.claude/scripts/` was pruned by `/vg:update` (correct per global doctrine).
  - close.md line 818 hardcodes `python3 .claude/scripts/vg-orchestrator
    run-complete` with NO tier fallback.
  - Python errors with "No such file or directory" → exit 2 → script exits
    at line 822 BEFORE the inline Python at line 826 that flips PIPELINE-STATE.
  - User runs `/vg:next`, reads stale `next_command: /vg:build 8.1` from
    PIPELINE-STATE.json (last updated 2026-05-17 by blueprint close), gets
    looped back into build instead of advancing to review.

Fix: move PIPELINE-STATE flip into `cmd_run_complete` so the canonical state
transition is owned by the orchestrator binary, not the skill-side bash. Skill
flip remains as a parallel path for backwards compatibility; both writers are
idempotent.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator"


def _setup_phase(tmp_path: Path, phase: str = "8.1", phase_slug: str = "test-phase") -> Path:
    """Construct a minimal .vg layout with one phase dir + events.db."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    vg = repo / ".vg"
    vg.mkdir()
    phases = vg / "phases"
    phases.mkdir()
    pdir = phases / f"{phase}-{phase_slug}"
    pdir.mkdir()
    # Pre-existing PIPELINE-STATE from blueprint close
    (pdir / "PIPELINE-STATE.json").write_text(json.dumps({
        "steps": {
            "specs": {"status": "done"},
            "scope": {"status": "done"},
            "blueprint": {"status": "done"},
        },
        "next_command": f"/vg:build {phase}",
        "next_command_emitted_at": "2026-05-17T00:00:00Z",
    }), encoding="utf-8")
    # active-runs entry
    active = vg / "active-runs"
    active.mkdir()
    sid = "test-sess"
    run_id = "test-run-id"
    (active / f"{sid}.json").write_text(json.dumps({
        "run_id": run_id,
        "session_id": sid,
        "command": "vg:build",
        "phase": phase,
        "args": "",
        "started_at": "2026-05-18T05:00:00Z",
    }), encoding="utf-8")
    # current-run pointer (state_mod reads this)
    (vg / "current-run.json").write_text(json.dumps({
        "run_id": run_id,
        "session_id": sid,
        "command": "vg:build",
        "phase": phase,
        "args": "",
    }), encoding="utf-8")
    # events.db schema
    db_path = vg / "events.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            command TEXT,
            phase TEXT,
            args TEXT,
            started_at TEXT,
            completed_at TEXT,
            outcome TEXT,
            session_id TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            ts TEXT,
            event_type TEXT,
            phase TEXT,
            command TEXT,
            step TEXT,
            actor TEXT,
            outcome TEXT,
            payload TEXT
        );
    """)
    conn.execute(
        "INSERT INTO runs (run_id, command, phase, args, started_at, session_id) VALUES (?,?,?,?,?,?)",
        (run_id, "vg:build", phase, "", "2026-05-18T05:00:00Z", sid),
    )
    # Seed required build.completed event so the contract verify passes the
    # must_emit_telemetry gate. (Real runs emit this via build/close.md line 273.)
    conn.execute(
        "INSERT INTO events (run_id, ts, event_type, phase, command, actor, outcome, payload) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (run_id, "2026-05-18T06:00:00Z", "build.completed", phase, "vg:build",
         "cli", "PASS", json.dumps({"phase": phase})),
    )
    conn.commit()
    conn.close()
    return repo


def _run_orch(cmd: list[str], repo: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "VG_REPO_ROOT": str(repo), "VG_PROJECT": str(repo),
           "VG_HOME": str(repo / ".claude"), "VG_NO_CONTRACT_VERIFY": "1"}
    return subprocess.run(
        [sys.executable, str(ORCH), *cmd],
        cwd=repo, capture_output=True, text=True, env=env,
    )


# ---------------------------------------------------------------------------
# Module-level: helper + map exist + correct shape
# ---------------------------------------------------------------------------

def test_b81_flip_map_covers_canonical_pipeline() -> None:
    """The pipeline-flip map must cover every step from specs to accept."""
    body = (ORCH / "__main__.py").read_text(encoding="utf-8")
    expected = ["vg:specs", "vg:scope", "vg:blueprint", "vg:build",
                "vg:review", "vg:test-spec", "vg:test", "vg:accept"]
    for cmd in expected:
        assert f'"{cmd}"' in body, f"flip map missing {cmd}"


def test_b81_flip_helper_signature() -> None:
    body = (ORCH / "__main__.py").read_text(encoding="utf-8")
    assert "def _flip_pipeline_state" in body
    assert "_PIPELINE_FLIP_MAP" in body
    assert "_flip_pipeline_state(command, phase, caller_outcome)" in body, (
        "cmd_run_complete must call the flip helper"
    )


def test_b81_mirror_byte_identical() -> None:
    canonical = (ORCH / "__main__.py").read_bytes()
    mirror = (REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py").read_bytes()
    assert canonical == mirror, "vg-orchestrator/__main__.py mirror drift"


# ---------------------------------------------------------------------------
# Behavioral — actually invoke run-complete and check PIPELINE-STATE
# ---------------------------------------------------------------------------

def _import_orch():
    """Import the orchestrator module so we can call _flip_pipeline_state directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("vg_orch_main", ORCH / "__main__.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ORCH))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


def test_b81_flip_helper_writes_state(tmp_path: Path, monkeypatch) -> None:
    """Direct call: _flip_pipeline_state('vg:build', '8.1', 'PASS') writes
    next_command='/vg:review 8.1' + status=executed + steps.build entry.
    """
    repo = _setup_phase(tmp_path, "8.1", "test-phase")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("VG_REPO_ROOT", str(repo))
    monkeypatch.setenv("VG_PROJECT", str(repo))

    mod = _import_orch()
    # contracts.PHASES_DIR is module-global resolved at import; patch it.
    mod.contracts.PHASES_DIR = repo / ".vg" / "phases"

    ok = mod._flip_pipeline_state("vg:build", "8.1", "PASS")
    assert ok is True

    state_file = repo / ".vg" / "phases" / "8.1-test-phase" / "PIPELINE-STATE.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["next_command"] == "/vg:review 8.1", state
    assert state["status"] == "executed"
    assert state["pipeline_step"] == "build-complete"
    assert state["steps"]["build"]["status"] == "built-complete"
    # Preserved upstream steps untouched
    assert state["steps"]["specs"]["status"] == "done"
    assert state["steps"]["scope"]["status"] == "done"
    assert state["steps"]["blueprint"]["status"] == "done"


def test_b81_flip_helper_returns_false_when_outcome_blocked(tmp_path: Path, monkeypatch) -> None:
    """Block outcome must NOT flip state — retries land in same step."""
    repo = _setup_phase(tmp_path, "8.1", "test-phase")
    monkeypatch.chdir(repo)
    mod = _import_orch()
    mod.contracts.PHASES_DIR = repo / ".vg" / "phases"

    pre = (repo / ".vg" / "phases" / "8.1-test-phase" / "PIPELINE-STATE.json").read_text()
    ok = mod._flip_pipeline_state("vg:build", "8.1", "BLOCK")
    assert ok is False
    post = (repo / ".vg" / "phases" / "8.1-test-phase" / "PIPELINE-STATE.json").read_text()
    assert pre == post, "BLOCK must not mutate PIPELINE-STATE"


def test_b81_flip_helper_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Two consecutive calls reach the same end state."""
    repo = _setup_phase(tmp_path, "8.1", "test-phase")
    monkeypatch.chdir(repo)
    mod = _import_orch()
    mod.contracts.PHASES_DIR = repo / ".vg" / "phases"

    mod._flip_pipeline_state("vg:build", "8.1", "PASS")
    after_first = (repo / ".vg" / "phases" / "8.1-test-phase" / "PIPELINE-STATE.json").read_text()
    mod._flip_pipeline_state("vg:build", "8.1", "PASS")
    after_second = (repo / ".vg" / "phases" / "8.1-test-phase" / "PIPELINE-STATE.json").read_text()
    # Only updated_at + next_command_emitted_at differ. Strip those then compare.
    a = json.loads(after_first); b = json.loads(after_second)
    for k in ("updated_at", "next_command_emitted_at"):
        a.pop(k, None); b.pop(k, None)
    for d in (a, b):
        for sk in d.get("steps", {}).values():
            sk.pop("finished_at", None); sk.pop("updated_at", None)
    assert a == b, f"non-idempotent: {a}\nvs\n{b}"


def test_b81_flip_helper_handles_each_pipeline_step(tmp_path: Path, monkeypatch) -> None:
    """Verify every entry in _PIPELINE_FLIP_MAP produces a valid state write."""
    repo = _setup_phase(tmp_path, "1.0", "smoke")
    monkeypatch.chdir(repo)
    mod = _import_orch()
    mod.contracts.PHASES_DIR = repo / ".vg" / "phases"

    state_file = repo / ".vg" / "phases" / "1.0-smoke" / "PIPELINE-STATE.json"
    for cmd, expected in mod._PIPELINE_FLIP_MAP.items():
        ok = mod._flip_pipeline_state(cmd, "1.0", "PASS")
        assert ok is True, f"{cmd} failed to flip"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["status"] == expected["status"], cmd
        assert state["pipeline_step"] == expected["step"], cmd
        if expected["next"]:
            assert state["next_command"] == expected["next"].format(phase="1.0"), cmd
        # accept has next=None → next_command should still be set (from prior cmd
        # iteration) but pipeline_step=accept-complete confirms terminal.
        if cmd == "vg:accept":
            assert state["pipeline_step"] == "accept-complete"


def test_b81_flip_skips_when_phase_dir_missing(tmp_path: Path, monkeypatch) -> None:
    """Unknown phase → returns False, doesn't crash."""
    repo = _setup_phase(tmp_path, "8.1", "test-phase")
    monkeypatch.chdir(repo)
    mod = _import_orch()
    mod.contracts.PHASES_DIR = repo / ".vg" / "phases"
    ok = mod._flip_pipeline_state("vg:build", "99.99", "PASS")
    assert ok is False
