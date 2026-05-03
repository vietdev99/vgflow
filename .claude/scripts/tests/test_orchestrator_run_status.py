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


def test_run_abort_clears_orphan_active_state_without_fk_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    active_dir = repo / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    orphan_state = active_dir / "default.json"
    orphan_state.write_text(
        json.dumps({
            "run_id": "missing-run-row",
            "command": "vg:review",
            "phase": "3.2",
            "started_at": "2026-05-03T10:51:54Z",
            "session_id": "default",
        }),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = "default"
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_SYNC_CHECK_DISABLED"] = "true"
    orch_dir = str(REPO_ROOT / "scripts" / "vg-orchestrator")
    env["PYTHONPATH"] = (
        orch_dir + os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH") else orch_dir
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ORCH),
            "run-abort",
            "--reason",
            "clear orphan active run",
        ],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "cleared-orphan-active-run" in result.stdout
    assert not orphan_state.exists()


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
