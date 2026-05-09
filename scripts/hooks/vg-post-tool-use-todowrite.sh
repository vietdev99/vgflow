#!/usr/bin/env bash
# PostToolUse on TodoWrite | TaskCreate | TaskUpdate — capture payload,
# diff vs contract, write signed evidence via
# vg-orchestrator-emit-evidence-signed.py.
#
# v2.51+ — TaskCreate/TaskUpdate compatibility (newer Claude Code runtimes
# expose TaskCreate instead of TodoWrite). Per-call appends are aggregated
# into .vg/runs/{run_id}/.taskcreate-trace.jsonl and reconstructed into a
# todos[] shape so the existing matching logic works unchanged.

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"
session_id="$(vg_resolve_session_id)"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
contract_path=".vg/runs/${run_id}/tasklist-contract.json"
if [ ! -f "$contract_path" ]; then
  exit 0
fi

# Build evidence payload from TodoWrite input + contract.
# NOTE: pass hook input via env var (VG_HOOK_INPUT) — heredoc consumes stdin.
payload="$(VG_HOOK_INPUT="$input" python3 - "$contract_path" "$run_id" <<'PY'
import hashlib, json, os, sqlite3, sys
from pathlib import Path
from datetime import datetime, timezone
contract_path, run_id = sys.argv[1:]
hook_input = json.loads(os.environ.get("VG_HOOK_INPUT", "{}"))
contract = json.loads(open(contract_path).read())

# v2.51+ tool dispatch: TodoWrite is legacy; TaskCreate/TaskUpdate are the
# native task UI on newer Claude Code runtimes. TaskCreate fires once per
# todo; aggregate via per-run trace file so a single 37-call sequence
# reconstructs the same {todos: [...]} shape TodoWrite would have produced.
tool_name = hook_input.get("tool_name") or "TodoWrite"
trace_path = Path(f".vg/runs/{run_id}/.taskcreate-trace.jsonl")

if tool_name == "TodoWrite":
    todos = hook_input.get("tool_input", {}).get("todos", []) or []
elif tool_name == "TaskCreate":
    tool_input = hook_input.get("tool_input", {}) or {}
    subject = (tool_input.get("subject") or "").strip()
    # Optional task_id captured from response so TaskUpdate can match later
    task_id = ""
    tr = hook_input.get("tool_response") or hook_input.get("tool_result") or {}
    if isinstance(tr, dict):
        task_id = str(tr.get("task_id") or tr.get("id") or "")
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

# Reconstruct todos[] from trace when this is a TaskCreate/TaskUpdate run.
if tool_name in ("TaskCreate", "TaskUpdate"):
    items_by_id = {}        # task_id -> {content, status}
    items_no_id = []        # entries without task_id (degraded fallback)
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
                entry = {"content": rec.get("subject", ""), "status": rec.get("status", "pending")}
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

# Tolerant match: each contract checklist matched if any group-header todo
# content contains its id or its title. Allows AI to format group content
# as "id", "title", or "id: title (N steps)" without breaking verification.
todo_contents = [t.get("content", "").strip() for t in todos if t.get("content")]

# Task 44b — Rule V2 (depth check): scan all raw todos in order and count, per
# group_header, the number of immediately-following items prefixed with "↳".
# A group with 0 children is "flat" → depth_valid=false. The previous
# implementation FILTERED OUT ↳ rows before matching (audit P4 smoking gun);
# that REWARDED flat tasklists. We now keep raw order and walk it linearly.

def _is_sub(content: str) -> bool:
    return content.lstrip().startswith("↳")

# Walk todos in order. For each group-header (non-↳), count the number of ↳
# items that immediately follow before the next group-header.
groups_seen = []        # ordered list of (matched_id, header_text)
sub_counts = {}         # matched_id -> int
current_id = None
for content in todo_contents:
    if _is_sub(content):
        if current_id is not None:
            sub_counts[current_id] = sub_counts.get(current_id, 0) + 1
        # else: orphan sub before any group — ignored
        continue
    # group-header row: try to match against contract checklists by id or title.
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

