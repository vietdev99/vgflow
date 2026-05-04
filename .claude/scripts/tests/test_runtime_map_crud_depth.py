"""Regression tests for verify-runtime-map-crud-depth.py."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-runtime-map-crud-depth.py"


def _phase(repo: Path) -> Path:
    phase = repo / ".vg" / "phases" / "09-crud"
    phase.mkdir(parents=True, exist_ok=True)
    return phase


def _write_goals(phase: Path, body: str | None = None) -> None:
    phase.joinpath("TEST-GOALS.md").write_text(
        body
        or (
            "## Goal G-01: Create campaign\n\n"
            "**Surface:** ui\n\n"
            "**Start view:** /campaigns\n\n"
            "**Success criteria:** Created campaign appears in the list.\n\n"
            "**Mutation evidence:** POST /api/campaigns returns 201 and row count +1.\n\n"
            "**Persistence check:** Reload and re-read the campaign row.\n"
        ),
        encoding="utf-8",
    )


def _write_runtime(phase: Path, sequence: dict) -> None:
    phase.joinpath("RUNTIME-MAP.json").write_text(
        json.dumps({"views": {}, "goal_sequences": {"G-01": sequence}}, indent=2),
        encoding="utf-8",
    )


def _write_crud_surfaces(phase: Path) -> None:
    phase.joinpath("CRUD-SURFACES.md").write_text(
        "```json\n"
        + json.dumps(
            {
                "version": "1",
                "resources": [
                    {
                        "name": "Campaign",
                        "operations": ["list", "create", "update", "delete"],
                        "platforms": {
                            "web": {
                                "list": {
                                    "route": "/campaigns",
                                    "heading": "Campaigns",
                                    "table": {"columns": ["name", "status"]},
                                }
                            }
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n```\n",
        encoding="utf-8",
    )


def _run(repo: Path, phase: str = "9", extra_args: list[str] | None = None) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase] + (extra_args or []),
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return proc.returncode, payload


def _evidence_types(payload: dict) -> set[str]:
    return {e["type"] for e in payload.get("evidence", [])}


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = Path("C:/Program Files/Git/usr/bin/bash.exe")
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


def _shell_path(path: Path) -> str:
    return path.resolve().as_posix()


def test_passed_mutation_goal_with_list_only_sequence_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goals(phase)
    _write_runtime(
        phase,
        {
            "result": "passed",
            "start_view": "/campaigns",
            "steps": [
                {"action": "goto", "url": "/campaigns"},
                {"assert": "Campaigns table visible"},
            ],
            "network": [{"method": "GET", "url": "/api/campaigns", "status": 200}],
        },
    )

    rc, payload = _run(tmp_path)

    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert "runtime_crud_no_mutation_network" in _evidence_types(payload)


def test_mutation_network_without_persistence_probe_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goals(phase)
    _write_runtime(
        phase,
        {
            "result": "passed",
            "steps": [
                {"action": "click", "target": "Create"},
                {"action": "fill", "target": "Name", "value": "Launch"},
                {"action": "click", "target": "Save"},
            ],
            "network": [{"method": "POST", "url": "/api/campaigns", "status": 201}],
        },
    )

    rc, payload = _run(tmp_path)

    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert "runtime_crud_no_persistence_probe" in _evidence_types(payload)


def test_mutation_network_with_persistence_probe_passes(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goals(phase)
    _write_runtime(
        phase,
        {
            "result": "passed",
            "steps": [
                {"action": "click", "target": "Create"},
                {"action": "click", "target": "Save"},
                {
                    "action": "reload",
                    "persistence_probe": {
                        "persisted": True,
                        "method": "reload_and_re_read",
                    },
                },
            ],
            "network": [{"method": "POST", "url": "/api/campaigns", "status": 201}],
        },
    )

    rc, payload = _run(tmp_path)

    assert rc == 0, payload
    assert payload["verdict"] == "PASS"


def test_crud_surface_goal_without_per_goal_sequence_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_crud_surfaces(phase)
    _write_goals(
        phase,
        (
            "## Goal G-01: Campaign list renders table columns\n\n"
            "**Surface:** ui\n\n"
            "**Start view:** /campaigns\n\n"
            "**Success criteria:** Campaign table shows name and status columns.\n\n"
            "**Mutation evidence:** none\n"
        ),
    )
    phase.joinpath("RUNTIME-MAP.json").write_text(
        json.dumps(
            {
                "views": {},
                "goal_sequences": {
                    "campaign_surfaces": {
                        "result": "passed",
                        "steps": [{"action": "goto", "url": "/campaigns"}],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rc, payload = _run(tmp_path)

    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert "runtime_crud_sequence_missing" in _evidence_types(payload)
    assert "campaign_surfaces" in json.dumps(payload["evidence"])


def test_structural_fallback_allows_non_mutation_crud_missing_sequence(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_crud_surfaces(phase)
    _write_goals(
        phase,
        (
            "## Goal G-01: Campaign list renders table columns\n\n"
            "**Surface:** ui\n\n"
            "**Start view:** /campaigns\n\n"
            "**Success criteria:** Campaign table shows name and status columns.\n\n"
            "**Mutation evidence:** none\n"
        ),
    )
    phase.joinpath("RUNTIME-MAP.json").write_text(
        json.dumps({"views": {}, "goal_sequences": {}}, indent=2),
        encoding="utf-8",
    )

    rc, payload = _run(tmp_path, extra_args=["--allow-structural-fallback"])

    assert rc == 0, payload
    assert payload["verdict"] == "PASS"


def test_structural_fallback_still_blocks_mutation_missing_sequence(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_crud_surfaces(phase)
    _write_goals(phase)
    phase.joinpath("RUNTIME-MAP.json").write_text(
        json.dumps({"views": {}, "goal_sequences": {}}, indent=2),
        encoding="utf-8",
    )

    rc, payload = _run(tmp_path, extra_args=["--allow-structural-fallback"])

    assert rc == 1
    assert payload["verdict"] == "BLOCK"
    assert "runtime_crud_sequence_missing" in _evidence_types(payload)


def test_matrix_merger_downgrades_list_only_crud_goal(tmp_path: Path) -> None:
    bash = _bash()
    if bash is None:
        pytest.skip("bash is required for matrix-merger integration test")

    phase = _phase(tmp_path)
    _write_goals(phase)
    _write_runtime(
        phase,
        {
            "result": "passed",
            "start_view": "/campaigns",
            "steps": [{"action": "goto", "url": "/campaigns"}],
            "network": [{"method": "GET", "url": "/api/campaigns", "status": 200}],
        },
    )
    phase.joinpath(".surface-probe-results.json").write_text("{}", encoding="utf-8")
    output = phase / "GOAL-COVERAGE-MATRIX.md"
    runner = tmp_path / "run-matrix.sh"
    runner.write_text(
        "\n".join(
            [
                "set -euo pipefail",
                f'source "{_shell_path(REPO_ROOT / "commands/vg/_shared/lib/matrix-merger.sh")}"',
                "PYTHON_BIN=python",
                (
                    f'merge_and_write_matrix "{_shell_path(phase)}" '
                    f'"{_shell_path(phase / "TEST-GOALS.md")}" '
                    f'"{_shell_path(phase / "RUNTIME-MAP.json")}" '
                    f'"{_shell_path(phase / ".surface-probe-results.json")}" '
                    f'"{_shell_path(output)}"'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [bash, str(runner)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    matrix = output.read_text(encoding="utf-8")
    assert "VERDICT=BLOCK" in proc.stdout
    assert "| G-01 | important | ui | BLOCKED | shallow CRUD evidence" in matrix


def test_matrix_merger_ignores_none_mutation_evidence(tmp_path: Path) -> None:
    bash = _bash()
    if bash is None:
        pytest.skip("bash is required for matrix-merger integration test")

    phase = _phase(tmp_path)
    _write_goals(
        phase,
        (
            "## Goal G-01: Campaign list renders\n\n"
            "**Surface:** ui\n\n"
            "**Start view:** /campaigns\n\n"
            "**Success criteria:** Existing campaigns are visible.\n\n"
            "**Mutation evidence:** none\n"
        ),
    )
    _write_runtime(
        phase,
        {
            "result": "passed",
            "steps": [{"action": "goto", "url": "/campaigns"}],
            "network": [{"method": "GET", "url": "/api/campaigns", "status": 200}],
        },
    )
    phase.joinpath(".surface-probe-results.json").write_text("{}", encoding="utf-8")
    output = phase / "GOAL-COVERAGE-MATRIX.md"
    runner = tmp_path / "run-matrix-read-only.sh"
    runner.write_text(
        "\n".join(
            [
                "set -euo pipefail",
                f'source "{_shell_path(REPO_ROOT / "commands/vg/_shared/lib/matrix-merger.sh")}"',
                "PYTHON_BIN=python",
                (
                    f'merge_and_write_matrix "{_shell_path(phase)}" '
                    f'"{_shell_path(phase / "TEST-GOALS.md")}" '
                    f'"{_shell_path(phase / "RUNTIME-MAP.json")}" '
                    f'"{_shell_path(phase / ".surface-probe-results.json")}" '
                    f'"{_shell_path(output)}"'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [bash, str(runner)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    matrix = output.read_text(encoding="utf-8")
    assert "VERDICT=PASS" in proc.stdout
    assert "| G-01 | important | ui | READY | browser: 1 steps |" in matrix


def test_read_only_goal_does_not_require_mutation_layers(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goals(
        phase,
        (
            "## Goal G-01: Campaign list renders\n\n"
            "**Surface:** ui\n\n"
            "**Start view:** /campaigns\n\n"
            "**Success criteria:** Existing campaigns are visible.\n\n"
            "**Mutation evidence:** none\n"
        ),
    )
    _write_runtime(
        phase,
        {
            "result": "passed",
            "network": [{"method": "GET", "url": "/api/campaigns", "status": 200}],
        },
    )

    rc, payload = _run(tmp_path)

    assert rc == 0, payload
    assert payload["verdict"] == "PASS"
