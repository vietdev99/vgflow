from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"


def _phase(tmp_path: Path) -> Path:
    phase = tmp_path / ".vg" / "phases" / "06-lifecycle-sample"
    phase.mkdir(parents=True)
    return phase


def _run(tmp_path: Path, phase: str = "6") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase],
        cwd=str(tmp_path),
        env=env,
        text=True,
        capture_output=True,
    )


def _write_goal(phase: Path, body: str) -> None:
    (phase / "TEST-GOALS.md").write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")


def _valid_lifecycle(phase: Path) -> None:
    stages = [
        "read_before",
        "create",
        "read_after_create",
        "update",
        "read_after_update",
        "delete",
        "read_after_delete",
    ]
    spec = {
        "schema_version": "1.0",
        "goals": {
            "G-01": {
                "actors": [
                    {"id": "owner", "role": "owner", "session": "owner_session"},
                    {"id": "invitee", "role": "invitee", "session": "invitee_session"},
                ],
                "fixture_dag": [
                    {"id": "owner_user", "kind": "user", "depends_on": [], "cleanup": "delete"},
                    {"id": "invitee_user", "kind": "user", "depends_on": [], "cleanup": "delete"},
                ],
                "preconditions": [{"id": "invitee_absent", "assert": "invitee not active"}],
                "steps": [{"stage": stage, "actor": "owner"} for stage in stages],
                "artifact_capture": [
                    {"id": "invite_token", "source": "email_or_test_inbox", "consumer_step": "create"}
                ],
                "cleanup": [
                    {"target": "owner_user", "action": "delete"},
                    {"target": "invitee_user", "action": "delete"},
                ],
            }
        },
    }
    (phase / "LIFECYCLE-SPECS.json").write_text(json.dumps(spec), encoding="utf-8")


def test_mutation_goal_without_lifecycle_specs_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goal(
        phase,
        """
        ## Goal G-01: Create team member
        **goal_type:** mutation
        **Mutation evidence:** POST /api/team returns 201
        **Persistence check:** reload and re-read member row
        """,
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "BLOCK"
    assert payload["evidence"][0]["type"] == "lifecycle_spec_missing"


def test_valid_multi_actor_invite_lifecycle_passes(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goal(
        phase,
        """
        ## Goal G-01: Owner invites invitee by email token
        **goal_type:** multi-actor
        **Mutation evidence:** POST /api/invitations returns 201 and emits email token
        **Persistence check:** invitee accepts, owner changes role, owner revokes access
        """,
    )
    _valid_lifecycle(phase)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["verdict"] == "PASS"


def test_artifact_goal_without_artifact_capture_blocks(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goal(
        phase,
        """
        ## Goal G-01: User accepts magic link token
        **goal_type:** mutation
        **Mutation evidence:** POST /api/magic-link emits email token
        **Persistence check:** token can be consumed once
        """,
    )
    _valid_lifecycle(phase)
    data = json.loads((phase / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
    data["goals"]["G-01"]["artifact_capture"] = []
    (phase / "LIFECYCLE-SPECS.json").write_text(json.dumps(data), encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    evidence_types = {e["type"] for e in json.loads(result.stdout)["evidence"]}
    assert "artifact_capture_missing" in evidence_types


def test_readonly_goal_does_not_require_lifecycle_file(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    _write_goal(
        phase,
        """
        ## Goal G-01: List dashboard metrics
        **goal_class:** readonly
        **Surface:** ui
        """,
    )

    result = _run(tmp_path)

    assert result.returncode == 0
    assert json.loads(result.stdout)["verdict"] == "PASS"


def test_split_goal_files_are_parsed(tmp_path: Path) -> None:
    phase = _phase(tmp_path)
    goals_dir = phase / "TEST-GOALS"
    goals_dir.mkdir()
    (goals_dir / "G-01.md").write_text(
        textwrap.dedent(
            """
            # G-01: Update account status
            **goal_type:** mutation
            **Mutation evidence:** PATCH /api/accounts/A returns 200
            **Persistence check:** reload account detail and re-read status
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert json.loads(result.stdout)["evidence"][0]["file"].endswith("TEST-GOALS/G-01.md")
