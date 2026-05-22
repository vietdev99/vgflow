"""B80 v4.63.12 — PR #195 TaskCreate camelCase taskId + accumulation
threshold projection_items count.

Two latent bugs in `scripts/hooks/_vg_tasklist_evidence_payload.py` that
hit simultaneously on every hierarchical TodoWrite projection (Claude Code
v2.51+ TaskCreate/TaskUpdate adapter). Reported by user dogfood session
PrintwayV3 `/vg:blueprint 8.3` 2026-05-18.

Bug 1 — TaskCreate task_id always empty. Helper read `tool_response`
field as snake_case `task_id` or `id`. Claude TaskCreate response is
camelCase `taskId`. Every trace `create` row got `task_id=""` → later
TaskUpdate could never pair → status stuck `pending` forever.

Bug 2 — Accumulation threshold compared against wrong count.
`accumulation_threshold = max(contract_projection_count × 1.5,
contract_projection_count + 3)` where `contract_projection_count =
len(checklists)` (group headers only). For a 7-group × 5-substep
contract → 38 todos. Threshold = max(10.5, 10) = 10.5. 38 > 10.5 →
false-positive `accumulation_suspected=true`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "hooks" / "_vg_tasklist_evidence_payload.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "hooks" / "_vg_tasklist_evidence_payload.py"


# ---------------------------------------------------------------------------
# Bug 1 — taskId camelCase
# ---------------------------------------------------------------------------

def test_b80_taskid_camelcase_present_in_helper() -> None:
    """Source-level: camelCase ``taskId`` must be probed before snake_case.

    Post-B105 (#198) the lookup moved into the dedicated
    ``_resolve_tool_response_task_id`` helper, but the ordering invariant
    still holds — flat camelCase wins over the snake_case legacy fallback
    so a value-bearing ``taskId`` is never shadowed by an empty
    ``task_id``.
    """
    body = HELPER.read_text(encoding="utf-8")
    # The new helper enumerates the probe order in a single tuple literal.
    # Accept either the original inline probe OR the post-B105 tuple form.
    inline_present = 'tr.get("taskId")' in body
    tuple_present = '"taskId", "task_id"' in body
    assert inline_present or tuple_present, (
        "camelCase taskId lookup missing from both inline + tuple forms"
    )
    if inline_present:
        idx_camel = body.index('tr.get("taskId")')
        idx_snake = body.index('tr.get("task_id")')
        assert idx_camel < idx_snake, (
            "taskId must be probed before task_id (inline form)"
        )
    else:
        idx_camel = body.index('"taskId"')
        idx_snake = body.index('"task_id"')
        assert idx_camel < idx_snake, (
            "taskId must be listed before task_id in the probe tuple"
        )


def test_b80_taskid_behavioral(tmp_path: Path) -> None:
    """End-to-end: TaskCreate with `taskId` in tool_response → trace row carries it."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({
        "checklists": [{"id": "step_1", "title": "Setup"}],
        "projection_items": [{"id": "step_1"}],
    }), encoding="utf-8")
    run_dir = tmp_path / ".vg" / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "Setup"},
        "tool_response": {"taskId": "T-camel-123"},
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    trace = run_dir / ".taskcreate-trace.jsonl"
    assert trace.exists(), "trace file not written"
    rec = json.loads(trace.read_text(encoding="utf-8").strip())
    assert rec["task_id"] == "T-camel-123", (
        f"taskId not picked up; got task_id={rec['task_id']!r}"
    )


