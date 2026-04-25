---
name: vg:scope
description: Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md
argument-hint: "<phase> [--skip-crossai] [--auto] [--update] [--deepen=D-XX]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
runtime_contract:
  # Scope MUST produce CONTEXT.md (enriched decisions) + DISCUSSION-LOG.md.
  # Without these, blueprint has nothing to plan against.
  must_write:
    # v2.5.1 anti-forge: CONTEXT.md must have at least 1 decision heading
    # (### D-XX or ### P{phase}.D-XX) — prevents empty stub.
    - path: "${PHASE_DIR}/CONTEXT.md"
      content_min_bytes: 500
      content_required_sections: ["D-"]
    - "${PHASE_DIR}/DISCUSSION-LOG.md"
  must_touch_markers:
    - "0_parse_and_validate"
    - "1_deep_discussion"
    - "2_artifact_generation"
  must_emit_telemetry:
    # v2.5.1 anti-forge: tasklist visibility
    - event_type: "scope.tasklist_shown"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.started"
      phase: "${PHASE_NUMBER}"
    - event_type: "scope.completed"
      phase: "${PHASE_NUMBER}"
  forbidden_without_override:
    - "--skip-crossai"
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained. Do NOT call /gsd-discuss-phase.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **SPECS.md required** — must exist before scoping. No SPECS = BLOCK.
4. **Scope = DISCUSSION only** — do NOT create API-CONTRACTS.md, TEST-GOALS.md, or PLAN.md. Those are blueprint's job.
5. **Enriched CONTEXT.md** — each decision `P{phase}.D-XX` has structured sub-sections (endpoints:, ui_components:, test_scenarios:). Blueprint reads these to generate artifacts accurately.

**Namespace (không gian tên) BREAKING v1.8.0:** CONTEXT.md decisions use `P{phase}.D-XX` format, where `{phase}` is the phase number (e.g., `P7.10.1.D-01` for phase 7.10.1, decision 01). Bare `D-XX` is LEGACY — written by pre-v1.8.0 scope runs, migrated via `.claude/scripts/migrate-d-xx-namespace.py`. Rationale: prevent collision (xung đột) with FOUNDATION.md `F-XX` and with other phases' `D-XX` at phase 15+.
6. **DISCUSSION-LOG.md is APPEND-ONLY** — never overwrite, never delete existing content. Only append new sessions.
7. **Pipeline names** — use V5 names: `/vg:blueprint` (not plan), `/vg:build` (not execute).
8. **5 rounds, then loop** — every round locks decisions. No round is skippable (except Round 4 UI/UX for backend-only profile).
9. **Ngôn ngữ câu hỏi — loại người, không loại máy (OHOK-9, 2026-04-22)** — khi hỏi user trong 5 rounds, MUST dùng ngôn ngữ tự nhiên của con người diễn đạt ngữ cảnh. Tuyệt đối không hỏi kiểu technical/machine language (schema-like, enum-list, code-identifier) vì user không phải AI/dev technical, họ không biết giải thích theo ngôn ngữ đó. Áp dụng cả Round 1 (scope/goal), Round 2 (multi-surface + endpoints), Round 3 (auth/data), Round 4 (UI/UX), Round 5 (edge cases).

   **Nguyên tắc**:
   - **Mô tả ngữ cảnh** bằng câu chuyện thực tế ("publisher mở dashboard, bấm vào sites, cần thấy gì?") thay vì yêu cầu giá trị field ("list fields for sites table: id/name/status/...?")
   - **Dùng ví dụ cụ thể** ("như khi user login vào gmail, nếu sai password hiện gì?") thay vì abstract pattern ("define error handling strategy for auth failure")
   - **Cho lựa chọn** (a/b/c) với mô tả hành vi quan sát được, không phải technical enum
   - **Giải thích trước khi hỏi** — nêu background 1-2 câu, rồi mới đặt câu hỏi để user hiểu tại sao mình đang quyết định
   - **Tiếng Việt tự nhiên** — "trong lúc chạy cái này, bạn muốn system hành xử thế nào khi..." thay vì "specify expected behavior for <edge_case_N>"
   - **Glossary inline** — thuật ngữ EN (graphify, CrossAI, ORG dimension, quota, override-debt) phải kèm giải thích ngắn trong ngoặc lần đầu xuất hiện

   **Ví dụ SAI** (ngôn ngữ máy — không dùng):
   > "Round 2: specify endpoints for this phase. For each: method, path, request schema, response schema, auth level."

   **Ví dụ ĐÚNG** (ngôn ngữ người):
   > "Round 2 — về các API cho phase này: bạn hình dung ở các màn hình user sẽ chạm vào những chức năng gì? Ví dụ lúc bấm nút Save, hệ thống có gọi server để lưu không, lưu những gì, và nếu fail thì hiện lỗi gì cho user thấy? Tôi sẽ tự suy ra method/path/schema sau từ mô tả của bạn — chỉ cần bạn kể scenario."

   **Enforcement**: nếu Opus hỏi câu technical-schema mà user trả lời "không hiểu ý" / "hỏi gì khó hiểu" / "không biết giải thích kiểu đó" → treat là user_pushback, rewrite câu hỏi dạng conversational, RE-ASK. Log bug-detection event với pattern `scope_question_too_technical`.
</rules>

<objective>
Step after specs in VG pipeline. Deep structured discussion to extract all decisions for a phase.
Output: CONTEXT.md (enriched with endpoint/UI/test notes per decision) + DISCUSSION-LOG.md (append-only trail).

Pipeline: specs -> **scope** -> blueprint -> build -> review -> test -> accept
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR, $PROFILE).

