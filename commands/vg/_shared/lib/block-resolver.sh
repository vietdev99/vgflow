# shellcheck shell=bash
# zsh-compat: enable bash-style word-splitting under Claude Code's /bin/zsh.
# See commands/vg/_shared/lib/zsh-compat.sh.
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT 2>/dev/null

# Block Resolver — bash function library (v1.9.1 R2+R4)
# Companion runtime for gate blocks in review / test / build / accept.
#
# Purpose:
#   Replace the anti-pattern "echo BLOCK; print options A/B/C; exit 1"
#   with a 4-level resolver:
#     L1 (inline)    — try auto-fix candidates at the gate, pass rationalization-guard
#     L2 (architect) — spawn provider-native diagnostic subagent with FULL phase context
#     L3 (present)   — show proposal via provider-native prompt
#     L4 (escalate)  — only when L1+L2 exhausted AND user rejects
#
# Exposed functions:
#   - block_resolve GATE_ID GATE_CONTEXT EVIDENCE_JSON [PHASE_DIR] [FIX_CANDIDATES_JSON]
#   - _collect_phase_context PHASE_DIR               (stdout: structured context blob)
#   - _block_resolve_l1_inline ...                   (try fix candidates + ratguard)
#   - _block_resolve_l2_architect ...                (emits prompt file path on fd 3)
#
# Telemetry events emitted:
#   - block_self_resolved_inline    (L1 succeeds)
#   - block_architect_proposed      (L2 returns proposal)
#   - block_user_chose_proposal     (L3 user applied proposal)
#   - block_truly_stuck             (L4 fallback — user rejected everything)

# Check if resolver enabled (config-driven, default ON)
block_resolver_enabled() {
  [ "${CONFIG_BLOCK_RESOLVER_ENABLED:-true}" = "true" ]
}

block_resolver_runtime() {
  case "${VG_RUNTIME:-${VG_PROVIDER:-}}" in
    claude|claude-*) echo "claude"; return ;;
    codex|codex-*) echo "codex"; return ;;
  esac
  if [ -n "${CLAUDE_SESSION_ID:-}" ] || [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] || [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    echo "claude"
    return
  fi
  if [ -n "${CODEX_SANDBOX:-}" ] || [ -n "${CODEX_CLI_SANDBOX:-}" ] || [ -n "${CODEX_HOME:-}" ]; then
    echo "codex"
    return
  fi
  echo "claude"
}

block_resolver_l2_backend_label() {
  case "$(block_resolver_runtime)" in
    codex) echo "Codex scanner adapter" ;;
    *) echo "Claude Haiku" ;;
  esac
}

block_resolver_l3_prompt_label() {
  case "$(block_resolver_runtime)" in
    codex) echo "Codex main-thread prompt" ;;
    *) echo "AskUserQuestion" ;;
  esac
}

