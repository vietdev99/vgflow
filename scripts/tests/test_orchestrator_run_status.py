from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_SYNC_CHECK_DISABLED"] = "true"
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    orch_dir = str(REPO_ROOT / "scripts" / "vg-orchestrator")
    env["PYTHONPATH"] = (
        orch_dir + os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH") else orch_dir
    )
    return subprocess.run(
        [sys.executable, str(ORCH), *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_run_start_backfills_synthetic_session_in_db(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr
    run_id = started.stdout.strip().splitlines()[-1]

    status = _run(repo, "run-status")
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)

    expected_sid = f"session-unknown-{run_id[:8]}"
    assert payload["current_run"]["session_id"] == expected_sid
    assert payload["run_row"]["session_id"] == expected_sid
    assert "other_sessions_active" not in payload


def test_run_status_tolerates_active_state_without_run_id(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    active_dir = repo / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "unknown.json").write_text(
        json.dumps({"command": "vg:review", "phase": "3.2"}),
        encoding="utf-8",
    )

    status = _run(repo, "run-status")
    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == "no-active-run"


def test_selftest_legacy_snapshot_does_not_mask_synthetic_active_run(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    vg = repo / ".vg"
    active_dir = vg / "active-runs"
    active_dir.mkdir(parents=True)
    active_dir.joinpath("session-unknown-review123.json").write_text(
        json.dumps({
            "run_id": "review123",
            "command": "vg:review",
            "phase": "3.2",
            "started_at": "2026-05-02T00:00:00Z",
            "session_id": "session-unknown-review123",
        }),
        encoding="utf-8",
    )
    vg.joinpath("current-run.json").write_text(
        json.dumps({
            "run_id": "selftest-missing-evidence",
            "command": "vg:blueprint",
            "phase": "99999999",
            "session_id": "selftest",
        }),
        encoding="utf-8",
    )

    status = _run(repo, "run-status")
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)

    assert payload["current_run"]["run_id"] == "review123"
    assert payload["current_run"]["command"] == "vg:review"
    assert "other_sessions_active" not in payload


def test_run_status_pretty_renders_taskboard(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase_dir = repo / ".vg" / "phases" / "3.2-demo"
    phase_dir.mkdir(parents=True)

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr

    emitted = _run(
        repo,
        "emit-event",
        "review.tasklist_shown",
        "--payload",
        json.dumps({
            "phase": "3.2",
            "command": "vg:review",
            "profile": "web-fullstack",
            "steps": ["0_parse_and_validate", "phase1_code_scan", "complete"],
            "step_count": 3,
        }),
    )
    assert emitted.returncode == 0, emitted.stderr

    marked = _run(repo, "mark-step", "review", "0_parse_and_validate")
    assert marked.returncode == 0, marked.stderr

    status = _run(repo, "run-status", "--pretty")
    assert status.returncode == 0, status.stderr
    assert "Taskboard" not in status.stderr
    assert "vg:review — Phase 3.2 — Profile web-fullstack" in status.stdout
    assert "Progress: 1/3 step(s) completed" in status.stdout
    assert "[x]  1. 0_parse_and_validate" in status.stdout
    assert "[>]  2. phase1_code_scan" in status.stdout


def test_mark_step_prints_compact_progress_when_taskboard_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase_dir = repo / ".vg" / "phases" / "3.2-demo"
    phase_dir.mkdir(parents=True)

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr

    emitted = _run(
        repo,
        "emit-event",
        "review.tasklist_shown",
        "--payload",
        json.dumps({
            "phase": "3.2",
            "command": "vg:review",
            "profile": "web-fullstack",
            "steps": [
                "00_gate_integrity_precheck",
                "0_parse_and_validate",
                "0a_env_mode_gate",
                "0b_goal_coverage_gate",
                "create_task_tracker",
                "phase1_code_scan",
                "complete",
            ],
            "step_count": 7,
        }),
    )
    assert emitted.returncode == 0, emitted.stderr

    marked = _run(repo, "mark-step", "review", "00_gate_integrity_precheck")
    assert marked.returncode == 0, marked.stderr
    assert "marked: review/00_gate_integrity_precheck" in marked.stdout
    assert "Progress: 1/7 step(s) completed" in marked.stdout
    assert "[>]  2. 0_parse_and_validate" in marked.stdout


def test_step_active_surfaces_current_running_step(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    phase_dir = repo / ".vg" / "phases" / "3.2-demo"
    phase_dir.mkdir(parents=True)

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr

    emitted = _run(
        repo,
        "emit-event",
        "review.tasklist_shown",
        "--payload",
        json.dumps({
            "phase": "3.2",
            "command": "vg:review",
            "profile": "web-fullstack",
            "steps": ["phase1_code_scan", "phase2a_api_contract_probe", "phase2_browser_discovery"],
            "step_count": 3,
        }),
    )
    assert emitted.returncode == 0, emitted.stderr

    active = _run(repo, "step-active", "phase2a_api_contract_probe")
    assert active.returncode == 0, active.stderr
    assert "active: phase2a_api_contract_probe" in active.stdout
    assert "Active: phase2a_api_contract_probe" in active.stdout
    assert "[>]  2. phase2a_api_contract_probe" in active.stdout

    status = _run(repo, "run-status", "--pretty")
    assert status.returncode == 0, status.stderr
    assert "Active: phase2a_api_contract_probe" in status.stdout

    marked = _run(repo, "mark-step", "review", "phase2a_api_contract_probe")
    assert marked.returncode == 0, marked.stderr
    assert "Active:" not in marked.stdout
    assert "[>]  1. phase1_code_scan" in marked.stdout


def test_tasklist_projected_binds_native_projection_event(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr
    run_id = started.stdout.strip().splitlines()[-1]

    contract_path = repo / ".vg" / "runs" / run_id / "tasklist-contract.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(
        json.dumps({
            "schema": "native-tasklist.v1",
            "run_id": run_id,
            "command": "vg:review",
            "phase": "3.2",
            "profile": "web-fullstack",
            "projection_required": True,
            "checklists": [
                {
                    "id": "review_be",
                    "title": "BE/API Checks",
                    "items": ["phase1_code_scan", "phase2_browser_discovery"],
                }
            ],
            "items": [
                {"id": "phase1_code_scan", "title": "Phase 1 Code Scan"},
                {"id": "phase2_browser_discovery", "title": "Phase 2 Browser Discovery"},
            ],
        }),
        encoding="utf-8",
    )

    projected = _run(repo, "tasklist-projected", "--adapter", "codex")
    assert projected.returncode == 0, projected.stderr
    assert "native-tasklist-projected: review.native_tasklist_projected" in projected.stdout
    assert "items=2" in projected.stdout
    assert "checklists=1" in projected.stdout

    events = _run(
        repo,
        "query-events",
        "--run-id",
        run_id,
        "--event-type",
        "review.native_tasklist_projected",
    )
    assert events.returncode == 0, events.stderr
    payload = json.loads(events.stdout)
    assert len(payload) == 1
    event_payload = json.loads(payload[0]["payload_json"])
    assert event_payload["adapter"] == "codex"
    assert event_payload["item_ids"] == [
        "phase1_code_scan",
        "phase2_browser_discovery",
    ]
    assert event_payload["checklist_ids"] == ["review_be"]


def test_tasklist_projected_blocks_without_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr

    projected = _run(repo, "tasklist-projected", "--adapter", "codex")
    assert projected.returncode == 2
    assert "tasklist-contract.json missing" in projected.stderr


def test_native_tasklist_projection_event_cannot_be_forged_via_emit_event(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started = _run(repo, "run-start", "vg:review", "3.2", "3.2")
    assert started.returncode == 0, started.stderr

    forged = _run(repo, "emit-event", "review.native_tasklist_projected")
    assert forged.returncode == 2
    assert "RESERVED for orchestrator" in forged.stderr