**Bug detection (v1.11.2 R6 — MANDATORY):** Read `.claude/commands/vg/_shared/bug-detection-guide.md` BEFORE starting. Apply 6 detection patterns throughout: schema_violation (subagent JSON shape), helper_error (bash exit ≠ 0), user_pushback (keywords nhầm/sai/wrong/bug), ai_inconsistency (same input → different outputs), gate_loop (3+ same gate fails), self_discovery (AI's own bug findings). When pattern detected: NARRATE intent + CALL `report_bug` via bash + CONTINUE workflow (non-blocking).

**Adversarial challenger (v1.9.1 R3, v1.9.3 R3.2 upgraded — 8 lenses + Opus, v1.9.5 R3.4 fd-3 content fix):** Source `.claude/commands/vg/_shared/lib/answer-challenger.sh` at top of command. After EVERY user answer in Rounds 1-5 AND in the Deep Probe Loop, invoke `challenge_answer "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft"`.

**v1.9.5 R3.4 FIX — subagent sandbox isolation:** Helper emits prompt CONTENT (not path) on fd 3. Tmp file kept for audit only. **v1.14.1+ REFACTOR:** call wrapper script instead of raw fd-3 pattern (safer — encapsulates redirection + trivial-skip):
```bash
PROMPT=$(bash .claude/commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
         "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft")
wrapper_rc=$?
# rc=0 success (PROMPT contains content) | rc=2 trivial answer (skip challenge) | rc=1 error
[ $wrapper_rc -eq 2 ] && { echo "↷ Trivial answer — skip challenger"; PROMPT=""; }
```

Legacy direct-fd invocation still supported for back-compat:
```bash
PROMPT=$(challenge_answer "$user_answer" "round-$ROUND" "phase-scope" "$accumulated" 3>&1 1>/dev/null 2>/dev/null)
```
(Prior docs said "Read the prompt file" — that failed because Task subagents can't access parent's /tmp.)

Orchestrator MUST:
1. Capture fd 3 via `3>&1 1>/dev/null 2>/dev/null` pattern → `$PROMPT` contains full inline content
1b. **Inject bootstrap rules** into prompt so promoted rules apply to subagent reasoning:
    ```bash
    source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
    BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope")
    vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope" "${PHASE_NUMBER}"
    PROMPT="${PROMPT}

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>"
    ```
2. Dispatch Task tool (subagent_type=general-purpose, model=`${config.scope.adversarial_model:-opus}` — v1.9.3 default Opus, zero parent context) with `prompt=$PROMPT` parameter
3. Parse subagent stdout (one JSON line)
4. Call `challenger_dispatch "$subagent_json" "round-$ROUND" "phase-scope" "$PHASE_NUMBER"`
5. If `has_issue=true` → AskUserQuestion with 3 options:
   - **Address** → re-enter Q for that round (don't advance); merge user's revised answer
   - **Acknowledge** → record tradeoff under `## Acknowledged tradeoffs` in CONTEXT.md staged
   - **Defer** → record under `## Open questions` in CONTEXT.md staged
6. Call `challenger_record_user_choice "$PHASE_NUMBER" "round-$ROUND" "phase-scope" "$choice"` to resolve telemetry
7. If `challenger_count_for_phase` reaches `config.scope.adversarial_max_rounds` (default 3) → helper auto-skips remaining challenges (loop guard)

Skip challenger when `config.scope.adversarial_check: false` (rapid prototyping) or answer is trivial (Y/N, single-word confirm — helper auto-detects via `challenger_is_trivial`).

**Dimension Expander (v1.9.3 R3.2 — NEW, proactive gap finding, v1.9.5 R3.4 fd-3 content fix):** Source `.claude/commands/vg/_shared/lib/dimension-expander.sh` at top of command. At the END of EACH round (Rounds 1-5) and at the END of the Deep Probe Loop, AFTER the adversarial challenger loop concludes and BEFORE advancing to next round, invoke `expand_dimensions "$ROUND" "$ROUND_TOPIC" "$round_qa_accumulated" "${PLANNING_DIR}/FOUNDATION.md"`.

**v1.9.5 R3.4 FIX — same pattern as challenger:** Helper emits prompt CONTENT on fd 3. **v1.14.1+ REFACTOR:** call wrapper instead:
```bash
PROMPT=$(bash .claude/commands/vg/_shared/lib/vg-expand-round-wrapper.sh \
         "$ROUND" "$ROUND_TOPIC" "$round_qa_accumulated" "${PLANNING_DIR}/FOUNDATION.md")
```

Legacy direct-fd invocation still supported:
```bash
PROMPT=$(expand_dimensions "$ROUND" "$ROUND_TOPIC" "$accumulated" "${PLANNING_DIR}/FOUNDATION.md" 3>&1 1>/dev/null 2>/dev/null)
```

Orchestrator MUST:
1. Capture fd 3 via `3>&1 1>/dev/null 2>/dev/null` → `$PROMPT` = full inline prompt content
1b. **Inject bootstrap rules** (same pattern as challenger — rules match `target_step=scope` fire here):
    ```bash
    source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
    BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope")
    vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope" "${PHASE_NUMBER}"
    PROMPT="${PROMPT}

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>"
    ```
2. Dispatch Task tool (subagent_type=general-purpose, model=`${config.scope.dimension_expand_model:-opus}`, zero parent context) with `prompt=$PROMPT`
3. Parse subagent stdout (one JSON line)
4. Call `expander_dispatch "$subagent_json" "round-$ROUND" "$PHASE_NUMBER"`
5. If `critical_missing[] > 0` OR `nice_to_have_missing[] > 0` → AskUserQuestion with 3 options:
   - **Address critical** → re-enter round with each CRITICAL missing dimension added as new Q (append to round-$ROUND-followups.md)
   - **Acknowledge** → record dimensions under `## Acknowledged gaps` in CONTEXT.md staged
   - **Defer to open questions** → record under `## Open questions` in CONTEXT.md staged (will be re-raised in blueprint)
6. Call `expander_record_user_choice "$PHASE_NUMBER" "round-$ROUND" "$choice"` to resolve telemetry
7. If `expander_count_for_phase` reaches `config.scope.dimension_expand_max` (default 6 = 5 rounds + 1 deep probe) → helper auto-skips remaining expansions (loop guard)

Skip dimension-expander when `config.scope.dimension_expand_check: false` (rapid prototyping). Unlike challenger, expander runs ONCE per round (not per answer) — cost is bounded.

**Two helpers, complementary scope:**
- `answer-challenger` (per-answer): "is this specific answer wrong?" — 8 lenses on single answer
- `dimension-expander` (per-round): "what haven't we discussed yet?" — gap analysis on whole round

<step name="0_parse_and_validate">
## Step 0: Parse arguments + validate prerequisites

```bash
# Harness v2.6.1 (2026-04-26): inject rule cards at skill entry — gives AI
# a 5-30 line digest of skill rules instead of skimming 1500-line body.
# Cards generated by extract-rule-cards.py. Per AUDIT.md D4 finding
# (inject_rule_cards 0/44 invocation = memory mechanism dead).
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-scope" "0_parse_and_validate" 2>&1 || true

# Parse arguments
PHASE_NUMBER=""
SKIP_CROSSAI=false
AUTO_MODE=false
UPDATE_MODE=false       # OHOK Day 5 — incremental delta-diff instead of wipe
DEEPEN_DECISION=""      # OHOK Day 5 — targeted drill-down on one D-XX

for arg in $ARGUMENTS; do
  case "$arg" in
    --skip-crossai) SKIP_CROSSAI=true ;;
    --auto) AUTO_MODE=true ;;
    --update) UPDATE_MODE=true ;;
    --deepen=*) DEEPEN_DECISION="${arg#*=}" ;;
    --deepen) ;;  # next token is decision id — simple parse below
    *) PHASE_NUMBER="$arg" ;;
  esac
done

# --update mode: read existing CONTEXT.md + DISCUSSION-LOG.md, spawn Haiku
# delta-diff subagent to compute proposed delta vs user's new input, present
# interactive y/n/e per delta. Does NOT wipe existing decisions (opposite
# of default re-discuss flow). Requires CONTEXT.md present.
#
# --deepen=D-XX: skip rounds 1-5, run targeted sub-decision exploration for
# the named decision. Appends D-XX.1, D-XX.2, ... as sub-decisions resolving
# branching. Requires CONTEXT.md with D-XX present.
#
# Both flags are mutually exclusive with --auto (incremental updates need
# user per-delta confirmation by definition).
if [ "$UPDATE_MODE" = "true" ] && [ "$AUTO_MODE" = "true" ]; then
  echo "⛔ --update incompatible with --auto (incremental mode needs user confirmation)" >&2
  exit 1
fi
if [ -n "$DEEPEN_DECISION" ] && [ "$AUTO_MODE" = "true" ]; then
  echo "⛔ --deepen incompatible with --auto" >&2
  exit 1
fi

# v1.15.2 — register run so Stop hook can verify runtime_contract evidence
# v2.2 — direct orchestrator call replaces bash-function indirection.
# No fail-open: if orchestrator missing, skill cannot proceed. This is
# the "AI can't skip init" contract — wrapper outside LLM rationalization.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start \
    vg:scope "${PHASE_NUMBER}" "${ARGUMENTS}" || {
  echo "⛔ vg-orchestrator run-start failed — cannot proceed" >&2
  exit 1
}

# v2.5.1 anti-forge: show task list at flow start so user sees planned steps
${PYTHON_BIN:-python3} .claude/scripts/emit-tasklist.py \
  --command "vg:scope" \
  --profile "${PROFILE:-web-fullstack}" \
  --phase "${PHASE_NUMBER:-unknown}" 2>&1 | head -40 || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 0_parse_and_validate 2>/dev/null || true
```

**Validate:**
1. `$PHASE_NUMBER` is provided. If empty -> BLOCK: "Usage: /vg:scope <phase>"
2. Read `${PLANNING_DIR}/ROADMAP.md` — confirm phase exists
3. Determine `$PHASE_DIR` by scanning `${PHASES_DIR}/` for matching directory
4. Check `${PHASE_DIR}/SPECS.md` exists. Missing -> BLOCK:
   ```
   SPECS.md not found for Phase {N}.
   Run first: /vg:specs {phase}
   ```

**Phase profile detection (P5, v1.9.2) — short-circuit for non-feature phases.**

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"

  case "$PHASE_PROFILE" in
    infra|hotfix|bugfix|migration|docs)
      echo "ℹ Phase profile='${PHASE_PROFILE}' — scope discussion không cần 5 vòng đầy đủ."
      echo "  Tạo CONTEXT.md rút gọn + thoát sớm. Blueprint sẽ chỉ tạo PLAN (+ ROLLBACK nếu migration)."
      # Generate minimal CONTEXT.md if not exists
      if [ ! -f "${PHASE_DIR}/CONTEXT.md" ]; then
        ${PYTHON_BIN} - "${PHASE_DIR}/CONTEXT.md" "$PHASE_NUMBER" "$PHASE_PROFILE" <<'PY'
import sys
from datetime import datetime
out, phase, profile = sys.argv[1], sys.argv[2], sys.argv[3]
content = f"""# Phase {phase} — Scope context ({profile} profile)

**Profile:** {profile}  
**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}  
**Scope mode:** short-circuit (no 5-round discussion — profile does not require feature-depth scoping)

## Decisions

_Non-feature profiles typically don't have architectural decisions — execution details live in SPECS.md.  
If you discover a decision worth recording, add it here with ID `P{phase}.D-XX`._

## Next

Run `/vg:blueprint {phase}` — will skip scope/contract/test-goals generation for non-feature profile.
"""
open(out, 'w', encoding='utf-8').write(content)
print(f"✓ CONTEXT.md stub written for profile={profile}")
PY
      fi
      echo "✓ Scope short-circuit done. Next: /vg:blueprint ${PHASE_NUMBER}"
      exit 0
      ;;
    feature|*)
      # default path — 5 rounds
      ;;
  esac