# ═══════════════════════════════════════════════════════════════════════
# L1 — Inline auto-fix
# ═══════════════════════════════════════════════════════════════════════
# FIX_CANDIDATES_JSON format:
#   [{"id":"retry-scan","cmd":"<shell>","confidence":0.8,"rationale":"..."},
#    {"id":"reclassify","cmd":"<shell>","confidence":0.6,"rationale":"..."}]
#
# For each candidate with confidence >= 0.7, call rationalization-guard with
# gate_id + skip_reason = candidate.rationale. If PASS, execute cmd.
# If cmd exits 0, L1 succeeded. Otherwise try next candidate.
#
# Returns on stdout (single JSON line):
#   {"resolved":true, "candidate_id":"<id>", "evidence":"<tail output>"}
#   {"resolved":false, "reason":"<why all candidates failed>"}
_block_resolve_l1_inline() {
  local gate_id="$1"
  local gate_context="$2"
  local candidates_json="${3:-[]}"
  local threshold="${CONFIG_BLOCK_L1_CONFIDENCE_THRESHOLD:-0.7}"

  if [ "$candidates_json" = "[]" ] || [ -z "$candidates_json" ]; then
    echo '{"resolved":false,"reason":"no fix candidates provided"}'
    return 1
  fi

  # Iterate candidates meeting threshold
  local count
  count=$(${PYTHON_BIN:-python3} -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$candidates_json" 2>/dev/null || echo 0)

  for i in $(seq 0 $((count - 1))); do
    local cand_id cand_cmd cand_conf cand_rationale
    cand_id=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1])[int(sys.argv[2])]['id'])" "$candidates_json" "$i" 2>/dev/null)
    cand_cmd=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1])[int(sys.argv[2])]['cmd'])" "$candidates_json" "$i" 2>/dev/null)
    cand_conf=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1])[int(sys.argv[2])]['confidence'])" "$candidates_json" "$i" 2>/dev/null)
    cand_rationale=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1])[int(sys.argv[2])].get('rationale',''))" "$candidates_json" "$i" 2>/dev/null)

    # Threshold check
    if ! awk -v c="$cand_conf" -v t="$threshold" 'BEGIN{exit (c+0 >= t+0)?0:1}'; then
      echo "  ↳ L1 skip candidate '${cand_id}' (confidence ${cand_conf} < ${threshold})" >&2
      continue
    fi

    echo "  ↳ L1 try candidate '${cand_id}' (confidence ${cand_conf})" >&2

    # Rationalization-guard check — prevent AI from rationalizing its own inline fix.
    # If guard fn available, ESCALATE = skip this candidate (do not auto-execute).
    if type -t rationalization_guard_check >/dev/null 2>&1; then
      local rg_result verdict
      rg_result=$(rationalization_guard_check "$gate_id" "$gate_context" "L1 inline fix: ${cand_rationale}" 2>/dev/null)
      verdict=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('verdict',''))" "$rg_result" 2>/dev/null || echo "")
      if [ "$verdict" = "ESCALATE" ]; then
        echo "  ↳ L1 candidate '${cand_id}' blocked by rationalization-guard (ESCALATE)" >&2
        continue
      fi
    fi

    # Execute candidate command
    local out rc
    out=$(bash -c "$cand_cmd" 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ]; then
      # L1 succeeded
      local evidence_tail
      evidence_tail=$(echo "$out" | tail -c 400 | tr '\n' ' ' | tr -d '"')
      printf '{"resolved":true,"candidate_id":"%s","evidence":"%s"}\n' "$cand_id" "$evidence_tail"
      return 0
    else
      echo "  ↳ L1 candidate '${cand_id}' failed rc=${rc}" >&2
    fi
  done

  echo '{"resolved":false,"reason":"all candidates failed or below confidence threshold"}'
  return 1
}

# ═══════════════════════════════════════════════════════════════════════
# _collect_phase_context — build structured input for L2 architect
# ═══════════════════════════════════════════════════════════════════════
# Reads SPECS / CONTEXT / PLAN / TEST-GOALS / SUMMARY / API-CONTRACTS /
# RUNTIME-MAP / codebase test framework state. Concatenates with section
# headers. Truncates each artifact to MAX_ARTIFACT_CHARS (default 6000)
# to keep prompt tractable for the cheap diagnostic scanner.
_collect_phase_context() {
  local phase_dir="$1"
  local max_chars="${CONFIG_BLOCK_ARCHITECT_MAX_ARTIFACT_CHARS:-6000}"
  [ -d "$phase_dir" ] || { echo "PHASE_DIR_MISSING: $phase_dir"; return 1; }

  _emit_artifact() {
    local label="$1" path="$2"
    if [ -f "$path" ]; then
      echo "═══ ${label} (${path}) ═══"
      head -c "$max_chars" "$path"
      local size
      size=$(wc -c < "$path" 2>/dev/null || echo 0)
      [ "$size" -gt "$max_chars" ] && echo "... [truncated, total $size bytes]"
      echo ""
    fi
  }

  _emit_artifact "SPECS"         "${phase_dir}/SPECS.md"
  _emit_artifact "CONTEXT"       "${phase_dir}/CONTEXT.md"
  _emit_artifact "PLAN"          "${phase_dir}/PLAN.md"
  _emit_artifact "TEST-GOALS"    "${phase_dir}/TEST-GOALS.md"
  _emit_artifact "API-CONTRACTS" "${phase_dir}/API-CONTRACTS.md"
  _emit_artifact "SUMMARY"       "${phase_dir}/SUMMARY.md"
  _emit_artifact "RUNTIME-MAP"   "${phase_dir}/RUNTIME-MAP.json"
  _emit_artifact "GOAL-COVERAGE" "${phase_dir}/GOAL-COVERAGE-MATRIX.md"
  _emit_artifact "SANDBOX-TEST"  "${phase_dir}/SANDBOX-TEST.md"

  # Codebase test framework state — quick probe
  echo "═══ CODEBASE TEST FRAMEWORK STATE ═══"
  if [ -f "${REPO_ROOT:-.}/package.json" ]; then
    grep -E '"(test|test:|vitest|playwright|jest)"' "${REPO_ROOT:-.}/package.json" 2>/dev/null | head -10
  fi
  [ -f "${REPO_ROOT:-.}/playwright.config.ts" ] && echo "  playwright.config.ts: present"
  [ -f "${REPO_ROOT:-.}/vitest.config.ts" ] && echo "  vitest.config.ts: present"
  if [ -d "${REPO_ROOT:-.}/apps/web/e2e" ]; then
    local e2e_count
    e2e_count=$(find "${REPO_ROOT:-.}/apps/web/e2e" -name "*.spec.ts" 2>/dev/null | wc -l | tr -d ' ')
    echo "  apps/web/e2e: ${e2e_count} .spec.ts files"
  fi
  echo ""

  # vg.config.md snippet (profile + build_gates)
  if [ -f "${REPO_ROOT:-.}/.claude/vg.config.md" ]; then
    echo "═══ vg.config.md (snippet) ═══"
    grep -E "^(profile|models|build_gates|environments):" -A 3 "${REPO_ROOT:-.}/.claude/vg.config.md" 2>/dev/null | head -60
    echo ""
  fi
}

