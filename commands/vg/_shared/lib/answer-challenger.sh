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

# Skip trivial answers (Y/N-only, single-word confirmations) — don't waste Haiku calls.
#
# v2.6 anti-lazy fix (2026-04-25):
#   "approve" / "approve_all" REMOVED from trivial list. Those words mean
#   "user is confirming AI's draft" — the draft IS the answer that needs
#   challenging. Letting them count as trivial gave AI a lazy escape: present
#   recommend-first answer, get user "approve all", skip entire 8-lens check.
#   Phase 7.14 + 7.15 DISCUSSION-LOG entries proved this happened in real runs.
#
#   Same logic for "ok|okay|yes|y|đúng|có|next|proceed" — kept in trivial list
#   ONLY when accumulated has NO AI-draft pattern. When draft present, challenger
#   swaps the user's confirmation with the draft text (challenger_extract_ai_draft).
challenger_is_trivial() {
  local ans="$1"
  local stripped
  # Use Python for unicode-aware lowercase (tr only handles ASCII; Vietnamese
  # capital letters Đ / Â / Ấ / Ơ / Ư etc. need .lower() to normalize).
  stripped=$(${PYTHON_BIN:-python3} -c 'import sys; print("".join(sys.argv[1].split()).lower())' "$ans" 2>/dev/null)
  [ -z "$stripped" ] && stripped=$(echo "$ans" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  local len=${#stripped}
  # ≤3 chars, OR matches genuine deny/skip tokens (NOT approve patterns)
  [ "$len" -le 3 ] && return 0
  case "$stripped" in
    # Genuine deny tokens — nothing to challenge, user explicitly rejecting
    no|n|sai|không|skip|pass|cancel|abort|stop|huỷ|hủy) return 0 ;;
    # Soft confirms — trivial ONLY when accumulated has no AI draft (caller swaps).
    # Caller guards the swap; here we just flag triviality.
    # NOTE: stripped removes whitespace so "approve all" → "approveall".
    yes|y|ok|okay|đúng|có|next|proceed|continue|tiếp|tiếp_tục|tieptục|tieptuc|approve|approveall|approve_all|approved|confirm|confirmed|allgood|alright|sounds_good|soundsgood) return 0 ;;
  esac

  # v2.6.1 (2026-04-25): option-pick patterns — user replies with letter/number
  # to pick from an AI-presented option list. The option content (not the
  # letter) is what needs challenging. Caller swap logic extracts option text.
  # Patterns: "a", "(a)", "[a]", "1", "(1)", "option a", "option 1",
  #           "chọn a", "đáp án 1", "(theo recommended)", "theo a", "pick 1"
  case "$stripped" in
    # Single letter/digit (a-z, 0-9) — pure option pick
    [a-z]|[0-9]) return 0 ;;
    # Parenthesized/bracketed option: (a), [b], (1), [2]
    \([a-z]\)|\[[a-z]\]|\([0-9]\)|\[[0-9]\]) return 0 ;;
    # "option a" / "option 1" / "đáp án a" / "chọn 1" / "pick a" / "select 2"
    option[a-z]|option[0-9]|đápán[a-z]|đápán[0-9]|chọn[a-z]|chọn[0-9]|pick[a-z]|pick[0-9]|select[a-z]|select[0-9]) return 0 ;;
    # "theo recommended" / "(theo recommend)" / "per recommended" — confirm AI draft
    theorecommended|theorecommend|perrecommended|perrecommend|recommended|recommend|đềxuất|theođềxuất|theoa|theob|theoc|theo1|theo2|theo3) return 0 ;;
    # Bare option-with-paren: "(theo recommended)" → "theorecommended" after strip
    \(theorecommended\)|\(theorecommend\)|\(theođềxuất\)|\(recommended\)|\(recommend\)) return 0 ;;
    # Common "default", "as-is", "as proposed"
    default|asis|as_is|asproposed|as_proposed|sameasrec|sameasrecommended|likerec|likerecommended|theyourcall|your_call|yourcall) return 0 ;;
  esac
  return 1
}

