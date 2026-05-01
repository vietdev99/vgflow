# shellcheck shell=bash
# Dimension Expander — proactive dimension gap-finding at end of each /vg:scope round
# Companion runtime for: v1.9.3 R3.2 — complements answer-challenger
#
# Purpose: At the END of each scope discussion round (after all Q&A), an isolated
# Opus subagent with zero parent context analyzes the round topic + accumulated
# user answers and identifies dimensions the user HAS NOT covered.
#
# This is COMPLEMENTARY to answer-challenger:
#   - answer-challenger (per-answer):  "is this specific answer wrong?"
#   - dimension-expander (per-round):   "what haven't we discussed yet?"
#
# Subagent receives ONLY: round topic + all Q&A of round + FOUNDATION.md.
# No parent context, no goals, no prior rounds.
#
# It produces a categorized dimension gap report:
#   - critical_missing: ship-blocker if not resolved
#   - nice_to_have_missing: can defer (tracked as open question)
#
# Exposed functions:
#   - expander_enabled
#   - expand_dimensions ROUND_NUM ROUND_TOPIC ACCUMULATED FOUNDATION_PATH
#   - expander_dispatch RESULT_JSON ROUND_ID PHASE
#   - expander_record_user_choice PHASE ROUND_ID USER_CHOICE
#   - expander_count_for_phase PHASE  # loop guard
#
# Infinite-loop guard: expander_count_for_phase() caps total expansions per phase
# at CONFIG_SCOPE_DIMENSION_EXPAND_MAX (default 6 = 5 rounds + 1 deep probe pass).
# Beyond cap → skip expansion (log WARN).

expander_enabled() {
  [ "${CONFIG_SCOPE_DIMENSION_EXPAND_CHECK:-true}" = "true" ] || return 1
  return 0
}

# Count prior expansions emitted for this phase/session — loop guard
expander_count_for_phase() {
  local phase="$1"
  local path="${TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"
  [ -f "$path" ] || { echo 0; return; }
  ${PYTHON_BIN:-python3} - "$path" "$phase" <<'PY'
import json, sys
path, phase = sys.argv[1], sys.argv[2]
n = 0
try:
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line: continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("event_type") == "scope_dimension_expanded" \
           and str(ev.get("phase") or "") == phase:
            n += 1
except Exception:
    pass
print(n)
PY
}

