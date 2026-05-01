# shellcheck shell=bash
# T8 gate integrity check — shared by build/review/test/accept commands.
#
# Replaces raw "exit 1 if gate-conflicts.md exists" with block_resolve flow:
#   L1 — parse gate-conflicts.md; if every entry carries a resolution marker
#        ({resolved-upstream|resolved-merged|skipped}) or file is empty,
#        auto-delete + pass (safe — nothing for human to inspect).
#   L2 — architect proposal for unresolved conflicts.
#   L4 — traditional block with fix command.
#
# Usage in command body:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/t8-gate-check.sh"
#   t8_gate_check "${PLANNING_DIR}" "build" || exit $?
#
# Return:
#   0 — no conflicts, or L1 cleared them
#   1 — L4 stuck; caller must exit 1
#   2 — L2 proposal dumped (caller presents to user)

t8_gate_check() {
  local planning_dir="${1:-.vg}"
  local command_name="${2:-unknown}"
  local conflicts_file="${planning_dir}/vgflow-patches/gate-conflicts.md"

  # Fast path — no conflict file at all.
  [ -f "$conflicts_file" ] || return 0

  # ─── L0 inline quick-check — file exists but all entries resolved? ───
  # Grep for any heading entry that is NOT followed by a resolution marker
  # on the same or next line. If 0 unresolved → safe to delete + pass.
  local unresolved_count total_count
  total_count=$(grep -cE '^## ' "$conflicts_file" 2>/dev/null || echo 0)
  # An entry is "resolved" if any of its body lines contains:
  #   [resolved-upstream] | [resolved-merged] | [skipped] | [manual-review]
  unresolved_count=$("${PYTHON_BIN:-python3}" - "$conflicts_file" <<'PY' 2>/dev/null || echo "999"
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0); sys.exit(0)
text = p.read_text(encoding="utf-8", errors="replace")
entries = re.split(r'(?m)^## ', text)
unresolved = 0
for entry in entries[1:]:
    if not re.search(r'\[(resolved-upstream|resolved-merged|skipped|manual-review)\]', entry):
        unresolved += 1
print(unresolved)
PY
)

  if [ "${total_count:-0}" = "0" ] || [ "${unresolved_count:-999}" = "0" ]; then
    echo "▸ T8 gate: all ${total_count} conflict entries resolved — auto-clearing stale file" >&2
    # Keep a copy for audit, delete active file
    local archive="${conflicts_file%.md}.resolved-$(date +%Y%m%d-%H%M%S).md"
    mv "$conflicts_file" "$archive" 2>/dev/null || rm -f "$conflicts_file"
    # Also remove sibling diff dir if empty
    [ -d "${planning_dir}/vgflow-patches/gate-conflicts" ] && \
      rmdir "${planning_dir}/vgflow-patches/gate-conflicts" 2>/dev/null || true
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "block_self_resolved_inline" "${VG_CURRENT_PHASE:-unknown}" \
        "${command_name}.t8-gate" "t8-integrity" "RESOLVED" \
        "{\"archived_to\":\"${archive}\",\"reason\":\"all entries carry resolution markers\"}"
    fi
    return 0
  fi

  # ─── Unresolved entries exist — try block_resolve for L2/L4 path ───
  if type -t block_resolve >/dev/null 2>&1; then
    export VG_CURRENT_STEP="${command_name}.t8-gate"
    local evidence
    evidence=$("${PYTHON_BIN:-python3}" -c "
import json
print(json.dumps({
    'conflicts_file': '${conflicts_file}',
    'total_entries': ${total_count:-0},
    'unresolved_entries': ${unresolved_count:-999},
}))
")
    local candidates='[
      {"id":"retry-parse","cmd":"false","confidence":0.2,
       "rationale":"no safe L1 auto-fix for unresolved gate drift — human must inspect each diff"}
    ]'
    local gate_context="T8 gate integrity: /vg:update 3-way merge altered hard-gate blocks. ${unresolved_count} unresolved conflicts remain in ${conflicts_file}. Pipeline cannot trust its own enforcement until a human resolves each via /vg:reapply-patches --verify-gates."
    local br_result
    br_result=$(block_resolve "t8-gate-integrity" "$gate_context" "$evidence" "" "$candidates")
    local br_level
    br_level=$("${PYTHON_BIN:-python3}" -c "import json,sys; print(json.loads(sys.argv[1]).get('level',''))" "$br_result" 2>/dev/null)
    case "$br_level" in
      L1) return 0 ;;
      L2)
        if type -t block_resolve_l2_handoff >/dev/null 2>&1; then
          block_resolve_l2_handoff "t8-gate-integrity" "$br_result" ""
        fi
        return 2
        ;;
      *) ;;  # fall through to L4
    esac
  fi

  # ─── L4 — human must resolve ───
  echo "⛔ T8 gate integrity: ${unresolved_count}/${total_count} conflicts unresolved." >&2
  echo "   File: ${conflicts_file}" >&2
  echo "   Fix:  /vg:reapply-patches --verify-gates" >&2
  return 1
}
