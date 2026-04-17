# shellcheck shell=bash
# Answer Challenger — adversarial review of user answers in /vg:scope and /vg:project
# Companion runtime for: .claude/commands/vg/_shared/answer-challenger.md (docs)
#
# Purpose: Every user answer in a scope/project discussion round gets adversarially
# challenged by an isolated Opus subagent (v1.9.3 R3.2 — upgraded from Haiku for
# reasoning depth). The subagent receives ONLY the answer + accumulated draft +
# FOUNDATION.md + prior decisions — no parent context, no goals.
# It checks 8 lenses (expanded from 4 in v1.9.3):
#   1. Contradicts prior decisions (D-XX / F-XX)?
#   2. Hidden assumption not stated?
#   3. Edge case missed (failure / scale / concurrency / timezone / unicode / multi-tenant)?
#   4. FOUNDATION conflict (platform / compliance / scale drift)?
#   5. Security threat (auth / authz / data leak / injection / rate-limit bypass)?
#   6. Performance budget (latency / throughput / DB query cost / memory / p95)?
#   7. Failure mode (retry / idempotency / circuit breaker / partial fail / timeout)?
#   8. Integration chain (downstream caller / upstream dep / webhook contract / data contract)?
#
# Exposed functions:
#   - challenger_enabled
#   - challenge_answer ANSWER_TEXT ROUND_ID SCOPE_KIND ACCUMULATED_CONTEXT
#   - challenger_dispatch RESULT_JSON ROUND_ID SCOPE_KIND PHASE
#
# Infinite-loop guard: challenger_count_for_phase() caps total challenges per phase
# at CONFIG_SCOPE_ADVERSARIAL_MAX_ROUNDS (default 3). Beyond cap → skip challenge.

challenger_enabled() {
  [ "${CONFIG_SCOPE_ADVERSARIAL_CHECK:-true}" = "true" ] || return 1
  return 0
}