fi
```

**If CONTEXT.md already exists:**
```
AskUserQuestion:
  header: "Existing Scope"
  question: "CONTEXT.md already exists for Phase {N} ({decision_count} decisions). What would you like to do?"
  options:
    - "Update — re-discuss and enrich existing scope"
    - "View — show current CONTEXT.md contents"
    - "Skip — proceed to /vg:blueprint"
```
- "Update" -> continue (will overwrite CONTEXT.md but APPEND to DISCUSSION-LOG.md)
- "View" -> display contents, then re-ask
- "Skip" -> exit with "Next: /vg:blueprint {phase}"

**If codebase-map.md exists:** Read `${PLANNING_DIR}/codebase-map.md` silently -> inject god nodes + communities as context for discussion rounds.

**Read SPECS.md:** Extract Goal, In-scope items, Out-of-scope items, Constraints, Success criteria. Hold in memory for all rounds.

**Update PIPELINE-STATE.json:** Set `steps.scope.status = "in_progress"`, `steps.scope.started_at = {now}`.
</step>

<step name="1_deep_discussion">
## Step 1: DEEP DISCUSSION (5 structured rounds)

For each round: AI presents analysis/recommendation FIRST (recommend-first pattern), then asks user to confirm/edit/expand. Each round locks a set of decisions.

Track all Q&A exchanges for DISCUSSION-LOG.md generation in Step 2.

### Round 1 — Domain & Business

AI reads SPECS.md goal + in-scope items. Pre-analyze:
- What user stories does this phase serve?
- Which roles are involved?
- What business rules apply?

Present analysis, then ask:

**Conversational preamble (R9 rule):**

> "Vòng 1 (Domain & Business — bối cảnh nghiệp vụ) chốt **ai làm gì trong phase này và tại sao**: user story (kịch bản người dùng), role (vai trò — advertiser/publisher/admin/dsp-partner), và business rule (quy tắc nghiệp vụ — vd: chỉ publisher mới approve được inventory của chính họ). Đây là nền tảng cho 4 vòng còn lại — nếu sai ở đây, kỹ thuật + API + UI + test đều lệch theo.
>
> Tôi đã đọc SPECS.md và phân tích sơ bộ. Bạn review, chỉnh chỗ nào AI đoán sai, hoặc bổ sung context nếu thiếu."

```
AskUserQuestion:
  header: "Round 1 — Bối cảnh nghiệp vụ"
  question: |
    Dựa trên SPECS.md, đây là hiểu biết của tôi:

    **Mục tiêu phase:** {extracted goal}

    **User stories (kịch bản người dùng — ai muốn làm gì):**
    - US-1: {story}
    - US-2: {story}

    Ví dụ đã điền:
    - US-1: DSP partner muốn tạo deal mới với publisher để chạy campaign direct (không qua auction)
    - US-2: SSP admin muốn review + approve/reject deal trước khi nó active

    **Roles (vai trò — ai có quyền làm):** {roles}
    Ví dụ: dsp-partner (tạo deal), ssp-admin (approve/reject), publisher (xem deal về inventory của mình)

    **Business rule (quy tắc nghiệp vụ — luật bắt buộc):** {rules}
    Ví dụ:
    - Deal mới luôn start ở state 'pending', chỉ ssp-admin đổi sang 'approved'/'rejected'
    - Publisher chỉ thấy deal về inventory của chính họ, không thấy deal khác

    Câu trả lời: "ok" hoặc chỉnh cụ thể ("role X nên thêm quyền Y", "business rule Z chưa đầy đủ vì...").
  (open text)
```

**If --auto mode:** AI picks recommended answers based on SPECS.md + codebase context. Log "[AUTO]" in discussion log.

From response, lock decisions:
- `P${PHASE_NUMBER}.D-01` through `P${PHASE_NUMBER}.D-XX` (category: business)
- Each decision captures: title, decision text, rationale
- **Namespace enforcement:** Always prefix with `P${PHASE_NUMBER}.` (where ${PHASE_NUMBER} is extracted from $ARGUMENTS). If phase is "7.10.1", the decision ID is `P7.10.1.D-01`. Never write bare `D-01` (legacy — blocked by commit-msg hook from v1.10.1).

**Adversarial challenge** (v1.9.1 R3 + v1.9.3 R3.2 upgrade — 8 lenses + Opus, applies to EVERY round including Rounds 2-5 and deep probes): after recording the user answer but BEFORE advancing to the next round, run `challenge_answer` + `challenger_dispatch` per the protocol in `<process>` header. If the challenger flags an issue and user chooses **Address**, re-enter this round with the user's revised answer. If **Acknowledge** → append under `## Acknowledged tradeoffs` in `CONTEXT.md.staged`. If **Defer** → append under `## Open questions`.

