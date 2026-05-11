from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_MERGER = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "matrix-merger.sh"
REQUIRED_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "update",
    "read_after_update",
    "delete",
    "read_after_delete",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _lifecycle_goal(*, family: str = "web", runner: str = "playwright", surface: str = "ui") -> dict:
    return {
        "title": "Closed-loop resource lifecycle",
        "priority": "important",
        "goal_type": "mutation",
        "surface": surface,
        "actors": [{"id": "owner", "role": "owner", "session": "owner_session"}],
        "fixture_dag": [
            {"id": "owner_session", "kind": "auth", "depends_on": [], "cleanup": "revoke"},
            {"id": "resource", "kind": "state", "depends_on": ["owner_session"], "cleanup": "delete"},
        ],
        "steps": [
            {"stage": stage, "actor": "owner", "action": stage, "evidence": ["proof"]}
            for stage in REQUIRED_STAGES
        ],
        "artifact_capture": [],
        "cleanup": [{"target": "resource", "action": "delete"}],
        "execution_plan": {
            "profile": "web-fullstack" if family == "web" else "cli-tool",
            "family": family,
            "runner": runner,
            "entrypoints": ["/resource" if family == "web" else "resource-cli"],
            "assertions": ["execute every lifecycle stage in order"],
            "artifacts": ["trace" if family == "web" else "stdout"],
        },
    }


def _write_deep_specs(phase: Path, goals: dict[str, dict]) -> None:
    _write_json(
        phase / "LIFECYCLE-SPECS.json",
        {
            "schema_version": "1.0",
            "phase": phase.name,
            "phase_profile": "mixed",
            "goals": goals,
        },
    )
    _write_json(
        phase / "TEST-FIXTURE-DAG.json",
        {
            "schema_version": "1.0",
            "nodes": [{"id": f"{gid}:resource", "goal": gid} for gid in goals],
            "edges": [],
        },
    )
    _write_json(
        phase / "TEST-EXECUTION-PLAN.json",
        {
            "schema_version": "1.0",
            "phase": phase.name,
            "phase_profile": "mixed",
            "goals": {
                gid: spec["execution_plan"]
                for gid, spec in goals.items()
            },
        },
    )
    _write(phase / "DEEP-TEST-SPECS.md", "# Deep Test Specs\n\nLifecycle contract present.\n")


def _run_matrix(phase: Path) -> tuple[str, str]:
    bash = shutil.which("bash") or "/bin/bash"
    if not Path(bash).exists():
        pytest.skip("bash unavailable")
    output = phase / "GOAL-COVERAGE-MATRIX.md"
    cmd = (
        "set -euo pipefail; "
        f"source '{MATRIX_MERGER.as_posix()}'; "
        f"merge_and_write_matrix '{phase.as_posix()}' "
        f"'{(phase / 'TEST-GOALS.md').as_posix()}' "
        f"'{(phase / 'RUNTIME-MAP.json').as_posix()}' "
        f"'{(phase / '.surface-probe-results.json').as_posix()}' "
        f"'{output.as_posix()}'"
    )
    proc = subprocess.run(
        [bash, "-c", cmd],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, output.read_text(encoding="utf-8")


def test_review_matrix_consumes_lifecycle_specs_for_runtime_clean_goal(tmp_path: Path) -> None:
    phase = tmp_path / "06-lifecycle"
    _write(
        phase / "TEST-GOALS.md",
        """
        # Test Goals

        ## Goal G-01: Resource can be managed
        **Priority:** important
        **Surface:** ui

        **Success criteria:** Resource appears in the list.
        """,
    )
    _write_json(
        phase / "RUNTIME-MAP.json",
        {
            "views": {},
            "goal_sequences": {
                "G-01": {
                    "result": "passed",
                    "steps": [{"do": "goto", "url": "/resource"}],
                    "network": [{"method": "GET", "url": "/api/resource", "status": 200}],
                }
            },
        },
    )
    _write_json(phase / ".surface-probe-results.json", {"results": {}})
    _write_deep_specs(phase, {"G-01": _lifecycle_goal()})

    stdout, matrix = _run_matrix(phase)

    assert "VERDICT=TEST_PENDING" in stdout
    assert "LIFECYCLE_CONTRACTS=1" in stdout
    assert "| G-01 | important | ui | TEST_PENDING | lifecycle contract pending" in matrix
    assert "LIFECYCLE-SPECS.json/TEST-FIXTURE-DAG.json/TEST-EXECUTION-PLAN.json" in matrix


def test_review_matrix_uses_runner_family_for_lifecycle_only_goal(tmp_path: Path) -> None:
    phase = tmp_path / "07-cli"
    _write(
        phase / "TEST-GOALS.md",
        """
        # Test Goals

        Legacy parser could not extract the lifecycle goal from this shape.
        """,
    )
    _write_json(phase / "RUNTIME-MAP.json", {"views": {}, "goal_sequences": {}})
    _write_json(phase / ".surface-probe-results.json", {"results": {}})
    _write_deep_specs(
        phase,
        {
            "G-02": _lifecycle_goal(
                family="cli",
                runner="cli",
                surface="cli",
            )
        },
    )

    stdout, matrix = _run_matrix(phase)

    assert "VERDICT=TEST_PENDING" in stdout
    assert "TOTAL=1" in stdout
    assert "NOT_SCANNED=0" in stdout
    assert "| G-02 | important | cli | TEST_PENDING | runner-native lifecycle proof pending" in matrix
