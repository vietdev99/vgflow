#!/usr/bin/env bash
# PreToolUse on Write/Edit — closes Codex bypass #2 (forgeable evidence).
# Blocks direct writes to protected evidence/marker/event paths.
#
# NOTE: this hook does NOT use the VG context guard. Protected-path
# enforcement is filesystem-scoped, not session-scoped. Any caller
# (VG or not) writing to .vg/runs/*/evidence-* or .vg/events.db
# corrupts the signed evidence pipeline. See R5.5 design §3.3.
# Regression test: tests/hooks/test_write_protection_unconditional.py

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"
file_path="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"

if [ -z "$file_path" ]; then
  exit 0
fi

# Protected path patterns.
protected_patterns=(
  '\.vg/runs/[^/]+/\.tasklist-projected\.evidence\.json$'
  '\.vg/runs/[^/]+/evidence-.*\.json$'
  '\.vg/runs/[^/]+/.*evidence.*'
  '\.vg/phases/.*/\.step-markers/.*\.done$'
  '\.vg/events\.db$'
  '\.vg/events\.jsonl$'
)

# HOTFIX session 2 (2026-05-05) — universal mutating-tool tasklist gate.
# Codex insight #1: bash gate alone doesn't stop Edit/Write; AI can skip
# step-active entirely and write code via Write/Edit/MultiEdit without
# ever projecting the tasklist. This block adds a pre-flight check:
#   - run-active && evidence file missing && file_path NOT in whitelist → DENY
# Whitelist (allowed when evidence missing): paths under .vg/ (orchestrator
# state, blocks, contracts) so the harness itself can write its own files.
session_id="$(vg_resolve_session_id)"
run_file=".vg/active-runs/${session_id}.json"
if [ -f "$run_file" ]; then
  run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file" 2>/dev/null || echo "")"
  if [ -n "$run_id" ]; then
    evidence_path=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
    tasklist_gate_cause=""
    if [ ! -f "$evidence_path" ]; then
      tasklist_gate_cause="mutating tool blocked: tasklist not yet projected for run ${run_id}"
    elif [ -f ".vg/events.db" ]; then
      tasklist_sync_result="$(VG_RUN_ID="${run_id}" VG_EV_PATH="$evidence_path" VG_DB_PATH=".vg/events.db" python3 - <<'PY'
import json, os, sqlite3, sys
from pathlib import Path

run_id = os.environ["VG_RUN_ID"]
ev_path = Path(os.environ["VG_EV_PATH"])
db_path = Path(os.environ["VG_DB_PATH"])

try:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT step, ts FROM events "
        "WHERE run_id = ? AND event_type = 'step.marked' AND step IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    conn.close()
except Exception:
    row = None

if not row:
    print("ok", end="")
    sys.exit(0)

latest_step, latest_ts = row
try:
    payload = json.loads(ev_path.read_text(encoding="utf-8")).get("payload", {})
except Exception as exc:
    print(f"unreadable:{exc}", end="")
    sys.exit(0)

if payload.get("latest_marked_step") != latest_step or payload.get("latest_marked_at") != latest_ts:
    print(f"stale after mark-step {latest_step}@{latest_ts}", end="")
    sys.exit(0)
if payload.get("adapter") == "claude" and payload.get("latest_marked_status_valid") is not True:
    print(f"TodoWrite status stale for {latest_step}", end="")
    sys.exit(0)
print("ok", end="")
PY
)"
      if [ "$tasklist_sync_result" != "ok" ]; then
        tasklist_gate_cause="mutating tool blocked: task UI not refreshed (${tasklist_sync_result})"
      fi
    fi
    if [ -n "$tasklist_gate_cause" ]; then
      # Whitelist: only allow writes under .vg/ when tasklist not yet projected.
      # AI can still run emit-tasklist.py preflight (writes contract under .vg/runs/)
      # and orchestrator state, but cannot edit code/specs/anything outside .vg/.
      if [[ ! "$file_path" =~ ^(\.vg/|\./\.vg/|/.*/\.vg/) ]] && [[ ! "$file_path" =~ /\.vg/ ]]; then
        gate_id="PreToolUse-Write-tasklist-required"
        block_dir=".vg/blocks/${run_id}"
        block_file="${block_dir}/${gate_id}.md"
        cause="$tasklist_gate_cause"
        mkdir -p "$block_dir" 2>/dev/null
        cat > "$block_file" <<EOF
