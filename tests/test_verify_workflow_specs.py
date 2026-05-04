"""Task 40 — verify workflow specs validator.

Pin: each WF-NN.md must declare workflow_id + actors[] + steps[] + state_machine.
state_after strings in steps[] must appear in state_machine.states[].
cred_switch_marker required when consecutive steps have different actors.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-workflow-specs.py"


VALID_WF = """\
workflow_id: WF-001
name: User request → admin approval → user notification
goal_links: [G-04, G-05, G-12]
actors:
  - role: user
    cred_fixture: USER_PUBLISHER_CRED
  - role: admin
    cred_fixture: ADMIN_CRED
steps:
  - step_id: 1
    actor: user
    view: /sites
    action: open_modal
    target: CreateSiteModal
    goals: [G-04]
  - step_id: 2
    actor: user
    action: submit
    api: POST /api/sites
    state_after: { request: pending_admin_review }
  - step_id: 3
    actor: admin
    cred_switch_marker: true
    view: /admin/site-requests
    action: see_pending
    api: GET /api/admin/site-requests?status=pending
  - step_id: 4
    actor: admin
    action: click
    target: ApproveButton
    api: POST /api/admin/sites/:id/approve
    state_after: { request: approved }
  - step_id: 5
    actor: user
    cred_switch_marker: true
    view: /sites
    action: see_approved
    visibility_signal: site appears in My Sites with active badge
state_machine:
  states: [pending_admin_review, approved, rejected, cancelled]
  transitions:
    - { from: null, to: pending_admin_review, by: actor:user, via: step_id:2 }
    - { from: pending_admin_review, to: approved, by: actor:admin, via: step_id:4 }
ui_assertions_per_step:
  - step_id: 1
    ui_state: form-validation-active
    rcrurd_invariant_ref: G-04
  - step_id: 4
    ui_state: success-toast + list-row-removed-from-pending
    rcrurd_invariant_ref: G-12
  - step_id: 5
    ui_state: site-card-with-active-badge
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(VALIDATOR), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def test_valid_workflow_passes(tmp_path: Path) -> None:
    wf_dir = tmp_path / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    (wf_dir / "WF-001.md").write_text("```yaml\n" + VALID_WF + "```\n", encoding="utf-8")
    (wf_dir / "index.md").write_text("# index\n- WF-001\n", encoding="utf-8")

    result = _run(["--workflows-dir", str(wf_dir)], REPO)
    assert result.returncode == 0, f"got: {result.stdout}\n{result.stderr}"


def test_state_after_not_in_state_machine_states_blocks(tmp_path: Path) -> None:
    wf_dir = tmp_path / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    bad = VALID_WF.replace("pending_admin_review", "PENDING_REVIEW", 1)  # only first occurrence: state_after
    (wf_dir / "WF-001.md").write_text("```yaml\n" + bad + "```\n", encoding="utf-8")
    (wf_dir / "index.md").write_text("# index\n", encoding="utf-8")

    result = _run(["--workflows-dir", str(wf_dir)], REPO)
    assert result.returncode != 0
    assert "state_after" in result.stdout + result.stderr


def test_missing_cred_switch_marker_warns(tmp_path: Path) -> None:
    wf_dir = tmp_path / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    bad = VALID_WF.replace("    cred_switch_marker: true\n", "")
    (wf_dir / "WF-001.md").write_text("```yaml\n" + bad + "```\n", encoding="utf-8")
    (wf_dir / "index.md").write_text("# index\n", encoding="utf-8")

    result = _run(["--workflows-dir", str(wf_dir)], REPO)
    assert result.returncode != 0
    assert "cred_switch_marker" in result.stdout + result.stderr


def test_empty_index_passes_when_no_workflows_declared(tmp_path: Path) -> None:
    """Phases without multi-actor workflows: empty index OK, no WF files needed."""
    wf_dir = tmp_path / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    (wf_dir / "index.md").write_text("# WORKFLOW-SPECS index\n\nflows: []\n", encoding="utf-8")

    result = _run(["--workflows-dir", str(wf_dir)], REPO)
    assert result.returncode == 0


def test_missing_required_field_blocks(tmp_path: Path) -> None:
    wf_dir = tmp_path / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    bad = VALID_WF.replace("state_machine:", "state_machine_TYPO:")
    (wf_dir / "WF-001.md").write_text("```yaml\n" + bad + "```\n", encoding="utf-8")
    (wf_dir / "index.md").write_text("# index\n", encoding="utf-8")

    result = _run(["--workflows-dir", str(wf_dir)], REPO)
    assert result.returncode != 0
    assert "state_machine" in result.stdout + result.stderr
