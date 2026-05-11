from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GEN = REPO_ROOT / "scripts" / "generate-deep-test-specs.py"
VAL = REPO_ROOT / "scripts" / "validators" / "verify-deep-test-specs.py"


def _make_phase(root: Path) -> Path:
    phase = root / ".vg" / "phases" / "06-merchant-team"
    phase.mkdir(parents=True)
    (phase / "SUMMARY.md").write_text("# Summary\n\nBuild done.\n", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text(
        """# Test Goals

## Goal G-TEAM-INVITE: owner invites a member and manages role
goal_type: multi-actor
Surface: merchant team settings
Mutation evidence: POST /api/team/invitations returns invitation id and token/email artifact
Persistence check: GET /api/team/members shows active invitee after accept; role patch persists; revoke removes session
Dependencies: owner user, invitee user, invitation token/email, accept invite
""",
        encoding="utf-8",
    )
    return phase


def test_generate_deep_test_specs_post_build(tmp_path: Path) -> None:
    phase = _make_phase(tmp_path)
    app = tmp_path / "src" / "routes"
    app.mkdir(parents=True)
    (app / "team.tsx").write_text(
        """
        export const path = "/merchant/team";
        fetch("/api/team/invitations", { method: "POST" });
        <form data-testid="invite-member-form"></form>
        """,
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(GEN),
            "--phase",
            "6",
            "--phase-dir",
            str(phase),
            "--root",
            str(tmp_path),
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["lifecycle_goals"] == 1
    assert summary["forms"] >= 1
    assert (phase / "DEEP-TEST-SPECS.md").is_file()
    assert (phase / "LIFECYCLE-SPECS.json").is_file()
    assert (phase / "TEST-FIXTURE-DAG.json").is_file()
    assert (phase / "PLAYWRIGHT-SPEC-PLAN.md").is_file()
    assert (phase / "TEST-SPEC-GAPS.md").is_file()

    lifecycle = json.loads((phase / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
    spec = lifecycle["goals"]["G-TEAM-INVITE"]
    stages = [step["stage"] for step in spec["steps"]]
    assert stages == [
        "read_before",
        "create",
        "read_after_create",
        "update",
        "read_after_update",
        "delete",
        "read_after_delete",
    ]
    assert len(spec["actors"]) >= 2
    assert spec["artifact_capture"]


def test_verify_deep_test_specs_blocks_missing(tmp_path: Path) -> None:
    _make_phase(tmp_path)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(VAL), "--phase", "6"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "BLOCK"
    assert any(item["type"] == "deep_test_spec_missing" for item in payload["evidence"])


def test_pipeline_wiring_places_test_spec_between_build_and_review() -> None:
    lifecycle = (REPO_ROOT / "commands" / "vg" / "LIFECYCLE.md").read_text(encoding="utf-8")
    phase_recon = (REPO_ROOT / "scripts" / "phase-recon.py").read_text(encoding="utf-8")
    review_preflight = (REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "preflight.md").read_text(encoding="utf-8")

    review = (REPO_ROOT / "commands" / "vg" / "review.md").read_text(encoding="utf-8")
    assert "build → test-spec → **review**" in review
    assert "/vg:test-spec" in lifecycle
    assert '"build", "test-spec", "review"' in phase_recon
    assert "/vg:test-spec ${PHASE_NUMBER} before /vg:review" in review_preflight

def test_test_spec_command_supports_global_only_install() -> None:
    command = (REPO_ROOT / "commands" / "vg" / "test-spec.md").read_text(encoding="utf-8")

    assert 'VG_HOME="${VG_HOME:-${HOME}/.vgflow}"' in command
    assert 'ORCH="${REPO_ROOT}/.claude/scripts/vg-orchestrator"' in command
    assert 'ORCH="${VG_HOME}/scripts/vg-orchestrator"' in command
    assert '"$ORCH" run-start vg:test-spec' in command
    assert 'PHASE_RESOLVER="${VG_HOME}/commands/vg/_shared/lib/phase-resolver.sh"' in command
    assert 'SCRIPT="${VG_HOME}/scripts/generate-deep-test-specs.py"' in command
    assert 'VALIDATOR="${VG_HOME}/scripts/validators/verify-deep-test-specs.py"' in command