# v2.6.1 (2026-04-25): normalize an option-pick answer to a canonical token.
# Returns one of:
#   - single letter "a".."z"  → user picked option (a/b/c/...)
#   - single digit  "0".."9"  → user picked option 1/2/3/...
#   - "_recommended_"         → user said "(theo Recommended)" / "as proposed"
#   - "" (empty)              → not an option pick (caller falls back to draft extract)
challenger_normalize_pick() {
  local ans="$1"
  local stripped
  # Unicode-aware lowercase (Vietnamese accented capitals)
  stripped=$(${PYTHON_BIN:-python3} -c 'import sys; print("".join(sys.argv[1].split()).lower())' "$ans" 2>/dev/null)
  [ -z "$stripped" ] && stripped=$(echo "$ans" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  # Strip surrounding parens/brackets
  stripped="${stripped#\(}"; stripped="${stripped%\)}"
  stripped="${stripped#\[}"; stripped="${stripped%\]}"

  case "$stripped" in
    [a-z]|[0-9])
      echo "$stripped"; return ;;
    option[a-z]|chọn[a-z]|pick[a-z]|select[a-z]|đápán[a-z]|theo[a-z])
      echo "${stripped: -1}"; return ;;
    option[0-9]|chọn[0-9]|pick[0-9]|select[0-9]|đápán[0-9]|theo[0-9])
      echo "${stripped: -1}"; return ;;
    theorecommended|recommended|perrecommended|đềxuất|theođềxuất|recommend|theorecommend|asproposed|as_proposed|sameasrec|sameasrecommended|likerec|likerecommended|default|asis|as_is)
      echo "_recommended_"; return ;;
  esac
  echo ""
}