**Dimension expansion** (v1.9.3 R3.2 NEW, applies to EVERY round including Rounds 2-5 and deep probes — runs ONCE per round AFTER all Q&A + adversarial challenges complete, BEFORE advancing to next round): Invoke `expand_dimensions "$ROUND" "$ROUND_TOPIC" "$round_qa_accumulated" "${PLANNING_DIR}/FOUNDATION.md"` where `$round_qa_accumulated` = all user answers of this round merged, `$ROUND_TOPIC` = the round's topic string (e.g., "Domain & Business" for Round 1). Dispatch Task tool (model=`${config.scope.dimension_expand_model:-opus}`, zero parent context) with prompt contents, parse subagent JSON, call `expander_dispatch` per the protocol in `<process>` header. If `critical_missing[]` or `nice_to_have_missing[]` non-empty, user picks: **Address critical** → re-enter round appending each CRITICAL dimension as new Q → merge user's new answers. **Acknowledge** → append dimensions under `## Acknowledged gaps` in `CONTEXT.md.staged`. **Defer** → append under `## Open questions` for blueprint to re-raise.

### Round 2 — Technical Approach

**Multi-surface gate (v1.10.0 R4 NEW):** if `config.surfaces` block declared (multi-platform project), Round 2 MUST first ask user which surfaces this phase touches.

```bash
if grep -qE "^surfaces:" .claude/vg.config.md; then
  # List surfaces from config
  AVAILABLE_SURFACES=$(${PYTHON_BIN} -c "
import re
cfg = open('.claude/vg.config.md', encoding='utf-8').read()
m = re.search(r'^surfaces:\n((?:  [^\n]+\n)+)', cfg, re.M)
if m:
    for line in m.group(1).split('\n'):
        sm = re.match(r'^  (\w[\w-]*):', line)
        if sm: print(sm.group(1))
")
  echo "Multi-surface project detected. Surfaces declared: $AVAILABLE_SURFACES"
  # AskUserQuestion multi-select: which surfaces does this phase touch?
  # Example: phase 13 (DSP admin) touches [web, api] but not [rtb, workers]
  # Lock SURFACE_LIST in CONTEXT.md + pick primary SURFACE_ROLE for design lookup
fi
```

**AskUserQuestion for surfaces** (only when multi-surface config exists):
```
header: "Surfaces touched"
question: "Phase này touch surfaces nào? (multi-select)"
multiSelect: true
options: [<from config.surfaces keys>]
```

Lock `P{phase}.D-surfaces: [api, web]` decision.

**Primary role lookup** — for design resolution, if phase touches `web` surface, read `config.surfaces.web.design` → set `SURFACE_ROLE` var for Round 4 DESIGN.md resolve.

**Surface gap auto-detect (v1.14.1+ NEW):** After AI generates the tech approach recommendation (end of Round 2 analysis, BEFORE locking decisions), scan the recommendation text for mentioned paths (`apps/X`, `packages/X`) and diff against declared surfaces. If the recommendation touches paths NOT covered by any declared surface, auto-propose config amendment.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-gap-detector.sh"

if surface_gap_detector_is_enabled ".claude/vg.config.md"; then
  GAPS_JSON=$(detect_surface_gaps "$R2_RECOMMENDATION_TEXT" ".claude/vg.config.md")
  MISSING_COUNT=$(echo "$GAPS_JSON" | ${PYTHON_BIN} -c "import json,sys; print(len(json.loads(sys.stdin.read()).get('missing_surfaces',[])))")

  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "━━━ Surface Gap Detected ━━━"
    format_gap_narrative "$GAPS_JSON"
    echo ""
    echo "Phase's tech approach touches ${MISSING_COUNT} path(s) not declared in surfaces: block of vg.config.md."
    # AskUserQuestion:
    #   header: "Surface gap"
    #   question: "Add missing surface(s) to vg.config.md?"
    #   options:
    #     - "Add surfaces + lock P{phase}.D-XX amendment decision (Recommended)"
    #     - "Acknowledge gap (lock as known tradeoff)"
    #     - "Skip — phase doesn't need multi-surface support"
    # If user accepts: lock decision P{phase}.D-YY "add surface {name}" with paths+stack
    # Amendment applies during /vg:blueprint preflight (see blueprint.md Step 0)
  fi
fi
```

The detected surface gap becomes a lockable `P{phase}.D-XX` config-amendment decision. Blueprint preflight (v1.14.1+ Step 0) enforces application before tasks can spawn. Prevents "phase scope mentions Rust but RTB surface never declared → downstream surface-aware checks skip silently".

---

AI pre-analyzes existing code via `config.code_patterns` paths. Identify:
- Which services/modules need changes?
- Database collections/schema shape?
- External dependencies?
- **Utility needs (v1.14.2+ NEW):** scan planned functionality for helper needs (money, date, number, string, async). Cross-reference `PROJECT.md` → `## Shared Utility Contract` exports table. Classify each helper as REUSE (already exists), EXTEND (exists but missing variant — add param/overload), or NEW (not in contract — must be added to `packages/utils` FIRST, not inline per-file).

Present analysis with code status table:

**Conversational preamble (R9 rule — ngôn ngữ loại người):**

Trước khi show bảng, narrate 2-3 câu giải thích context + mục tiêu round này:

> "Vòng 2 (Technical Approach — cách làm kỹ thuật) chốt **ai làm gì** trong code base: module nào cần sửa, cần table mới trong database không, và helper (hàm tiện ích dùng chung) nào phải thêm vào `packages/utils` trước khi business logic đụng tới. Lý do gộp vào vòng này: phase sau không sửa kiến trúc được, nên ta phải thấy đúng hình dạng code ngay bây giờ.
>
> Tôi đã quét codebase và thấy [tóm tắt 1-2 câu hiện trạng]. Đề xuất của tôi bên dưới. Bạn đọc, chỉnh chỗ nào AI đoán sai, hoặc nói 'ok' nếu ổn."

```
AskUserQuestion:
  header: "Round 2 — Cách làm kỹ thuật"
  question: |
    **Kiến trúc (architecture — cấu trúc các module phối hợp):**

    | Module | Hiện trạng | Đề xuất |
    |--------|-----------|---------|
    | {module tên thật} | {đã có / làm mới / cần mở rộng} | {sửa gì cụ thể — 1 dòng} |

    Ví dụ đã điền:
    | `apps/api/src/modules/deals` | đã có (CRUD cơ bản) | thêm endpoint bulk-update state, sửa index mongo `deals_by_publisher_state` |

    **Database (storage layer):** {collection/table mới + index cần thiết}
    **External deps (thư viện bên ngoài):** {npm/cargo packages mới, nếu có}

    **Shared utilities (helper dùng chung — tránh duplicate):**

    | Helper cần | Đã có trong `packages/utils`? | Hành động |
    |-----------|------------------------------|-----------|
    | formatCurrency | ✓ có rồi | REUSE (dùng lại) |
    | formatDealState | ✗ chưa có | NEW — thêm vào `packages/utils/src/deals.ts` TRƯỚC khi task business dùng |

    Câu trả lời của bạn có thể là: "ok đề xuất trên" — hoặc chỉnh cụ thể: "module X nên làm Y thay vì Z vì..."
  (open text)
```

**Enforcement:** If user confirms NEW helpers, scope MUST lock decision `P{phase}.D-utilities` with format:
```
**Utilities added:**
- formatDealState(state: DealState): string → packages/utils/src/deals.ts (NEW)
- formatCurrency → REUSE existing
```
This forces blueprint to generate a Task 0 (extend utils) BEFORE business-logic tasks. Gate: blueprint's plan-checker rejects PLAN where task N uses helper not yet added by task M < N.

Lock decisions D-XX+1.. (category: technical, including `P{phase}.D-utilities` if applicable)

### Round 3 — API Design

