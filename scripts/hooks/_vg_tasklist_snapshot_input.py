#!/usr/bin/env python3
"""Resolve TodoWrite/TaskCreate display labels → contract step_ids and pipe
to the snapshot writer (vg-tasklist-snapshot.py).

Extracted from inline heredoc Python so the parent shell script
(vg-post-tool-use-todowrite.sh) parses on bash 3.2 (macOS default).

Inputs:
  argv[1]  snapshot_helper_path  — vg-tasklist-snapshot.py

Environment:
  VG_HOOK_INPUT — JSON string of the PostToolUse hook payload
  VG_RUN_ID     — current VGFlow run id

Behaviour:
  - For TodoWrite: read tool_input.todos[] directly.
  - For TaskCreate/TaskUpdate: replay .taskcreate-trace.jsonl.
  - Resolve labels via scripts/tasklist_id_resolver.py (or fallback) to
    contract step_ids; then pipe schema_version=2 payload to the snapshot
    helper subprocess.

Never raises — always exits 0 (best-effort snapshot).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 0
    helper = sys.argv[1]
    hook_input = json.loads(os.environ.get("VG_HOOK_INPUT", "{}") or "{}")
    run_id = os.environ.get("VG_RUN_ID", "")
    if not run_id:
        return 0

    contract_path = Path(f".vg/runs/{run_id}/tasklist-contract.json")
    contract_items: list = []
    contract_hash = ""
    if contract_path.exists():
        try:
            contract_body = contract_path.read_text(encoding="utf-8")
            contract = json.loads(contract_body)
            contract_items = contract.get("projection_items") or []
            contract_hash = (
                "sha256:"
                + hashlib.sha256(contract_body.encode("utf-8")).hexdigest()[:16]
            )
        except Exception:
            contract_items = []

    # Locate resolver — canonical scripts/ first, fall back to .claude/scripts.
    resolver_mod = None
    for cand in [
        Path("scripts/tasklist_id_resolver.py"),
        Path(".claude/scripts/tasklist_id_resolver.py"),
    ]:
        if cand.exists():
            spec = importlib.util.spec_from_file_location(
                "tasklist_id_resolver", cand
            )
            if spec and spec.loader:
                resolver_mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(resolver_mod)
                    break
                except Exception:
                    resolver_mod = None

    def _resolve_label(label, fallback_id):
        if resolver_mod is None or not contract_items:
            return (str(fallback_id or label or "").strip(), "exact")
        try:
            return resolver_mod.resolve(str(label), contract_items)
        except Exception:
            return (str(fallback_id or label or "").strip(), "exact")

    tool_name = hook_input.get("tool_name") or "TodoWrite"
    todos: list = []

    if tool_name == "TodoWrite":
        raw_todos = hook_input.get("tool_input", {}).get("todos") or []
        contract_ids_set = {
            it.get("id") for it in contract_items if it.get("id")
        }
        for t in raw_todos:
            if not isinstance(t, dict):
                continue
            content = (
                t.get("content") or t.get("activeForm") or t.get("subject") or ""
            )
            raw_id = str(t.get("id") or "").strip()
            if raw_id and raw_id in contract_ids_set:
                step_id, match_class = raw_id, "exact"
            else:
                step_id, match_class = _resolve_label(content, raw_id)
            todos.append({
                "id": step_id,
                "content": str(content),
                "status": t.get("status", "pending"),
                "match_class": match_class,
            })
    else:
        trace = Path(f".vg/runs/{run_id}/.taskcreate-trace.jsonl")
        if trace.exists():
            items_by_id, items_no_id = {}, []
            for line in trace.read_text(encoding="utf-8").splitlines():
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
                    subject = rec.get("subject", "") or ""
                    step_id, match_class = _resolve_label(subject, tid)
                    entry = {
                        "id": step_id,
                        "content": subject,
                        "status": rec.get("status", "pending"),
                        "match_class": match_class,
                        "_trace_task_id": tid,
                    }
                    if tid:
                        items_by_id[tid] = entry
                    else:
                        items_no_id.append(entry)
                elif act == "update":
                    if tid in items_by_id and rec.get("status"):
                        items_by_id[tid]["status"] = rec["status"]
            todos = list(items_by_id.values()) + items_no_id

    if not todos:
        return 0

    if resolver_mod is not None:
        by_step: dict = {}
        for t in todos:
            sid = t["id"]
            if sid not in by_step:
                by_step[sid] = t
            else:
                prev = by_step[sid]
                if (
                    resolver_mod.status_precedence(prev["status"], t["status"])
                    != prev["status"]
                ):
                    by_step[sid] = t
        todos = list(by_step.values())

    for t in todos:
        t.pop("_trace_task_id", None)

    payload = json.dumps({
        "schema_version": 2,
        "items": todos,
        "id_map_provenance": {
            "contract_path": str(contract_path),
            "contract_hash": contract_hash,
        },
    })
    subprocess.run(
        [sys.executable, helper, "--write", "--run-id", run_id],
        input=payload,
        capture_output=True,
        text=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Best-effort snapshot — never block the hook.
        sys.exit(0)
