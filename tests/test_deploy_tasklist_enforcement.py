"""Task 44b — deploy flow tasklist enrollment (Bug L Pattern P5).

Audit P5: deploy.md had ZERO tasklist surface (no emit-tasklist.py
call, no TodoWrite IMPERATIVE, no telemetry events declared, not in
CHECKLIST_DEFS, not in is_bootstrap_before_tasklist allowlist). This
suite locks all four enrollment artifacts:

1. deploy.md frontmatter declares deploy.tasklist_shown +
   deploy.native_tasklist_projected.
2. emit-tasklist.py CHECKLIST_DEFS has a `vg:deploy` entry.
3. PreToolUse hook BLOCKs `step-active` for a synthetic deploy run
   when evidence is missing (since deploy is now in CHECKLIST_DEFS,
   tasklist-contract.json will exist; missing evidence → BLOCK).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")
DEPLOY_MD = REPO_ROOT / "commands/vg/deploy.md"
EMIT_TASKLIST = REPO_ROOT / "scripts/emit-tasklist.py"


def test_deploy_md_declares_tasklist_telemetry() -> None:
    """deploy.md must_emit_telemetry must declare both tasklist events."""
    text = DEPLOY_MD.read_text(encoding="utf-8")
    assert "deploy.tasklist_shown" in text, (
        "deploy.md must declare deploy.tasklist_shown in must_emit_telemetry"
    )
    assert "deploy.native_tasklist_projected" in text, (
        "deploy.md must declare deploy.native_tasklist_projected in must_emit_telemetry"
    )
    assert "TodoWrite" in text, (
        "deploy.md must list TodoWrite in allowed-tools"
    )


def test_deploy_in_checklist_defs() -> None:
    """scripts/emit-tasklist.py CHECKLIST_DEFS must have vg:deploy entry."""
    text = EMIT_TASKLIST.read_text(encoding="utf-8")
    # Look for the dict key "vg:deploy" inside CHECKLIST_DEFS section.
    assert '"vg:deploy"' in text, (
        "emit-tasklist.py CHECKLIST_DEFS must include 'vg:deploy' key"
    )
    # Spot-check the deploy_preflight group ID is present.
    assert "deploy_preflight" in text, (
        "vg:deploy entry must include deploy_preflight group"
    )
    assert "deploy_execute" in text, (
        "vg:deploy entry must include deploy_execute group"
    )
    assert "deploy_close" in text, (
        "vg:deploy entry must include deploy_close group"
    )


def _setup_deploy_run(tmp: Path) -> str:
    run_id = "test-run-deploy-44b"
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:deploy",
        "phase": "test-1.0",
        "checklists": [
            {"id": "deploy_preflight", "title": "Deploy Preflight",
             "items": ["0_parse_and_validate", "0a_env_select_and_confirm"],
             "status": "pending"},
            {"id": "deploy_execute", "title": "Deploy Per Env",
             "items": ["1_deploy_per_env"], "status": "pending"},
        ],
    }
    (runs_dir / "tasklist-contract.json").write_text(
        json.dumps(contract, sort_keys=True), encoding="utf-8"
    )

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:deploy", "phase": "test-1.0"}),
        encoding="utf-8",
    )
    return run_id


def test_deploy_step_active_blocks_without_evidence(tmp_path: Path) -> None:
    """Synthetic deploy run with contract but no evidence → step-active BLOCKED."""
    _setup_deploy_run(tmp_path)
    # No evidence file. Hook should BLOCK on a non-bootstrap deploy step.
    cmd = "python3 .claude/scripts/vg-orchestrator step-active 1_deploy_per_env"
    payload = json.dumps({"tool_input": {"command": cmd}})
    result = subprocess.run(
        ["bash", PRE_HOOK],
        input=payload,
        env={
            **os.environ,
            "CLAUDE_HOOK_SESSION_ID": "test-session",
            "VG_REPO_ROOT": str(tmp_path),
        },
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=15,
    )
    assert result.returncode == 2, (
        f"expected BLOCK exit 2 for deploy step-active without evidence; "
        f"got {result.returncode}\nstderr: {result.stderr}"
    )
    diag = result.stderr
    assert "TodoWrite" in diag or "tasklist" in diag.lower(), (
        f"diagnostic must mention TodoWrite/tasklist; got:\n{diag}"
    )


def test_deploy_bootstrap_step_passes_without_contract(tmp_path: Path) -> None:
    """vg:deploy:0_parse_and_validate is in bootstrap allowlist — passes pre-tasklist."""
    run_id = "test-run-deploy-bootstrap"
    runs_dir = tmp_path / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    # NO tasklist-contract.json — bootstrap step must still pass.
    active_dir = tmp_path / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:deploy", "phase": "test-1.0"}),
        encoding="utf-8",
    )

    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0_parse_and_validate"
    payload = json.dumps({"tool_input": {"command": cmd}})
    result = subprocess.run(
        ["bash", PRE_HOOK],
        input=payload,
        env={
            **os.environ,
            "CLAUDE_HOOK_SESSION_ID": "test-session",
            "VG_REPO_ROOT": str(tmp_path),
        },
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"expected PASS exit 0 for deploy bootstrap step; got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
