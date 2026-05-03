# test codegen (STEP 5 — HEAVY, subagent)

HEAVY step. You MUST delegate goal-based test generation to
`vg-test-codegen` subagent (tool name `Agent`, not `Task`).

<HARD-GATE>
DO NOT generate Playwright test files inline. DO NOT run codegen logic
in the main agent.

You MUST spawn `vg-test-codegen` for step 5d_codegen. The subagent:
- Runs goal-status-aware codegen (READY/MANUAL/DEFERRED/INFRA_PENDING gates)
- Applies fixture inject (RFC v9 post-generation pass)
- Runs binding verification (`verify-goal-test-binding.py`) — L1/L2 gate
- Handles R7 console monitoring enforcement
- Handles adversarial coverage gate

Skipping requires `--skip-codegen` + override-debt log.
</HARD-GATE>

---

## Orchestration order

1. **Pre-spawn**: `vg-orchestrator step-active 5d_codegen`. Validate inputs
   (goals via vg-load, RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md). Detect
   mobile branch.
2. **Spawn**: `Agent(subagent_type="vg-test-codegen", prompt=<from delegation.md>)`
3. **Post-spawn validation**: parse JSON return, check spec_files + bindings_satisfied.
4. **L2 escalation**: if `l2_escalations` non-empty, invoke `AskUserQuestion`
   per escalation, collect user resolution, re-spawn for affected goals.
5. **Mobile branch** (if `PHASE_PROFILE=mobile-*`): read `mobile-codegen.md`
   and execute `5d_mobile_codegen`.
6. **Deep-probe hand-off** (if `DEEP_PROBE_ENABLED=true`): read `deep-probe.md`
   and execute `5d_deep_probe` (UNCHANGED, orchestrator-side).
7. **Mark step 5d_codegen**.

---

## STEP 5.1 — pre-spawn checklist

```bash
vg-orchestrator step-active 5d_codegen

# Inject rule cards (harness v2.6.1)
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/inject-rule-cards.sh" && \
  inject_rule_cards "vg-test" "5d_codegen" 2>&1 || true

# Verify RUNTIME-MAP.json (written by /vg:review)
[ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || {
  echo "⛔ RUNTIME-MAP.json missing — run /vg:review ${PHASE_NUMBER} first."
  exit 1
}

# Verify GOAL-COVERAGE-MATRIX.md (written by /vg:review)
[ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ] || {
  echo "⛔ GOAL-COVERAGE-MATRIX.md missing — run /vg:review ${PHASE_NUMBER} first."
  exit 1
}

# Ensure generated tests dir exists
mkdir -p "${GENERATED_TESTS_DIR:-apps/web/e2e/generated/${PHASE_NUMBER}}" 2>/dev/null

# Discover goal IDs via vg-load --list (cheap index), then slice ONE goal at a
# time via `vg-load --goal G-NN` for the subagent. NEVER cat flat TEST-GOALS.md
# for AI/codegen consumption — per-goal slice keeps subagent context bounded
# and lets the binding gate cite stable goal-id paths. See review-v2 D1/D2.
GOAL_INDEX=$(vg-load --phase "${PHASE_NUMBER}" --artifact goals --list 2>/dev/null)
if [ -z "$GOAL_INDEX" ]; then
  echo "⛔ vg-load --list returned empty — run /vg:blueprint ${PHASE_NUMBER} first."
  exit 1
fi
GOAL_IDS=$(echo "$GOAL_INDEX" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(' '.join(g.get('id','') for g in d.get('goals',[]) if g.get('id')))" 2>/dev/null)
GOAL_COUNT=$(echo "$GOAL_IDS" | wc -w | tr -d ' ')
[ "$GOAL_COUNT" -gt 0 ] || { echo "⛔ no goal ids parsed from vg-load --list"; exit 1; }

# Pre-fetch each goal's slice once into VG_TMP — subagent reads slice files
# (per-goal vg-load --goal output), never the flat TEST-GOALS.md.
VG_TMP_DIR="${VG_TMP:-${PHASE_DIR}/.vg-tmp}"
mkdir -p "${VG_TMP_DIR}/goals" 2>/dev/null
for GID in $GOAL_IDS; do
  vg-load --phase "${PHASE_NUMBER}" --artifact goals --goal "$GID" \
    > "${VG_TMP_DIR}/goals/${GID}.json" 2>/dev/null || true
done
echo "✓ Goals sliced via vg-load --goal: ${GOAL_COUNT} goal(s) in ${VG_TMP_DIR}/goals/"

# Detect mobile branch
case "${PHASE_PROFILE:-feature}" in
  mobile-*) IS_MOBILE=true ;;
  *) IS_MOBILE=false ;;
esac
echo "ℹ Profile=${PHASE_PROFILE}, is_mobile=${IS_MOBILE}"

# Session-reuse setup (P17 D-04/D-05)
E2E_DIR=""
for candidate in "apps/web/e2e" "e2e" "tests/e2e"; do
  if [ -d "${REPO_ROOT}/${candidate}" ]; then
    E2E_DIR="${REPO_ROOT}/${candidate}"
    break
  fi
done

if [ -n "$E2E_DIR" ] && [ "$IS_MOBILE" = "false" ]; then
  GS_DST="${E2E_DIR}/global-setup.ts"
  GS_SRC="${REPO_ROOT}/.claude/commands/vg/_shared/templates/playwright-global-setup.template.ts"
  if [ ! -f "$GS_DST" ] && [ -f "$GS_SRC" ]; then
    cp "$GS_SRC" "$GS_DST"
    echo "✓ P17 D-04: copied global-setup.ts to ${GS_DST}"
  fi
  STORAGE_PATH=$(awk '/^test:/{f=1; next} f && /^[a-z_]/{f=0} f && /storage_state_path:/{print $2; exit}' "${REPO_ROOT}/vg.config.md" 2>/dev/null | tr -d '"')
  export VG_STORAGE_STATE_PATH="${STORAGE_PATH:-apps/web/e2e/.auth/}"
  GITIGNORE="${REPO_ROOT}/.gitignore"
  STORAGE_REL="${VG_STORAGE_STATE_PATH%/}"
  if [ -f "$GITIGNORE" ] && ! grep -qF "${STORAGE_REL}/" "$GITIGNORE"; then
    printf '\n# Phase 17 D-04 — Playwright auth storage state\n%s/\n' "${STORAGE_REL}" >> "$GITIGNORE"
    echo "✓ P17 D-04: appended ${STORAGE_REL}/ to .gitignore"
  fi
fi
```

