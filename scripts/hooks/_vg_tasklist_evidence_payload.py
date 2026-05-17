#!/usr/bin/env python3
"""Build TodoWrite/TaskCreate evidence payload for vg-post-tool-use-todowrite.sh.

Extracted from inline heredoc Python so the parent shell script parses on
bash 3.2 (macOS default). bash 3.2 cannot parse heredocs nested inside
$(...) command substitution — the same script ran fine on bash 4+ on Linux
CI which masked the regression.

Inputs:
  argv[1]  contract_path  — .vg/runs/{run_id}/tasklist-contract.json
  argv[2]  run_id

Environment:
  VG_HOOK_INPUT — JSON string of the PostToolUse hook payload (tool_name +
                  tool_input + tool_response). Passed via env to avoid stdin
                  conflicts.

Stdout:
  Single line JSON evidence payload (consumed by parent shell + piped to
  vg-orchestrator-emit-evidence-signed.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(
            f"usage: {sys.argv[0]} <contract_path> <run_id>", file=sys.stderr,
        )
        return 2

    contract_path, run_id = sys.argv[1], sys.argv[2]
    hook_input = json.loads(os.environ.get("VG_HOOK_INPUT", "{}") or "{}")
    contract = json.loads(open(contract_path).read())

    # v2.51+ tool dispatch: TodoWrite is legacy; TaskCreate/TaskUpdate are
    # the native task UI on newer Claude Code runtimes. TaskCreate fires
    # once per todo; aggregate via per-run trace file so a single 37-call
    # sequence reconstructs the same {todos: [...]} shape TodoWrite would
    # have produced.
    tool_name = hook_input.get("tool_name") or "TodoWrite"
    trace_path = Path(f".vg/runs/{run_id}/.taskcreate-trace.jsonl")

    todos: list[dict] = []

    if tool_name == "TodoWrite":
        todos = hook_input.get("tool_input", {}).get("todos", []) or []
    elif tool_name == "TaskCreate":
        tool_input = hook_input.get("tool_input", {}) or {}
        subject = (tool_input.get("subject") or "").strip()
        task_id = ""
        tr = hook_input.get("tool_response") or hook_input.get("tool_result") or {}
        if isinstance(tr, dict):
            # B79: Claude TaskCreate tool_response field is camelCase `taskId`.
            # Old check for snake_case `task_id` always missed → trace records
            # `task_id=""` → TaskUpdate cannot pair against create row → status
            # stays "pending" → tasklist-projected gate fires false-positive.
            task_id = str(
                tr.get("taskId")
                or tr.get("task_id")
                or tr.get("id")
                or ""
            )
        if subject:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "action": "create",
                    "task_id": task_id,
                    "subject": subject,
                    "status": "pending",
                }) + "\n")
    elif tool_name == "TaskUpdate":
        tool_input = hook_input.get("tool_input", {}) or {}
        upd_id = str(tool_input.get("taskId") or "")
        upd_status = str(tool_input.get("status") or "")
        if upd_id and upd_status and trace_path.exists():
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "action": "update",
                    "task_id": upd_id,
                    "status": upd_status,
                }) + "\n")
    # else: unknown tool — leave trace untouched

    # Reconstruct todos[] from trace when this is a TaskCreate/TaskUpdate
    # run.
    if tool_name in ("TaskCreate", "TaskUpdate"):
        items_by_id: dict[str, dict] = {}
        items_no_id: list[dict] = []
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                act = rec.get("action")
                tid = rec.get("task_id") or ""
                if act == "create":
                    entry = {
                        "content": rec.get("subject", ""),
                        "status": rec.get("status", "pending"),
                    }
                    if tid:
                        items_by_id[tid] = entry
                    else:
                        items_no_id.append(entry)
                elif act == "update":
                    if tid in items_by_id and rec.get("status"):
                        items_by_id[tid]["status"] = rec["status"]
        todos = list(items_by_id.values()) + items_no_id

    checklists = contract.get("checklists", [])
    projection_items = contract.get("projection_items", []) or []

    # Tolerant match: each contract checklist matched if any group-header
    # todo content contains its id or its title.
    todo_contents = [
        t.get("content", "").strip() for t in todos if t.get("content")
    ]

    def _is_sub(content: str) -> bool:
        return content.lstrip().startswith("↳")

    groups_seen: list[tuple] = []
    sub_counts: dict[str, int] = {}
    current_id = None
    for content in todo_contents:
        if _is_sub(content):
            if current_id is not None:
                sub_counts[current_id] = sub_counts.get(current_id, 0) + 1
            continue
        matched = None
        for c in checklists:
            if c["id"] in content or c["title"] in content:
                matched = c["id"]
                break
        current_id = matched
        if matched is not None and matched not in sub_counts:
            sub_counts[matched] = 0
            groups_seen.append((matched, content))

    matched_ids = set(sub_counts.keys())
    contract_ids = sorted([c["id"] for c in checklists])
    match = matched_ids == set(contract_ids)

    flat_groups = [gid for gid, n in sub_counts.items() if n == 0]
    groups_with_subs_count = sum(1 for n in sub_counts.values() if n >= 1)
    depth_valid = (len(matched_ids) > 0) and (len(flat_groups) == 0)

    latest_marked_step = None
    latest_marked_at = None
    latest_marked_status = None
    latest_marked_status_valid = True
    db_path = Path(".vg/events.db")
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT step, ts FROM events "
                "WHERE run_id = ? AND event_type = 'step.marked' "
                "ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            conn.close()
        except Exception:
            row = None
        if row and row[0]:
            latest_marked_step = row[0]
            latest_marked_at = row[1]
            accepted = {latest_marked_step}
            for item in projection_items:
                if (
                    item.get("kind") == "step"
                    and item.get("id") == latest_marked_step
                ):
                    title = str(item.get("title") or "").strip()
                    if title:
                        accepted.add(title)
                        accepted.add(title.lstrip(" ↳").strip())
            latest_marked_status_valid = False
            for todo in todos:
                content = str(todo.get("content") or "")
                if any(token and token in content for token in accepted):
                    latest_marked_status = str(todo.get("status") or "")
                    latest_marked_status_valid = (
                        latest_marked_status == "completed"
                    )
                    break

    contract_projection_count = len(contract_ids)
    # B79: accumulation threshold MUST compare against projection_items count
    # (groups + sub-steps), NOT checklists count (groups only). Otherwise a
    # correctly hierarchical TodoWrite (e.g. 7 groups × ~5 sub-steps = 38)
    # trips a false-positive accumulation block, since 38 > 1.5×7 even though
    # every sub-step is contract-bound. Fall back to checklists count when
    # projection_items missing (legacy schema).
    projection_count_full = len(projection_items) if projection_items else contract_projection_count
    todo_count_actual = len(todos)
    accumulation_threshold = max(
        projection_count_full * 1.5, projection_count_full + 3
    )
    accumulation_suspected = bool(
        projection_count_full > 0
        and todo_count_actual > accumulation_threshold
    )

    payload = {
        "run_id": run_id,
        "adapter": "claude",
        "tool_name": tool_name,
        "todowrite_at": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "todo_count": todo_count_actual,
        "contract_projection_count": contract_projection_count,
        "accumulation_suspected": accumulation_suspected,
        "contract_sha256": hashlib.sha256(
            open(contract_path, "rb").read()
        ).hexdigest(),
        "todo_ids": sorted(matched_ids),
        "contract_ids": contract_ids,
        "match": match,
        "depth_valid": depth_valid,
        "groups_with_subs_count": groups_with_subs_count,
        "flat_groups": sorted(flat_groups),
        "latest_marked_step": latest_marked_step,
        "latest_marked_at": latest_marked_at,
        "latest_marked_status": latest_marked_status,
        "latest_marked_status_valid": latest_marked_status_valid,
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