AI SUGGESTS endpoints derived from locked decisions. **v1.14.0+ — bắt buộc hỏi về `depends_on_phase` khi endpoint chạm view/data phase khác:**

**Conversational preamble (R9 rule):**

> "Vòng 3 (API Design — hợp đồng request/response giữa frontend và backend) chốt **hình dạng endpoint**: đường dẫn (path), method (GET/POST/PUT/DELETE), ai được gọi (auth role — vai trò xác thực), và input/output shape. Sau vòng này, blueprint sẽ tự sinh code Zod schema từ những gì bạn chốt ở đây, nên bây giờ càng cụ thể càng tốt.
>
> Nếu có endpoint chỉ test được khi phase khác đã xong (vd: conversion event cần pixel server ship trước), note cột 'phụ thuộc phase nào' để review sau không mark FAILED oan."

```
AskUserQuestion:
  header: "Round 3 — API Design"
  question: |
    Từ các quyết định vòng 1-2, tôi đề xuất các endpoint sau:

    | # | Endpoint | Method | Ai gọi được (auth) | Mục đích | Từ quyết định | Phụ thuộc phase nào? |
    |---|----------|--------|--------------------|----------|---------------|----------------------|
    | 1 | /api/v1/{tên resource} | POST | {role} | {mô tả ngắn} | D-{XX} | _(không / X.Y)_ |
    | 2 | /api/v1/{tên resource} | GET  | {role} | {mô tả ngắn} | D-{XX} | _(không / X.Y)_ |

    Ví dụ đã điền:
    | 1 | /api/v1/deals | POST | dsp-partner | tạo deal mới từ DSP bidder | D-03 | không |
    | 2 | /api/v1/deals/:id/state | PUT | ssp-admin | publisher approve/reject deal | D-04 | không |

    **Request/response shape (hình dạng dữ liệu):**
    - POST /api/v1/deals: body `{ publisherId, creativeSpec, floorCpm }` → 201 `{ id, state: 'pending' }`
    - PUT /api/v1/deals/:id/state: body `{ state: 'approved' | 'rejected', reason? }` → 200 `{ id, state, updatedAt }`

    **Cột "Phụ thuộc phase nào"** — giải thích: nếu endpoint chỉ verify được khi phase khác đã ship (vd: conversion event endpoint phụ thuộc pixel server từ phase 7.12), điền số phase target (vd: `7.12`). Goal gắn tag này sẽ được mark DEFERRED (hoãn, không FAIL) ở review.

    Câu trả lời của bạn: "ok" hoặc chỉnh endpoint cụ thể ("endpoint 2 nên dùng POST không PUT vì...").
  (open text)
```

User confirms/edits each endpoint. Lock ENDPOINT NOTES + (nếu có) `depends_on_phase: X.Y` embedded within existing decisions dưới dạng:

```
**Endpoints:**
- POST /api/v1/conversion-events (auth: advertiser, purpose: record conversion)
  depends_on_phase: 7.12   # chỉ verify được khi pixel server ship
```

### Round 4 — UI/UX

**Skip condition:** If `$PROFILE` is "web-backend-only" or "cli-tool" or "library" -> skip this round entirely. Log: "Round 4 skipped (profile: {profile})."

**Design System integration (v1.10.0 R4 NEW):**

Before asking UI questions, source `design-system.sh` and resolve applicable DESIGN.md:

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh"
if design_system_enabled; then
  # Scope Round 2 should have locked `surface_role` metadata from user answer
  # (multi-surface projects: user declares which role this phase targets)
  DESIGN_RESOLVED=$(design_system_resolve "$PHASE_DIR" "${SURFACE_ROLE:-}")

  if [ -n "$DESIGN_RESOLVED" ]; then
    echo "✓ DESIGN.md resolved: $DESIGN_RESOLVED"
    echo "  Will inject into Round 4 discussion + build task prompts."
    DESIGN_CONTEXT=$(design_system_inject_context "$PHASE_DIR" "${SURFACE_ROLE:-}")
    # Use $DESIGN_CONTEXT in Round 4 AskUserQuestion + lock as decision note
  else
    echo "⚠ No DESIGN.md resolved for phase (role=${SURFACE_ROLE:-<none>})"
    echo "  Round 4 will offer 3 options: pick from library / import existing / create from scratch"
    DESIGN_CONTEXT=""
  fi
fi
```

**If `$DESIGN_CONTEXT` set (DESIGN.md resolved):** Round 4 Q includes "Dùng design này làm base? Hay customize cho phase?" với design reference. Pages/components suggested phải tôn trọng color palette + typography + spacing rules từ DESIGN.md.

**If `$DESIGN_CONTEXT` empty (no DESIGN.md):** Round 4 Q offers 3 options:
1. **Pick from 58 brands** — `/vg:design-system --browse` để list. User pick → auto-run `/vg:design-system --import <brand> --role=<current-role>`.
2. **Import existing** — user paste DESIGN.md content hoặc link URL → save to `${PLANNING_DIR}/design/DESIGN.md` hoặc `${PLANNING_DIR}/design/{role}/DESIGN.md`.
3. **Create from scratch** — `/vg:design-system --create --role=<role>` → guided discussion tạo DESIGN.md custom.
4. **Skip (not recommended)** — UI phase without design standards → flag "design-debt" trong CONTEXT.md.

**Conversational preamble (R9 rule):**

> "Vòng 4 (UI/UX — giao diện người dùng) chốt **những trang và component** frontend cần build, dựa trên endpoint đã có ở vòng 3. Một endpoint POST /api/v1/deals thường cần 1 form tạo + 1 bảng list + 1 modal chi tiết — vòng này ta quyết định cụ thể trang nào, layout sao, trong dashboard nào (advertiser / publisher / admin).
>
> Nếu có design asset (Figma link, screenshot, Pencil mockup) thì load bây giờ — build sau sẽ reference trực tiếp thay vì đoán mò."

AI đề xuất pages/components từ decisions + endpoint notes:

```
AskUserQuestion:
  header: "Round 4 — UI/UX"
  question: |
    **Trang/view cần thiết:**

    | Trang | Dashboard | Component chính | Map sang endpoint |
    |-------|-----------|-----------------|-------------------|
    | {tên trang} | {advertiser/publisher/admin} | {component list} | GET/POST /api/... |

    Ví dụ đã điền:
    | Deals list | SSP Admin | DataTable, StatusBadge, FilterBar | GET /api/v1/deals |
    | Deal detail | SSP Admin | DealForm, ApprovalActions | GET /api/v1/deals/:id, PUT /api/v1/deals/:id/state |

    **Key component (những component mới cần build — không tính component đã tái dùng):**
    - `DealForm`: form tạo deal với validate floor CPM + creative spec
    - `ApprovalActions`: 2 nút Approve/Reject + modal nhập lý do nếu Reject

    **Design reference (mockup tham khảo):**
    - Nếu có ảnh/Figma link: paste đường dẫn hoặc reference `${PHASE_DIR}/design-*.png` — build sẽ load làm guide
    - Nếu chưa có: tôi sẽ suggest layout dựa trên component cùng dashboard đang có

    Câu trả lời: "ok" hoặc chỉnh ("trang X đặt trong dashboard Y, không phải Z vì...").
  (open text)
