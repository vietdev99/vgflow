#!/usr/bin/env bash
# PostToolUse on Agent — Issue #140 mitigation (git add -N intent-to-add).
#
# When a subagent returns artifact paths (PLAN.md, API-CONTRACTS.md, etc.),
# mark them as intent-to-add so `git status` surfaces them. If a destructive
# git op is later attempted (checkout, reset, switch), git will refuse or
# warn instead of silently dropping the untracked content.
#
# Best-effort + fail-soft. NEVER blocks — only emits intent-to-add on success.
# Skips when:
#   - Not in a git repo
#   - No active VG run (no harness work to protect)
#   - Subagent return JSON does not contain recognizable artifact paths
#   - Path is outside repo (defensive — git add -N rejects anyway)

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"
session_id="$(vg_resolve_session_id)"
run_file=".vg/active-runs/${session_id}.json"

# No active run → nothing to protect → exit 0 (no narration)
if [ ! -f "$run_file" ]; then
  exit 0
fi

# Not a git repo → no-op
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# Extract artifact paths from subagent JSON return.
# Subagent return envelopes use varying field names:
#   - blueprint planner: paths[] + sub_files[]
#   - blueprint contracts: paths[]
#   - build task executor: artifacts[] + summary_path + build_log_path
#   - generic: tool_response.content[].text contains JSON with paths
# We look in tool_output OR tool_response (Claude Code field naming varies).
paths_json="$(VG_HOOK_INPUT="$input" python3 - <<'PY' 2>/dev/null || echo "[]"
import json
import os
import re
import sys

raw = os.environ.get("VG_HOOK_INPUT", "{}")
try:
    data = json.loads(raw)
except Exception:
    print("[]"); sys.exit(0)

candidates = []

def harvest(obj):
    if isinstance(obj, dict):
        for key in ("paths", "sub_files", "artifacts", "summary_path",
                    "build_log_path", "build_log_sub_files", "files"):
            v = obj.get(key)
            if isinstance(v, str):
                candidates.append(v)
            elif isinstance(v, list):
                candidates.extend(p for p in v if isinstance(p, str))
        # recurse
        for k, v in obj.items():
            if k in ("tool_output", "tool_response", "result", "output"):
                harvest(v)
    elif isinstance(obj, list):
        for item in obj:
            harvest(item)
    elif isinstance(obj, str):
        # Best-effort: scan strings for path-like tokens under .vg/runs/
        for m in re.finditer(r"(?:\.vg/runs/[A-Za-z0-9_\-./]+)", obj):
            candidates.append(m.group(0))

harvest(data)

# Dedup + restrict to relative paths under .vg/ (defensive)
seen = set()
out = []
for p in candidates:
    if not p or p in seen:
        continue
    seen.add(p)
    if p.startswith("/") or ".." in p.split("/"):
        continue
    if p.startswith(".vg/") or p.startswith(".claude/") or "/" in p:
        out.append(p)

print(json.dumps(out))
PY
)"

# Parse JSON array → bash array
mapfile -t paths < <(printf '%s' "$paths_json" | python3 -c '
import json, sys
try:
    arr = json.loads(sys.stdin.read())
    for p in arr:
        if isinstance(p, str):
            print(p)
except Exception:
    pass
' 2>/dev/null || true)

# No paths → exit silently
if [ "${#paths[@]}" -eq 0 ]; then
  exit 0
fi

# Best-effort intent-to-add on each path that exists.
# Quiet — no narration unless debug. Failures (path missing, git ignored, etc.)
# are non-fatal.
for p in "${paths[@]}"; do
  [ -z "$p" ] && continue
  if [ -f "$p" ]; then
    git add --intent-to-add -- "$p" >/dev/null 2>&1 || true
  fi
done

exit 0
