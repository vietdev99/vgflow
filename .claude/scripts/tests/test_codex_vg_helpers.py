from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_HELPER = REPO_ROOT / "scripts" / "codex-vg-env.py"
PLAN_PREP = REPO_ROOT / "scripts" / "codex-blueprint-plan-prep.py"


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    phase = repo / ".vg" / "phases" / "1-codex-fixture-cli-health"
    (repo / ".claude" / "scripts").mkdir(parents=True)
    phase.mkdir(parents=True)
    (repo / ".claude" / "vg.config.md").write_text(
        "---\n"
        "project_name: Codex Fixture\n"
        "package_manager: none\n"
        "profile: cli-tool\n"
        "paths:\n"
        "  planning_dir: .vg\n"
        "  phases_dir: .vg/phases\n"
        "---\n",
        encoding="utf-8",
    )
    (phase / "SPECS.md").write_text(
        "---\n"
        "profile: feature\n"
        "platform: cli-tool\n"
        "---\n"
        "# Specs\n",
        encoding="utf-8",
    )
    (phase / "CONTEXT.md").write_text(
        "# Context\n\n"
        "### P1.D-01\n\n"
        "**Endpoints:** none\n"
        "**Test Scenarios:** CLI smoke exits 0\n",
        encoding="utf-8",
    )
    return repo


def test_codex_vg_env_resolves_slugged_phase_and_cli_profile(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ENV_HELPER), "--phase", "1", "--format", "json"],
        cwd=repo,
        env={**os.environ},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["PHASE_DIR"].endswith(".vg/phases/1-codex-fixture-cli-health")
    assert payload["phase_dir"] == "1-codex-fixture-cli-health"
    assert payload["PROFILE"] == "cli-tool"
    assert payload["PHASE_PROFILE"] == "cli-tool"
    assert "UI-SPEC.md" in payload["SKIP_ARTIFACTS"]


def test_codex_blueprint_plan_prep_uses_orchestrator_and_writes_briefs(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    orch = repo / ".claude" / "scripts" / "vg-orchestrator"
    orch.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "log = Path('.vg/orchestrator.log')\n"
        "log.parent.mkdir(parents=True, exist_ok=True)\n"
        "with log.open('a', encoding='utf-8') as fh:\n"
        "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "print('active: 2a_plan')\n",
        encoding="utf-8",
    )
    orch.chmod(0o755)

    result = subprocess.run(
        [sys.executable, str(PLAN_PREP), "--phase", "1", "--arguments", "1"],
        cwd=repo,
        env={**os.environ},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    phase = repo / ".vg" / "phases" / "1-codex-fixture-cli-health"
    assert (phase / ".graphify-brief.md").exists()
    assert (phase / ".deploy-lessons-brief.md").exists()
    assert (phase / ".tmp" / "bootstrap-rules-blueprint.md").exists()
    assert (phase / ".tmp" / "codex-blueprint-plan-prep.json").exists()
    assert payload["context"]["decisions"] == 1
    assert payload["phase_profile"] == "cli-tool"
    assert "step-active 2a_plan" in (repo / ".vg" / "orchestrator.log").read_text(encoding="utf-8")
