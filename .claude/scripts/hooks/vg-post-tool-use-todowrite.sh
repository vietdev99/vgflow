#!/usr/bin/env bash
# PostToolUse on TodoWrite — capture payload, diff vs contract,
# write signed evidence via vg-orchestrator-emit-evidence-signed.py.

set -euo pipefail

input="$(cat)"
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
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
import hashlib, json, os, sys
from datetime import datetime, timezone
contract_path, run_id = sys.argv[1:]
hook_input = json.loads(os.environ.get("VG_HOOK_INPUT", "{}"))
todos = hook_input.get("tool_input", {}).get("todos", [])
contract = json.loads(open(contract_path).read())
checklists = contract.get("checklists", [])

# Tolerant match: each contract checklist matched if any todo content contains
# its id or its title. Sub-step todos (prefixed "↳") are ignored when matching
# group-level coverage. Allows AI to format content as "id", "title", or
# "id: title (N steps)" without breaking verification.
todo_contents = [t.get("content", "").strip() for t in todos if t.get("content")]
group_contents = [c for c in todo_contents if not c.lstrip().startswith("↳")]
matched_ids = set()
for content in group_contents:
    for c in checklists:
        if c["id"] in content or c["title"] in content:
            matched_ids.add(c["id"])
            break
contract_ids = sorted([c["id"] for c in checklists])
match = matched_ids == set(contract_ids)
payload = {
    "run_id": run_id,
    "todowrite_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "todo_count": len(todos),
    "contract_sha256": hashlib.sha256(open(contract_path, "rb").read()).hexdigest(),
    "todo_ids": sorted(matched_ids),
    "contract_ids": contract_ids,
    "match": match,
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
