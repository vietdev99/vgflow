from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DELTA = REPO_ROOT / "scripts" / "test-goal-delta.py"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-codex-test-goal-lane.py"
BLUEPRINT_MD = REPO_ROOT / "commands" / "vg" / "blueprint.md"
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"


def _phase(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "09-goals"
    phase.mkdir(parents=True)
    (phase / "CONTEXT.md").write_text(
        "### P9.D-01 Campaign list\n\n"
        "Users need filterable campaign list.\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: Campaign list (P9.D-01)\n\n"
        "User can filter campaign rows and pagination persists in URL.\n",
        encoding="utf-8",
    )
    return repo


def _run(cmd: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        cmd,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_delta_blocks_when_codex_proposes_uncovered_essential(tmp_path: Path) -> None:
    repo = _phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-goals"
    (phase / "TEST-GOALS.codex-proposal.md").write_text(
        "## Goal G-99: Campaign list hardening (P9.D-01)\n\n"
        "Add authz and rate limit checks for campaign list access.\n",
        encoding="utf-8",
    )

    result = _run([sys.executable, str(DELTA), "--phase-dir", str(phase)], repo)
    delta = (phase / "TEST-GOALS.codex-delta.md").read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "Status: BLOCK" in delta
    assert "authz" in delta
    assert "rate_limit" in delta


def test_delta_passes_after_final_goal_reconciles_terms(tmp_path: Path) -> None:
    repo = _phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-goals"
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: Campaign list (P9.D-01)\n\n"
        "User can filter campaign rows, pagination persists in URL, "
        "authz prevents cross-tenant access, and rate limit protects list API.\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.codex-proposal.md").write_text(
        "## Goal G-99: Campaign list hardening (P9.D-01)\n\n"
        "Add authz and rate limit checks for campaign list access.\n",
        encoding="utf-8",
    )

    result = _run([sys.executable, str(DELTA), "--phase-dir", str(phase)], repo)
    delta = (phase / "TEST-GOALS.codex-delta.md").read_text(encoding="utf-8")

    assert result.returncode == 0
    assert "Status: PASS" in delta


def test_codex_lane_validator_blocks_unresolved_delta(tmp_path: Path) -> None:
    repo = _phase(tmp_path)
    phase = repo / ".vg" / "phases" / "09-goals"
    (phase / "TEST-GOALS.codex-proposal.md").write_text(
        "## Goal G-99: Campaign list hardening (P9.D-01)\n\n"
        "Add authz and rate limit checks.\n",
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.codex-delta.md").write_text(
        "# Codex Test Goal Delta - 09-goals\n\n"
        "## Unresolved Items\n\n"
        "- P9.D-01: proposal covers authz, final does not\n"
        "- P9.D-01: proposal covers rate_limit, final does not\n\n"
        "Status: BLOCK\n",
        encoding="utf-8",
    )

    result = _run([sys.executable, str(VALIDATOR), "--phase", "09"], repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["verdict"] == "BLOCK"
    assert any(e["type"] == "delta_unresolved" for e in payload["evidence"])


def test_blueprint_and_orchestrator_wire_codex_goal_lane() -> None:
    blueprint = BLUEPRINT_MD.read_text(encoding="utf-8")
    orch = ORCH.read_text(encoding="utf-8")

    assert "2b5a_codex_test_goal_lane" in blueprint
    assert "TEST-GOALS.codex-proposal.md" in blueprint
    assert "TEST-GOALS.codex-delta.md" in blueprint
    assert "test-goal-delta.py" in blueprint
    assert "--skip-codex-test-goal-lane" in blueprint
    assert "verify-codex-test-goal-lane" in orch