# depth_valid: every matched group must have ≥1 ↳ child.
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
            if item.get("kind") == "step" and item.get("id") == latest_marked_step:
                title = str(item.get("title") or "").strip()
                if title:
                    accepted.add(title)
                    accepted.add(title.lstrip(" ↳").strip())
        latest_marked_status_valid = False
        for todo in todos:
            content = str(todo.get("content") or "")
            if any(token and token in content for token in accepted):
                latest_marked_status = str(todo.get("status") or "")
                latest_marked_status_valid = latest_marked_status == "completed"
                break

payload = {
    "run_id": run_id,
    "adapter": "claude",
    "tool_name": tool_name,
    "todowrite_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "todo_count": len(todos),
    "contract_sha256": hashlib.sha256(open(contract_path, "rb").read()).hexdigest(),
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
PY
)"

# Resolve helper path relative to this hook (works when synced to .claude/scripts/).
hook_dir="$(cd "$(dirname "$0")" && pwd)"
helper="${hook_dir}/../vg-orchestrator-emit-evidence-signed.py"
if [ ! -f "$helper" ]; then
  helper="scripts/vg-orchestrator-emit-evidence-signed.py"
fi

evidence_out=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
python3 "$helper" --out "$evidence_out" --payload "$payload"

# Emit telemetry event (best-effort).
if command -v vg-orchestrator >/dev/null 2>&1; then
  cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["command"])' "$run_file" | sed 's/^vg://')"
  vg-orchestrator emit-event "${cmd}.native_tasklist_projected" >/dev/null 2>&1 || true
fi

# F2 v2.60.0: capture latest TodoWrite payload to snapshot for F1 restore on
# resume/compact. Best-effort — never block the hook on snapshot failure.
# Reuses $input (the original stdin) so we don't try to re-read closed stdin.
snap_helper="${hook_dir}/vg-tasklist-snapshot.py"
if [ ! -f "$snap_helper" ]; then
  snap_helper="scripts/hooks/vg-tasklist-snapshot.py"
fi
if [ -f "$snap_helper" ]; then
  # Pull the todos[] (TodoWrite path) or reconstruct from the trace
  # (TaskCreate/TaskUpdate path) and pipe to the snapshot helper.
  VG_HOOK_INPUT="$input" VG_RUN_ID="$run_id" python3 - "$snap_helper" <<'PY' >/dev/null 2>&1 || true
import json, os, subprocess, sys
from pathlib import Path
helper = sys.argv[1]
hook_input = json.loads(os.environ.get("VG_HOOK_INPUT", "{}") or "{}")
run_id = os.environ.get("VG_RUN_ID", "")
if not run_id:
    sys.exit(0)
tool_name = hook_input.get("tool_name") or "TodoWrite"
todos = []
if tool_name == "TodoWrite":
    todos = hook_input.get("tool_input", {}).get("todos") or []
else:
    # TaskCreate / TaskUpdate — reconstruct from per-run trace file we just
    # appended to. Mirrors the logic above so snapshot stays in sync.
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
                entry = {"id": tid or rec.get("subject", ""),
                         "content": rec.get("subject", ""),
                         "status": rec.get("status", "pending")}
                if tid:
                    items_by_id[tid] = entry
                else:
                    items_no_id.append(entry)
            elif act == "update":
                if tid in items_by_id and rec.get("status"):
                    items_by_id[tid]["status"] = rec["status"]
        todos = list(items_by_id.values()) + items_no_id
if not todos:
    sys.exit(0)
payload = json.dumps({"items": todos})
proc = subprocess.run(
    [sys.executable, helper, "--write", "--run-id", run_id],
    input=payload, capture_output=True, text=True,
)
PY
fi