# Skip trivial answers (Y/N-only, single-word confirmations) — don't waste Haiku calls
challenger_is_trivial() {
  local ans="$1"
  local stripped
  stripped=$(echo "$ans" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  local len=${#stripped}
  # ≤3 chars, OR matches common confirm/deny tokens
  [ "$len" -le 3 ] && return 0
  case "$stripped" in
    yes|no|y|n|ok|okay|đúng|sai|có|không|skip|pass|next|proceed) return 0 ;;
  esac
  return 1
}

# Count prior challenges emitted for this phase/session — loop guard
challenger_count_for_phase() {
  local phase="$1"
  local path="${TELEMETRY_PATH:-.planning/telemetry.jsonl}"
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
        if ev.get("event_type") == "scope_answer_challenged" \
           and str(ev.get("phase") or "") == phase:
            n += 1
except Exception:
    pass
print(n)
PY
}

# Main API — build adversarial subagent prompt, emit path on fd 3, return fallback JSON
# The VG command orchestrator is responsible for reading the prompt file, dispatching
# the Task tool (model=opus per v1.9.3 R3.2, zero parent context), and piping subagent stdout back.
#
# Usage: result=$(challenge_answer "$answer" "$round_id" "$scope_kind" "$accumulated")
# Result (one JSON line): {has_issue, issue_kind, evidence, follow_up_question, proposed_alternative}
challenge_answer() {
  local answer_text="$1"
  local round_id="$2"        # e.g. "round-3", "round-deep-probe-5"
  local scope_kind="$3"      # "phase-scope" | "project-foundation"
  local accumulated="$4"     # draft CONTEXT.md / FOUNDATION.md + prior decisions

  if ! challenger_enabled; then
    echo '{"has_issue":false,"issue_kind":"","evidence":"","follow_up_question":"","proposed_alternative":"","_skipped":"disabled"}'
    return 0
  fi
  if challenger_is_trivial "$answer_text"; then
    echo '{"has_issue":false,"issue_kind":"","evidence":"","follow_up_question":"","proposed_alternative":"","_skipped":"trivial"}'
    return 0
  fi

  local subagent_model="${CONFIG_SCOPE_ADVERSARIAL_MODEL:-opus}"  # v1.9.3 R3.2: upgraded from haiku
  local prompt_path="${VG_TMP:-/tmp}/answer-challenger-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true

  # Always include FOUNDATION.md if it exists — adversary checks platform/compliance drift
  local foundation_excerpt=""
  if [ -f ".planning/FOUNDATION.md" ]; then
    foundation_excerpt=$(head -c 8000 ".planning/FOUNDATION.md" 2>/dev/null || true)
  fi

  # v1.9.5 R3.4: emit prompt CONTENT on fd 3 (not just path), because Task
  # subagents have sandbox isolation and cannot read /tmp files from parent.
  # Orchestrator captures fd 3 via: PROMPT=$(challenge_answer ... 3>&1 1>/dev/null 2>/dev/null)
  # then passes inline to Agent(prompt=$PROMPT).
  cat > "$prompt_path" <<PROMPT
You are an Adversarial Answer Challenger. You have ZERO context about the parent session.
Your ONLY job: challenge a user's design answer in a ${scope_kind} discussion round.

══════════════════════════════════════════════════════════════════════════════
ROUND: ${round_id}    SCOPE: ${scope_kind}
══════════════════════════════════════════════════════════════════════════════

── USER'S ANSWER ──────────────────────────────────────────────────────────────
${answer_text}

── ACCUMULATED DRAFT (current CONTEXT/FOUNDATION in progress) ─────────────────
${accumulated}

── FOUNDATION.md (locked project-wide decisions, F-XX namespace) ──────────────
${foundation_excerpt:-"(no FOUNDATION.md yet — this is likely /vg:project round)"}

══════════════════════════════════════════════════════════════════════════════
YOUR 8-LENS ADVERSARIAL CHECK (v1.9.3 — expanded from 4 lenses)
══════════════════════════════════════════════════════════════════════════════

Lens 1 — CONTRADICTS PRIOR DECISION?
  Does the answer violate any locked D-XX / F-XX above? Cite the specific ID.

Lens 2 — HIDDEN ASSUMPTION?
  Does the answer silently assume something (auth state, single-tenancy,
  offline behavior, preloaded data, user locale) WITHOUT stating it?

Lens 3 — EDGE CASE MISSED?
  Does the answer ignore: failure modes / retry / partial failure /
  scale (1000x growth) / concurrency (simultaneous writes) /
  timezone (DST, UTC shifts) / unicode (emoji, RTL) / multi-tenancy /
  rate limits / GDPR right-to-delete?

Lens 4 — FOUNDATION CONFLICT?
  Does the answer drift from FOUNDATION claims? Examples:
    - FOUNDATION says "single-tenancy" but answer implies cross-org sharing
    - FOUNDATION says "50 users scale" but answer implies horizontal shard
    - FOUNDATION says "no PII stored" but answer introduces user profiles
    - FOUNDATION says "VPS hosting" but answer assumes serverless cold-start

Lens 5 — SECURITY THREAT?
  Does the answer create an attack surface?
    - Authentication: missing auth check on sensitive endpoint
    - Authorization: org-scoped resource without tenancy check (IDOR)
    - Data leak: response/log exposes secret / PII / internal ID format
    - Injection: unsanitized input into SQL / Mongo query / shell / template
    - CSRF: state-changing endpoint without CSRF protection
    - Rate-limit bypass: expensive endpoint without throttle / quota

Lens 6 — PERFORMANCE BUDGET?
  Will the answer blow past budget? Check for:
    - Unbounded query (N+1, missing LIMIT, full table scan)
    - Synchronous blocking call in hot path (sleep, cross-DC fetch, file I/O)
    - Cache miss cost (no caching on expensive derivation)
    - Chatty protocol (10 round-trips where 1 would do)
    - Memory spike (load full collection into memory when cursor would suffice)
    - p95 latency beyond config.perf_budgets for this surface

Lens 7 — FAILURE MODE?
  Does the answer handle failures correctly?
    - Idempotency: retry causes duplicate side-effect?
    - Timeout: unbounded wait (no timeout) on external call?
    - Circuit breaker: cascading failure when dependency down?
    - Partial failure: multi-write with no rollback / compensating action?
    - Poison message: malformed input crashes worker repeatedly?
    - Retry storm: exponential-backoff missing, thundering herd?

Lens 8 — INTEGRATION CHAIN?
  Does the answer break cross-service contracts?
    - Downstream caller: API shape change breaks existing consumer
    - Upstream dep: relies on behavior not guaranteed by dep contract
    - Webhook contract: response format/retry semantics not aligned with receiver
    - Data contract: writes field that downstream reader doesn't know about
    - Schema migration: additive vs breaking; rollout vs rollback plan

══════════════════════════════════════════════════════════════════════════════
DECISION
══════════════════════════════════════════════════════════════════════════════

If ALL 8 lenses are clean → has_issue=false. Done.

If ANY lens flags a concrete issue → has_issue=true. Pick THE MOST CRITICAL one.

Priority order when multiple lenses fire: Security > Failure Mode > Contradiction
  > Foundation Conflict > Integration Chain > Edge Case > Hidden Assumption
  > Performance Budget.

Do NOT invent issues. Do NOT nitpick grammar / wording. Only flag if the answer
will cause real trouble downstream (build / test / deploy / compliance / ops).

══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT — exactly ONE line of strict JSON, no prose before/after
══════════════════════════════════════════════════════════════════════════════
{"has_issue": true|false,
 "issue_kind": "contradiction|hidden_assumption|edge_case|foundation_conflict|security|performance|failure_mode|integration_chain|",
 "evidence": "<≤200 char pointer: D-XX / F-XX cited, or specific edge case / attack vector / budget>",
 "follow_up_question": "<≤200 char VN question for user to resolve>",
 "proposed_alternative": "<≤200 char VN concrete alternative phrasing>"}
PROMPT

  # v1.9.5 R3.4 FIX: emit prompt CONTENT on fd 3 (subagent sandbox can't read /tmp).
  # Main orchestrator captures fd 3 output + passes inline to Agent tool.
  # Path on stderr for audit/debug only.
  cat "$prompt_path" >&3 2>/dev/null || true
  echo "answer-challenger prompt emitted on fd 3 | audit file: $prompt_path" >&2

  # Fallback when Task tool unavailable (pure shell): fail open (has_issue=false)
  # with reason code so caller can log. Adversarial check is ADDITIVE — missing it
  # should not block the discussion.
  echo '{"has_issue":false,"issue_kind":"","evidence":"","follow_up_question":"","proposed_alternative":"","_skipped":"task_tool_unavailable"}'
}

# Post-challenge dispatcher — call AFTER orchestrator feeds subagent output back
# Usage: challenger_dispatch "$result_json" "$round_id" "$scope_kind" "$phase"
# Returns: 0 always (non-blocking); prints narration for orchestrator to show user
# Side effect: emits telemetry event `scope_answer_challenged` with user_chose
challenger_dispatch() {
  local result="$1" round_id="$2" scope_kind="$3" phase="$4"
  local has_issue issue_kind evidence follow_up alternative skipped
  has_issue=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('has_issue', False))" "$result" 2>/dev/null || echo "False")
  issue_kind=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('issue_kind',''))" "$result" 2>/dev/null || echo "")
  evidence=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('evidence',''))" "$result" 2>/dev/null || echo "")
  follow_up=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('follow_up_question',''))" "$result" 2>/dev/null || echo "")
  alternative=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('proposed_alternative',''))" "$result" 2>/dev/null || echo "")
  skipped=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('_skipped',''))" "$result" 2>/dev/null || echo "")

  # Loop guard: cap challenges per phase
  local max_rounds="${CONFIG_SCOPE_ADVERSARIAL_MAX_ROUNDS:-3}"
  local current_count
  current_count=$(challenger_count_for_phase "$phase")
  if [ "$current_count" -ge "$max_rounds" ] && [ "$has_issue" = "True" ]; then
    echo "⚠ Adversarial challenger (phản biện) đã đạt giới hạn $max_rounds/phase — bỏ qua challenge này để tránh vòng lặp." >&2
    has_issue="False"
    skipped="max_rounds_reached"
  fi

  if [ "$has_issue" != "True" ]; then
    # Emit a light telemetry ping so we can count skips vs real challenges
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "scope_answer_challenged" "$phase" "$scope_kind" \
        "adversarial-answer-check" "SKIP" \
        "{\"round_id\":\"$round_id\",\"reason\":\"${skipped:-clean}\"}"
    fi
    return 0
  fi

  # Issue detected — narrate in Vietnamese with glossary translations
  local kind_vn
  case "$issue_kind" in
    contradiction)        kind_vn="mâu thuẫn (contradiction) với decision trước" ;;
    hidden_assumption)    kind_vn="giả định ngầm (hidden assumption) chưa state" ;;
    edge_case)            kind_vn="edge case bị bỏ sót" ;;
    foundation_conflict)  kind_vn="khác biệt nền tảng (foundation conflict)" ;;
    security)             kind_vn="rủi ro bảo mật (security threat) — attack surface mới" ;;
    performance)          kind_vn="vượt budget hiệu năng (performance budget)" ;;
    failure_mode)         kind_vn="failure mode chưa xử lý (retry / idempotency / timeout)" ;;
    integration_chain)    kind_vn="phá contract integration (downstream / upstream / webhook)" ;;
    *)                    kind_vn="vấn đề ($issue_kind)" ;;
  esac

  echo ""
  echo "🤔 Phản biện (adversarial challenge) — round ${round_id}"
  echo "   Loại: ${kind_vn}"
  echo "   Bằng chứng: ${evidence}"
  echo "   Câu hỏi follow-up: ${follow_up}"
  echo "   Đề xuất thay thế: ${alternative}"
  echo ""
  echo "Orchestrator MUST now invoke AskUserQuestion with 3 options:"
  echo "  (a) Address — rephrase / tighten the answer (re-enter this round)"
  echo "  (b) Acknowledge — accept tradeoff, record in CONTEXT.md \"## Acknowledged tradeoffs\""
  echo "  (c) Defer — track as open question in CONTEXT.md \"## Open questions\""

  # Emit telemetry for the challenge itself (user_chose filled in by orchestrator post-ask)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    local evidence_esc="${evidence//\"/\\\"}"
    emit_telemetry_v2 "scope_answer_challenged" "$phase" "$scope_kind" \
      "adversarial-answer-check" "FLAG" \
      "{\"round_id\":\"$round_id\",\"issue_kind\":\"$issue_kind\",\"evidence\":\"$evidence_esc\",\"user_chose\":\"pending\"}"
  fi
  return 0
}

# Called after user picks option — updates the pending telemetry row by emitting a resolution event
challenger_record_user_choice() {
  local phase="$1" round_id="$2" scope_kind="$3" user_chose="$4"
  # user_chose ∈ {"address","acknowledge","defer"}
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "scope_answer_challenged" "$phase" "$scope_kind" \
      "adversarial-answer-check" "RESOLVED" \
      "{\"round_id\":\"$round_id\",\"user_chose\":\"$user_chose\"}"
  fi
}
