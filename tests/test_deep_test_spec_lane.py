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
    phase = root / ".vg" / "phases" / "06-workspace-access"
    phase.mkdir(parents=True)
    (phase / "SUMMARY.md").write_text("# Summary\n\nBuild done.\n", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text(
        """# Test Goals

## Goal G-ACCESS-GRANT: owner grants collaborator access and manages role
goal_type: multi-actor
Surface: workspace access settings
Mutation evidence: POST /api/access/grants returns grant id and one-time artifact
Persistence check: GET /api/access/members shows active collaborator after acceptance; role patch persists; revoke removes session
Dependencies: owner account, collaborator account, one-time acceptance artifact
""",
        encoding="utf-8",
    )
    return phase


def test_generate_deep_test_specs_post_build(tmp_path: Path) -> None:
    phase = _make_phase(tmp_path)
    app = tmp_path / "src" / "routes"
    app.mkdir(parents=True)
    (app / "access.tsx").write_text(
        """
        export const path = "/workspace/access";
        fetch("/api/access/grants", { method: "POST" });
        <form data-testid="grant-access-form"></form>
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
    assert summary["phase_profile"] == "web-fullstack"
    assert summary["execution_plan_goals"] == 1
    assert (phase / "DEEP-TEST-SPECS.md").is_file()
    assert (phase / "LIFECYCLE-SPECS.json").is_file()
    assert (phase / "TEST-FIXTURE-DAG.json").is_file()
    assert (phase / "TEST-EXECUTION-PLAN.json").is_file()
    assert (phase / "TEST-SPEC-LOCALIZER" / "PROMPT.md").is_file()
    assert (phase / "PLAYWRIGHT-SPEC-PLAN.md").is_file()
    assert (phase / "TEST-SPEC-GAPS.md").is_file()

    lifecycle = json.loads((phase / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
    spec = lifecycle["goals"]["G-ACCESS-GRANT"]
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
    assert spec["execution_plan"]["runner"] == "playwright"

    execution = json.loads((phase / "TEST-EXECUTION-PLAN.json").read_text(encoding="utf-8"))
    assert execution["phase_profile"] == "web-fullstack"
    assert execution["goals"]["G-ACCESS-GRANT"]["entrypoints"]

    validated = subprocess.run(
        [sys.executable, str(VAL), "--phase", "6"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["verdict"] == "PASS"


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
    # v4.0 canonical: review BEFORE test-spec (review writes RUNTIME-MAP, test-spec consumes it)
    assert "build → **review**" in review or "review → test-spec" in review or "build → review" in review
    assert "/vg:test-spec" in lifecycle
    # v4.0 canonical PIPELINE_STEPS order: review before test-spec
    # Matches both scripts/phase-recon.py and .claude/scripts/phase-recon.py
    assert '"review", "test-spec"' in phase_recon
    # review/preflight.md still gates deep test specs (legacy gate still present)
    assert "/vg:test-spec ${PHASE_NUMBER}" in review_preflight
    assert 'DEEP_SPEC_VALIDATOR="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-deep-test-specs.py"' in review_preflight
    assert 'DIAG_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-block-diagnostic.py"' in review_preflight
    assert "review.deep_test_spec_blocked" in review_preflight
    assert 'state["next_command"] = f"/vg:test-spec {phase}"' in review_preflight
    assert "review.deep_test_spec_blocked" in review

def test_test_spec_command_supports_global_only_install() -> None:
    command = (REPO_ROOT / "commands" / "vg" / "test-spec.md").read_text(encoding="utf-8")

    assert 'VG_HOME="${VG_HOME:-${HOME}/.vgflow}"' in command
    assert 'ORCH="${REPO_ROOT}/.claude/scripts/vg-orchestrator"' in command
    assert 'ORCH="${VG_HOME}/scripts/vg-orchestrator"' in command
    assert '"$ORCH" run-start vg:test-spec' in command
    assert 'PHASE_RESOLVER="${VG_HOME}/commands/vg/_shared/lib/phase-resolver.sh"' in command
    assert 'SCRIPT="${VG_HOME}/scripts/generate-deep-test-specs.py"' in command
    assert 'VALIDATOR="${VG_HOME}/scripts/validators/verify-deep-test-specs.py"' in command
    assert "--ai-response=" in command

def test_review_block_diagnostic_routes_missing_lifecycle_to_test_spec(tmp_path: Path) -> None:
    phase = _make_phase(tmp_path)
    payload = {
        "verdict": "BLOCK",
        "evidence": [
            {
                "type": "deep_test_spec_missing",
                "message": "LIFECYCLE-SPECS.json missing",
                "file": str(phase / "LIFECYCLE-SPECS.json"),
                "fix_hint": "Run /vg:test-spec 6 before /vg:review.",
            },
            {
                "type": "fixture_dag_invalid_json",
                "message": "TEST-FIXTURE-DAG.json is missing or invalid JSON",
                "file": str(phase / "TEST-FIXTURE-DAG.json"),
            },
        ],
    }
    input_path = tmp_path / "deep-test-specs-review.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "review-block-diagnostic.py"),
            "--gate-id",
            "review.deep_test_specs",
            "--phase-dir",
            str(phase),
            "--input",
            str(input_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    assert "deep_test_spec_artifact_gap" in result.stdout
    assert "`/vg:test-spec 6`" in result.stdout
    assert "`/vg:review 6 --mode=full --force`" in result.stdout
    assert "Do not advance to `/vg:test`" in result.stdout
