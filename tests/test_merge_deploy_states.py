"""v2.85.0 Stage 7.1 — merge-deploy-states.py migration helper tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "migrate" / "merge-deploy-states.py"


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, r.stdout, r.stderr


def _seed_phase_state(project: Path, phase: str, deployed: dict, **kwargs) -> None:
    phase_dir = project / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    state = {"deployed": deployed, **kwargs}
    (phase_dir / "DEPLOY-STATE.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


def test_no_phase_states_returns_2(tmp_path):
    rc, out, err = _run(["--project-root", str(tmp_path), "--dry-run"])
    assert rc == 2
    assert "no per-phase" in err.lower()


def test_dry_run_merges_single_phase(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "abc", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    rc, out, err = _run(["--project-root", str(tmp_path), "--dry-run"])
    assert rc == 0
    parsed = json.loads(out)
    assert parsed["envs"]["fly.io"]["sha"] == "abc"
    assert parsed["envs"]["fly.io"]["phase_context"] == "5"


def test_dry_run_does_not_write_state_json(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "abc", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    _run(["--project-root", str(tmp_path), "--dry-run"])
    assert not (tmp_path / ".vg" / "deploy" / "STATE.json").exists()


def test_latest_deploy_wins_across_phases(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "old", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    _seed_phase_state(
        tmp_path,
        "6",
        {"fly.io": {"sha": "new", "deployed_at": "2026-05-10T12:00:00Z"}},
    )
    rc, out, err = _run(["--project-root", str(tmp_path)])
    assert rc == 0, f"err={err}"
    written = json.loads(
        (tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8")
    )
    assert written["envs"]["fly.io"]["sha"] == "new"
    assert written["envs"]["fly.io"]["phase_context"] == "6"


def test_preferred_env_per_phase_carried_over(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "abc", "deployed_at": "2026-05-10T10:00:00Z"}},
        preferred_env_for="fly.io",
    )
    rc, out, err = _run(["--project-root", str(tmp_path)])
    assert rc == 0, f"err={err}"
    written = json.loads(
        (tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8")
    )
    assert written["preferred_env_for_phase"]["5"] == "fly.io"


def test_multiple_envs_merged(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {
            "fly.io": {"sha": "a", "deployed_at": "2026-05-10T10:00:00Z"},
            "staging": {"sha": "b", "deployed_at": "2026-05-10T11:00:00Z"},
        },
    )
    rc, out, err = _run(["--project-root", str(tmp_path)])
    assert rc == 0
    written = json.loads(
        (tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8")
    )
    assert set(written["envs"].keys()) == {"fly.io", "staging"}


def test_skips_corrupt_phase_state(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "abc", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    bad = tmp_path / ".vg" / "phases" / "9" / "DEPLOY-STATE.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json}", encoding="utf-8")
    rc, out, err = _run(["--project-root", str(tmp_path)])
    assert rc == 0
    assert "skipping" in err.lower()
    written = json.loads(
        (tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8")
    )
    assert "fly.io" in written["envs"]


def test_backup_flag_creates_bak(tmp_path):
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "abc", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    # First run — no prior STATE.json to back up
    _run(["--project-root", str(tmp_path)])
    # Re-run with --backup
    _seed_phase_state(
        tmp_path,
        "5",
        {"fly.io": {"sha": "def", "deployed_at": "2026-05-10T12:00:00Z"}},
    )
    rc, out, err = _run(["--project-root", str(tmp_path), "--backup"])
    assert rc == 0
    backups = list((tmp_path / ".vg" / "deploy").glob("STATE.json.bak.*"))
    assert len(backups) == 1


def test_phase_context_added_when_missing(tmp_path):
    """Old per-phase entries didn't track phase_context — helper auto-fills."""
    _seed_phase_state(
        tmp_path,
        "12",
        {"prod": {"sha": "xyz", "deployed_at": "2026-05-10T10:00:00Z"}},
    )
    rc, out, err = _run(["--project-root", str(tmp_path)])
    assert rc == 0
    written = json.loads(
        (tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8")
    )
    assert written["envs"]["prod"]["phase_context"] == "12"
