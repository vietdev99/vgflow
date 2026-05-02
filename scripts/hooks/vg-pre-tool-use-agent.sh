#!/usr/bin/env bash
# PreToolUse on Agent — Codex fix #3 (correct tool name "Agent" not "Task").
# R1a scope: enforce subagent allow-list. Spawn-count check added in R2 build spec.

set -euo pipefail

input="$(cat)"
subagent="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("subagent_type",""))' 2>/dev/null || true)"

# Allow-list: general-purpose, Explore, Plan, vg-* custom agents, gsd-debugger only.
if [[ "$subagent" =~ ^(general-purpose|Explore|Plan|gsd-debugger)$ ]]; then
  exit 0
fi
if [[ "$subagent" == vg-* ]]; then
  exit 0
fi

# Block gsd-* explicitly (except gsd-debugger handled above).
if [[ "$subagent" == gsd-* ]]; then
  cat >&2 <<MSG
ERROR: subagent type '${subagent}' not allowed.
Only general-purpose, Explore, Plan, vg-*, gsd-debugger are allowed.
MSG
  exit 2
fi

# Default deny unknown.
cat >&2 <<MSG
ERROR: unknown subagent type '${subagent}'. Allowed: general-purpose, Explore, Plan, vg-*, gsd-debugger.
MSG
exit 2