# ═══════════════════════════════════════════════════════════════════════
# L2 — Architect proposal via provider-native diagnostic subagent
# ═══════════════════════════════════════════════════════════════════════
# Writes a prompt file combining:
#   - Architect role template (_shared/lib/architect-prompt-template.md)
#   - Gate context + evidence
#   - Full phase context blob from _collect_phase_context
# Emits prompt file path on fd 3. Claude dispatches Haiku/Task; Codex keeps
# the adapter path and uses codex read-only scanner when live L2 is needed.
#
# Fallback (Task unavailable): return "architect_unavailable" proposal.
_block_resolve_l2_architect() {
  local gate_id="$1"
  local gate_context="$2"
  local evidence_json="$3"
  local phase_dir="${4:-}"

  local runtime
  runtime="$(block_resolver_runtime)"
  local architect_model="${CONFIG_BLOCK_ARCHITECT_MODEL:-}"
  if [ -z "$architect_model" ]; then
    case "$runtime" in
      codex) architect_model="${VG_CODEX_MODEL_SCANNER:-codex-default}" ;;
      *) architect_model="haiku" ;;
    esac
  fi
  local architect_backend
  architect_backend="$(block_resolver_l2_backend_label)"
  local template="${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/architect-prompt-template.md"
  local prompt_path="${VG_TMP:-/tmp}/block-architect-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true

  {
    if [ -f "$template" ]; then
      cat "$template"
    else
      echo "# ARCHITECT ROLE"
      echo "You are the VG architect. Given a stuck phase gate, propose a structural change."
      echo "Return strict JSON: {type, summary, file_structure, framework_choice, decision_questions, confidence}"
    fi
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "STUCK GATE"
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "gate_id: ${gate_id}"
    echo ""
    echo "gate_context:"
    echo "${gate_context}"
    echo ""
    echo "evidence (from L1 attempts):"
    echo "${evidence_json}"
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "PHASE CONTEXT (FULL ARTIFACTS)"
    echo "═══════════════════════════════════════════════════════════════════════"
    if [ -n "$phase_dir" ] && [ -d "$phase_dir" ]; then
      _collect_phase_context "$phase_dir"
    else
      echo "[no phase_dir supplied — architect must recommend from gate context only]"
    fi
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "OUTPUT — strict single-line JSON, no prose before/after"
    echo "═══════════════════════════════════════════════════════════════════════"
    echo '{"type":"sub-phase|refactor|new-artifact|config-change","summary":"<≤ 200 chars>","file_structure":"<paths + purpose, ≤ 500 chars>","framework_choice":"<tool/lib + reason, ≤ 200 chars>","decision_questions":[{"q":"...","recommendation":"...","rationale":"..."}],"confidence":0.0}'
  } > "$prompt_path"

  # Emit prompt path on fd 3 for orchestrator to pick up; also stderr for debug
  echo "$prompt_path" >&3 2>/dev/null || true
  echo "block-architect-prompt: $prompt_path (runtime=${runtime} backend=${architect_backend} model=${architect_model})" >&2

  # RFC v9 PR-D3 stub-3 fix: try installed .claude/scripts helper for live
  # provider-native diagnostic invocation. Falls back to placeholder if script
  # unavailable, CLI not in PATH, or subagent fails.
  local spawn_script="${REPO_ROOT:-.}/.claude/scripts/spawn-diagnostic-l2.py"
  [ -f "$spawn_script" ] || spawn_script="${REPO_ROOT:-.}/scripts/spawn-diagnostic-l2.py"
  if [ -f "$spawn_script" ] && [ -n "$phase_dir" ] && [ -d "$phase_dir" ] && \
     [ "${VG_DIAGNOSTIC_L2_DISABLE:-0}" != "1" ]; then
    # Codex MEDIUM fix: block_family is the validator domain (provenance,
    # traceability, content-depth, ...), NOT the gate_id prefix. Map known
    # gate_id stems to families; default to "uncategorized" for unknown
    # gates (architect still gets full context via evidence_json).
    local block_family
    case "$gate_id" in
      *evidence*|*provenance*|*scanner*|*replay*) block_family="provenance" ;;
      *trace*|*orphan*|*coverage*|*matrix*) block_family="traceability" ;;
      *content*|*depth*|*skim*|*tbd*) block_family="content-depth" ;;
      *fixture*|*recipe*|*invariant*) block_family="fixtures" ;;
      *security*|*auth*|*secret*) block_family="security" ;;
      *contract*|*api-index*|*envelope*) block_family="contract" ;;
      *artifact*|*missing*|*prereq*) block_family="artifacts" ;;
      *) block_family="uncategorized" ;;
    esac
    local spawn_out
    spawn_out=$("${PYTHON_BIN:-python3}" "$spawn_script" \
      --gate-id "$gate_id" \
      --block-family "$block_family" \
      --phase-dir "$phase_dir" \
      --gate-context "$gate_context" \
      --evidence-json "$evidence_json" \
      ${VG_DIAGNOSTIC_L2_DRY_RUN:+--dry-run} \
      2>/dev/null)
    local spawn_rc=$?
    if [ "$spawn_rc" -eq 0 ]; then
      # Translate spawn-diagnostic-l2 output → architect proposal shape
      ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    out = {
        'type': 'diagnostic-l2',
        'summary': d.get('diagnosis', '')[:200],
        'file_structure': 'N/A — proposal stored at .l2-proposals/{}.json'.format(d.get('proposal_id','')),
        'framework_choice': 'diagnostic_l2 provider-native subagent',
        'decision_questions': [{
            'q': 'Apply proposed fix?',
            'recommendation': d.get('proposed_fix', '')[:300],
            'rationale': f'L2 audit trail: {d.get(\"proposal_id\",\"?\")}; confidence {d.get(\"confidence\",0):.2f}',
        }],
        'confidence': float(d.get('confidence', 0.0)),
        'proposal_id': d.get('proposal_id'),
    }
    print(json.dumps(out))
