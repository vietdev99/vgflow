from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"


def _run(
    repo: Path,
    *args: str,
    session_id: str | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_SYNC_CHECK_DISABLED"] = "true"
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env.pop("CODEX_SESSION_ID", None)
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
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


def test_run_start_allows_other_session_on_different_phase(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started_a = _run(
        repo,
        "run-start",
        "vg:review",
        "3.2",
        "3.2",
        session_id="sess-a",
    )
    assert started_a.returncode == 0, started_a.stderr

    started_b = _run(
        repo,
        "run-start",
        "vg:build",
        "4.1",
        "4.1",
        session_id="sess-b",
    )
    assert started_b.returncode == 0, started_b.stderr
    assert "Different phases are allowed concurrently" in started_b.stderr


def test_run_start_blocks_other_session_on_same_phase(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    started_a = _run(
        repo,
        "run-start",
        "vg:review",
        "3.2",
        "3.2",
        session_id="sess-a",
    )
    assert started_a.returncode == 0, started_a.stderr

    started_b = _run(
        repo,
        "run-start",
        "vg:build",
        "3.2",
        "3.2",
        session_id="sess-b",
    )
    assert started_b.returncode == 1
    assert "already owns phase 3.2" in started_b.stderr


def test_run_start_ignores_stale_session_context_when_other_phase_active(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    active_dir = repo / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    session_id = "codex-session-123"
    active = {
        "run_id": "new-deploy-run",
        "command": "vg:deploy",
        "phase": "4.3",
        "args": "",
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
    }
    active_dir.joinpath(f"{session_id}.json").write_text(
        json.dumps(active),
        encoding="utf-8",
    )
    (repo / ".vg" / "current-run.json").write_text(
        json.dumps(active),
        encoding="utf-8",
    )
    (repo / ".vg" / ".session-context.json").write_text(
        json.dumps({
            "run_id": "old-test-run",
            "session_id": session_id,
            "command": "vg:test",
            "phase": "4.2",
        }),
        encoding="utf-8",
    )

    started = _run(repo, "run-start", "vg:test", "4.2", "4.2")
    assert started.returncode == 0, started.stderr
    run_id = started.stdout.strip().splitlines()[-1]
    assert run_id != "old-test-run"
    assert run_id != "new-deploy-run"

    status = _run(repo, "run-status")
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)
    assert payload["current_run"]["run_id"] == run_id
    assert payload["current_run"]["session_id"] == f"session-unknown-{run_id[:8]}"

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


def test_mark_step_rejects_namespace_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    vg = repo / ".vg"
    active_dir = vg / "active-runs"
    active_dir.mkdir(parents=True)
    active = {
        "run_id": "scope-run-1",
        "command": "vg:scope",
        "phase": "4.5",
        "started_at": "2026-05-05T00:00:00Z",
        "session_id": "unknown",
    }
    active_dir.joinpath("unknown.json").write_text(
        json.dumps(active),
        encoding="utf-8",
    )
    vg.joinpath("current-run.json").write_text(
        json.dumps(active),
        encoding="utf-8",
    )

    marked = _run(repo, "mark-step", "blueprint", "2c_verify")

    assert marked.returncode == 2
    assert "namespace does not match active command" in marked.stderr
    assert "Required namespace: scope" in marked.stderr


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