```

Lock UI COMPONENT NOTES embedded within existing decisions.

### Round 5 — Test Scenarios

**Conversational preamble (R9 rule):**

> "Vòng 5 (Test Scenarios — kịch bản kiểm thử) là vòng cuối: chốt **khi nào phase này coi là DONE thật**. Mỗi scenario mô tả một hành động cụ thể user làm + kết quả mong đợi. Review sau sẽ check từng cái chạy được chưa — nên càng quan sát được (observable) càng dễ verify.
>
> Quan trọng: đánh dấu scenario nào **automated** (Playwright tự verify được) vs **manual** (cần người thật bấm trong UAT — vd: CAPTCHA, payment UI thật, SMS OTP). Nếu label sai (manual mà gắn automated), review sẽ mark PASSED oan → bug lọt production."

```
AskUserQuestion:
  header: "Round 5 — Kịch bản kiểm thử"
  question: |
    AI đề xuất scenarios từ decision + endpoint + component đã chốt. Bạn review + chỉnh.

    **Happy path (luồng chính user làm thành công):**

    | ID | Kịch bản (user làm gì + expect gì) | Endpoint | Status + Output | Từ quyết định | Cách verify |
    |----|------------------------------------|----------|-----------------|---------------|-------------|
    | TS-01 | {user gõ gì, bấm gì, thấy gì} | POST /api/... | 201 + {field trả về} | D-{XX} | automated |
    | TS-02 | {user mở trang, xem gì} | GET /api/... | 200 + {list item} | D-{XX} | automated |

    Ví dụ đã điền:
    | TS-01 | DSP partner bấm "Create Deal", nhập publisher ID + floor CPM + creative, bấm Submit | POST /api/v1/deals | 201 + `{ id, state: 'pending' }` | D-03 | automated |
    | TS-02 | SSP Admin vào trang Deals, thấy deal vừa tạo ở đầu bảng với badge "Pending" | GET /api/v1/deals | 200 + list chứa deal mới | D-04 | automated |

    **Edge case (lỗi hoặc trường hợp bất thường):**

    | ID | Kịch bản | Expect | Cách verify |
    |----|----------|--------|-------------|
    | TS-{N} | {điều gì sai có thể xảy ra} | {error code + message cụ thể} | automated |

    Ví dụ đã điền:
    | TS-05 | DSP partner nhập floor CPM = -1 (số âm) | 400 + `{ error: 'floorCpm must be ≥ 0' }` | automated |
    | TS-06 | DSP partner tạo deal nhưng publisher ID không tồn tại | 404 + `{ error: 'publisher not found' }` | automated |

    **Mutation evidence (dữ liệu thay đổi, verify ở đâu):**

    | Hành động | Verify ở chỗ nào |
    |-----------|------------------|
    | Create deal | Deal mới xuất hiện trong list + DB (mongo collection `deals`) + trạng thái "pending" |
    | Approve deal | Badge đổi "Pending" → "Approved" + `state` trong DB đổi + updatedAt cập nhật |
    | Reject deal | Badge đổi "Rejected" + modal hỏi lý do đã save vào `reason` field |

    **v1.14.0+ Verification strategy** (bắt buộc per scenario):
    - `automated` — E2E/Playwright verify được (happy path thông thường)
    - `manual` — người phải click thử trong UAT (vd: CAPTCHA, SMS OTP, Stripe payment UI thật)
    - `fixture` — cần test fixture/seed (vd: stripe test keys, pre-loaded sample data)
    - `faketime` — phải tua thời gian (vd: TTL, cronjob, subscription renewal)

    Scenario nào KHÔNG phải `automated` sẽ được mark MANUAL ở review → codegen
    sinh skeleton `.skip()` → user điền ở /vg:accept. Ngăn giả trang PASSED cho
    scenario thực tế cần human/infra.

    Confirm, edit, or add more scenarios?
  (open text)
```

Lock TEST SCENARIO NOTES + (nếu có) `verification_strategy: manual|fixture|faketime` embedded within existing decisions dưới dạng:

```
**Test Scenarios:**
- TS-01: user adds credit card → card stored, charge works → expected 200 + receipt
  verification_strategy: manual   # Stripe Elements iframe không auto-fill được
- TS-02: subscription auto-renew sau 30 ngày → next billing cycle processed
  verification_strategy: faketime # cần tua 30 ngày
