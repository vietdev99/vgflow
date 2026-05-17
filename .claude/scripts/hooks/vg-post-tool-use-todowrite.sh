#!/usr/bin/env bash
# PostToolUse on TodoWrite | TaskCreate | TaskUpdate — capture payload,
# diff vs contract, write signed evidence via
# vg-orchestrator-emit-evidence-signed.py.
#
# v2.51+ — TaskCreate/TaskUpdate compatibility (newer Claude Code runtimes
# expose TaskCreate instead of TodoWrite). Per-call appends are aggregated
# into .vg/runs/{run_id}/.taskcreate-trace.jsonl and reconstructed into a
# todos[] shape so the existing matching logic works unchanged.
#
# B78 (v4.63.10) — extracted inline heredoc Python to standalone helper
# scripts. Reason: macOS ships bash 3.2 (GPLv2 freeze) which cannot parse
# heredocs nested inside `"$(...)"` command substitution. Linux CI runs
# bash 4+ which masked the regression. Symptom on macOS:
#   line 31: unexpected EOF while looking for matching `)'
#
# Helpers (siblings of this hook):
#   _vg_tasklist_evidence_payload.py — builds evidence JSON payload
#   _vg_tasklist_snapshot_input.py    — resolves todo step_ids + snapshots

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

hook_dir="$(cd "$(dirname "$0")" && pwd)"
evidence_helper="${hook_dir}/_vg_tasklist_evidence_payload.py"
if [ ! -f "$evidence_helper" ]; then
  # Fallback when hook is symlinked/synced to .claude/scripts/hooks.
  evidence_helper=".claude/scripts/hooks/_vg_tasklist_evidence_payload.py"
fi

# Build evidence payload from TodoWrite/TaskCreate/TaskUpdate input.
# B78: hook input passes via VG_HOOK_INPUT env (NOT heredoc stdin) —
# heredoc-inside-command-substitution does not parse on bash 3.2 (macOS
# default). Helper writes evidence JSON to stdout.
payload="$(VG_HOOK_INPUT="$input" python3 "$evidence_helper" "$contract_path" "$run_id")"

# Resolve signed-evidence emitter path relative to this hook.
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

# F2 v2.60.0: capture latest TodoWrite payload to snapshot for F1 restore
# on resume/compact. Best-effort — never block the hook on snapshot
# failure.
snap_helper="${hook_dir}/vg-tasklist-snapshot.py"
if [ ! -f "$snap_helper" ]; then
  snap_helper="scripts/hooks/vg-tasklist-snapshot.py"
fi
snap_input_resolver="${hook_dir}/_vg_tasklist_snapshot_input.py"
if [ ! -f "$snap_input_resolver" ]; then
  snap_input_resolver=".claude/scripts/hooks/_vg_tasklist_snapshot_input.py"
fi
if [ -f "$snap_helper" ] && [ -f "$snap_input_resolver" ]; then
  VG_HOOK_INPUT="$input" VG_RUN_ID="$run_id" \
    python3 "$snap_input_resolver" "$snap_helper" >/dev/null 2>&1 || true
fi