# Block diagnostic — ${gate_id}

## Cause
${cause}

Mutating tools (Write/Edit/NotebookEdit) are blocked until the run's
tasklist contract is projected into the native TodoWrite UI. This
prevents AI from skipping the planning step and editing code without
the user seeing what work is queued.

## Required fix
1. Ensure \`.vg/runs/${run_id}/tasklist-contract.json\` exists. If missing,
   run the command's emit-tasklist.py preflight first.
2. Read the contract (parse \`checklists[]\`).
3. Call the \`TodoWrite\` tool with one group header per checklist + at
   least one \`↳\` sub-item per group.
4. Run: \`python3 .claude/scripts/vg-orchestrator tasklist-projected\`
   (auto-detect adapter — no flag needed).

After step 4, this hook will allow Write/Edit on \`${file_path}\`.

## Narration template (use session language)
[VG diagnostic] Bị chặn: chưa lên tasklist trước khi sửa code.
Đang xử lý: project tasklist-contract → call TodoWrite → tasklist-projected.

## After fix
\`\`\`
vg-orchestrator emit-event vg.block.handled --gate ${gate_id} \\
  --resolution "tasklist projected, retrying write"
\`\`\`
EOF
        VG_HOOK_REASON="${gate_id}: ${cause}
Block file: ${block_file}

Mutating tools are blocked until tasklist is projected. Required:
1. Verify .vg/runs/${run_id}/tasklist-contract.json exists (run emit-tasklist.py if missing).
2. Read it, parse checklists[].
3. Call TodoWrite with one group header per checklist + ≥1 ↳ sub-item per group.
4. Run: python3 .claude/scripts/vg-orchestrator tasklist-projected

After fix:
vg-orchestrator emit-event vg.block.handled --gate ${gate_id} --resolution \"tasklist projected, retrying write\"" \
        VG_HOOK_ADDL="VG run blocked — read ${block_file}" \
        python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": os.environ.get("VG_HOOK_REASON", ""),
  }
}))
' 2>/dev/null || true
        printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for fix\n" \
          "$gate_id" "$cause" "$block_file" >&2
        if command -v vg-orchestrator >/dev/null 2>&1; then
          vg-orchestrator emit-event vg.block.fired \
            --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
        fi
        exit 2
      fi
    fi
  fi
fi

for pattern in "${protected_patterns[@]}"; do
  if [[ "$file_path" =~ $pattern ]]; then
    gate_id="PreToolUse-Write-protected"
    session_id="$(vg_resolve_session_id)"
    run_file=".vg/active-runs/${session_id}.json"
    run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file" 2>/dev/null || echo unknown)"
    block_dir=".vg/blocks/${run_id}"
    block_file="${block_dir}/${gate_id}.md"
    cause="direct write to protected path: $file_path"

    mkdir -p "$block_dir" 2>/dev/null
    cat > "$block_file" <<EOF
# Block diagnostic — ${gate_id}

## Cause
${cause}

This path holds harness-controlled evidence; direct writes would forge
the harness's view of what AI did.

## Required fix
- For evidence files: use \`scripts/vg-orchestrator-emit-evidence-signed.py\`
- For markers: use \`vg-orchestrator mark-step <command> <step>\`
- For events: use \`vg-orchestrator emit-event <type> --payload <json>\`

## Narration template (use session language)
[VG diagnostic] Bước hiện tại bị chặn vì cố ghi vào đường dẫn được bảo vệ.
Đang xử lý: dùng helper signed.

## After fix
\`\`\`
vg-orchestrator emit-event vg.block.handled --gate ${gate_id} \\
  --resolution "switched to signed helper"
\`\`\`
EOF

    # Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
    printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for fix\n→ After fix: vg-orchestrator emit-event vg.block.handled --gate %s\n" \
      "$gate_id" "$cause" "$block_file" "$gate_id" >&2

    if command -v vg-orchestrator >/dev/null 2>&1; then
      vg-orchestrator emit-event vg.block.fired \
        --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
    fi
    exit 2
  fi
done

exit 0
