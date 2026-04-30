"""Verify spawn_recursive_probe.py falls back to vg.config review.target_env
when --target-env is omitted (Task 26f wiring).

Resolution priority:
  1. --target-env CLI flag
  2. ${PHASE_DIR}/../../config/vg.config.md  (project repo)
  3. ${PHASE_DIR}/../../vg.config.md         (repo root)
  4. baseline default 'sandbox'
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


def _seed(tmp_path: Path, *, config_target_env: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    phase = repo / ".vg" / "phases" / "1"
    shutil.copytree(FIXTURE, phase)
    (phase / ".phase-profile").write_text(
        "phase_profile: feature\nsurface: ui\n", encoding="utf-8"
    )
    if config_target_env is not None:
        cfg = repo / "vg.config.md"
        cfg.write_text(
            "# vg.config\n\n```yaml\nreview:\n"
            f"  target_env: \"{config_target_env}\"\n"
            "```\n",
            encoding="utf-8",
        )
    return phase


def _run(phase: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--phase-dir", str(phase), "--dry-run", "--json", *args],
        capture_output=True, text=True,
    )


def test_cli_overrides_config(tmp_path: Path) -> None:
    phase = _seed(tmp_path, config_target_env="staging")
    r = _run(phase, "--target-env", "local")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["target_env"] == "local"


def test_config_fallback_when_cli_omitted(tmp_path: Path) -> None:
    phase = _seed(tmp_path, config_target_env="staging")
    r = _run(phase)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    # Without --target-env, the repo-root vg.config.md staging value wins.
    assert payload["target_env"] == "staging", payload


def test_default_when_no_config(tmp_path: Path) -> None:
    phase = _seed(tmp_path, config_target_env=None)
    r = _run(phase)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    # No CLI, no config → baseline default 'sandbox'.
    assert payload["target_env"] == "sandbox", payload