# Main API — build dimension-expander subagent prompt, emit path on fd 3, return fallback JSON
# The VG command orchestrator reads the prompt file, dispatches Task tool
# (subagent_type=general-purpose, model=opus, zero parent context), pipes stdout back.
#
# Usage: result=$(expand_dimensions "$round_num" "$round_topic" "$accumulated" "$foundation_path")
# Result (one JSON line): {dimensions_total, dimensions_addressed, dimensions_missing,
#                          critical_missing:[...], nice_to_have_missing:[...]}
expand_dimensions() {
  local round_num="$1"     # "1" | "2" | "3" | "4" | "5" | "deep-probe"
  local round_topic="$2"   # "Domain & Business" | "Technical Approach" | ... | "Deep Probe Loop"
  local accumulated="$3"   # all Q&A pairs of this round, user answers merged
  local foundation_path="${4:-${PLANNING_DIR}/FOUNDATION.md}"

  if ! expander_enabled; then
    echo '{"dimensions_total":0,"dimensions_addressed":0,"dimensions_missing":0,"critical_missing":[],"nice_to_have_missing":[],"_skipped":"disabled"}'
    return 0
  fi

  local subagent_model="${CONFIG_SCOPE_DIMENSION_EXPAND_MODEL:-opus}"
  local prompt_path="${VG_TMP:-/tmp}/dimension-expander-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true

  # Include FOUNDATION.md excerpt — expander needs to know platform constraints
  local foundation_excerpt=""
  if [ -f "$foundation_path" ]; then
    foundation_excerpt=$(head -c 8000 "$foundation_path" 2>/dev/null || true)
  fi

  # v1.9.5 R3.4: emit prompt CONTENT on fd 3 (not path), because Task subagents
  # have sandbox isolation and cannot read /tmp files from parent process.
  # Orchestrator: PROMPT=$(expand_dimensions ... 3>&1 1>/dev/null 2>/dev/null)
  cat > "$prompt_path" <<PROMPT
You are a Dimension Expander. ZERO context about parent session.
Your ONLY job: identify dimensions the user HAS NOT covered yet in this scope round.

You are NOT critiquing answers (that's the answer-challenger's job).
You ARE expanding the space — flagging important dimensions the user forgot.

══════════════════════════════════════════════════════════════════════════════
ROUND: ${round_num}    TOPIC: ${round_topic}
══════════════════════════════════════════════════════════════════════════════

── USER'S ANSWERS IN THIS ROUND ───────────────────────────────────────────────
${accumulated}

── FOUNDATION.md (locked project-wide decisions) ──────────────────────────────
${foundation_excerpt:-"(no FOUNDATION.md yet — this is likely /vg:project run)"}

══════════════════════════════════════════════════════════════════════════════
YOUR 4-STEP ANALYSIS
══════════════════════════════════════════════════════════════════════════════

STEP 1 — Enumerate dimensions.
Based on the ROUND TOPIC "${round_topic}", list 8-12 dimensions a senior engineer
would ALWAYS consider for this topic.

Examples by typical topics (adapt to the actual topic given):

  "Domain/Business/Product":
    monetization model, target persona, SLA tier, pricing strategy,
    stakeholder approval chain, legal/compliance (GDPR/CCPA/PCI),
    brand risk, analytics requirements, market fit signals, support escalation

  "Technical Architecture":
    authentication flow, authorization model, scalability pattern,
    failure recovery, observability (logs/metrics/traces), deployment topology,
    rollback strategy, data storage/sharding, cache strategy,
    queue backpressure, secret management, config management

  "API Design":
    versioning strategy, idempotency keys, rate limiting policy,
    error taxonomy, pagination model, filtering/sorting,
    batch vs single endpoints, webhook retry semantics,
    deprecation policy, SDK/client codegen, OpenAPI contract

  "UI/UX / Frontend":
    accessibility (WCAG AA), i18n/l10n, loading state, empty state,
    error state, offline mode, mobile responsive, dark mode,
    keyboard navigation, screen reader support, analytics events,
    skeleton screens, optimistic updates

  "Test Strategy":
    happy path coverage, edge cases, performance budget,
    security (OWASP top 10), integration contracts, chaos drill,
    rollback drill, data migration dry-run, fixture seeding,
    flaky test budget, CI runtime budget, regression suite

If the topic is NONE of these — derive dimensions from first principles.

STEP 2 — Classify each dimension for this round.
  ADDRESSED   : user's answer explicitly covers this dimension
  PARTIAL     : user touched the topic but didn't specify enough (gaps remain)
  MISSING     : no mention at all

STEP 3 — For each MISSING or PARTIAL, classify priority.
  CRITICAL       : will cause ship-blocker if not resolved BEFORE build phase.
                   Examples: no auth flow decided, no rollback plan,
                   no error taxonomy, no rate-limit policy.
  NICE-TO-HAVE   : can defer to later phase or document as open question.
                   Examples: SDK codegen, dark mode, analytics events
                   (when not MVP-critical).

STEP 4 — For CRITICAL missing: draft a SPECIFIC follow-up question
that the parent scope orchestrator should ask the user NEXT.

══════════════════════════════════════════════════════════════════════════════
QUALITY RULES
══════════════════════════════════════════════════════════════════════════════

- Do NOT invent dimensions irrelevant to the topic.
- Do NOT duplicate coverage (if user said "use JWT" → authentication is ADDRESSED, not MISSING).
- Do NOT nitpick — if user addressed 80%+ of a dimension, mark ADDRESSED.
- Do NOT re-challenge user's ACTUAL answers — that's answer-challenger's job.
- Keep follow-up questions SPECIFIC (not "have you thought about X?" but
  "What's the rate limit policy for POST /api/v1/conversion-goals when an
  advertiser creates 100 goals/hour — drop / queue / 429?").

**CAP RULE (v1.10.0):** Cap critical_missing at **MAX 4 items**. Pick the 4 MOST
impactful dimensions that are ship-blockers. Push all other MISSING/PARTIAL
dimensions (including lower-priority "critical" ones) to nice_to_have_missing.
Rationale: avoid decision fatigue — user can resolve 4 criticals per round, not 10+.
If >4 real ship-blockers exist, it signals scope is too broad and needs splitting.

══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT — exactly ONE line of strict JSON, no prose before/after
══════════════════════════════════════════════════════════════════════════════

**SCHEMA RULE (v1.10.1):** `critical_missing` + `nice_to_have_missing` MUST be
arrays of OBJECTS with named fields, NOT flat arrays of strings.
WRONG: "critical_missing": ["test_pyramid", "fixture_strategy"]
RIGHT: "critical_missing": [{"dimension": "Test pyramid", "question": "...", "rationale": "..."}]

{"dimensions_total": <int>,
 "dimensions_addressed": <int>,
 "dimensions_missing": <int>,
 "critical_missing": [
   {"dimension": "<short name>", "question": "<VN follow-up ≤200 char>", "rationale": "<why critical ≤150 char>"}
 ],
 "nice_to_have_missing": [
   {"dimension": "<name>", "rationale": "<why defer ok ≤100 char>"}
 ]}
PROMPT

  # v1.9.5 R3.4 FIX: emit prompt CONTENT on fd 3 (subagent sandbox can't read /tmp).
  # Main orchestrator captures + passes inline to Agent tool.
  cat "$prompt_path" >&3 2>/dev/null || true
  echo "dimension-expander prompt emitted on fd 3 | audit file: $prompt_path" >&2

  # Fallback when Task tool unavailable (pure shell): fail open (no missing) with reason
  echo '{"dimensions_total":0,"dimensions_addressed":0,"dimensions_missing":0,"critical_missing":[],"nice_to_have_missing":[],"_skipped":"task_tool_unavailable"}'
}

# Post-expansion dispatcher — call AFTER orchestrator feeds subagent output back
# Usage: expander_dispatch "$result_json" "$round_id" "$phase"
# Returns: 0 always (non-blocking); prints narration for orchestrator to show user
# Side effect: emits telemetry event `scope_dimension_expanded` with user_chose
expander_dispatch() {
  local result="$1" round_id="$2" phase="$3"
  local total addressed missing critical_count nice_count skipped

  total=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('dimensions_total',0))" "$result" 2>/dev/null || echo "0")
  addressed=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('dimensions_addressed',0))" "$result" 2>/dev/null || echo "0")
  missing=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('dimensions_missing',0))" "$result" 2>/dev/null || echo "0")
  critical_count=$(${PYTHON_BIN:-python3} -c "import json,sys; print(len(json.loads(sys.argv[1]).get('critical_missing',[])))" "$result" 2>/dev/null || echo "0")
  nice_count=$(${PYTHON_BIN:-python3} -c "import json,sys; print(len(json.loads(sys.argv[1]).get('nice_to_have_missing',[])))" "$result" 2>/dev/null || echo "0")
  skipped=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('_skipped',''))" "$result" 2>/dev/null || echo "")

  # Loop guard: cap expansions per phase
  local max_expands="${CONFIG_SCOPE_DIMENSION_EXPAND_MAX:-6}"
  local current_count
  current_count=$(expander_count_for_phase "$phase")
  if [ "$current_count" -ge "$max_expands" ]; then
    echo "⚠ Dimension expander (mở rộng chiều) đã đạt giới hạn $max_expands/phase — bỏ qua expansion này để tránh vòng lặp." >&2
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "scope_dimension_expanded" "$phase" "phase-scope" \
        "dimension-expand-check" "SKIP" \
        "{\"round_id\":\"$round_id\",\"reason\":\"max_expands_reached\"}"
    fi
    return 0
  fi

  # If no critical missing and no nice-to-have, silent pass
  if [ "$critical_count" = "0" ] && [ "$nice_count" = "0" ]; then
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "scope_dimension_expanded" "$phase" "phase-scope" \
        "dimension-expand-check" "PASS" \
        "{\"round_id\":\"$round_id\",\"total\":$total,\"addressed\":$addressed,\"reason\":\"${skipped:-clean}\"}"
    fi
    # Short summary narration for user transparency
    echo ""
    echo "✓ Dimension expander — round ${round_id}: ${addressed}/${total} dimensions addressed, không thiếu critical."
    return 0
  fi

  # Narrate findings in Vietnamese
  echo ""
  echo "🔭 Dimension expander (mở rộng chiều) — round ${round_id}"
  echo "   Tổng dimensions: ${total} | Đã cover: ${addressed} | Thiếu: ${missing}"
  if [ "$critical_count" -gt 0 ]; then
    echo ""
    echo "   ⛔ CRITICAL missing (${critical_count} dimension cần giải quyết TRƯỚC khi advance round):"
    ${PYTHON_BIN:-python3} -c "
