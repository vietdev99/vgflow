# Scope deep discussion overview (STEP 2 entry)

> 5 structured rounds + Deep Probe Loop. Each round: AI presents
> recommendation, user confirms/edits/expands; per-answer challenger;
> per-round expander. Then advance.

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

On return:

```bash
bash scripts/vg-narrate-spawn.sh scope-challenger returned "<verdict>"
challenger_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
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

On return:

```bash
bash scripts/vg-narrate-spawn.sh scope-expander returned "<critical:N nice:M>"
expander_dispatch "$subagent_json" "round-${ROUND}" "phase-scope" "${PHASE_NUMBER}"
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

## §D. Mark step at end of STEP 2

After R5 + Deep Probe completes (no manual gate — Deep Probe ref enforces min-5):

```bash
vg-orchestrator mark-step scope 1_deep_discussion
```

Proceed to STEP 3 — Read `_shared/scope/env-preference.md`.
