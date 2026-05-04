# review verdict — overview (STEP 7 — inline split, NO subagent)

Single step `phase4_goal_comparison` covers Phase 4 — the final
goal-vs-runtime verdict synthesis that produces GOAL-COVERAGE-MATRIX.md
+ the 100% gate decision.

## Why no subagent

Audit (item #12 DOWNGRADED) confirmed `phase4_goal_comparison` has NO
weighted formula. Logic is binary RUNTIME-MAP lookup (READY | BLOCKED |
UNREACHABLE | INFRA_PENDING per goal). Subagent overhead not warranted;
complexity comes from branching + surface probe routing, not formula.

## Branching

Read this file to dispatch into one of the 3 sub-refs:

```
if UI_GOAL_COUNT == 0:
    # Pure backend phase — surface probes only, no browser RUNTIME-MAP needed
    Read pure-backend-fastpath.md
elif PROFILE in {"web-fullstack", "web-frontend-only"}:
    # Mixed UI + backend goals — full Phase 4 pipeline with surface probes
    Read web-fullstack.md
else:
    # web-backend-only / mobile-* / cli-tool / library / docs / migration
    Read profile-branches.md
```

`UI_GOAL_COUNT` is computed from TEST-GOALS.md `**Surface:** ui` rows
(case-sensitive match per the bash in `web-fullstack.md` step 4a).
`PROFILE` is set by preflight `0_parse_and_validate` (env var
`$PHASE_PROFILE`).

<HARD-GATE>
You MUST execute step 4.0 (RCRURD runtime verification) BEFORE branching
into a sub-ref. RCRURD walks every TEST-GOALS/G-NN.md with
`goal_type: mutation`, runs the runtime gate, and BLOCKs review on
assertion fail (R8 update_did_not_apply, etc).

You MUST NOT skip the matrix-merger + invariants gates in step 4c. The
8 invariant validators (verify-interface-standards, verify-goal-security,
verify-goal-perf, verify-security-baseline, verify-haiku-scan-completeness,
verify-runtime-map-coverage, verify-crud-runs-coverage,
verify-error-message-runtime) run on every full-mode review unless
`--skip-content-invariants="<reason>"` is set (logs OVERRIDE-DEBT).

You MUST NOT defer NOT_SCANNED goals to /vg:test (step 4c-pre rule). Test
codegen reads `goal_sequences[]` from RUNTIME-MAP — NOT_SCANNED = no
input. Resolve to one of {READY | BLOCKED | UNREACHABLE | INFRA_PENDING}
before exiting Phase 4.

vg-load convention: per-goal context loading inside step 4a (when
classifying surface or running fallback generation) should call
`vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical`
for the priority sweep, then `--goal G-NN` for per-goal lookup. DO NOT
cat TEST-GOALS.md flat (~8K lines on large phases — AI will skim).

The `verify-rcrurd-runtime.py`, `enrich-test-goals.py`, matrix-merger
helpers all read flat artifacts via grep/regex/JSON parsing — those
reads do NOT enter AI context and remain as-is.
</HARD-GATE>

---

## STEP 7.0 — RCRURD runtime gate (always runs, before branching)

<step name="phase4_goal_comparison" mode="full">
## Phase 4: GOAL COMPARISON

→ `narrate_phase "Phase 4 — Goal comparison" "So khớp ${N} goals từ TEST-GOALS với views đã khám phá"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase4_goal_comparison >/dev/null 2>&1 || true
```

### 4.0: RCRURD runtime verification (Task 23 — Codex GPT-5.5 review 2026-05-03)

For every TEST-GOALS/G-NN.md with `goal_type: mutation`, run the runtime
gate. BLOCK review on assertion fail (R8 update_did_not_apply, etc).
Action payload comes from per-phase fixture (`FIXTURES/G-NN.action.json`).

```bash
EVIDENCE_DIR="${PHASE_DIR}/.rcrurd-evidence"
mkdir -p "$EVIDENCE_DIR"
RCRURD_FAILED=0
RCRURD_RAN=0

if [ -d "${PHASE_DIR}/TEST-GOALS" ]; then
  for goal in "${PHASE_DIR}/TEST-GOALS"/G-*.md; do
    [ -f "$goal" ] || continue
    grep -qE "goal_type:[[:space:]]*mutation" "$goal" || continue
    RCRURD_RAN=$((RCRURD_RAN+1))
    ev_out="${EVIDENCE_DIR}/$(basename "$goal" .md).json"

    payload="{}"
    fixture="${PHASE_DIR}/FIXTURES/$(basename "$goal" .md).action.json"
    [ -f "$fixture" ] && payload=$(cat "$fixture")

    "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rcrurd-runtime.py \
      --goal-file "$goal" \
      --phase "${PHASE_NUMBER}" \
      --action-payload "$payload" \
      --auth-header "$(vg_config_get review.rcrurd_auth_header '')" \
      --evidence-out "$ev_out" || RCRURD_FAILED=1
  done
fi

if [ "$RCRURD_RAN" -gt 0 ]; then
  if [ "$RCRURD_FAILED" = "1" ]; then
    echo "⛔ Phase 4.0 RCRURD runtime — at least one mutation goal failed (of ${RCRURD_RAN} run)"
    echo "   Evidence: ${EVIDENCE_DIR}/*.json"
    echo "   Route through classifier (Task 7) — most are IN_SCOPE for current phase"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.rcrurd_runtime_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\",\"goals_run\":${RCRURD_RAN}}" \
      2>/dev/null || true
    exit 1
  fi

  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.rcrurd_runtime_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_run\":${RCRURD_RAN}}" \
    2>/dev/null || true
fi
```

### Branch dispatch

Compute UI_GOAL_COUNT and dispatch:

```bash
UI_GOAL_COUNT=$(grep -c '^\*\*Surface:\*\* ui' "${PHASE_DIR}/TEST-GOALS.md" || echo 0)

if [ "$UI_GOAL_COUNT" -eq 0 ]; then
  # Pure-backend fast-path
  : "Read commands/vg/_shared/review/verdict/pure-backend-fastpath.md"
elif [ "${PHASE_PROFILE}" = "web-fullstack" ] || [ "${PHASE_PROFILE}" = "feature" ]; then
  # Full-fledged web-fullstack pipeline
  : "Read commands/vg/_shared/review/verdict/web-fullstack.md"
else
  # web-frontend-only / web-backend-only / mobile-* / cli-tool / library / hotfix / bugfix / migration / docs
  : "Read commands/vg/_shared/review/verdict/profile-branches.md"
fi
```

The 3 sub-refs all converge on the same 4f gate decision (PASS iff
BLOCKED + UNREACHABLE == 0) and all write to `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`.

### Step-end markers

(executed by whichever sub-ref completes the verdict)

```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "phase4_goal_comparison" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/phase4_goal_comparison.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step review phase4_goal_comparison 2>/dev/null || true
```
</step>
