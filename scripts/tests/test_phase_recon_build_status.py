from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "phase-recon.py"


def _run_recon(phase_dir: Path, *, json_only: bool = False) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--phase-dir",
        str(phase_dir),
        "--profile",
        "web-fullstack",
    ]
    if json_only:
        cmd.append("--json-only")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        cwd=str(REPO_ROOT),
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _base_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "04.3-test-phase"
    phase_dir.mkdir(parents=True, exist_ok=True)
    _write(phase_dir / "SPECS.md", "# Specs\n")
    _write(phase_dir / "CONTEXT.md", "# Context\n")
    _write(phase_dir / "PLAN.md", "# Plan\n")
    _write(phase_dir / "API-CONTRACTS.md", "# Contracts\n")
    _write(phase_dir / "TEST-GOALS.md", "# Goals\n")
    return phase_dir


def test_build_requires_late_stage_evidence_not_preflight_marker(tmp_path: Path) -> None:
    phase_dir = _base_phase(tmp_path)
    _write(phase_dir / "SUMMARY.md", "# Build Summary\n")
    _write(
        phase_dir / ".step-markers" / "1a_build_queue_preflight.done",
        "v1|4.3|1a_build_queue_preflight|nogit|2026-05-06T00:00:00Z|run-1\n",
    )

    result = _run_recon(phase_dir, json_only=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["pipeline_position"]["build"]["status"] == "partial"
    assert data["recommended_action"]["step"] == "build"


def test_build_done_from_final_marker_and_pipeline_state(tmp_path: Path) -> None:
    phase_dir = _base_phase(tmp_path)
    _write(phase_dir / "SUMMARY.md", "# Build Summary\n")
    _write(phase_dir / "PRE-TEST-REPORT.md", "# Pre-Test Report\n")
    _write(phase_dir / ".build-progress.json", '{"phase":"4.3","current_wave":2}\n')
    _write(
        phase_dir / "PIPELINE-STATE.json",
        json.dumps({"status": "reviewing", "pipeline_step": "review"}),
    )
    _write(
        phase_dir / ".step-markers" / "build" / "12_run_complete.done",
        "v1|4.3|12_run_complete|nogit|2026-05-06T00:00:00Z|run-1\n",
    )

    result = _run_recon(phase_dir, json_only=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    build = data["pipeline_position"]["build"]
    assert build["status"] == "done"
    assert build["marker_present"] is True
    assert build["evidence"]["complete_marker"] is True
    assert data["recommended_action"]["step"] == "review"


def test_cache_invalidates_when_nested_marker_changes(tmp_path: Path) -> None:
    phase_dir = _base_phase(tmp_path)
    _write(phase_dir / "SUMMARY.md", "# Build Summary\n")

    first = _run_recon(phase_dir)
    assert first.returncode == 0, first.stderr
    initial_state = json.loads((phase_dir / ".recon-state.json").read_text(encoding="utf-8"))
    assert initial_state["pipeline_position"]["build"]["status"] == "partial"

    _write(
        phase_dir / ".step-markers" / "build" / "12_run_complete.done",
        "v1|4.3|12_run_complete|nogit|2026-05-06T00:00:00Z|run-1\n",
    )

    second = _run_recon(phase_dir)
    assert second.returncode == 0, second.stderr
    refreshed_state = json.loads((phase_dir / ".recon-state.json").read_text(encoding="utf-8"))
    assert refreshed_state["fingerprint"] != initial_state["fingerprint"]
    assert refreshed_state["pipeline_position"]["build"]["evidence"]["complete_marker"] is True
