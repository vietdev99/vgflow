#!/usr/bin/env bash
# PostToolUse on Agent — Issue #140 mitigation (git add -N intent-to-add)
#                     + v2.61.0 L2 post-wave reminder.
#
# (1) Issue #140: When a subagent returns artifact paths (PLAN.md,
#     API-CONTRACTS.md, etc.), mark them as intent-to-add so `git status`
#     surfaces them. If a destructive git op is later attempted (checkout,
#     reset, switch), git will refuse or warn instead of silently dropping
#     the untracked content.
#
# (2) v2.61.0 L2 reminder: When a wave-style executor subagent returns
#     (vg-build-task-executor, vg-test-codegen, vg-test-goal-verifier,
#     vg-deploy-executor, vg-accept-uat-builder) AND the active run is on
#     its final wave AND the corresponding post-step marker has NOT been
#     touched, emit a stderr reminder telling the AI to continue the
#     remaining steps of the command IN THE SAME TURN.
#
# Best-effort + fail-soft. NEVER blocks — exit 0 unconditionally.

set -uo pipefail

# shellcheck source=_lib.sh
. "$(dirname "$0")/_lib.sh"

input="$(cat)"
session_id="$(vg_resolve_session_id_from_input "$input" 2>/dev/null || echo unknown)"
run_file=".vg/active-runs/${session_id}.json"

# ---------------------------------------------------------------------------
# (1) intent-to-add path harvesting (#140)
# ---------------------------------------------------------------------------
# Wrapped in a function so a bail-out (no active run / no git / no paths)
# does NOT prevent (2) from running.
do_intent_to_add() {
  # No active run → nothing to protect
  [ -f "$run_file" ] || return 0
  # Not a git repo → nothing to add
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  # Extract artifact paths from subagent JSON return.
  local paths_json
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
        for k, v in obj.items():
            if k in ("tool_output", "tool_response", "result", "output"):
                harvest(v)
    elif isinstance(obj, list):
        for item in obj:
            harvest(item)
    elif isinstance(obj, str):
        for m in re.finditer(r"(?:\.vg/runs/[A-Za-z0-9_\-./]+)", obj):
            candidates.append(m.group(0))

harvest(data)

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

  local -a paths
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

  [ "${#paths[@]}" -eq 0 ] && return 0

  for p in "${paths[@]}"; do
    # Strip trailing CR (Python on Windows emits CRLF via mapfile)
    p="${p%$'\r'}"
    [ -z "$p" ] && continue
    if [ -f "$p" ]; then
      git add --intent-to-add -- "$p" >/dev/null 2>&1 || true
    fi
  done
}

# ---------------------------------------------------------------------------
# (2) v2.61.0 L2 — post-wave reminder
# ---------------------------------------------------------------------------
# Triggers when:
#   - active VG run exists
#   - tool_input.subagent_type matches a wave-style executor
#   - is-final-wave=true  OR  is-final-wave file absent (commands without
#     per-wave concept — e.g. vg:test, vg:deploy — assume final)
#   - the expected post-step marker has NOT been touched yet
#
# Output to STDERR (Claude Code surfaces stderr in tool result; AI sees it).
do_post_wave_reminder() {
  # No active run → no run to remind about
  [ -f "$run_file" ] || return 0

  # Extract subagent_type from tool input
  local subagent_type
  subagent_type="$(VG_HOOK_INPUT="$input" python3 - <<'PY' 2>/dev/null || true
import json, os, sys
try:
    d = json.loads(os.environ.get("VG_HOOK_INPUT", "{}"))
    print(d.get("tool_input", {}).get("subagent_type", "") or "")
except Exception:
    pass
PY
)"
  [ -z "$subagent_type" ] && return 0

  # Map subagent_type → command + post-step marker name
  local expected_command expected_marker
  case "$subagent_type" in
    vg-build-task-executor)
      expected_command="vg:build"; expected_marker="9_post_execution" ;;
    vg-test-codegen)
      expected_command="vg:test"; expected_marker="5c_goal_verification" ;;
    vg-test-goal-verifier)
      expected_command="vg:test"; expected_marker="write_report" ;;
    vg-deploy-executor)
      expected_command="vg:deploy"; expected_marker="2_persist_summary" ;;
    vg-accept-uat-builder)
      expected_command="vg:accept"; expected_marker="5_interactive_uat" ;;
    *)
      return 0 ;;  # not a wave-style executor
  esac

  # Read run_id, command, phase from active-run state.
  # Use VG_RUN_FILE env var (single-quoted heredoc — no shell expansion in
  # python source, and `read` strips trailing newline from $() so phase
  # cannot accidentally carry whitespace.)
  local run_id command phase
  run_id="$(VG_RUN_FILE="$run_file" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    with open(os.environ["VG_RUN_FILE"], "r", encoding="utf-8") as f:
        d = json.load(f)
    print((d.get("run_id", "") or "").strip())
except Exception:
    pass
PY
)"
  phase="$(VG_RUN_FILE="$run_file" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    with open(os.environ["VG_RUN_FILE"], "r", encoding="utf-8") as f:
        d = json.load(f)
    print((d.get("phase", "") or "").strip())
except Exception:
    pass
PY
)"
  [ -z "$run_id" ] && return 0
  [ -z "$phase" ] && return 0

  # Determine command segment for marker dir (vg:build → build, vg:test → test)
  local cmd_seg
  cmd_seg="${expected_command#vg:}"

  # Final-wave check:
  #   - file absent → assume final (commands without --wave concept)
  #   - file present with exact content "true" → final
  #   - anything else (including "false") → partial wave, skip
  local is_final_wave_file=".vg/runs/${run_id}/.is-final-wave"
  if [ -f "$is_final_wave_file" ]; then
    local content
    content="$(tr -d '[:space:]' < "$is_final_wave_file" 2>/dev/null || true)"
    if [ "$content" != "true" ]; then
      return 0
    fi
    final_wave_value="true"
  else
    final_wave_value="(absent — assumed final)"
  fi

  # Marker check: if already touched, no reminder needed
  local marker_file=".vg/phases/${phase}/.step-markers/${cmd_seg}/${expected_marker}.done"
  if [ -f "$marker_file" ]; then
    return 0
  fi

  # Emit reminder to stderr
  cat >&2 <<EOF
▸ POST-WAVE REMINDER (${expected_command})

Wave Agent (${subagent_type}) just returned. Active run: ${run_id} (phase ${phase}).
.is-final-wave=${final_wave_value}, post-step marker ${expected_marker} NOT yet touched.

You MUST continue ${expected_command}'s remaining steps IN THE SAME TURN:
  Read commands/vg/${cmd_seg}.md from STEP 5 (or equivalent post-wave step) onwards.
  Do NOT end the turn after this Agent return.

If this is a partial-wave run (--wave N where N < max), this reminder is harmless — the contract validator's is_partial_wave exemption skips post-execution markers. Only fires when missing markers indicate a real continuation gap.
EOF
}

# Run both, swallow any errors, always exit 0.
do_intent_to_add || true
do_post_wave_reminder || true

exit 0