```

### Deep Probe Loop (mandatory — minimum 5 probes after Round 5)

**Purpose:** Rounds 1-5 capture the KNOWN decisions. This loop discovers what's UNKNOWN — gray areas, edge cases, implicit assumptions the AI made, conflicts between decisions.

**Rules:**
1. AI asks ONE focused question per turn, with its own recommendation
2. Do NOT ask "do you have anything else?" — AI drives the investigation, not user
3. Target minimum 10 total probes (5 structured rounds + 5+ deep probes)
4. User adds extra ideas in their answers — AI integrates and continues probing
5. Stop only when AI genuinely cannot find more gray areas (not when user seems done)

**Probe generation strategy — AI self-analyzes locked decisions for:**
```
- CONFLICTS: D-XX says "use Redis cache" but D-YY says "minimize infrastructure" → which wins?
- IMPLICIT ASSUMPTIONS: D-XX assumes "user is logged in" but login flow not in scope → clarify
- MISSING ERROR PATHS: D-XX defines happy path but not what happens on failure
- EDGE CASES: D-XX says "max 20 items" but what about exactly 20? Or migrating from >20?
- PERMISSION GAPS: endpoints have auth but role escalation not discussed
- DATA LIFECYCLE: create and read discussed but archive/purge/retention not
- CONCURRENCY: what if 2 users do the same thing simultaneously?
- MIGRATION: existing data compatibility with new schema
- PERFORMANCE: scaling implications of chosen approach
- SECURITY: input validation, rate limiting, injection risks for this specific phase
```

**Probe format:**
```
AskUserQuestion:
  header: "Deep Probe #{N}"
  question: |
    Analyzing decisions so far, I found a gray area:

    **{specific concern}**

    Context: {D-XX says this, but {what's unclear}}

    **My recommendation:** {AI's suggested resolution}

    Agree with recommendation, or different approach?
  (open text)
```

**After each answer:** Lock/update the affected decision. Generate next probe from remaining gray areas. Continue until:
- AI has probed at least 5 times after Round 5 (10 total interactions minimum)
- AND AI genuinely cannot identify more gray areas in the locked decisions

**When exhausted (no more gray areas):**
AI states: "I've analyzed all {N} decisions for conflicts, edge cases, and gaps. {M} gray areas resolved through probes. Proceeding to artifact generation."
→ Proceed to Step 2. No confirmation question needed — AI decides when scope is thorough enough.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 1_deep_discussion 2>/dev/null || true
```
</step>

<step name="2_artifact_generation">
## Step 2: ARTIFACT GENERATION

Write ONLY 2 files. No API-CONTRACTS.md, no TEST-GOALS.md, no PLAN.md.

### CONTEXT.md

Write to `${PHASE_DIR}/CONTEXT.md`:

```markdown
# Phase {N} — {Name} — CONTEXT

Generated: {ISO date}
Source: /vg:scope structured discussion (5 rounds)

## Decisions

**Namespace:** IDs are `P{phase}.D-XX` where `{phase}` = `${PHASE_NUMBER}` (this phase's identifier from ROADMAP). Example below uses phase 7.10.1 → IDs like `P7.10.1.D-01`. Substitute actual phase number when generating.

### P${PHASE_NUMBER}.D-01: {decision title}
**Category:** business | technical
**Decision:** {what was decided}
**Rationale:** {why}
**Endpoints:**
- POST /api/v1/{resource} (auth: {role}, purpose: {description})
- GET /api/v1/{resource} (auth: {role}, purpose: {description})
**UI Components:**
- {ComponentName}: {description of what it shows/does}
- {ComponentName}: {description}
**Test Scenarios:**
- TS-01: {user does X} -> {expected result}
- TS-02: {edge case} -> {expected error}
**Constraints:** {if any, else omit this line}

### P${PHASE_NUMBER}.D-02: {decision title}
**Category:** ...
...

{repeat for all decisions}

## Summary
- Total decisions: {N}
- Endpoints noted: {N}
- UI components noted: {N}
- Test scenarios noted: {N}
- Categories: {business: N, technical: N}

## Deferred Ideas
- {ideas captured during discussion but explicitly out of scope}
- {or "None" if no deferred ideas}
```

**Rules for CONTEXT.md:**
- Decisions MUST be numbered sequentially: `P{phase}.D-01`, `P{phase}.D-02`, ... (phase prefix MANDATORY — see namespace rule in command header)
- Every decision with endpoints MUST have at least 1 test scenario
- Endpoint format: `METHOD /path (auth: role, purpose: description)`
- UI component format: `ComponentName: description`
- Test scenario format: `TS-XX: action -> expected result`
- Omit empty sub-sections (e.g., if a technical decision has no endpoints, omit **Endpoints:** entirely)

**Write-strict gate (v1.9.0 T5 — HARD BLOCK):**
Before promoting `CONTEXT.md.staged` to `CONTEXT.md`, run the namespace validator:

```bash
# shellcheck disable=SC1091
source .claude/commands/vg/_shared/lib/namespace-validator.sh

STAGED="${PHASE_DIR}/CONTEXT.md.staged"
if ! validate_d_xx_namespace "$STAGED" "phase:${PHASE_NUMBER}"; then
  echo ""
  echo "⛔ Scope gate chặn: CONTEXT.md.staged còn chứa bare D-XX."
  echo "   Sửa bare D-XX thành P${PHASE_NUMBER}.D-XX trong file .staged, rồi chạy lại /vg:scope ${PHASE_NUMBER}."
  exit 1
fi
mv "$STAGED" "${PHASE_DIR}/CONTEXT.md"
```

The validator tolerates legacy `D-XX` inside fenced code blocks and blockquotes (cho phép example/migration docs). Live decisions outside code fences MUST use `P${PHASE_NUMBER}.D-XX`.

### DISCUSSION-LOG.md

**APPEND-ONLY.** If file already exists, append a new session block. Never overwrite existing content.

Append to `${PHASE_DIR}/DISCUSSION-LOG.md`:

```markdown
# Discussion Log — Phase {N}

## Session {ISO date} — {Initial Scope | Re-scope | Update}

### Round 1: Domain & Business
**Q:** {AI's question/analysis — abbreviated}
**A:** {user's response — full text}
**Locked:** D-01, D-02, D-03

### Round 2: Technical Approach
**Q:** {AI's analysis}
**A:** {user's response}
**Locked:** D-04, D-05

### Round 3: API Design
**Q:** {AI's endpoint suggestions}
**A:** {user's edits/confirmations}
**Locked:** Endpoint notes added to D-01, D-03, D-05

### Round 4: UI/UX
**Q:** {AI's component suggestions}
**A:** {user's response}
**Locked:** UI notes added to D-01, D-02

### Round 5: Test Scenarios
**Q:** {AI's scenario suggestions}
**A:** {user's response}
**Locked:** TS-01 through TS-{N}

### Loop: Additional Discussion
{if any additional rounds occurred, log them here}
{or omit this section if user chose "Done" after Round 5}
```

**If file already exists (re-scope):** Read existing content, then append new session with incremented session label. Preserve all previous sessions verbatim.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 2_artifact_generation 2>/dev/null || true
```
</step>

<step name="3_completeness_validation">
## Step 3: COMPLETENESS VALIDATION (automated)

Run automated checks on the generated CONTEXT.md.

**Check A — Endpoint Coverage (⛔ BLOCK if any gaps — tightened 2026-04-17):**
For every decision D-XX that has **Endpoints:** section, verify at least 1 test scenario references that endpoint. Downstream `blueprint.md` 2b5 parses these test scenarios to generate TEST-GOALS — missing coverage = orphan goals that fail phase-end binding gate.
Gap -> ⛔ BLOCK: "D-{XX} has endpoints but no test scenario covering them."

**Check B — Design Ref Coverage (WARN):**
If `config.design_assets` is configured, for every decision with **UI Components:** section, check if a design-ref exists in `${PHASE_DIR}/` or `config.design_assets.output_dir`.
Gap -> WARN: "D-{XX} has UI components but no design reference found. Consider running /vg:design-extract."

**Check C — Decision Completeness (⛔ BLOCK if gap ratio > 10% — tightened 2026-04-17):**
Compare SPECS.md in-scope items against CONTEXT.md decisions. Every in-scope item should map to at least 1 decision.
Gap -> ⛔ BLOCK if >10% of specs items lack decisions: "SPECS in-scope item '{item}' has no corresponding decision in CONTEXT.md." Downstream blueprint generates orphan tasks that have no decision trace → citation gate fails.

**Check D — Orphan Detection (WARN):**
Check for decisions that don't trace back to any SPECS.md in-scope item (potential scope creep).
Found -> WARN: "D-{XX} doesn't map to any SPECS in-scope item. Intentional addition or scope creep?"

**Report:**
```
Completeness Validation:
  Check A (endpoint coverage):  {PASS | ⛔ N blockers}
  Check B (design ref):         {PASS | N warnings | N/A (no design assets)}
  Check C (specs coverage):     {PASS | ⛔ N blockers (>10% ratio) | N warnings}
  Check D (orphan detection):   {PASS | N warnings}
```

**Implementation (v1.14.1+):** the 4 checks live in `.claude/scripts/vg_completeness_check.py`. Orchestrator runs:

```bash
ALLOW_INCOMPLETE_FLAG=""
if [[ "$ARGUMENTS" =~ --allow-incomplete ]]; then
  ALLOW_INCOMPLETE_FLAG="--allow-incomplete"
fi

PYTHONIOENCODING=utf-8 ${PYTHON_BIN} .claude/scripts/vg_completeness_check.py \
  --phase-dir "${PHASE_DIR}" ${ALLOW_INCOMPLETE_FLAG}
rc=$?

# rc=0 PASS  | rc=1 BLOCK  | rc=2 WARN only
case $rc in
  0) echo "✓ Completeness gate PASS" ;;
  2) echo "⚠ Completeness checks warn only — proceeding" ;;
  *)
    echo "⛔ Completeness gate FAILED. Resolve blockers before blueprint."
    echo "   Fix: /vg:scope ${PHASE_NUMBER}  (re-run discussion to add missing test scenarios / decisions)"
    echo "   Or:  edit CONTEXT.md manually, then /vg:blueprint ${PHASE_NUMBER} (blueprint re-validates)"
    exit 1
    ;;
esac
```

**Stemmed keyword match for Check C (v1.14.1+ FIX — addresses false negatives):**
Previous inline substring match missed inflections — "QPS throttling" (SPECS) vs "QPS throttle" (decision title). Script now stems both sides (strips -ing/-tion/-ed/-s/...) + applies prefix-tolerance match so "throttl" ↔ "throttle" count as same root. Reduces false-negative unmatched spec items.

Check B and D still WARN (softer signals). Check A and C are structural — block downstream errors.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 3_completeness_validation 2>/dev/null || true
```
</step>

<step name="4_crossai_review">
## Step 4: CROSSAI REVIEW (config-driven, explicit enforcement)

**v2.5.2.9+ enforcement** — AI KHÔNG được silent skip. Bash block dưới đây bắt buộc chạy trước prose CrossAI invocation.

