"""Task 34 — tasklist projection enforcement for /vg:review.

Pin: when an AI tries `vg-orchestrator step-active` for a review run
without first creating `.tasklist-projected.evidence.json`, the
PreToolUse-bash hook MUST BLOCK with a diagnostic that explicitly
names the TodoWrite tool + tasklist-projected subcommand.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")


def _setup_review_run(tmp: Path) -> str:
    """Create a synthetic review run with tasklist-contract.json but no evidence."""
    run_id = "test-run-tasklist-34"
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    (runs_dir / "tasklist-contract.json").write_text(json.dumps({
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:review",
        "phase": "test-1.0",
        "checklists": [{"id": "review_preflight", "items": ["0a_env_mode_gate"], "status": "pending"}],
    }), encoding="utf-8")

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(json.dumps({
        "run_id": run_id, "command": "vg:review", "phase": "test-1.0",
    }), encoding="utf-8")
    return run_id


def _run_hook(tmp: Path, command: str, session_id: str = "test-session") -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", HOOK],
        input=payload,
        env={**os.environ,
             "CLAUDE_HOOK_SESSION_ID": session_id,
             "VG_REPO_ROOT": str(tmp)},
        capture_output=True, text=True, cwd=str(tmp), timeout=10,
    )


def test_block_message_names_todowrite_tool(tmp_path: Path) -> None:
    """When evidence missing, block diagnostic MUST mention `TodoWrite` + `tasklist-projected`."""
    _setup_review_run(tmp_path)
    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    result = _run_hook(tmp_path, cmd)
    assert result.returncode == 2, f"expected BLOCK exit 2, got {result.returncode}: {result.stderr}"
    diag = result.stderr
    assert "TodoWrite" in diag, f"diagnostic must name TodoWrite tool; got:\n{diag}"
    assert "tasklist-projected" in diag, f"diagnostic must name tasklist-projected subcommand; got:\n{diag}"


def test_block_emits_review_specific_telemetry(tmp_path: Path) -> None:
    """When BLOCK fires for a review run, hook MUST emit `review.tasklist_projection_skipped`."""
    run_id = _setup_review_run(tmp_path)
    # Seed events.db so emit-event has a target. Hook calls vg-orchestrator
    # which writes to .vg/events.db.
    events_db = tmp_path / ".vg" / "events.db"
    if not events_db.exists():
        import sqlite3
        conn = sqlite3.connect(str(events_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                run_id TEXT, command TEXT, event_type TEXT,
                ts TEXT, payload_json TEXT, actor TEXT, outcome TEXT
            )""")
        conn.commit()
        conn.close()

    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    _run_hook(tmp_path, cmd)

    import sqlite3
    conn = sqlite3.connect(str(events_db))
    rows = conn.execute(
        "SELECT event_type FROM events WHERE event_type='review.tasklist_projection_skipped'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1, "expected at least 1 review.tasklist_projection_skipped event"


def test_pass_when_evidence_exists(tmp_path: Path) -> None:
    """Hook PASSes when both tasklist-contract.json and evidence file present."""
    run_id = _setup_review_run(tmp_path)
    evidence = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    evidence.write_text(json.dumps({"projected_at": "2026-05-04T00:00:00Z"}), encoding="utf-8")

    cmd = "python3 .claude/scripts/vg-orchestrator step-active 0a_env_mode_gate"
    result = _run_hook(tmp_path, cmd)
    # Hook may exit 0 (pass) OR exit 2 for OTHER reasons (HMAC sig missing in
    # synthetic env). Accept exit 0 as definitive PASS; if non-zero, just
    # assert the diagnostic does NOT mention tasklist projection.
    if result.returncode != 0:
        assert "TodoWrite" not in result.stderr, (
            "hook blocked but for non-tasklist reason; should not mention "
            f"TodoWrite. stderr:\n{result.stderr}"
        )


def test_review_md_instruction_block_present_at_top(tmp_path: Path) -> None:
    """review.md slim entry MUST reference _shared/lib/tasklist-projection-instruction.md.

    R3 pilot 2026-05-04: review.md is now a slim entry (~500 lines). Step-active
    invocations moved to refs in commands/vg/_shared/review/. The slim entry
    references the projection-instruction ref BEFORE delegating to STEP refs.
    Test now validates: (1) reference exists, (2) it's positioned BEFORE the
    'Steps' section (which routes to step-active-bearing refs)."""
    review_md = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")

    instruction_marker = "_shared/lib/tasklist-projection-instruction.md"
    instruction_pos = review_md.find(instruction_marker)
    assert instruction_pos != -1, (
        "review.md must reference _shared/lib/tasklist-projection-instruction.md"
    )

    # In slim-entry pattern, step-active fires inside refs (e.g. preflight.md).
    # The instruction reference must come BEFORE the slim entry's 'Steps' section
    # which is where ref delegations begin (## Steps or ### STEP 1).
    steps_section = review_md.find("## Steps")
    if steps_section == -1:
        steps_section = review_md.find("### STEP 1")
    assert steps_section != -1, "review.md slim entry must have a 'Steps' section"
    assert instruction_pos < steps_section, (
        f"projection instruction at byte {instruction_pos} must come BEFORE "
        f"the Steps section at byte {steps_section}"
    )


def test_review_md_declares_tasklist_projection_skipped_telemetry() -> None:
    text = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "review.tasklist_projection_skipped" in text, \
        "review.md must_emit_telemetry must declare 'review.tasklist_projection_skipped' (else Stop hook silent-skips)"
