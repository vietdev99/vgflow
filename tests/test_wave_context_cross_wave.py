"""Task 42 — verify wave-context generator adds cross-WORKFLOW block.

Pin: when ≥1 task in current wave has capsule.workflow_id != null AND
WORKFLOW-SPECS/<workflow_id>.md declares siblings in other waves, the
generated wave-{N}-context.md must include a 'Cross-WORKFLOW constraint:'
block citing those siblings + the exact state_after value.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def synthetic_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)

    # WORKFLOW-SPECS — WF-001 spans waves 3 + 5 + 7
    wf_dir = phase_dir / "WORKFLOW-SPECS"
    wf_dir.mkdir()
    (wf_dir / "index.md").write_text("# WF index\n- WF-001\n", encoding="utf-8")
    (wf_dir / "WF-001.md").write_text(
        "```yaml\n"
        "workflow_id: WF-001\n"
        "name: User → admin approval → user notification\n"
        "actors:\n  - {role: user}\n  - {role: admin}\n"
        "steps:\n"
        "  - {step_id: 2, actor: user, api: POST /api/sites, state_after: {request: pending_admin_review}}\n"
        "  - {step_id: 4, actor: admin, cred_switch_marker: true, api: POST /api/admin/sites/:id/approve, state_after: {request: approved}}\n"
        "  - {step_id: 5, actor: user, cred_switch_marker: true, api: GET /api/sites}\n"
        "state_machine:\n"
        "  states: [pending_admin_review, approved]\n"
        "```\n",
        encoding="utf-8",
    )

    # Capsule cache for waves 3 + 5 + 7
    capsules_dir = tmp_path / ".task-capsules"
    capsules_dir.mkdir()

    def _w(task_num: int, wave: int, actor: str, workflow_step: int, write_phase: str | None) -> None:
        (capsules_dir / f"task-{task_num:02d}.capsule.json").write_text(
            json.dumps({
                "capsule_version": "2",
                "phase": "N1",
                "task_num": task_num,
                "wave_id": wave,
                "actor_role": actor,
                "workflow_id": "WF-001",
                "workflow_step": workflow_step,
                "write_phase": write_phase,
            }),
            encoding="utf-8",
        )

    _w(6, wave=3, actor="user", workflow_step=2, write_phase="create")
    _w(12, wave=5, actor="admin", workflow_step=4, write_phase="update")
    _w(18, wave=7, actor="user", workflow_step=5, write_phase=None)

    # Non-workflow task in wave 3 — should NOT appear in cross-WORKFLOW block
    (capsules_dir / "task-07.capsule.json").write_text(
        json.dumps({
            "capsule_version": "2",
            "phase": "N1",
            "task_num": 7,
            "wave_id": 3,
            "actor_role": None,
            "workflow_id": None,
            "workflow_step": None,
            "write_phase": None,
        }),
        encoding="utf-8",
    )

    return phase_dir


def test_wave_3_context_includes_cross_workflow_block(synthetic_phase: Path) -> None:
    from generate_wave_context import generate_wave_context  # type: ignore

    output = generate_wave_context(
        phase_dir=synthetic_phase,
        wave_id=3,
        wave_task_nums=[6, 7],
        capsules_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    assert "## Task 6" in output
    assert "Cross-WORKFLOW constraint:" in output
    assert "Task 12" in output and "wave 5" in output and "ADMIN" in output
    assert "Task 18" in output and "wave 7" in output and "USER" in output
    assert "pending_admin_review" in output, \
        "must cite the state_after value per WORKFLOW-SPECS"


def test_wave_3_non_workflow_task_omitted_from_cross_block(synthetic_phase: Path) -> None:
    from generate_wave_context import generate_wave_context  # type: ignore

    output = generate_wave_context(
        phase_dir=synthetic_phase,
        wave_id=3,
        wave_task_nums=[6, 7],
        capsules_dir=synthetic_phase.parent.parent.parent / ".task-capsules",
    )
    # Task 7 has workflow_id=None, so its section must NOT contain Cross-WORKFLOW block
    task_7_section_start = output.find("## Task 7")
    if task_7_section_start == -1:
        return  # absent is fine
    task_7_to_end = output[task_7_section_start:]
    next_task = task_7_to_end.find("## Task ", 1)
    task_7_section = task_7_to_end[: next_task] if next_task != -1 else task_7_to_end
    assert "Cross-WORKFLOW constraint:" not in task_7_section, \
        "non-workflow task must not have cross-workflow block"


def test_no_workflow_specs_skips_cross_block(tmp_path: Path) -> None:
    """Phases without WORKFLOW-SPECS — generator falls back to existing behavior, no error."""
    from generate_wave_context import generate_wave_context  # type: ignore

    phase_dir = tmp_path / ".vg" / "phases" / "N1"
    phase_dir.mkdir(parents=True)
    capsules_dir = tmp_path / ".task-capsules"
    capsules_dir.mkdir()
    (capsules_dir / "task-01.capsule.json").write_text(
        json.dumps({"capsule_version": "1", "phase": "N1", "task_num": 1, "wave_id": 1}),
        encoding="utf-8",
    )

    output = generate_wave_context(
        phase_dir=phase_dir,
        wave_id=1,
        wave_task_nums=[1],
        capsules_dir=capsules_dir,
    )
    assert "Cross-WORKFLOW constraint:" not in output


def test_telemetry_event_declared_in_build_md() -> None:
    text = (REPO / "commands/vg/build.md").read_text(encoding="utf-8")
    assert "build.cross_wave_workflow_cited" in text
