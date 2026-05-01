"""Tests for scripts/spawn-diagnostic-l2.py — RFC v9 PR-D3."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn-diagnostic-l2.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime.diagnostic_l2 import load_proposal, proposal_dir  # noqa: E402


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "PYTHONPATH": str(REPO_ROOT / "scripts")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _make_stub_cli(tmp_path: Path, response: str) -> str:
    """Create a python script that, when run, prints `response` on stdout.

    Returns the shlex-joined command for --cli override.
    """
    stub = tmp_path / "stub_cli.py"
    stub.write_text(
        f"import sys\nprint({response!r})\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {stub}"


def test_dry_run_emits_stub_proposal(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--gate-context", "test gate",
        "--evidence-json", '{"goal":"G-10"}',
        "--dry-run",
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["confidence"] == 0.0
    assert out["proposal_id"].startswith("l2-")
    # File written
    pid = out["proposal_id"]
    proposal = load_proposal(phase_dir, pid)
    assert proposal.gate_id == "missing-evidence"


def test_live_invocation_with_stub_cli(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({
        "diagnosis": "Mutation step at G-10/step[2] missing evidence.source",
        "proposed_fix": "Re-run scanner with /vg:review --re-scan-goals=G-10",
        "confidence": 0.85,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--gate-context", "G-10 lacks evidence after retry",
        "--evidence-json", '{"goal":"G-10"}',
        "--cli", cli_cmd,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = json.loads(result.stdout)
    assert out["confidence"] == 0.85
    assert "Re-run scanner" in out["proposed_fix"]
    proposal = load_proposal(phase_dir, out["proposal_id"])
    assert proposal.confidence == 0.85
    assert proposal.diagnosis.startswith("Mutation step")


def test_subagent_returns_short_diagnosis_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({"diagnosis": "x", "proposed_fix": "y", "confidence": 0.5})
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "too short" in json.loads(result.stdout)["error"]


def test_subagent_confidence_out_of_range(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    response = json.dumps({
        "diagnosis": "long enough diagnosis text",
        "proposed_fix": "long enough proposed fix text",
        "confidence": 1.5,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "out of range" in json.loads(result.stdout)["error"]


def test_subagent_missing_fields_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Missing confidence
    response = json.dumps({
        "diagnosis": "long enough diagnosis text",
        "proposed_fix": "long enough proposed fix text",
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "missing fields" in json.loads(result.stdout)["error"]


def test_subagent_emits_prose_around_json_still_parses(tmp_path):
    """Tolerance for models that wrap JSON in prose despite our instruction."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    json_block = json.dumps({
        "diagnosis": "long enough diagnosis here",
        "proposed_fix": "long enough proposed fix here",
        "confidence": 0.7,
    })
    response = f"Here's my analysis:\\n\\n{json_block}\\n\\nLet me know if you need more."
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"


def test_subagent_invalid_json_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    cli_cmd = _make_stub_cli(tmp_path, "not json at all")
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "not valid JSON" in json.loads(result.stdout)["error"]


def test_subagent_nonzero_exit_fails(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    failing = tmp_path / "fail.py"
    failing.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    cli_cmd = f"{sys.executable} {failing}"
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "{}",
        "--cli", cli_cmd,
    )
    assert result.returncode == 1
    assert "exited 2" in json.loads(result.stdout)["error"]


def test_phase_dir_missing_returns_2(tmp_path):
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(tmp_path / "nonexistent"),
        "--evidence-json", "{}",
        "--dry-run",
    )
    assert result.returncode == 2


def test_invalid_evidence_json_returns_2(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    result = _run(
        "--gate-id", "g", "--block-family", "f",
        "--phase-dir", str(phase_dir),
        "--evidence-json", "not json",
        "--dry-run",
    )
    assert result.returncode == 2


def test_proposal_persisted_with_evidence_round_trip(tmp_path):
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    evidence = {"goal": "G-10", "step_idx": 2, "fail_reason": "no source"}
    response = json.dumps({
        "diagnosis": "Step 2 of G-10 missing scanner source field",
        "proposed_fix": "Re-run scanner; ensure verify-evidence-provenance threshold met",
        "confidence": 0.92,
    })
    cli_cmd = _make_stub_cli(tmp_path, response)
    result = _run(
        "--gate-id", "missing-evidence",
        "--block-family", "provenance",
        "--phase-dir", str(phase_dir),
        "--evidence-json", json.dumps(evidence),
        "--cli", cli_cmd,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    proposal = load_proposal(phase_dir, out["proposal_id"])
    assert proposal.evidence_in == evidence
    assert proposal.confidence == 0.92
    assert proposal.gate_id == "missing-evidence"