except Exception as e:
    print(json.dumps({'type':'parse-error','summary':str(e),'file_structure':'','framework_choice':'','decision_questions':[],'confidence':0.0}))
" "$spawn_out"
      return 0
    else
      echo "  spawn-diagnostic-l2 exited rc=${spawn_rc} — falling back to placeholder" >&2
    fi
  fi

  # Fallback return when spawn unavailable: emit placeholder proposal so
  # caller (orchestrator harness) can decide L3/L4 manually.
  printf '{"type":"config-change","summary":"architect_unavailable — provider-native diagnostic dispatch required","file_structure":"N/A","framework_choice":"N/A","decision_questions":[{"q":"Architect subagent could not be dispatched in this context. Proceed with manual direction?","recommendation":"Re-run command from Claude/Codex harness or provide manual fix.","rationale":"Raw shell has no provider-native subagent capability. Claude should use Haiku/Task; Codex should use the Codex scanner adapter. Set VG_DIAGNOSTIC_L2_DRY_RUN=1 to test plumbing without invoking CLI."}],"confidence":0.1}\n'
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve — main entry
# ═══════════════════════════════════════════════════════════════════════
# Usage:
#   block_resolve GATE_ID GATE_CONTEXT EVIDENCE_JSON [PHASE_DIR] [FIX_CANDIDATES_JSON]
#
# Output (single JSON line on stdout):
#   {"level":"L1|L2|L4","action":"resolved|proposal|stuck","proposal":{...}|null,
#    "telemetry_event":"block_self_resolved_inline|block_architect_proposed|block_truly_stuck"}
#
# Return code:
#   0 — L1 resolved (gate passes automatically, caller continues)
#   2 — L2 produced proposal; caller MUST invoke provider-native L3 prompt before proceeding
#   1 — L4 truly stuck; caller MUST exit with human-direction message
block_resolve() {
  local gate_id="$1"
  local gate_context="$2"
  local evidence_json="${3:-{\}}"
  local phase_dir="${4:-}"
  local candidates_json="${5:-[]}"
  local phase_number="${VG_CURRENT_PHASE:-unknown}"
  local step="${VG_CURRENT_STEP:-unknown}"

  if ! block_resolver_enabled; then
    echo '{"level":"L4","action":"stuck","proposal":null,"telemetry_event":"block_truly_stuck","reason":"resolver disabled"}'
    return 1
  fi

  echo "┌─ Block resolver cho gate '${gate_id}' ─────────────────────────────" >&2
  echo "│ Evidence: $(echo "$evidence_json" | head -c 160)" >&2
  echo "└───────────────────────────────────────────────────────────────────" >&2

  # ─── L1 ─────────────────────────────────────────────────────────────
  echo "▸ L1 inline fix (auto-vá tại chỗ)..." >&2
  local l1_result
  l1_result=$(_block_resolve_l1_inline "$gate_id" "$gate_context" "$candidates_json")
  local l1_resolved
  l1_resolved=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('resolved',False))" "$l1_result" 2>/dev/null || echo "False")

  if [ "$l1_resolved" = "True" ]; then
    echo "✓ L1 self-resolved — gate pass tự động" >&2
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "block_self_resolved_inline" "$phase_number" "$step" "$gate_id" "RESOLVED" "$l1_result"
    fi
    printf '{"level":"L1","action":"resolved","proposal":null,"telemetry_event":"block_self_resolved_inline","l1_result":%s}\n' "$l1_result"
    return 0
  fi
  echo "  L1 không fix được: $(echo "$l1_result" | head -c 120)" >&2

  # ─── L2 ─────────────────────────────────────────────────────────────
  echo "▸ L2 architect proposal (gợi ý cấu trúc — $(block_resolver_l2_backend_label))..." >&2
  local proposal_json
  proposal_json=$(_block_resolve_l2_architect "$gate_id" "$gate_context" "$evidence_json" "$phase_dir")

  # Validate JSON parseable
  local proposal_type
  proposal_type=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('type',''))" "$proposal_json" 2>/dev/null || echo "")

  if [ -z "$proposal_type" ]; then
    # Malformed — fall through to L4
    echo "  L2 trả về proposal không parse được JSON — coi như stuck" >&2
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "block_truly_stuck" "$phase_number" "$step" "$gate_id" "STUCK" \
        "{\"reason\":\"architect proposal malformed\",\"raw\":$(printf '%s' "$proposal_json" | head -c 200 | ${PYTHON_BIN:-python3} -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}"
    fi
    printf '{"level":"L4","action":"stuck","proposal":null,"telemetry_event":"block_truly_stuck","reason":"architect malformed"}\n'
    return 1
  fi

  echo "✓ L2 proposal: type=${proposal_type}" >&2
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_architect_proposed" "$phase_number" "$step" "$gate_id" "PROPOSAL" \
      "{\"proposal_type\":\"$proposal_type\"}"
  fi

  # Emit L2 result; caller MUST present via provider-native prompt (L3)
  # and decide L4 only if user rejects.
  printf '{"level":"L2","action":"proposal","proposal":%s,"telemetry_event":"block_architect_proposed"}\n' "$proposal_json"
  return 2
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve_l4_stuck — caller invokes when user rejected L3 proposal
# ═══════════════════════════════════════════════════════════════════════
# Emits final telemetry, prints human-direction message, returns 1.
block_resolve_l4_stuck() {
  local gate_id="$1"
  local user_reason="${2:-no reason supplied}"
  local phase_number="${VG_CURRENT_PHASE:-unknown}"
  local step="${VG_CURRENT_STEP:-unknown}"

  echo "⛔ Gate '${gate_id}' thực sự stuck — cần human direction" >&2
  echo "   L1 inline fix: không resolve được" >&2
  echo "   L2 architect proposal: đã trình, user reject" >&2
  echo "   Reason: ${user_reason}" >&2

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_truly_stuck" "$phase_number" "$step" "$gate_id" "STUCK" \
      "{\"user_reason\":\"${user_reason//\"/\\\"}\"}"
  fi
  return 1
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve_l2_handoff — standardized L2 exit (v1.14.4+)
# ═══════════════════════════════════════════════════════════════════════
# Replaces ad-hoc `echo "▸ L2 architect proposal" >&2; exit 2` pattern with:
#   1. Write proposal to ${PHASE_DIR}/.block-resolver-l2-brief.md
#   2. Emit standardized marker `⛔ BLOCK_RESOLVER_L2_HANDOFF` on stderr
#   3. Tell orchestrator explicitly to use provider-native L3 prompt
#   4. Exit 2
#
# Usage (in build.md/review.md/test.md):
#   BR_RESULT=$(block_resolve "gate-id" "$ctx" "$ev" "$PHASE_DIR" "$candidates")
#   BR_LVL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "...")
#   if [ "$BR_LVL" = "L2" ]; then
#     block_resolve_l2_handoff "gate-id" "$BR_RESULT" "$PHASE_DIR"
#     exit 2
#   fi
block_resolve_l2_handoff() {
  local gate_id="$1"
  local br_result="$2"
  local phase_dir="${3:-${PHASE_DIR:-.}}"
  local brief="${phase_dir}/.block-resolver-l2-brief.md"

  # Codex-R7 fix: previously extracted only legacy `proposal.rationale` and
  # `proposal.suggested_actions`. The diagnostic-L2 shape (built at line ~269)
  # puts the actionable fix under `decision_questions[0].recommendation` and
  # `decision_questions[0].rationale`. Extract from BOTH shapes so the brief
  # always shows the architect's recommendation to L3.
  local extract_py='
import json, sys
try:
    d = json.loads(sys.stdin.read())
    p = d.get("proposal") or {}
    out = {
        "type": p.get("type", "?"),
        "summary": p.get("summary", ""),
        "confidence": p.get("confidence", 0),
        # Legacy shape paths
        "rationale": p.get("rationale", ""),
        "actions": p.get("suggested_actions") or [],
    }
    # Diagnostic-L2 shape — decision_questions array carries fix
    dqs = p.get("decision_questions") or []
    if dqs and isinstance(dqs[0], dict):
        dq0 = dqs[0]
        if not out["rationale"]:
            out["rationale"] = dq0.get("rationale", "")
        rec = dq0.get("recommendation", "")
        if rec and rec not in out["actions"]:
            out["actions"] = [rec] + list(out["actions"])
    print(json.dumps(out))
except Exception:
    print("{}")
'
  local extracted=$(echo "$br_result" | ${PYTHON_BIN:-python3} -c "$extract_py" 2>/dev/null)
  local p_type=$(echo "$extracted" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('type','?'))" 2>/dev/null)
  local p_summary=$(echo "$extracted" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('summary',''))" 2>/dev/null)
  local p_confidence=$(echo "$extracted" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('confidence',0))" 2>/dev/null)
  local p_rationale=$(echo "$extracted" | ${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read()).get('rationale',''))" 2>/dev/null)
  local p_actions=$(echo "$extracted" | ${PYTHON_BIN:-python3} -c "import json,sys; print('\n'.join('- ' + str(a) for a in json.loads(sys.stdin.read()).get('actions',[])))" 2>/dev/null)

  # Write brief file for orchestrator Task tool
  cat > "$brief" <<EOF
# Block Resolver L2 Handoff — Gate: ${gate_id}

**Generated:** $(date -u +%FT%TZ)
**Phase:** ${VG_CURRENT_PHASE:-unknown}
**Step:** ${VG_CURRENT_STEP:-unknown}
**Level:** L2 (architect proposal — user decision required via L3)

## Proposal

- **Type:** ${p_type}
- **Summary:** ${p_summary}
- **Confidence:** ${p_confidence}
- **Rationale:** ${p_rationale}

## Suggested actions

${p_actions:-_(architect did not provide explicit actions)_}

## Orchestrator contract

Build/review/test workflow has HALTED at this gate. Before re-running the blocked command:

1. **Read this brief** — understand proposal type + rationale
2. **Present to user via provider-native prompt** (L3):
   - Claude Code: AskUserQuestion tool
   - Codex: main-thread prompt or closest Codex user-input UI
   - Option A: Apply proposal (action depends on type)
   - Option B: Override with \`--override-reason="<text>"\` (logs to override-debt register)
   - Option C: Abort workflow — investigate manually
3. **If user accepts**: execute proposal actions, delete this brief, re-run blocked command
4. **If user rejects**: call \`block_resolve_l4_stuck\` helper to log STUCK + telemetry
EOF

  # Emit standardized marker (recognized by orchestrator as "halt + Task spawn required")
  echo "⛔ BLOCK_RESOLVER_L2_HANDOFF gate=${gate_id} brief=${brief}" >&2
  echo "   Orchestrator MUST:" >&2
  echo "     1. Read ${brief}" >&2
  echo "     2. Invoke $(block_resolver_l3_prompt_label) with proposal options (L3)" >&2
  echo "     3. Execute user choice → delete brief → re-run blocked command" >&2

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_architect_handoff" "${VG_CURRENT_PHASE:-unknown}" "${VG_CURRENT_STEP:-unknown}" "$gate_id" "L2_HANDOFF" \
      "{\"proposal_type\":\"${p_type//\"/\\\"}\",\"brief\":\"${brief//\"/\\\"}\"}"
  fi

  return 2
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve_l3_present — emit provider-native prompt JSON template (v1.14.4+)
# ═══════════════════════════════════════════════════════════════════════
# Called by orchestrator AFTER block_resolve_l2_handoff produces brief.
# Reads .block-resolver-l2-brief.md, formats a prompt template, and emits to
# stdout for the orchestrator. Claude invokes AskUserQuestion; Codex asks the
# same choices in the main thread / closest user-input UI.
#
# Workflow:
#   1. block_resolve returns L2 → block_resolve_l2_handoff writes brief + exit 2
#   2. Orchestrator catches exit 2, sees marker BLOCK_RESOLVER_L2_HANDOFF
#   3. Orchestrator calls block_resolve_l3_present "$gate_id" "$phase_dir"
#   4. Helper reads brief + emits structured JSON
#   5. Orchestrator parses JSON + calls provider-native user prompt with options
#   6. After user choice, orchestrator calls block_resolve_l3_apply for telemetry
block_resolve_l3_present() {
  local gate_id="$1"
  local phase_dir="${2:-${PHASE_DIR:-.}}"
  local brief="${phase_dir}/.block-resolver-l2-brief.md"

  if [ ! -f "$brief" ]; then
    echo "⛔ block_resolve_l3_present: brief missing at ${brief}" >&2
    echo "   Cannot present L3 — call block_resolve_l2_handoff first" >&2
    return 1
  fi

  # Extract proposal fields from brief header
  local p_type=$(grep -E "^\- \*\*Type:\*\*" "$brief" | head -1 | sed 's/.*Type:\*\*\s*//')
  local p_summary=$(grep -E "^\- \*\*Summary:\*\*" "$brief" | head -1 | sed 's/.*Summary:\*\*\s*//')
  local p_rationale=$(grep -E "^\- \*\*Rationale:\*\*" "$brief" | head -1 | sed 's/.*Rationale:\*\*\s*//')

  # Extract suggested actions (lines under "## Suggested actions" up to next ##)
  local p_actions=$(awk '/^## Suggested actions/{flag=1; next} /^## /{flag=0} flag && /^- /' "$brief" | sed 's/^- //')

  # Emit JSON template for orchestrator provider-native prompt call
  cat <<JSON
{
  "marker": "BLOCK_RESOLVER_L3_PROMPT",
  "gate_id": "${gate_id}",
  "brief_path": "${brief}",
  "prompt_contract": "provider-native: Claude AskUserQuestion; Codex main-thread prompt",
  "ask_user_question_template": {
    "question": "Gate '${gate_id}' blocked. Architect proposed: ${p_summary}",
    "header": "Block resolver L3 — apply proposal?",
    "multiSelect": false,
    "options": [
      {
        "label": "Apply (Recommended) — ${p_type}",
        "description": "${p_rationale}"
      },
      {
        "label": "Override với reason",
        "description": "Skip proposal, --override-reason='<text>' (logs override-debt register)"
      },
      {
        "label": "Abort — investigate manually",
        "description": "Halt workflow, user inspects ${brief} + decides next step"
      }
    ]
  },
  "suggested_actions": $(echo "$p_actions" | ${PYTHON_BIN:-python3} -c "import sys, json; lines = [l.strip() for l in sys.stdin if l.strip()]; print(json.dumps(lines))" 2>/dev/null || echo '[]')
}
JSON

  echo "▸ Orchestrator: parse JSON above, invoke $(block_resolver_l3_prompt_label) with template, then call block_resolve_l3_apply '${gate_id}' '<chosen_option>'" >&2

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_l3_prompt_emitted" "${VG_CURRENT_PHASE:-unknown}" "${VG_CURRENT_STEP:-unknown}" "$gate_id" "L3_PROMPT" \
      "{\"brief\":\"${brief//\"/\\\"}\",\"proposal_type\":\"${p_type//\"/\\\"}\"}"
  fi

  return 0
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve_l3_single_advisory — D26 single-advisory variant (RFC v9 PR-D3)
# ═══════════════════════════════════════════════════════════════════════
# When the architect's proposal has high confidence (typically ≥ 0.8) and
# the right answer is clear, do NOT fabricate a 3-option menu. Lead with
# the recommendation, ask Y/n. Override + abort remain reachable via [d]etails.
#
# RFC v9 D26 rule (user-stated): "khi có 1 đường đúng, đừng tạo menu giả định
# người dùng có lựa chọn" — when there's a clear right path, advise straight.
#
# Args:
#   $1 — gate_id (e.g., "missing-evidence")
#   $2 — phase_dir (defaults to $PHASE_DIR)
#   $3 — confidence (0.0 .. 1.0; default 0.8)
#
# Behavior:
#   - confidence >= threshold (config.review.l3_single_advisory_min_confidence,
#     default 0.7): emit single-advisory JSON (one primary action + [d]etails)
#   - confidence < threshold: fall through to block_resolve_l3_present (3-option)
#
# Use when:
#   - L2 architect surfaces high-confidence fix.
#   - Recovery paths in vg:review/test/build where the alternative is just
#     "do nothing" or "investigate manually" (not a real divergent decision).
block_resolve_l3_single_advisory() {
  local gate_id="$1"
  local phase_dir="${2:-${PHASE_DIR:-.}}"
  local confidence="${3:-0.8}"
  local brief="${phase_dir}/.block-resolver-l2-brief.md"
  local threshold="${CONFIG_REVIEW_L3_SINGLE_ADVISORY_MIN_CONFIDENCE:-0.7}"

  if [ ! -f "$brief" ]; then
    echo "⛔ block_resolve_l3_single_advisory: brief missing at ${brief}" >&2
    return 1
  fi

  # Compare confidence vs threshold (POSIX bash arithmetic via awk for floats)
  local should_advise
  should_advise=$(awk "BEGIN { print ($confidence >= $threshold) ? 1 : 0 }")
  if [ "$should_advise" != "1" ]; then
    # Low confidence — fall back to 3-option menu (preserve audit trail)
    echo "▸ confidence=$confidence < threshold=$threshold → falling back to multi-option L3" >&2
    block_resolve_l3_present "$gate_id" "$phase_dir"
    return $?
  fi

  local p_type=$(grep -E "^\- \*\*Type:\*\*" "$brief" | head -1 | sed 's/.*Type:\*\*\s*//')
  local p_summary=$(grep -E "^\- \*\*Summary:\*\*" "$brief" | head -1 | sed 's/.*Summary:\*\*\s*//')
  local p_rationale=$(grep -E "^\- \*\*Rationale:\*\*" "$brief" | head -1 | sed 's/.*Rationale:\*\*\s*//')

  cat <<JSON
{
  "marker": "BLOCK_RESOLVER_L3_PROMPT_SINGLE_ADVISORY",
  "gate_id": "${gate_id}",
  "brief_path": "${brief}",
  "confidence": ${confidence},
  "prompt_contract": "provider-native: Claude AskUserQuestion; Codex main-thread prompt",
  "ask_user_question_template": {
    "question": "Áp dụng đề xuất sửa cho '${gate_id}'? ${p_summary}",
    "header": "L3 single-advisory (confidence=${confidence})",
    "multiSelect": false,
    "options": [
      {
        "label": "Yes — apply now",
        "description": "${p_rationale}"
      },
      {
        "label": "No — show details",
        "description": "Reveal full L2 brief at ${brief}; choose override/abort then"
      }
    ]
  }
}
JSON

  echo "▸ Orchestrator: invoke $(block_resolver_l3_prompt_label) with the template above, then call block_resolve_l3_apply '${gate_id}' '<chosen_option>'" >&2

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_l3_single_advisory_emitted" "${VG_CURRENT_PHASE:-unknown}" "${VG_CURRENT_STEP:-unknown}" "$gate_id" "L3_SINGLE_ADVISORY" \
      "{\"confidence\":${confidence},\"proposal_type\":\"${p_type//\"/\\\"}\"}"
  fi

  return 0
}

# ═══════════════════════════════════════════════════════════════════════
# block_resolve_l3_apply — telemetry helper when user accepts proposal
# ═══════════════════════════════════════════════════════════════════════
block_resolve_l3_apply() {
  local gate_id="$1"
  local proposal_type="$2"
  local phase_number="${VG_CURRENT_PHASE:-unknown}"
  local step="${VG_CURRENT_STEP:-unknown}"

  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "block_user_chose_proposal" "$phase_number" "$step" "$gate_id" "APPLIED" \
      "{\"proposal_type\":\"$proposal_type\"}"
  fi
  echo "✓ User applied L3 proposal (type=${proposal_type}) — continuing" >&2
}