def test_b80_taskid_snake_case_fallback(tmp_path: Path) -> None:
    """Legacy: snake_case `task_id` still works when camelCase absent."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({"checklists": [], "projection_items": []}),
                             encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    hook_input = {
        "tool_name": "TaskCreate",
        "tool_input": {"subject": "Legacy"},
        "tool_response": {"task_id": "T-snake-456"},
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
    assert rec["task_id"] == "T-snake-456"


# ---------------------------------------------------------------------------
# Bug 2 — threshold uses projection_items count
# ---------------------------------------------------------------------------

def test_b80_threshold_uses_projection_count_full() -> None:
    """Source-level: `projection_count_full` must be defined + used."""
    body = HELPER.read_text(encoding="utf-8")
    assert "projection_count_full" in body, "new full-count variable missing"
    assert "len(projection_items) if projection_items" in body, (
        "fallback to checklists count missing"
    )
    assert "projection_count_full * 1.5" in body
    assert "projection_count_full + 3" in body


def test_b80_threshold_behavioral_hierarchical(tmp_path: Path) -> None:
    """38 hierarchical todos against 7-group × 5-substep contract →
    accumulation_suspected MUST be False (was true under bug).
    """
    contract_path = tmp_path / "contract.json"
    # 7 group headers + 31 sub-steps = 38 projection items
    checklists = [{"id": f"step_{i}", "title": f"Group {i}"} for i in range(7)]
    projection_items = []
    for i in range(7):
        projection_items.append({"id": f"step_{i}", "kind": "group"})
        for j in range(4 if i < 3 else 5):
            projection_items.append({"id": f"step_{i}_sub_{j}", "kind": "step"})
    # ensure 38 items: 7 + 4*3 + 5*4 = 7 + 12 + 20 = 39 — close enough; test below
    n_proj = len(projection_items)
    contract_path.write_text(json.dumps({
        "checklists": checklists,
        "projection_items": projection_items,
    }), encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    todos = []
    for i in range(7):
        todos.append({"content": f"step_{i}: Group {i}", "status": "in_progress"})
        for j in range(4 if i < 3 else 5):
            todos.append({"content": f"  ↳ step_{i}_sub_{j}", "status": "pending"})

    hook_input = {
        "tool_name": "TodoWrite",
        "tool_input": {"todos": todos},
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["accumulation_suspected"] is False, (
        f"hierarchical projection (todos={len(todos)} ≈ projection_items={n_proj}) "
        f"should NOT trip accumulation gate. Got payload={payload}"
    )


def test_b80_threshold_behavioral_real_accumulation(tmp_path: Path) -> None:
    """True accumulation (699 todos for 7-item projection) MUST trip gate."""
    contract_path = tmp_path / "contract.json"
    checklists = [{"id": f"step_{i}", "title": f"G{i}"} for i in range(7)]
    contract_path.write_text(json.dumps({
        "checklists": checklists,
        "projection_items": [{"id": f"step_{i}"} for i in range(7)],
    }), encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    todos = [{"content": f"step_{i % 7}: stale", "status": "completed"}
             for i in range(699)]
    hook_input = {"tool_name": "TodoWrite", "tool_input": {"todos": todos}}
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps(hook_input)},
        capture_output=True, text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["accumulation_suspected"] is True, (
        f"699 todos vs 7-item projection must trip gate. payload={payload}"
    )


def test_b80_threshold_legacy_contract_falls_back(tmp_path: Path) -> None:
    """Contract without `projection_items` falls back to checklists count."""
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({
        "checklists": [{"id": f"step_{i}", "title": f"G{i}"} for i in range(7)],
    }), encoding="utf-8")
    (tmp_path / ".vg" / "runs" / "test-run").mkdir(parents=True)

    # 700 todos vs 7-checklist legacy contract → still trips gate
    todos = [{"content": f"step_{i % 7}", "status": "pending"} for i in range(700)]
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(contract_path), "test-run"],
        cwd=tmp_path,
        env={**os.environ, "VG_HOOK_INPUT": json.dumps({
            "tool_name": "TodoWrite", "tool_input": {"todos": todos}
        })},
        capture_output=True, text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["accumulation_suspected"] is True


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b80_helper_mirror_byte_identical() -> None:
    assert HELPER.read_bytes() == MIRROR.read_bytes(), (
        "_vg_tasklist_evidence_payload.py mirror drift"
    )