---

## STEP 5.2 — spawn vg-test-codegen

Read `codegen/delegation.md` for the full prompt template. **MANDATORY**:
emit colored-tag narration before + after the spawn (per vg-meta-skill).

```bash
bash scripts/vg-narrate-spawn.sh vg-test-codegen spawning \
  "phase ${PHASE_NUMBER} codegen (${GOAL_COUNT} goals, profile=${PHASE_PROFILE})"
```

Then call:
```
Agent(subagent_type="vg-test-codegen", prompt=<rendered template>)
```

### Codex runtime spawn path

If the runtime is Codex, apply
`commands/vg/_shared/codex-spawn-contract.md` instead of calling the
Claude-only `Agent(...)` syntax:

1. Render `codegen/delegation.md` into
   `${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-test-codegen.prompt.md`.
2. Run `codex-spawn.sh --tier executor --sandbox workspace-write
   --spawn-role vg-test-codegen --spawn-id vg-test-codegen` with
   `--out ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-test-codegen.json`.
3. Set `SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"` and run STEP 5.3 unchanged.
4. Treat missing helper, missing Codex CLI, non-zero exit, empty output,
   malformed JSON, missing spec files, or `bindings_satisfied=MISSING` as a
   HARD BLOCK.

Do NOT generate Playwright specs inline on Codex.

The subagent writes:
- `${GENERATED_TESTS_DIR}/{phase}-goal-{group}.spec.ts` (READY goals)
- `${GENERATED_TESTS_DIR}/auto-{goal-id-slug}.spec.ts` (G-AUTO-* / G-CRUD-* skeletons)
- Skeleton `.skip()` specs for MANUAL / INFRA_PENDING goals
- DEFERRED goals skipped (no file)

Returns JSON with spec_files, bindings_satisfied, l1_resolved_count, l2_escalations,
warnings.

```bash
bash scripts/vg-narrate-spawn.sh vg-test-codegen returned \
  "codegen + binding gate complete"
```

If subagent error JSON or empty output:
```bash
bash scripts/vg-narrate-spawn.sh vg-test-codegen failed "<one-line cause>"
```

---

## STEP 5.3 — post-spawn validation