```bash
# ─────────────────────────────────────────────────────────────────────────
# Explicit skip enforcement (v2.5.2.9)
# Previously this step had prose "Skip if $SKIP_CROSSAI or empty crossai_clis"
# and AI could silently fall through — scope CrossAI bị skip HOÀN TOÀN qua
# 3 phase liên tiếp (7.14/7.15/7.16) với 0 events ghi nhận.
# Now: explicit bash check → shared guard helper → emit event or block.
# ─────────────────────────────────────────────────────────────────────────

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-skip-guard.sh" 2>/dev/null || {
  echo "⚠ crossai-skip-guard.sh missing — không enforce được skip audit trail" >&2
}

SKIP_CAUSE=$(crossai_detect_skip_cause "${ARGUMENTS:-}" ".claude/vg.config.md" 2>/dev/null || echo "")

if [ -n "$SKIP_CAUSE" ]; then
  REASON_TEXT="scope CrossAI skip cho phase ${PHASE_NUMBER} (args=${ARGUMENTS:-none})"
  if ! crossai_skip_enforce "vg:scope" "$PHASE_NUMBER" "scope.4_crossai_review" \
       "$SKIP_CAUSE" "$REASON_TEXT"; then
    echo "⛔ Guard chặn skip — exit. Chạy lại không có --skip-crossai hoặc đổi reason." >&2
    exit 1
  fi
  # Skip allowed — mark marker + exit step. Không chạy CrossAI invocation bên dưới.
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 4_crossai_review 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/4_crossai_review.done"
  # Use return nếu step được source từ orchestrator, else bash 'return' ngoài function fails
  # → dùng exit 0 khi no parent function, else return 0
  return 0 2>/dev/null || exit 0
fi

echo "▸ CrossAI scope review starting — phase ${PHASE_NUMBER}"
echo "  AI thứ 2 sẽ review SPECS + CONTEXT decisions để bắt drift/contradiction."
echo "  Kết quả → ${PHASE_DIR}/crossai/result-*.xml + event crossai.verdict."
```

Prepare context file at `${VG_TMP}/vg-crossai-${PHASE_NUMBER}-scope-review.md`:

```markdown
# CrossAI Scope Review — Phase {PHASE_NUMBER}

Review the discussion output. Find gaps between SPECS requirements and CONTEXT decisions.

## Checklist
1. Every SPECS in-scope item has a corresponding CONTEXT decision
2. No CONTEXT decision contradicts a SPECS constraint
3. Success criteria achievable given decisions
4. No critical ambiguity unresolved
5. Out-of-scope items not accidentally addressed (scope creep)
6. Endpoint notes are complete (method, auth, purpose)
7. Test scenarios cover happy path AND edge cases for every endpoint

## Verdict Rules
- pass: coverage >=90%, no critical findings, score >=7
- flag: coverage >=70%, no critical findings, score >=5
- block: coverage <70%, OR any critical finding, OR score <5

## Artifacts
---
[SPECS.md full content]
---
[CONTEXT.md full content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="scope-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

**Handle results:**
- **Minor findings:** Log only, no action needed.
- **Major/Critical findings:** Present table to user:
  ```
  | # | Finding | Severity | CLI Source | Action |
  |---|---------|----------|------------|--------|
  | 1 | {issue} | major | Codex+Gemini | Re-discuss / Note / Ignore |
  ```
  For each major/critical finding:
  ```
  AskUserQuestion:
    header: "CrossAI Finding"
    question: "{finding description}"
    options:
      - "Re-discuss — open additional round to address this"
      - "Note — acknowledge and add to CONTEXT.md deferred section"
      - "Ignore — false positive, skip"
  ```
  If "Re-discuss" -> open free-form round focused on that finding, then re-run validation (Step 3) on updated CONTEXT.md.
  If "Note" -> append to CONTEXT.md ## Deferred Ideas section.
  If "Ignore" -> log in DISCUSSION-LOG.md as "CrossAI finding ignored: {reason}".

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 4_crossai_review 2>/dev/null || true
```
</step>

<step name="4_5_bootstrap_reflection">
## Step 4.5: End-of-Step Reflection (v1.15.0 Bootstrap Overlay)

Before committing scope artifacts, spawn reflector to analyze this step's
CONTEXT.md + DISCUSSION-LOG.md + user messages for learnings.

**Skip silently if `.vg/bootstrap/` absent.** Per `.claude/commands/vg/_shared/reflection-trigger.md`:

```bash
if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="scope"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 Running end-of-scope reflection..."
  # Spawn Agent (Haiku) with vg-reflector skill per reflection-trigger.md protocol
  # After: if REFLECT_OUT has candidates, show interactive y/n/e/s prompt
  # User 'y' → delegate to /vg:learn --promote L-{id}
fi
```

See `.claude/commands/vg/_shared/reflection-trigger.md` for full spawn template and interactive flow.

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 4_5_bootstrap_reflection 2>/dev/null || true
```
</step>

<step name="5_commit_and_next">
## Step 5: Commit + suggest next

**Update PIPELINE-STATE.json:** Set `steps.scope.status = "done"`, `steps.scope.finished_at = {now}`, `last_action = "scope: {N} decisions, {M} endpoints, {K} test scenarios"`.

```bash
# Count from CONTEXT.md — supports both new P{phase}.D-XX and legacy D-XX headers
DECISION_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")
ENDPOINT_COUNT=$(grep -c '^\- .* /api/' "${PHASE_DIR}/CONTEXT.md" || echo 0)
TEST_SCENARIO_COUNT=$(grep -c '^\- TS-' "${PHASE_DIR}/CONTEXT.md" || echo 0)

git add "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/DISCUSSION-LOG.md" "${PHASE_DIR}/PIPELINE-STATE.json"
git commit -m "scope(${PHASE_NUMBER}): ${DECISION_COUNT} decisions, ${ENDPOINT_COUNT} endpoints, ${TEST_SCENARIO_COUNT} test scenarios"

# v2.2: mark final step + emit completion event + invoke run-complete.
# Orchestrator runs phase-exists + context-structure validators, emits
# run.completed or run.blocked based on contract check. No bash catch-up
# needed — individual steps mark as they finish (see _mark calls above).
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 5_commit_and_next 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "scope.completed" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"decisions\":${DECISION_COUNT},\"endpoints\":${ENDPOINT_COUNT},\"scenarios\":${TEST_SCENARIO_COUNT}}" >/dev/null

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
  echo "⛔ scope run-complete BLOCK — review orchestrator output + fix before /vg:blueprint" >&2
  exit $RUN_RC
fi
```

**Display summary:**
```
Scope complete for Phase {N}.
  Decisions: {N} ({business} business, {technical} technical)
  Endpoints: {M} noted
  UI Components: {K} noted
  Test Scenarios: {J} noted
  CrossAI: {verdict} ({score}/10) | skipped
  Validation: {pass_count}/4 checks passed, {warn_count} warnings

  Next: /vg:blueprint {phase}
```
</step>

</process>

<success_criteria>
- SPECS.md was read and all in-scope items are mapped to decisions
- 5 structured rounds completed (Round 4 skipped only for non-UI profiles)
- CONTEXT.md created with enriched decisions (endpoints, UI components, test scenarios per decision)
- DISCUSSION-LOG.md appended with full Q&A trail for this session
- Completeness validation ran (4 checks) and warnings surfaced
- CrossAI gap review ran (or skipped if flagged/no CLIs)
- All artifacts committed to git
- PIPELINE-STATE.json updated
- Next step guidance shows /vg:blueprint
</success_criteria>
