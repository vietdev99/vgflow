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

input="$(cat)"
file_path="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"

if [ -z "$file_path" ]; then
  exit 0
fi

# Protected path patterns.
protected_patterns=(
  '\.vg/runs/[^/]+/\.tasklist-projected\.evidence\.json$'
  '\.vg/runs/[^/]+/\.codex-spawn-manifest\.jsonl$'
  '\.vg/runs/[^/]+/\.spawn-count\.json$'
  '\.vg/runs/[^/]+/codex-spawns/.*'
  '\.vg/runs/[^/]+/evidence-.*\.json$'
  '\.vg/runs/[^/]+/.*evidence.*'
  '\.vg/phases/.*/\.step-markers/.*\.done$'
  '\.vg/events\.db$'
  '\.vg/events\.jsonl$'
)

for pattern in "${protected_patterns[@]}"; do
  if [[ "$file_path" =~ $pattern ]]; then
    gate_id="PreToolUse-Write-protected"
    session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
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
