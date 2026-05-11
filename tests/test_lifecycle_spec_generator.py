from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"


def _phase(tmp_path: Path) -> Path:
    phase = tmp_path / ".vg" / "phases" / "06-lifecycle-sample"
    phase.mkdir(parents=True)
    return phase


def _run(tmp_path: Path, phase: str = "6") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--phase", phase, "--json"],
        cwd=str(tmp_path),
        env=env,
        text=True,
        capture_output=True,
    )


def test_generator_creates_multi_actor_artifact_lifecycle_specs(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    goals = phase / "TEST-GOALS"
    goals.mkdir()
    (goals / "G-01.md").write_text(
        textwrap.dedent(
            """
            # G-01: Merchant invites vendor by email token
            **goal_type:** multi-actor
            **Surface:** api
            **Priority:** critical
            **Mutation evidence:** POST /api/team/invitations returns 201 and emits email token
            **Persistence check:** invitee accepts token, owner updates role, owner revokes access
            **Dependencies:** merchant account and vendor account
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((phase / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
    spec = payload["goals"]["G-01"]
    assert payload["formula"]["stages"] == [
        "read_before",
        "create",
        "read_after_create",
        "update",
        "read_after_update",
        "delete",
        "read_after_delete",
    ]
    assert len(spec["actors"]) >= 2
    assert {step["stage"] for step in spec["steps"]} == set(payload["formula"]["stages"])
    assert spec["primary_endpoints"] == [{"method": "POST", "path": "/api/team/invitations"}]
    assert spec["artifact_capture"], "email/token goal must capture emitted artifact"
    assert any(item["id"] == "artifact_sink" for item in spec["fixture_dag"])
    assert spec["cleanup"]


def test_generator_skips_readonly_goals_by_default(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    (phase / "TEST-GOALS.md").write_text(
        textwrap.dedent(
            """
            ## Goal G-01: List dashboard metrics
            **goal_class:** readonly
            **Surface:** ui
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((phase / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
    assert payload["summary"]["goals_seen"] == 1
    assert payload["summary"]["goals_emitted"] == 0
    assert payload["goals"] == {}


def test_generator_output_passes_lifecycle_depth_validator(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    (phase / "TEST-GOALS.md").write_text(
        textwrap.dedent(
            """
            ## Goal G-01: Admin freezes merchant store and replays queue on unfreeze
            **goal_type:** mutation
            **Surface:** api
            **Mutation evidence:** POST /api/admin/stores/123/freeze returns 200 and queues events
            **Persistence check:** GET /api/admin/stores/123 shows Frozen, then unfreeze restores Active
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    generated = _run(tmp_path)
    assert generated.returncode == 0, generated.stderr + generated.stdout

    validator = REPO_ROOT / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(validator), "--phase", "6"],
        cwd=str(tmp_path),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["verdict"] == "PASS"
