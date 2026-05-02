#!/usr/bin/env bash
# PreToolUse on Write/Edit — closes Codex bypass #2 (forgeable evidence).
# Blocks direct writes to protected evidence/marker/event paths.

set -euo pipefail

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

for pattern in "${protected_patterns[@]}"; do
  if [[ "$file_path" =~ $pattern ]]; then
    cat >&2 <<MSG
═══════════════════════════════════════════
DIAGNOSTIC REQUIRED — Gate: PreToolUse-Write-protected
═══════════════════════════════════════════

CAUSE:
  Direct write to protected evidence path:
    ${file_path}
  This path holds harness-controlled evidence; direct writes would
  forge the harness's view of what AI did.

REQUIRED FIX:
  Use scripts/vg-orchestrator-emit-evidence-signed.py to write signed
  evidence, OR use vg-orchestrator subcommand for markers/events.

YOU MUST DO ALL THREE BEFORE CONTINUING:
  A) Tell user: "[VG diagnostic] Bước hiện tại bị chặn vì cố ghi vào
     đường dẫn được bảo vệ. Đang xử lý: dùng helper signed."
  B) Bash: vg-orchestrator emit-event vg.block.handled \\
            --gate PreToolUse-Write-protected \\
            --resolution "switched to signed helper"
  C) Retry with the signed helper.
═══════════════════════════════════════════
MSG
    if command -v vg-orchestrator >/dev/null 2>&1; then
      vg-orchestrator emit-event vg.block.fired \
        --gate PreToolUse-Write-protected \
        --cause "direct write to $file_path" >/dev/null 2>&1 || true
    fi
    exit 2
  fi
done

exit 0
