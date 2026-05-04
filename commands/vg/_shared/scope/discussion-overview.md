# scope discussion-overview (STEP 2)

> 5 structured rounds + Deep Probe Loop. Each round: AI presents
> recommendation, user confirms/edits/expands; per-answer challenger;
> per-round expander. Then advance.

<HARD-GATE>
You MUST execute all 5 rounds + Deep Probe in order. This file is the
START of STEP 2 and MUST emit `step-active 1_deep_discussion` BEFORE
loading sources / running rounds (Critical-4 r2 fix — was previously
fired only at the end of STEP 2 inside `discussion-deep-probe.md`,
leaving the 5 rounds + deep probe untracked). The deep-probe ref keeps
the matching `mark-step 1_deep_discussion` at STEP 2 END.

For EACH user answer in EACH round you MUST invoke per-answer challenger
(see §A) AND per-round expander at round end (see §B). Skipping is
adversarial-suppression risk and was blocked by Codex consensus.

Subagent type is `general-purpose` (NOT a custom `vg-*` type) — Claude
Agent tool only resolves registered subagent types.
</HARD-GATE>

## Step active (BEGIN of STEP 2 — Critical-4 r2 fix)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 1_deep_discussion
```

The matching `mark-step 1_deep_discussion` fires at STEP 2 END inside
`discussion-deep-probe.md` (single-owner pattern preserved).

## Sources (load once at top of STEP 2)

```bash
source commands/vg/_shared/lib/answer-challenger.sh        # exports challenge_answer, challenger_dispatch, challenger_count_for_phase, challenger_record_user_choice, challenger_is_trivial
source commands/vg/_shared/lib/dimension-expander.sh       # exports expand_dimensions, expander_dispatch
source commands/vg/_shared/lib/bootstrap-inject.sh         # exports vg_bootstrap_render_block, vg_bootstrap_emit_fired
```

Read `commands/vg/_shared/bug-detection-guide.md` once. Apply 6 detection patterns throughout discussion: schema_violation, helper_error, user_pushback, ai_inconsistency, gate_loop, self_discovery. When a pattern is detected, narrate intent + call `report_bug` via bash + continue (non-blocking).

## Round loop (5 fixed + Deep Probe)

For ROUND in 1..5:
1. Read `_shared/scope/discussion-round-${ROUND}-<topic>.md` and follow it.
2. After EACH user answer, invoke per-answer challenger (see pattern §A below).
3. After ALL answers in the round, invoke per-round expander (§B).
4. Advance to next round.

After R5 completes: Read `_shared/scope/discussion-deep-probe.md` and run mandatory minimum 5 probes.

## §A. Per-answer challenger pattern (re-used in EVERY round)

```bash
PROMPT=$(bash commands/vg/_shared/lib/vg-challenge-answer-wrapper.sh \
         "$user_answer" "round-${ROUND}" "phase-scope" "$accumulated_draft")
wrapper_rc=$?
case $wrapper_rc in
  0)  ;;  # success — PROMPT contains content
  2)  echo "↷ Trivial answer — skip challenger"; PROMPT="" ;;
  *)  echo "⚠ challenger wrapper failed rc=$wrapper_rc" >&2; PROMPT="" ;;
esac

if [ -n "$PROMPT" ]; then
  # Inject bootstrap rules (promoted L-IDs) into prompt
  BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope")
  vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "scope" "${PHASE_NUMBER}"
  PROMPT="${PROMPT}

<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>"

  bash scripts/vg-narrate-spawn.sh scope-challenger spawning "round-${ROUND} answer-${ANSWER_N}"
fi
```

Then in AI runtime (only if `$PROMPT` non-empty):

`Agent(subagent_type="general-purpose", model="opus", prompt=<PROMPT>)`

On success return:

```bash
bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"
challenger_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
```

On Agent error (subagent crash / timeout / non-JSON output) — R6 Task 8 fail-closed:

```bash
bash scripts/vg-narrate-spawn.sh scope-challenger failed "round-${ROUND} answer-${ANSWER_N} — <error one-liner>"

# Emit telemetry — challenger crash is a real signal, not noise
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "scope.challenger_crashed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"round\":\"${ROUND}\",\"answer_n\":\"${ANSWER_N}\",\"reason\":\"<error>\"}" \
  >/dev/null 2>&1 || true

# Append to DISCUSSION-LOG.md for audit trail
echo "challenger crashed: <reason>" >> "${PHASE_DIR}/DISCUSSION-LOG.md"