```bash
# spec_files must be non-empty array
SPEC_COUNT=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('spec_files',[])))" 2>/dev/null || echo 0)

[ "${SPEC_COUNT:-0}" -gt 0 ] || {
  echo "⛔ vg-test-codegen returned no spec_files."
  echo "   Re-spawn or check delegation.md input contract."
  exit 1
}

# bindings_satisfied must be present
BINDINGS=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('bindings_satisfied','MISSING'))" 2>/dev/null || echo "MISSING")
[ "$BINDINGS" != "MISSING" ] || {
  echo "⛔ vg-test-codegen did not return bindings_satisfied."
  exit 1
}

echo "✓ Output validated: ${SPEC_COUNT} spec file(s), bindings=${BINDINGS}"

# Emit telemetry
type -t emit_telemetry_v2 >/dev/null 2>&1 && \
  emit_telemetry_v2 "test_5d_codegen" "${PHASE_NUMBER}" \
    "test.5d_codegen" "codegen" "PASS" \
    "{\"specs\":${SPEC_COUNT}}" \
  2>/dev/null || true
```

---

## STEP 5.4 — L2 escalation handler

If the subagent returns `l2_escalations` (non-empty array), the binding gate
could not self-resolve at L1 for one or more goals. The main agent handles
L2 via `AskUserQuestion` — do NOT ignore or auto-skip.

```bash
L2_COUNT=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('l2_escalations',[])))" 2>/dev/null || echo 0)

if [ "${L2_COUNT:-0}" -gt 0 ]; then
  echo ""
  echo "━━━ L2 binding escalations — ${L2_COUNT} goal(s) need architect resolution ━━━"

  # For each L2 escalation: extract proposal text, ask user
  L2_ITEMS=$(echo "${SUBAGENT_OUTPUT}" | ${PYTHON_BIN:-python3} -c "
import json, sys
d = json.load(sys.stdin)
for item in d.get('l2_escalations', []):
    print(f\"{item['goal_id']}||{item['architect_proposal']}||{item.get('evidence','')}\")
" 2>/dev/null)

  while IFS='||' read -r GOAL_ID PROPOSAL EVIDENCE; do
    [ -z "$GOAL_ID" ] && continue
    echo ""
    echo "⚠ L2 escalation: ${GOAL_ID}"
    echo "   Architect proposal: ${PROPOSAL}"
    [ -n "$EVIDENCE" ] && echo "   Evidence: ${EVIDENCE}"

    # AskUserQuestion — routes to user for resolution
    # (L3 per plan: user provides binding resolution or waiver)
    USER_RESOLUTION=$(AskUserQuestion \
      "Goal ${GOAL_ID} has unresolved binding. Architect proposes: ${PROPOSAL}. How should this be resolved? Options: (a) accept proposal, (b) skip goal for this phase, (c) provide alternative spec path.")

    echo "ℹ User resolved ${GOAL_ID}: ${USER_RESOLUTION}"

    # Re-spawn subagent for affected goal with resolution in prompt
    bash scripts/vg-narrate-spawn.sh vg-test-codegen spawning \
      "re-codegen ${GOAL_ID} with L2 resolution"
    # Agent(subagent_type="vg-test-codegen", prompt=<delegation.md + L2_RESOLUTION=${USER_RESOLUTION}, AFFECTED_GOALS=${GOAL_ID}>)
    bash scripts/vg-narrate-spawn.sh vg-test-codegen returned \
      "re-codegen ${GOAL_ID} complete"

  done <<< "$L2_ITEMS"
fi
```

---

## STEP 5.5 — mobile branch hand-off

If `IS_MOBILE=true`, after the web subagent returns (or instead, if mobile-only),
execute mobile codegen:

```bash
if [ "$IS_MOBILE" = "true" ]; then
  echo ""
  echo "━━━ Mobile profile detected — executing 5d_mobile_codegen ━━━"
  # Read mobile-codegen.md and execute (orchestrator-side, not a subagent)
  # This ref is at: commands/vg/_shared/test/codegen/mobile-codegen.md
fi
```

---

## STEP 5.6 — deep-probe hand-off

After codegen (and mobile codegen if applicable), execute deep-probe:

```bash
echo ""
echo "━━━ 5d_deep_probe — edge-case variants (UNCHANGED behavior) ━━━"
# Read deep-probe.md and execute (orchestrator-side, Sonnet+adversarial).
# This ref is at: commands/vg/_shared/test/codegen/deep-probe.md
# Executes AFTER codegen complete regardless of profile.
```

---

## STEP 5.7 — mark 5d_codegen

After all sub-steps complete (subagent return validated, L2 resolved, mobile
and deep-probe hands-off done):

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && \
  mark_step "${PHASE_NUMBER:-unknown}" "5d_codegen" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/5d_codegen.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator \
  mark-step test 5d_codegen 2>/dev/null || true
```

Note: `5d_binding_gate` is NOT marked at orchestrator level — it is internal
to the `vg-test-codegen` subagent. `5d_deep_probe` and `5d_mobile_codegen`
are marked inside their respective orchestrator-side ref steps.

After marker touched, return to test.md entry skill → STEP 6 (regression).