# v2.6.1 (2026-04-25): extract option (a) / (b) / (1) text from accumulated.
# Patterns supported:
#   - "- (a) text" or "* (a) text"
#   - "- a) text"  or "* a) text"
#   - "- a. text"  or "* a. text"
#   - numbered lists: "1. text" / "(1) text"
# Returns option body if ≥30 chars, else empty.
challenger_extract_option() {
  local accumulated="$1"
  local pick="$2"
  [ -z "$pick" ] && { echo ""; return; }
  ${PYTHON_BIN:-python3} - "$accumulated" "$pick" <<'PY' 2>/dev/null
import re, sys
text, pick = sys.argv[1], sys.argv[2]
pick_esc = re.escape(pick)
# Try several option-list formats. Stop at next option marker, blank line,
# next bold heading, or end-of-text.
patterns = [
    rf'^\s*[-*]\s*\({pick_esc}\)\s*(.*?)(?=\n\s*[-*]\s*\([a-z0-9]\)|\n\s*\n|\n\s*\*\*|\Z)',
    rf'^\s*[-*]\s*{pick_esc}\)\s*(.*?)(?=\n\s*[-*]\s*[a-z0-9]\)|\n\s*\n|\n\s*\*\*|\Z)',
    rf'^\s*[-*]\s*{pick_esc}\.\s*(.*?)(?=\n\s*[-*]\s*[a-z0-9]\.|\n\s*\n|\n\s*\*\*|\Z)',
    rf'^\s*\({pick_esc}\)\s*(.*?)(?=\n\s*\([a-z0-9]\)|\n\s*\n|\n\s*\*\*|\Z)',
    rf'^\s*{pick_esc}\)\s*(.*?)(?=\n\s*[a-z0-9]\)|\n\s*\n|\n\s*\*\*|\Z)',
    rf'^\s*{pick_esc}\.\s*(.*?)(?=\n\s*[a-z0-9]\.|\n\s*\n|\n\s*\*\*|\Z)',
]
for pat in patterns:
    m = re.search(pat, text, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    if m:
        body = m.group(1).strip()
        if len(body) >= 30:
            print(body)
            sys.exit(0)
sys.exit(0)
PY
}

# v2.6 anti-lazy fix (2026-04-25): extract AI's recommend-first draft from
# accumulated text. When user gives a trivial confirmation ("ok", "approve all"),
# the orchestrator's accumulated draft contains the AI's proposed answer and
# THAT is what needs challenging — not the empty confirmation.
#
# Detection patterns (case-insensitive, multi-line aware):
#   1. "**Recommended:**" or "**Recommend:**" or "**Đề xuất:**"
#   2. "## Recommendation" heading
#   3. <ai-draft>...</ai-draft> explicit XML tags
#   4. "Recommended answer:" or "AI suggests:" or "Tôi đề xuất:"
#
# Returns: draft text if found (≥50 chars), empty string otherwise.
# When empty, caller treats answer as genuinely trivial (skip challenger).
challenger_extract_ai_draft() {
  local accumulated="$1"
  [ -z "$accumulated" ] && { echo ""; return; }

  # Use Python for robust multi-line regex (bash awk is brittle on
  # accumulated strings with embedded newlines + special chars).
  ${PYTHON_BIN:-python3} - "$accumulated" <<'PY' 2>/dev/null
import re, sys
text = sys.argv[1]
patterns = [
    # XML tag — most explicit
    (r'<ai-draft>(.*?)</ai-draft>', re.DOTALL | re.IGNORECASE),
    # Bold marker patterns
    (r'\*\*Recommended:\*\*\s*(.*?)(?=\n\n|\n\*\*[A-Z]|\n## |\Z)', re.DOTALL | re.IGNORECASE),
    (r'\*\*Recommend:\*\*\s*(.*?)(?=\n\n|\n\*\*[A-Z]|\n## |\Z)', re.DOTALL | re.IGNORECASE),
    (r'\*\*Đề xuất:\*\*\s*(.*?)(?=\n\n|\n\*\*[A-Z]|\n## |\Z)', re.DOTALL | re.IGNORECASE),
    # Heading patterns
    (r'## Recommendation\s*\n(.*?)(?=\n## |\n---|\Z)', re.DOTALL | re.IGNORECASE),
    (r'## Đề xuất\s*\n(.*?)(?=\n## |\n---|\Z)', re.DOTALL | re.IGNORECASE),
    # Inline patterns
    (r'Recommended answer:\s*(.*?)(?=\n\n|\Z)', re.DOTALL | re.IGNORECASE),
    (r'AI suggests:\s*(.*?)(?=\n\n|\Z)', re.DOTALL | re.IGNORECASE),
    (r'Tôi đề xuất:\s*(.*?)(?=\n\n|\Z)', re.DOTALL | re.IGNORECASE),
]
for pat, flags in patterns:
    matches = re.findall(pat, text, flags)
    if matches:
        # Use the LAST match (most recent in accumulated context)
        draft = matches[-1].strip()
        # Filter: too-short drafts are likely false positives (heading echo,
        # placeholder text). Genuine recommendations are 50+ chars.
        if len(draft) >= 50:
            print(draft)
            sys.exit(0)
sys.exit(0)
PY
}

# Count prior challenges emitted for this phase/session — loop guard
challenger_count_for_phase() {
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

  # v2.6 anti-lazy fix (2026-04-25), v2.6.1 (option pick): when user confirms
  # trivially ("ok", "approve all", "a", "1", "(theo Recommended)"), the
  # substance to challenge is AI's recommend-first DRAFT or specific option
  # in the accumulated context — not the empty confirmation. Extract and
  # swap. Skip ONLY when no draft/option exists (genuine empty trivial).
  local _user_confirmed_draft="false"
  local _swap_kind=""  # "draft" | "option_letter" | "option_recommended"
  if challenger_is_trivial "$answer_text"; then
    local extracted_draft=""
    local pick
    pick=$(challenger_normalize_pick "$answer_text")

    if [ -n "$pick" ] && [ "$pick" != "_recommended_" ]; then
      # User picked option letter/digit (a/b/c/1/2/3) — extract that option
      extracted_draft=$(challenger_extract_option "$accumulated" "$pick")
      [ -n "$extracted_draft" ] && _swap_kind="option_${pick}"
    fi

    if [ -z "$extracted_draft" ]; then
      # Either no specific pick OR pick="_recommended_" → fall back to
      # generic draft extraction (looks for **Recommended:** / <ai-draft>)
      extracted_draft=$(challenger_extract_ai_draft "$accumulated")
      [ -n "$extracted_draft" ] && _swap_kind="${_swap_kind:-draft}"
    fi

    if [ -n "$extracted_draft" ] && [ "${#extracted_draft}" -ge 30 ]; then
      # AI-drafted-then-confirmed pattern detected — challenge the DRAFT
      _user_confirmed_draft="true"
      local swap_note="USER CONFIRMED AI'S DRAFT"
      [ -n "$pick" ] && [ "$pick" != "_recommended_" ] && \
        swap_note="USER PICKED OPTION (${pick}) FROM AI'S OPTION LIST"
      answer_text="[${swap_note} — challenger reviews the AI-proposed text below as if it were the user's authoritative answer, because user gave a trivial confirmation/pick.]

${extracted_draft}"
      # Telemetry: log the swap so we can measure how often AI lazy-presented
      # drafts/options that user just rubber-stamped (this is the v2.6 metric).
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "scope_draft_swapped_for_confirm" "${VG_CURRENT_PHASE:-unknown}" \
          "${scope_kind}" "adversarial-answer-check" "INFO" \
          "{\"round_id\":\"$round_id\",\"swap_kind\":\"${_swap_kind}\",\"pick\":\"${pick}\",\"draft_chars\":${#extracted_draft}}"
      fi
    else
      # Genuine trivial answer (no AI draft/option to challenge) — skip
      echo '{"has_issue":false,"issue_kind":"","evidence":"","follow_up_question":"","proposed_alternative":"","_skipped":"trivial_no_draft"}'
      return 0
    fi
  fi

  local subagent_model="${CONFIG_SCOPE_ADVERSARIAL_MODEL:-opus}"  # v1.9.3 R3.2: upgraded from haiku
  local prompt_path="${VG_TMP:-/tmp}/answer-challenger-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true

  # Always include FOUNDATION.md if it exists — adversary checks platform/compliance drift
  local foundation_excerpt=""
  if [ -f "${PLANNING_DIR}/FOUNDATION.md" ]; then
    foundation_excerpt=$(head -c 8000 "${PLANNING_DIR}/FOUNDATION.md" 2>/dev/null || true)
  fi

  # v1.9.5 R3.4: emit prompt CONTENT on fd 3 (not just path), because Task
  # subagents have sandbox isolation and cannot read /tmp files from parent.
  # Orchestrator captures fd 3 via: PROMPT=$(challenge_answer ... 3>&1 1>/dev/null 2>/dev/null)
  # then passes inline to Agent(prompt=$PROMPT).
  # v2.6 anti-lazy fix: add mode marker so subagent prompt makes the
  # confirmed-draft case explicit. Lens scoring should be STRICTER on
  # AI-drafted content because the user didn't write it themselves —
  # it's the AI's reasoning that needs to survive 8-lens scrutiny.
  local mode_marker=""
  if [ "$_user_confirmed_draft" = "true" ]; then
    mode_marker="
══════════════════════════════════════════════════════════════════════════════
⚠ MODE: USER-CONFIRMED-DRAFT (v2.6 anti-lazy)
══════════════════════════════════════════════════════════════════════════════

The 'USER'S ANSWER' below is actually AI's recommend-first DRAFT that the
user rubber-stamped with a trivial confirmation ('ok', 'approve all', etc).
You MUST be STRICTER than usual: AI's draft was generated quickly and the
user didn't rewrite it from their domain knowledge. Flag every plausible
gap. Set has_issue=true unless ALL 8 lenses are convincingly clean.

Default presumption: AI-drafted text has ≥1 hidden assumption or edge case.
Your job is to find it.
"
  fi

  cat > "$prompt_path" <<PROMPT
You are an Adversarial Answer Challenger. You have ZERO context about the parent session.
Your ONLY job: challenge a user's design answer in a ${scope_kind} discussion round.
${mode_marker}
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