# Fail-closed: BLOCK unless --skip-challenger-crash override + reason provided.
# Anti-rationalization purpose: silent skip means a real adversarial-check
# gap goes undetected. If challenger crashed BECAUSE of a real issue with
# the answer, treating it as no-issue defeats the guard's reason for being.
if [[ "$ARGUMENTS" =~ --skip-challenger-crash ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-challenger-crash requires --override-reason=<text>" >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    "--flag=--skip-challenger-crash" \
    "--reason=Scope challenger crashed at round ${ROUND} answer ${ANSWER_N} (phase ${PHASE_NUMBER})" \
    >/dev/null 2>&1 || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "--skip-challenger-crash" "${PHASE_NUMBER}" "scope.discussion" \
      "Challenger crash skipped at round ${ROUND}" "scope-challenger-crashed"
  echo "⚠ --skip-challenger-crash set — proceeding, debt logged"
  # Continue to next answer (skip the challenger result for this answer)
else
  echo "⛔ Challenger crashed at round ${ROUND} answer ${ANSWER_N}." >&2
  echo "   Anti-rationalization guard requires explicit acknowledgment." >&2
  echo "   Fix options:" >&2
  echo "     1. Investigate crash cause (check logs in .vg/blocks/)" >&2
  echo "     2. Re-run /vg:scope to retry" >&2
  echo "     3. Skip with: --skip-challenger-crash --override-reason=\"<ticket>\"" >&2
  exit 1
fi
```

If `has_issue=true` → AskUserQuestion (3 options):
- **Address** → re-enter Q for that round, merge user's revised answer
- **Acknowledge** → record under `## Acknowledged tradeoffs` in CONTEXT.md.staged
- **Defer** → record under `## Open questions` in CONTEXT.md.staged

Then:

```bash
challenger_record_user_choice "${PHASE_NUMBER}" "round-${ROUND}" "phase-scope" "$choice"
```

Loop guard: if `challenger_count_for_phase` ≥ `${config.scope.adversarial_max_rounds:-3}`, helper auto-skips remaining (no manual gate).

**Rapid-prototyping disable** (config-level, not per-round): set `config.scope.adversarial_check: false` in `.claude/vg.config.md` to fully disable challenger across all rounds. Trivial answers (Y/N, single-word) already auto-skip via `challenger_is_trivial` (helper-internal) — wrapper returns rc=2.

## §B. Per-round expander pattern (re-used at EVERY round end)

After ALL answers + challengers in a round are done, BEFORE advancing:

```bash
PROMPT=$(bash commands/vg/_shared/lib/vg-expand-round-wrapper.sh \
         "${ROUND}" "${ROUND_TOPIC}" "${round_qa_accumulated}" "${PLANNING_DIR}/FOUNDATION.md")
bash scripts/vg-narrate-spawn.sh scope-expander spawning "round-${ROUND}"
```

`Agent(subagent_type="general-purpose", model="opus", prompt=<PROMPT>)`

On success return:

```bash
bash scripts/vg-narrate-spawn.sh scope-expander returned "<critical:N nice:M>"
expander_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
```

On Agent error (subagent crash / timeout / non-JSON output) — R6 Task 8 fail-closed:

```bash
bash scripts/vg-narrate-spawn.sh scope-expander failed "round-${ROUND} — <error one-liner>"

# Emit telemetry — expander crash is a real signal, not noise
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "scope.expander_crashed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"round\":\"${ROUND}\",\"reason\":\"<error>\"}" \
  >/dev/null 2>&1 || true

# Append to DISCUSSION-LOG.md for audit trail
echo "expander crashed: <reason>" >> "${PHASE_DIR}/DISCUSSION-LOG.md"

# Fail-closed: BLOCK unless --skip-expander-crash override + reason provided.
# Anti-rationalization purpose: silent "no critical_missing" assumption on
# crash defeats the dimension-expansion guard. If expander crashed because
# the round is structurally incomplete, advancing silently buries the gap.
if [[ "$ARGUMENTS" =~ --skip-expander-crash ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-expander-crash requires --override-reason=<text>" >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
    "--flag=--skip-expander-crash" \
    "--reason=Scope expander crashed at round ${ROUND} (phase ${PHASE_NUMBER})" \
    >/dev/null 2>&1 || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "--skip-expander-crash" "${PHASE_NUMBER}" "scope.discussion" \
      "Expander crash skipped at round ${ROUND}" "scope-expander-crashed"
  echo "⚠ --skip-expander-crash set — proceeding, debt logged"
  # Advance to next round (skip the expander result for this round)
else
  echo "⛔ Expander crashed at round ${ROUND}." >&2
  echo "   Anti-rationalization guard requires explicit acknowledgment." >&2
  echo "   Fix options:" >&2
  echo "     1. Investigate crash cause (check logs in .vg/blocks/)" >&2
  echo "     2. Re-run /vg:scope to retry" >&2
  echo "     3. Skip with: --skip-expander-crash --override-reason=\"<ticket>\"" >&2
  exit 1
fi
```

If `critical_missing[]` non-empty → AskUserQuestion (3 options):
- **Address critical** → re-enter round appending each CRITICAL dimension as new Q, merge user's new answers
- **Acknowledge** → append dimensions under `## Acknowledged gaps` in CONTEXT.md.staged
- **Defer** → append under `## Open questions` for blueprint to re-raise

Loop guard: `${config.scope.dimension_expand_max:-6}` (default 6 = 5 rounds + 1 deep probe) — helper skips after limit.

**Rapid-prototyping disable**: set `config.scope.dimension_expand_check: false` in `.claude/vg.config.md` to disable expander across all rounds. Unlike challenger, expander runs ONCE per round (not per-answer) — cost bounded.

## §C. Decision lock pattern (every round)

When user confirms a round answer, lock decisions:

```
### P${PHASE_NUMBER}.D-XX: <decision title>
**Category:** <business|technical|api|ui|test>
**Decision:** <text>
**Rationale:** <why>
**Quote source:** DISCUSSION-LOG.md#round-${ROUND}
endpoints:        # only for api category
  - METHOD /path — purpose
ui_components:    # only for ui category
  - <component> — purpose
test_scenarios:   # only for test category
  - TS-XX: <scenario>
```

Namespace enforcement: ALWAYS prefix `P${PHASE_NUMBER}.` (e.g. `P3.2.D-01`). Bare `D-XX` is LEGACY and blocked by commit-msg hook from v1.10.1.

Do NOT write CONTEXT.md inside discussion rounds — staged only. STEP 4 (`artifact-write.md`) does the atomic file write.

## §D. Advance after Deep Probe

After R5 + Deep Probe completes (no manual gate — Deep Probe ref enforces min-5),
the **deep-probe ref** is the sole owner of the `1_deep_discussion` marker
(Critical-3 fix: removed duplicate mark-step that previously fired here).

Proceed to STEP 3 — Read `_shared/scope/env-preference.md`.