import json, sys
r = json.loads(sys.argv[1])
for i, c in enumerate(r.get('critical_missing', []), 1):
    print(f'      {i}. {c.get(\"dimension\",\"?\")}')
    print(f'         Q: {c.get(\"question\",\"?\")}')
    print(f'         Lý do: {c.get(\"rationale\",\"?\")}')
" "$result" 2>/dev/null
  fi
  if [ "$nice_count" -gt 0 ]; then
    echo ""
    echo "   ℹ nice-to-have missing (${nice_count} dimension — có thể defer):"
    ${PYTHON_BIN:-python3} -c "
import json, sys
r = json.loads(sys.argv[1])
for i, n in enumerate(r.get('nice_to_have_missing', []), 1):
    print(f'      {i}. {n.get(\"dimension\",\"?\")} — {n.get(\"rationale\",\"?\")}')
" "$result" 2>/dev/null
  fi

  echo ""
  echo "Orchestrator MUST now invoke AskUserQuestion với 3 options:"
  echo "  (a) Address critical — quay lại hỏi các dimension CRITICAL missing (re-enter round)"
  echo "  (b) Acknowledge — ghi nhận dimensions thiếu vào CONTEXT.md \"## Acknowledged gaps\""
  echo "  (c) Defer to open questions — track trong CONTEXT.md \"## Open questions\" (sẽ xử lý sau)"

  # Emit telemetry (user_chose filled in by orchestrator post-ask)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "scope_dimension_expanded" "$phase" "phase-scope" \
      "dimension-expand-check" "FLAG" \
      "{\"round_id\":\"$round_id\",\"total\":$total,\"addressed\":$addressed,\"critical_count\":$critical_count,\"nice_count\":$nice_count,\"user_chose\":\"pending\"}"
  fi
  return 0
}

# Called after user picks option — updates telemetry by emitting resolution event
expander_record_user_choice() {
  local phase="$1" round_id="$2" user_chose="$3"
  # user_chose ∈ {"address","acknowledge","defer"}
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "scope_dimension_expanded" "$phase" "phase-scope" \
      "dimension-expand-check" "RESOLVED" \
      "{\"round_id\":\"$round_id\",\"user_chose\":\"$user_chose\"}"
  fi
}
