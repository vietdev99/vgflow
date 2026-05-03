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

# Allow-list: general-purpose, Explore, Plan, vg-* custom agents, gsd-debugger only.
if [[ "$subagent" =~ ^(general-purpose|Explore|Plan|gsd-debugger)$ ]]; then
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
- \`general-purpose\` — generic task delegation
- \`Explore\` — read-only code search
- \`Plan\` — implementation planning (read-only)
- \`vg-*\` — VG custom agents (vg-blueprint-planner, vg-blueprint-contracts, vg-haiku-scanner, etc.)
- \`gsd-debugger\` — GSD debug session manager

## Required fix
Switch \`subagent_type\` to one in the allow-list above.
\`gsd-*\` agents (except gsd-debugger) are blocked because R1a scope is VG-only.

## Narration template (use session language)
[VG diagnostic] Spawn subagent bị chặn vì kiểu '${subagent}' không trong allow-list.
EOF

  # Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to title.
  printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for allowed list\n" "$gate_id" "$cause" "$block_file" >&2

  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
  fi
  exit 2
}

# Block gsd-* explicitly (except gsd-debugger handled above).
if [[ "$subagent" == gsd-* ]]; then
  emit_block "subagent type '${subagent}' not allowed (R1a scope is VG-only)"
fi

# Default deny unknown.
emit_block "unknown subagent type '${subagent}'"
