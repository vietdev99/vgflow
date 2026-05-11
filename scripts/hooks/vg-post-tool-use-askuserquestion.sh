#!/usr/bin/env bash
# PostToolUse on AskUserQuestion — non-blocking reminder so the AI updates
# the native task UI (TodoWrite / TaskCreate / TaskUpdate) after the user's
# answer, before continuing the workflow step.
#
# Surfaced gap (#TODO-tasklist-after-askuserquestion):
#   AI asks 1-2-3, user picks #3 (Other) and types custom text. AI receives
#   the answer, makes a decision, executes the next bash/edit — but does NOT
#   call TaskUpdate to reflect the chosen branch. The native task UI drifts
#   behind the actual decision, so the user loses real-time visibility.
#
# This hook fires AFTER each AskUserQuestion answer and emits a
# `hookSpecificOutput.additionalContext` reminder. The hook is non-blocking
# (advisory). It is silent when no VG run is active (context guard) and
# when no tasklist contract exists yet (e.g. early in run-start).

set -euo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"

session_id="$(vg_resolve_session_id)"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file" 2>/dev/null || true)"
if [ -z "$run_id" ]; then
  exit 0
fi

contract_path=".vg/runs/${run_id}/tasklist-contract.json"
if [ ! -f "$contract_path" ]; then
  exit 0
fi

reminder='VG tasklist sync (post-AskUserQuestion): you just received the user answer. If this answer chose a branch, scoped the step, or added/removed work in the active phase, you MUST call TaskUpdate (or TodoWrite on legacy runtime) to reflect the new branch BEFORE running the next bash/edit. Pattern: keep group header, append/edit the active step or its `↳` sub-items so the native task UI mirrors the decision. The task UI is the user'\''s primary progress signal — do not let it drift behind your decisions.'

VG_HOOK_REMINDER="$reminder" python3 - <<'PY' 2>/dev/null || true
import json, os, sys
sys.stdout.write(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": os.environ.get("VG_HOOK_REMINDER", ""),
    }
}))
PY

exit 0
