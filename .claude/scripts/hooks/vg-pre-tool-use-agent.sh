#!/usr/bin/env bash
# PreToolUse on Agent — Codex fix #3 (correct tool name "Agent" not "Task").
# R1a scope: enforce subagent allow-list. Spawn-count check added in R2 build spec.

set -euo pipefail

input="$(cat)"

# ── VG context guard ──
# Hook is harmless when no VG run is active. Silent exit prevents
# false blocks on unrelated Claude Code skills (superpowers, gsd, etc).
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0
fi

subagent="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("subagent_type",""))' 2>/dev/null || true)"

# Allow-list: general-purpose, Explore, Plan, vg-* custom agents.
# Debug retries should use `general-purpose` (canonical), not `gsd-debugger`
# (deprecated — GSD framework agent, no longer needed in VG).
if [[ "$subagent" =~ ^(general-purpose|Explore|Plan)$ ]]; then
  exit 0
fi
if [[ "$subagent" == vg-* ]]; then
  exit 0
fi

emit_block() {
  local cause="$1"
  local gate_id="PreToolUse-Agent-allowlist"
  local session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
  local run_file=".vg/active-runs/${session_id}.json"
  local run_id
  run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file" 2>/dev/null || echo unknown)"
  local block_dir=".vg/blocks/${run_id}"
  local block_file="${block_dir}/${gate_id}.md"

  mkdir -p "$block_dir" 2>/dev/null
  cat > "$block_file" <<EOF
# Block diagnostic — ${gate_id}

## Cause
${cause}

## Allowed subagents
- \`general-purpose\` — generic task delegation (also the canonical debug-retry slot)
- \`Explore\` — read-only code search
- \`Plan\` — implementation planning (read-only)
- \`vg-*\` — VG custom agents (vg-blueprint-planner, vg-blueprint-contracts, vg-haiku-scanner, etc.)

## Required fix
Switch \`subagent_type\` to one in the allow-list above.
\`gsd-*\` agents are blocked — VG framework no longer borrows from GSD.
For debug retries, use \`general-purpose\` (or invoke \`/vg:debug\` interactively).

## Narration template (use session language)
[VG diagnostic] Spawn subagent bị chặn vì kiểu '${subagent}' không trong allow-list.
EOF

  # Tier 1 #108 — JSON stdout (Claude Code 2.0+ permissionDecision channel).
  # Mirrors .claude/scripts/vg-agent-spawn-guard.py:140-177 dual-channel pattern.
  VG_HOOK_REASON="${gate_id}: ${cause}
Block file: ${block_file}

Allowed subagents:
- general-purpose — generic task delegation (also canonical debug-retry slot)
- Explore — read-only code search
- Plan — implementation planning (read-only)
- vg-* — VG custom agents (vg-blueprint-planner, vg-blueprint-contracts, vg-haiku-scanner, etc.)

Required fix:
Switch subagent_type to one in the allow-list above.
gsd-* agents are blocked — VG framework no longer borrows from GSD.
For debug retries, use general-purpose (or invoke /vg:debug interactively)." \
  VG_HOOK_ADDL="VG run blocked — read ${block_file} for allowed-list + fix" \
  python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": os.environ.get("VG_HOOK_REASON", ""),
    "additionalContext": os.environ.get("VG_HOOK_ADDL", ""),
  }
}))
' 2>/dev/null || true

  # Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
  printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for allowed list\n" "$gate_id" "$cause" "$block_file" >&2

  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
  fi
  exit 2
}

# Block gsd-* explicitly — VG no longer borrows from GSD framework.
if [[ "$subagent" == gsd-* ]]; then
  emit_block "subagent type '${subagent}' not allowed — VG framework no longer borrows from GSD; use 'general-purpose' for debug retries"
fi

# Default deny unknown.
emit_block "unknown subagent type '${subagent}'"
