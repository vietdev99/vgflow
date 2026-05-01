"""Tests for verify-backend-mutation-evidence.py — RFC v9 PR-Z."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-backend-mutation-evidence.py"


def _run(repo: Path, phase: str, *flags: str) -> tuple[int, dict]:
    cmd = [sys.executable, str(VALIDATOR), "--phase", phase, *flags]
    proc = subprocess.run(
        cmd,
        env={"VG_REPO_ROOT": str(repo), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"verdict": "PARSE_ERROR", "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, out


def _phase(tmp_path: Path, surface: str, sequences: dict) -> Path:
    phases_dir = tmp_path / ".vg" / "phases"
    phase_dir = phases_dir / "99.9-backend"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(
        f"## Goal G-01: Backend goal\n"
        f"**Surface:** {surface}\n"
        f"**Mutation evidence:** POST /api/x → 200\n",
        encoding="utf-8",
    )
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps({"goal_sequences": sequences}), encoding="utf-8",
    )
    return phase_dir


def _good_step(surface: str = "api") -> dict:
    step = {
        "replay": {
            "method": "POST",
            "endpoint": "/api/x",
            "status": 200,
            "captured_at": "2026-05-02T10:00:00Z",
        },
        "evidence": {
            "source": "scanner",
            "artifact_hash": "sha256:abcdef",
            "captured_at": "2026-05-02T10:00:00Z",
            "scanner_run_id": "haiku-r1",
            "schema_version": "1.0",
        },
    }
    if surface == "data":
        step["replay"]["side_effect_resource"] = {"count_query": "SELECT COUNT(*)", "count": 1}
    return step


def test_complete_api_evidence_passes(tmp_path):
    repo = tmp_path
    _phase(repo, "api", {"G-01": {"steps": [_good_step("api")]}})
    rc, out = _run(repo, "99.9")
    assert rc == 0, out
    assert out["verdict"] in ("PASS", "WARN")


def test_data_surface_requires_side_effect_resource(tmp_path):
    repo = tmp_path
    step = _good_step("api")  # missing side_effect_resource
    _phase(repo, "data", {"G-01": {"steps": [step]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "side_effect_resource_missing" in types


def test_missing_replay_blocks(tmp_path):
    repo = tmp_path
    _phase(repo, "api", {"G-01": {"steps": [{"evidence": {"source": "scanner"}}]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "replay_missing" in types


def test_missing_evidence_blocks(tmp_path):
    repo = tmp_path
    step = _good_step("api")
    del step["evidence"]
    _phase(repo, "api", {"G-01": {"steps": [step]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "evidence_missing" in types


def test_manual_source_rejected_for_backend(tmp_path):
    repo = tmp_path
    step = _good_step("api")
    step["evidence"]["source"] = "manual"
    _phase(repo, "api", {"G-01": {"steps": [step]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "evidence_source_invalid_for_backend" in types


def test_status_4xx_blocks(tmp_path):
    repo = tmp_path
    step = _good_step("api")
    step["replay"]["status"] = 422
    _phase(repo, "api", {"G-01": {"steps": [step]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "replay_status_not_2xx" in types


def test_ui_surface_skipped(tmp_path):
    """UI goals are not the responsibility of this validator."""
    repo = tmp_path
    phases_dir = repo / ".vg" / "phases"
    phase_dir = phases_dir / "99.9-ui"
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-01: UI\n**Surface:** ui\n**Mutation evidence:** click submit\n",
        encoding="utf-8",
    )
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps({"goal_sequences": {"G-01": {"steps": []}}}),
        encoding="utf-8",
    )
    rc, out = _run(repo, "99.9")
    assert rc == 0  # UI not flagged here
    msg = " ".join(e.get("message", "") for e in out["evidence"])
    assert "0 backend mutation goals" in msg


def test_warn_severity_downgrades(tmp_path):
    repo = tmp_path
    _phase(repo, "api", {"G-01": {"steps": [{"evidence": {"source": "scanner"}}]}})
    rc, out = _run(repo, "99.9", "--severity", "warn")
    assert rc == 0
    assert out["verdict"] in ("WARN", "PASS")
    types = [e["type"] for e in out["evidence"]]
    assert "severity_downgraded" in types


def test_missing_goal_sequence_blocks(tmp_path):
    repo = tmp_path
    _phase(repo, "api", {})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "goal_sequence_missing" in types


def test_no_mutation_step_blocks(tmp_path):
    repo = tmp_path
    # Step without replay or evidence — neutral; produces no_mutation_step error
    _phase(repo, "api", {"G-01": {"steps": [{"do": "nothing"}]}})
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out["evidence"]]
    assert "no_mutation_step" in types
