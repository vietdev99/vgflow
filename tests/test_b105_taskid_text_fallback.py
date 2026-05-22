"""B105 (#198) — TaskCreate/TaskUpdate task_id parsed from tool_response text.

Follow-on to B80 (PR #195). On real Claude Code runtimes the
``tool_response`` from a TaskCreate / TaskUpdate call no longer always
carries the structured ``taskId`` / ``task_id`` / ``id`` field that the
B80 patch relied on. Instead the id is embedded in the human-readable
confirmation text — e.g.::

    "Task #25 created successfully: ↳ 0_gate_integrity_precheck — passed"
    "Updated task #25 status"

When that happens, the trace records ``task_id=""`` on every create and
the later ``TaskUpdate`` cannot pair against the create row → status
stays ``pending`` forever → ``tasklist-projected`` gate refuses to
clear → /vg:build STEP 1.6 blocks.

This module exercises the new ``_resolve_tool_response_task_id`` probe
chain so the regression cannot return.

Reported by dogfood session PrintwayV3 /vg:build 8.2.2 2026-05-22.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "hooks" / "_vg_tasklist_evidence_payload.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "hooks" / "_vg_tasklist_evidence_payload.py"


# ---------------------------------------------------------------------------
# Probe chain — text fallback
# ---------------------------------------------------------------------------

def test_b105_content_list_text_yields_taskid(tmp_path: Path) -> None:
    """tool_response.content[*].text = "Task #25 created …" → id 25."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({
        "checklists": [{"id": "step_1", "title": "Setup"}],
        "projection_items": [{"id": "step_1"}],
    }), encoding="utf-8")
    run_dir = tmp_path / ".vg" / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "↳ 0_gate_integrity_precheck"},
        "tool_response": {
            "content": [{
                "type": "text",
                "text": "Task #25 created successfully: ↳ 0_gate_integrity_precheck",
            }],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    trace = run_dir / ".taskcreate-trace.jsonl"
    rec = json.loads(trace.read_text(encoding="utf-8").strip())
    assert rec["task_id"] == "25"


def test_b105_plain_string_response_yields_taskid(tmp_path: Path) -> None:
    """tool_response = "Task #42 created" (plain string) → id 42."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({"checklists": [], "projection_items": []}),
                             encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "Quick task"},
        "tool_response": "Task #42 created successfully: Quick task",
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    trace = tmp_path / ".vg" / "runs" / "test-run" / ".taskcreate-trace.jsonl"
    rec = json.loads(trace.read_text(encoding="utf-8").strip())
    assert rec["task_id"] == "42"


def test_b105_camelcase_still_wins_over_text(tmp_path: Path) -> None:
    """Flat camelCase ``taskId`` MUST still be probed before the regex fallback."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({"checklists": [], "projection_items": []}),
                             encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "Order matters"},
        "tool_response": {
            "taskId": "T-camel-99",
            # Text mentions a DIFFERENT id — flat field must win.
            "content": [{"type": "text", "text": "Task #1 created earlier"}],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    trace = tmp_path / ".vg" / "runs" / "test-run" / ".taskcreate-trace.jsonl"
    rec = json.loads(trace.read_text(encoding="utf-8").strip())
    assert rec["task_id"] == "T-camel-99", (
        "Flat camelCase taskId must beat text-regex fallback"
    )


def test_b105_taskupdate_text_fallback_pairs_status(tmp_path: Path) -> None:
    """End-to-end: TaskCreate (text id) + TaskUpdate (text id) → status patched."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({
        "checklists": [{"id": "step_1", "title": "Setup"}],
        "projection_items": [{"id": "step_1"}],
    }), encoding="utf-8")
    run_dir = tmp_path / ".vg" / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    # Step 1: TaskCreate without flat id — only in text.
    create_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "↳ step_1"},
        "tool_response": {
            "content": [{"type": "text", "text": "Task #7 created successfully"}],
        },
    }
    subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(create_input)},
        capture_output=True, text=True, check=True,
    )

    # Step 2: TaskUpdate with empty tool_input.taskId, id only echoed in text.
    update_input = {
        "tool_name": "TaskUpdate",
        "tool_input": {"taskId": "", "status": "completed"},
        "tool_response": {
            "content": [{"type": "text", "text": "Updated task #7 status"}],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(update_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr

    trace_path = run_dir / ".taskcreate-trace.jsonl"
    records = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    update_recs = [r for r in records if r["action"] == "update"]
    assert update_recs, "TaskUpdate record missing from trace"
    assert update_recs[-1]["task_id"] == "7", (
        f"Update should pair against create id 7, got {update_recs[-1]}"
    )


def test_b105_no_taskid_anywhere_writes_subject_only(tmp_path: Path) -> None:
    """Defensive: when no id discoverable anywhere, create row still lands
    (subject-only) so the matcher's tolerant content-search can still fire.
    """
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({"checklists": [], "projection_items": []}),
                             encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "no-id-anywhere"},
        "tool_response": {"unrelated": "noise"},
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    trace = tmp_path / ".vg" / "runs" / "test-run" / ".taskcreate-trace.jsonl"
    rec = json.loads(trace.read_text(encoding="utf-8").strip())
    assert rec["task_id"] == "", "expected empty id when no signal anywhere"
    assert rec["subject"] == "no-id-anywhere"


# ---------------------------------------------------------------------------
# Mirror parity (sibling check matches B80)
# ---------------------------------------------------------------------------

def test_b105_helper_mirror_byte_identical() -> None:
    assert HELPER.read_bytes() == MIRROR.read_bytes(), (
        "_vg_tasklist_evidence_payload.py mirror drift after B105 patch"
    )
