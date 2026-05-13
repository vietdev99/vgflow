<step name="step5_fix_loop" mode="full">
## Step 5: FIX LOOP (post-test execute) (max 5 iterations)

**Iteration cap (v2.65.0 A4):** `MAX_ITER=5`. Bumped from 3 → 5 because multi-class
violation buckets (e.g. 1 SPEC_GAP + 2 CODE_BUG together) typically need 4–5 passes
to fully resolve. Each iteration emits `review.fix_iteration_started` so operators
have mid-loop telemetry instead of a black box.

→ `narrate_phase "Phase 5 — Fix loop (iteration ${I}/${MAX_ITER:-5})" "Sửa bug MINOR, escalate MODERATE/MAJOR"`

```bash
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator step-active step5_fix_loop >/dev/null 2>&1 || true

# v2.65.0 A4 — fix-loop iteration cap (max_iter=5)
# Each iteration body MUST emit review.fix_iteration_started with
# {iter, max_iter, violations} metadata so progress is observable mid-loop.
MAX_ITER=5
export MAX_ITER
```

**If no errors found in Phase 2 → skip to Phase 4.**
**If --fix-only → load RUNTIME-MAP, find errors, fix them.**

### 3a: Error Summary

Collect errors from ALL sources:
- RUNTIME-MAP.json: `errors[]` array + per-view `issues[]` + failed `goal_sequences` + `free_exploration` issues
- `${PHASE_DIR}/REVIEW-FEEDBACK.md` (if exists — written by /vg:test when MODERATE/MAJOR issues found):
  Parse issues table → add to error list with severity from test classification
  These are issues test couldn't fix — review MUST address them in this fix loop
- `${PLANNING_DIR}/KNOWN-ISSUES.json`: issues matching current phase/views (already loaded at init)

### 3b: Classify Errors

For each error:
- **CODE BUG** → fix immediately (wrong logic, missing validation, UI mismatch)
- **INFRA ISSUE** → escalate to user (service unavailable, config wrong)
- **SPEC GAP** → record in SPEC-GAPS.md (see 3b-spec-gaps) — feature not built, decision missing from CONTEXT/PLAN
- **PRE-EXISTING** → don't fix, write to `${PLANNING_DIR}/KNOWN-ISSUES.json` (see below)

### 3b-spec-gaps: Feed SPEC_GAPS back to blueprint (fixes G9)

When ≥3 SPEC_GAP errors accumulate, or any critical-priority goal maps to SPEC_GAP, emit `${PHASE_DIR}/SPEC-GAPS.md` and surface to user with a concrete re-plan command:

```markdown
# Spec Gaps — Phase {phase}

Detected during /vg:review phase 3b. Listed issues trace to missing CONTEXT decisions or un-tasked PLAN items — not code bugs. Review cannot fix these; blueprint must re-plan.

## Gaps
| # | Observed Issue | Related Goal | Likely Missing | Source Evidence |
|---|----------------|--------------|----------------|-----------------|
| 1 | Site delete has no confirmation modal | G-08 (delete site) | D-XX: "delete requires confirmation" decision | screenshot {phase}-sites-delete-error.png |
| 2 | Bulk import UI absent | G-12 (bulk import) | Task for CSV upload handler + FE form | grep "bulk" in code returns 0 matches |
...

## Recommended action

This is NOT a code bug. Re-run blueprint in patch mode to append tasks covering these gaps:

    /vg:blueprint {phase} --from=2a

This spawns planner with the gap list as input. Existing tasks preserved; missing ones appended. Then re-run build → review.

Do NOT attempt to fix these in the review fix loop — the fix loop targets code bugs, not missing scope.
```

Threshold + auto-suggestion:
```bash
SPEC_GAP_COUNT=$(count of SPEC_GAP-classified errors)
CRITICAL_SPEC_GAPS=$(count where related goal is priority:critical)

if [ $SPEC_GAP_COUNT -ge 3 ] || [ $CRITICAL_SPEC_GAPS -ge 1 ]; then
  echo "⚠ ${SPEC_GAP_COUNT} spec gaps detected (${CRITICAL_SPEC_GAPS} critical)."
  echo "See: ${PHASE_DIR}/SPEC-GAPS.md"
  echo ""
  echo "This is a planning gap, not a code bug. Recommended:"
  echo "   /vg:blueprint ${PHASE} --from=2a   (re-plan with gap feedback)"
  echo ""
  echo "Review fix loop will continue for code bugs only; spec gaps stay open until blueprint re-run."
fi
```

Do NOT block review — let fix loop handle code bugs. Just surface spec gaps with the right next command.

### 3b-known: Write PRE-EXISTING to KNOWN-ISSUES.json

Shared file across all phases: `${PLANNING_DIR}/KNOWN-ISSUES.json`

```
Read existing KNOWN-ISSUES.json (create if missing)

For each PRE-EXISTING error:
  Check if already recorded (match by view + description)
  IF new → append:
    {
      "id": "KI-{auto_increment}",
      "found_in_phase": "{current phase}",
      "view": "{view_path where observed}",
      "description": "{what's wrong}",
      "evidence": { "network": [...], "console_errors": [...], "screenshot": "..." },
      "affects_views": ["{list of views where this issue appears}"],
      "suggested_phase": "{phase that owns this area — AI infers from code_patterns}",
      "severity": "low|medium|high",
      "status": "open"
    }

Write back KNOWN-ISSUES.json
```

**Future phases auto-consume:** At the start of every review (Phase 2, before discovery), read KNOWN-ISSUES.json → filter issues where `suggested_phase` matches current phase OR `affects_views` overlaps with views being reviewed → display to AI as "known issues to verify/fix in this phase".

### 3c: Fix + Ripple Check + Redeploy

**🎯 3-tier fix routing (tightened 2026-04-17 — cost + context isolation):**

Sau khi bug classified ở 3a/3b (MINOR/MODERATE/MAJOR + size metadata), route tới model phù hợp theo config. Main model KHÔNG tự fix mọi thứ — MODERATE phải spawn để isolate context và save main-model tokens.

**Config (pure user-side, workflow không giả định model vendor/tier):**

```yaml
# vg.config.md
models:
  # Existing keys: planner, executor, debugger
  review_fix_inline: <model-id>    # model cho MINOR inline (thường = main/planner tier)
  review_fix_spawn:  <model-id>    # model cheaper cho MODERATE + MINOR-big-scope

review:
  fix_routing:
    minor:
      inline_when:
        max_files: <int>
        max_loc_estimate: <int>
      else: "spawn"                # route to models.review_fix_spawn
    moderate:
      action: "spawn"              # always route to models.review_fix_spawn
      parallel: <bool>
      max_concurrent: <int>
    major:
      action: "escalate"           # REVIEW-FEEDBACK.md, không auto-fix
    tripwire:
      minor_bloat_loc: <int>
      action: "warn|rollback"
```

Workflow CHỈ đọc model id từ `config.models.review_fix_inline` / `review_fix_spawn`. Không hardcode tên vendor (Claude/GPT/Gemini), tier (Opus/Sonnet/Haiku, o3/gpt-4o), hay capability.

Thiếu config → fallback: inline = main model hiện tại, spawn = cùng model (degraded — không có cost optimization nhưng vẫn có context isolation).

**Algorithm per CODE BUG:**

```
1. Load severity từ error classification (step 3b)
2. Estimate fix scope trước khi fix:
   - files_to_touch = heuristic từ error location + related callers
   - loc_estimate = peek file around error line, count context
3. Route theo severity:
```

**MINOR + small scope → inline (fast path, main model):**
```
If severity == MINOR AND files <= config.review.fix_routing.minor.inline_when.max_files
                   AND loc_estimate <= config.review.fix_routing.minor.inline_when.max_loc_estimate:
  Main model reads file + edits inline (current behavior)
  narrate_fix "[inline] MINOR ${bug_title} (${files} files, ~${loc} LOC)"
```

**MINOR big scope OR MODERATE → spawn (config-driven model):**

**Runtime branching (v2.65.0 A6) — Claude vs Codex spawn primitives:**

Fix-agent spawn site is dual-path: Claude Code uses the native `Agent` tool;
Codex (`VG_RUNTIME=codex`) does NOT have the `Agent` tool, so it MUST shell
out to `codex-spawn.sh --tier executor` (write access required because fixes
edit code). See `codex-skills/vg-build/SKILL.md` "Codex spawn precedence"
table — `/vg:review` fix agents map to `--tier executor` with
`workspace-write` sandbox.

```bash
SPAWN_MODEL="${config.models.review_fix_spawn:-${config.models.executor}}"
PROMPT_FILE="${PHASE_DIR}/.fix-prompt-${ERR_ID:-$idx}.md"
# (Render the structured prompt below into $PROMPT_FILE before spawning.)

if [ "${VG_RUNTIME:-claude}" = "codex" ]; then
  # Codex path (v2.65.0 A6) — no Agent tool; use codex-spawn.sh executor tier.
  # Sandbox=workspace-write because fix-agents edit code/tests.
  bash commands/vg/_shared/lib/codex-spawn.sh \
       --tier executor \
       --task "fix-${ERR_ID:-$idx}" \
       --sandbox workspace-write \
       --prompt-file "${PROMPT_FILE}" \
       --out "${PHASE_DIR}/.fix-out-${ERR_ID:-$idx}.json" \
    || { echo "⚠ codex-spawn fix-agent failed for ${ERR_ID:-$idx} — escalate to REVIEW-FEEDBACK.md" >&2; }
else
  # Claude path — preserve existing Agent tool spawn (narrate first, then call).
  bash scripts/vg-narrate-spawn.sh general-purpose spawning "fix-${ERR_ID:-$idx}" 2>/dev/null || true
  # Then invoke the Agent tool with the prompt body below; model/$SPAWN_MODEL
  # is passed as the model parameter (provider-native).
fi
```

Prompt body (rendered into `${PROMPT_FILE}` for Codex, or passed inline to
the `Agent(...)` tool call on Claude):

```
Agent(
  model="$SPAWN_MODEL",
  description="[fix ${idx}/${total}] ${severity} ${file}:${line} — ${bug_type}"
):
  prompt = """
  Fix this reviewed bug. Focused scope — no tangent changes.

  ## BUG
  Severity: ${severity}
  Observed: ${error_description}
  Expected: ${expected_behavior}
  View: ${view_url}
  File hint: ${suspected_file}
  Evidence: ${console_errors}, ${network_failures}, ${screenshot}

  ## CONSTRAINTS
  - Touch only files related to this bug
  - No refactor/rename unless required for fix
  - Write test if missing (project convention)
  - Commit: fix(${phase}): ${short description}
  - Per CONTEXT.md D-XX OR Covers goal: G-XX in commit body

  ## RETURN
  - Files changed (list)
  - LOC delta
  - One-line summary
  """

narrate_fix "[spawn:${SPAWN_MODEL}] ${severity} ${bug_title}"
```

**MAJOR → escalate (no auto-fix):**
```
Append to REVIEW-FEEDBACK.md:
| bug_id | view | severity | description | why_escalated |

narrate_fix "[escalated] MAJOR ${bug_title} → REVIEW-FEEDBACK.md"
```

**Parallel spawning:**

Nếu `config.review.fix_routing.moderate.parallel: true` và có >1 MODERATE bugs độc lập (no shared files):
- Group bugs by affected file → spawn Sonnet parallel per group
- Max `config.review.fix_routing.moderate.max_concurrent` at once
- Wait all → aggregate commits

**Post-fix tripwire (catch misclassification):**

```bash
TRIPWIRE_LOC="${config.review.fix_routing.tripwire.minor_bloat_loc:-0}"
TRIPWIRE_ACTION="${config.review.fix_routing.tripwire.action:-warn}"

if [ "$TRIPWIRE_LOC" -gt 0 ]; then
  # Check each MINOR-routed-inline fix
  for commit in $MINOR_INLINE_COMMITS; do
    ACTUAL_LOC=$(git show --stat "$commit" | tail -1 | grep -oE '[0-9]+ insertion' | grep -oE '^[0-9]+')
    if [ "${ACTUAL_LOC:-0}" -gt "$TRIPWIRE_LOC" ]; then
      case "$TRIPWIRE_ACTION" in
        rollback)
          echo "⛔ MINOR inline fix bloated ($ACTUAL_LOC > $TRIPWIRE_LOC LOC) — rolling back, re-route Sonnet"
          git reset --hard "${commit}^"
          # Re-queue bug với severity upgrade → MODERATE → spawn Sonnet
          ;;
        warn|*)
          echo "⚠ MINOR fix ($commit) bloated: $ACTUAL_LOC LOC > $TRIPWIRE_LOC threshold. Consider re-classify."
          echo "tripwire: $commit actual_loc=$ACTUAL_LOC severity=MINOR" >> "${PHASE_DIR}/build-state.log"
          ;;
      esac
    fi
  done
fi
```

**Narration format:**

```
  ▶ Fix 1/5: [inline] MINOR edit button label mismatch
       ✓ Fixed 1 file, 2 LOC

  ▶ Fix 2/5: [spawn] MODERATE form validation missing on /sites/new
       ✓ Agent completed: 3 files, 24 LOC  (model: ${SPAWN_MODEL})

  ▶ Fix 3/5: [escalated] MAJOR bulk import UI absent
       → REVIEW-FEEDBACK.md

  ▶ Fix 4/5: [inline] MINOR CSS overflow on mobile
       ⚠ Tripwire hit: 45 LOC > 15 threshold — flagged for re-classify
```

Narrator chỉ hiển thị model id user đã config, KHÔNG hardcode "Sonnet"/"GPT-4o"/etc.

**Then for each fixed bug (inline OR via Sonnet):**

1. Read the relevant source file
2. Fix the issue
3. **Ripple check (graphify-powered, if active):**
   ```bash
   if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
     # Get files changed by this fix
     FIXED_FILES=$(git diff --name-only HEAD)
     echo "$FIXED_FILES" > "${PHASE_DIR}/.fix-ripple-input.txt"

     # Run ripple analysis on fixed files
     ${PYTHON_BIN} ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/build-caller-graph.py \
       --changed-files-input "${PHASE_DIR}/.fix-ripple-input.txt" \
       --config .claude/vg.config.md \
       --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
       --output "${PHASE_DIR}/.fix-ripple.json"

     # Check if fix affects callers outside the fixed file
     RIPPLE_COUNT=$(${PYTHON_BIN} -c "
     import json
     d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
     callers = d.get('affected_callers', [])
     print(len(callers))
     ")

     if [ "$RIPPLE_COUNT" -gt 0 ]; then
       echo "⚠ Fix ripple: ${RIPPLE_COUNT} callers may be affected by this change"
       echo "  Adding caller views to re-verify list (step 3d)"
       # Map caller files → views for re-verification in step 3d
       RIPPLE_VIEWS=$(${PYTHON_BIN} -c "
       import json
       d = json.load(open('${PHASE_DIR}/.fix-ripple.json'))
       for c in d.get('affected_callers', []):
         print(c)
       ")
     fi
   fi
   ```
   Without graphify: step 3d re-verifies affected views by git diff only (may miss indirect callers).
4. Commit with message: `fix({phase}): {description}`

After all fixes:
```
Redeploy using env-commands.md deploy(env)
Health check → if fail → rollback
```

### 3d: Re-verify (Sonnet parallel — focused on fixed zones)

After fix+redeploy, spawn Sonnet agents to re-verify affected views + ripple zones:

```
1. Get new SHA: git rev-parse HEAD
2. git diff old_sha..new_sha → list changed files
3. Map changed files to views (using code_patterns from config):
   - Changed API routes → views that call those endpoints
   - Changed page components → those specific views
   - Graphify ripple callers (from step 3c) → views importing those callers
4. Group affected views + ripple views into zones

5. Spawn Sonnet agents (parallel) for affected zones ONLY:
   Agent prompt: "Re-verify these fixed actions in {zone}.
     Previous errors: {error list from 3a}
     Expected: errors should be resolved.
     Test each previously-failed action.
     Also check: did the fix break anything else on this view?
     Report: {action, was_broken, now_works, new_issues}"

6. Wait all → merge results:
   - Fixed errors → update matrix: ❌ → 🔍 REVIEW-PASSED
   - Still broken → keep ❌, increment iteration
   - New errors from fix → add to error list
   - Update RUNTIME-MAP with corrected observations
   - Log current build SHA in PIPELINE-STATE.json `steps.review.last_fix_sha`
```

### 3d.5: QA-Checker meta-verification (v2.68.0 C2, hardened v2.69.0)

**v2.69.0 T3 escape hatch:** `SKIP_QA_CHECK=1` short-circuits this step
(set by parse loop when `--skip-qa-check` is passed; logs override-debt).
When unset, full QA-Checker spawn runs.

After Phase 3 fix-loop converges (verdict=ok or max_iter reached), spawn QA-Checker
to verify each fix commit ACTUALLY addresses the original review finding it was
meant to fix — not just makes tests pass. Detects suppression hacks, false fixes,
and test reverts.

```bash
if [ "${SKIP_QA_CHECK:-0}" = "1" ]; then
  echo "▸ Phase 3d.5: --skip-qa-check set (debt-tracked); skipping QA-Checker meta-verification" >&2
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/phase3d_5_qa_checker.done"
  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator mark-step review phase3d_5_qa_checker 2>/dev/null || true
else
  bash scripts/vg-narrate-spawn.sh vg-review-qa-checker spawning "QA-check ${PHASE_NUMBER} fix commits"
  # Then: Agent(subagent_type="vg-review-qa-checker",
  #             prompt=<rendered with phase_dir + fix_commits list>)
fi
```

Marker: `phase3d_5_qa_checker` (v2.69.0:
`required_unless_flag: --skip-qa-check` — hard-block flipped from
v2.68.0 advisory severity=warn).

The QA-Checker returns PASS|PARTIAL|FAIL per fix and a cumulative verdict.
On PARTIAL/FAIL (v2.69.0 onward), review BLOCKs unless
`--skip-qa-check --override-reason=<text>` was passed. Operators must
either fix the underlying issue, route to /vg:amend, or log debt via the
escape hatch.

### 3e: Iterate

Repeat 3a-3d until:
- RUNTIME-MAP is **stable** (no new errors between 2 iterations)
- Zero CODE BUG errors remaining
- `MAX_ITER=5` iterations reached (v2.65.0 A4 bump from 3 → 5 for multi-class buckets)

**Per-iteration telemetry (v2.65.0 A4):** at the top of every iteration body, emit
`review.fix_iteration_started` so operators can watch progress mid-loop:

```bash
# Emit at the start of each iteration (after ITER + VIOLATION_COUNT are known).
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event \
  "review.fix_iteration_started" --actor "review" --outcome "INFO" \
  --metadata "{\"iter\":${ITER},\"max_iter\":${MAX_ITER:-5},\"violations\":${VIOLATION_COUNT:-0}}" \
  >/dev/null 2>&1 || true
```

Display after each iteration:
```
Fix iteration {N}/${MAX_ITER:-5}:
  Errors fixed: {N}
  Errors remaining: {N} (infra: {N}, spec-gap: {N}, pre-existing: {N})
  Sonnet agents spawned: {N} (re-verified {M} views)
  New errors found: {N}
  Matrix coverage: {review_passed}/{total} goals
  Map stable: {YES|NO}
```

### 3e: Iter limit fallback — Diagnostic L2 (RFC v9 D11 + D26, PR-E)

When the final iteration (`ITER == MAX_ITER`, default 5) exits with errors STILL
remaining (loop hit cap without self-resolving), do NOT silent-BLOCK. Spawn
diagnostic_l2 single-advisory fallback:

1. Capture residual evidence: list of unresolved error rows from
   RUNTIME-MAP + scan-*.json + recipe_executor logs.
2. Spawn isolated Haiku subagent (zero parent context — RFC v9 D11) to
   classify root cause `block_family` ∈ {schema_drift, validation_bug,
   auth_issue, db_constraint, business_logic, integration_failure,
   unknown}.
3. L2 generates `L2Proposal.json` with confidence + proposed_fix.
4. Present to user via single-advisory pattern (D26):
     - confidence ≥ 0.7  → "Đề xuất: <fix>. [Yes / chi tiết]"
     - confidence < 0.7  → 3-option block_resolve_l3_present (legacy)
5. **User gate is mandatory** — never auto-apply (per project policy).
6. User accept → apply fix → re-run one extra iteration grace (ITER+1).
7. User reject → BLOCK with full audit trail in
   `.l2-proposals/{proposal_id}.json` + DEFECT-LOG entry referencing
   the proposal.

```bash
if [ "${ITER:-1}" -eq "${MAX_ITER:-5}" ] && [ -n "${REMAINING_ERRORS}" ] && \
   { [ -f "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/spawn-diagnostic-l2.py" ] || [ -f "${REPO_ROOT}/scripts/spawn-diagnostic-l2.py" ]; }; then
  echo "━━━ Phase 3e — Diagnostic L2 fallback (iter ${ITER} hit cap=${MAX_ITER:-5}) ━━━"
  DIAGNOSTIC_L2="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/spawn-diagnostic-l2.py"
  [ -f "$DIAGNOSTIC_L2" ] || DIAGNOSTIC_L2="${REPO_ROOT}/scripts/spawn-diagnostic-l2.py"
  L2_ARGS=(
    --phase "${PHASE_NUMBER}"
    --gate-id "review.fix_loop"
    --evidence-file "${PHASE_DIR}/.fix-loop-evidence.json"
  )
  L2_OUT=$("${PYTHON_BIN:-python3}" "$DIAGNOSTIC_L2" \
    "${L2_ARGS[@]}" 2>&1)
  L2_PROPOSAL_ID=$(echo "$L2_OUT" | ${PYTHON_BIN:-python3} -c "
import json, sys
try: print(json.loads(sys.stdin.read()).get('proposal_id',''))
except: print('')
")
  if [ -n "$L2_PROPOSAL_ID" ]; then
    echo "  L2 proposal generated: $L2_PROPOSAL_ID"
    # Open DEFECT-LOG entry referencing the proposal
    TESTER_PRO_CLI="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/tester-pro-cli.py"
    [ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
    if [ -f "$TESTER_PRO_CLI" ]; then
      "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" defect new \
        --phase "${PHASE_NUMBER}" \
        --title "[ITER-LIMIT] Fix loop hit max=${MAX_ITER:-5}, L2 proposal $L2_PROPOSAL_ID" \
        --severity major --found-in review \
        --notes "L2 proposal at .l2-proposals/${L2_PROPOSAL_ID}.json — user decision pending" \
        2>&1 | sed 's/^/  /' || true
    fi
    # User gate is provider-native after spawn-diagnostic-l2.py:
    # Claude Code uses AskUserQuestion; Codex asks in the main thread/UI.
    # On accept → run-complete sees applied; on reject → BLOCK below.
    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event \
      "review.diagnostic_l2_spawned" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"proposal_id\":\"$L2_PROPOSAL_ID\"}" \
      >/dev/null 2>&1 || true
  fi
fi
```

> **Tại sao không tự apply L2 fix**: L2 đã sai trong dogfood 3.2
> (propose fix giả mà có vẻ hợp lý). User gate là single source of truth
> cho fix correctness. Audit trail (`.l2-proposals/`) cho phép trace
> sau-incident: proposal nào được accept/reject, fix tham chiếu commit nào.
</step>

<step name="step7_matrix_verdict" mode="full">
## Step 7: MATRIX VERDICT (post-fix-loop)

→ `narrate_phase "Phase 7 — Goal comparison" "So khớp ${N} goals từ TEST-GOALS với views đã khám phá"`

```bash
"${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator step-active step7_matrix_verdict >/dev/null 2>&1 || true
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

    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-rcrurd-runtime.py \
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
    "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event \
      "review.rcrurd_runtime_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\",\"goals_run\":${RCRURD_RAN}}" \
      2>/dev/null || true
    exit 1
  fi

  "${PYTHON_BIN:-python3}" ${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator emit-event \
    "review.rcrurd_runtime_passed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goals_run\":${RCRURD_RAN}}" \
    2>/dev/null || true
fi
```

### 4a: Load Goals + edge cases

Load goals via `vg-load --phase ${PHASE_NUMBER} --artifact goals` (generated by /vg:blueprint).
If missing → generate from CONTEXT.md + API-CONTRACTS.md (fallback).

**P1 v2.49+ — Edge case variants:** also load `${PHASE_DIR}/EDGE-CASES/G-NN.md`
per goal. Status format extended:
- Old: `G-04: PASS` / `G-04: FAIL` / `G-04: NOT_TESTED`
- New: `G-04: PASS (5/6 variants — G-04-c1 NOT_TESTED [needs concurrency harness])`

For each variant in EDGE-CASES/G-NN.md:
- Replay `start_view` (per RUNTIME-MAP) with variant's input
- Verify expected_outcome matches actual UI/API response
- Mark per-variant: PASS | FAIL | NOT_TESTED (with reason)
- Aggregate to goal status (goal PASS only when all critical/high variants PASS)

Skip variants when:
- EDGE-CASES file missing (legacy phase pre-v2.49) → emit
  `review.edge_cases_unavailable` (severity=warn) + treat goal as 1-variant
- Variant priority=low + `--skip-low-edge-cases` flag set
- No-CRUD phase (CRUD-SURFACES.resources empty) → no variants expected

Emit per gate-blocked variant: `review.edge_case_variant_blocked` with
`{goal_id, variant_id, reason}` payload.

Parse goals: ID, description, success criteria, mutation evidence, dependencies, priority.

**Post-build lifecycle contract (v3.6.7) — review MUST consume `/vg:test-spec` artifacts, not only gate their existence.**

Load these artifacts before mapping goals:
- `${PHASE_DIR}/LIFECYCLE-SPECS.json` — side-effecting / multi-actor lifecycle contract per goal.
- `${PHASE_DIR}/TEST-FIXTURE-DAG.json` — fixture dependency graph and cleanup order.
- `${PHASE_DIR}/TEST-EXECUTION-PLAN.json` — runner family per phase profile (`web`, `mobile`, `backend`, `cli`, `library`, `mixed`).
- `${PHASE_DIR}/DEEP-TEST-SPECS.md` — human-readable provenance and gap context.

Review uses them as the lifecycle comparison contract:
- Runtime blockers still produce `BLOCKED` and stay in review/debug.
- Missing RCRURDR lifecycle proof with clean runtime produces `TEST_PENDING`, then advances to `/vg:test`.
- Runner-native phases (`mobile`, `backend`, `cli`, `library`) must not be forced into Playwright/browser semantics; use `TEST-EXECUTION-PLAN.json.family`.
- If lifecycle artifacts name a goal that legacy `TEST-GOALS.md` parsing missed, include that goal in `GOAL-COVERAGE-MATRIX.md` so review cannot silently drop it.

**Surface classification (v1.9.1 R1 — lazy migration, runs BEFORE browser discover decisions):**

```bash
# shellcheck source=_shared/lib/goal-classifier.sh
. ${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
# rc=2 → provider-native cheap classifier
#        Claude: Haiku Task per row; Codex: read-only scanner adapter over pending TSV
# rc=3 → provider-native prompt (surface list from config), then classify_goals_apply
```

Parse `**Surface:** <name>` per goal.

**Surface-aware routing (tightened v1.9.1 R1):**

For each goal:
- `surface == "ui"` / `"ui-mobile"` → proceed with existing browser RUNTIME-MAP lookup below.
- `surface ∈ { api, data, time-driven, integration, custom }` → skip browser discover for this goal; instead run lightweight **surface probe**:
  * `api`        → grep `apps/**/src/**` for route handler matching contract path → READY if present.
  * `data`       → grep migrations + `config.infra_deps` for table/collection → READY if present; INFRA_PENDING if service unavailable.
  * `time-driven`→ grep cron/scheduler registration in `apps/workers/**`/`apps/api/**` → READY if handler wired.
  * `integration`→ check `${PHASE_DIR}/test-runners/fixtures/${gid}.integration.sh` exists AND downstream caller found → READY.

Result feeds GOAL-COVERAGE-MATRIX with `(status, surface, probe_evidence)`.

**Pure-backend fast-path:**
```bash
UI_GOAL_COUNT=$(grep -c '^\*\*Surface:\*\* ui' "${PHASE_DIR}/TEST-GOALS.md" || echo 0)
if [ "$UI_GOAL_COUNT" -eq 0 ]; then
  echo "🧭 Pure-backend phase (không có goal UI) — bỏ qua browser discovery (khám phá trình duyệt), dùng surface probes." >&2
  # Emit empty RUNTIME-MAP if not written yet, skip to 4b
  [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ] || echo '{"views":{},"goal_sequences":{}}' > "${PHASE_DIR}/RUNTIME-MAP.json"
  # Issue #120: runtime_contract still requires one root scan-*.json artifact
  # even when backend-only review legitimately skips browser discovery. Emit a
  # synthetic backend scan so run-complete does not false-block on must_write.
  BACKEND_SCAN_JSON="${PHASE_DIR}/scan-backend-surface-probes.json"
  if [ ! -f "$BACKEND_SCAN_JSON" ]; then
    "${PYTHON_BIN:-python3}" - "$BACKEND_SCAN_JSON" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "view": "backend://surface-probes",
    "surface": "backend",
    "generated_by": "step7_matrix_verdict.pure_backend_fastpath",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "results": [],
    "forms": [],
    "tables": [],
    "modal_triggers": [],
    "sub_views_discovered": [],
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  fi
fi
```

**Mixed-phase surface probe execution (v1.9.2.3 P3):**

For phases có CẢ UI goals (cần browser) VÀ backend goals (api/data/integration/time-driven), browser phase chỉ cover UI goals. Backend goals PHẢI được probe SEPARATELY để avoid rơi vào NOT_SCANNED branch.

```bash
# Run surface probes cho goals có surface ≠ ui
source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/surface-probe.sh" 2>/dev/null || true
if type -t run_surface_probe >/dev/null 2>&1; then
  PROBE_RESULTS_JSON="${PHASE_DIR}/.surface-probe-results.json"
  echo '{"probed_at":"'"$(date -u +%FT%TZ)"'","results":{' > "$PROBE_RESULTS_JSON"
  FIRST=true

  # Extract goal_id + surface pairs from TEST-GOALS.md
  ${PYTHON_BIN} -c "
import re
tg = open('${PHASE_DIR}/TEST-GOALS.md', encoding='utf-8').read()
for gid, surface in re.findall(r'^## Goal (G-[\w]+):.*?^\*\*Surface:\*\* (\w[\w-]*)', tg, re.M|re.S):
    print(f'{gid} {surface}')
" | while read -r gid surface; do
    surface="${surface%$'\r'}"
    # Skip UI — browser phase handles them
    [ "$surface" = "ui" ] || [ "$surface" = "ui-mobile" ] && continue

    PROBE=$(run_surface_probe "$gid" "$surface" "$PHASE_DIR" 2>/dev/null)
    STATUS=$(echo "$PROBE" | cut -d'|' -f1)
    EVIDENCE=$(echo "$PROBE" | cut -d'|' -f2- | sed 's/"/\\"/g')

    [ "$FIRST" = "true" ] && FIRST=false || echo "," >> "$PROBE_RESULTS_JSON"
    printf '"%s":{"surface":"%s","status":"%s","evidence":"%s"}' \
           "$gid" "$surface" "$STATUS" "$EVIDENCE" >> "$PROBE_RESULTS_JSON"
  done

  echo '}}' >> "$PROBE_RESULTS_JSON"

  # Summary narration
  PROBED=$(${PYTHON_BIN} -c "
import json
d = json.load(open('$PROBE_RESULTS_JSON'))['results']
from collections import Counter
c = Counter(r['status'] for r in d.values())
print(f'Phase 4a surface probes: {len(d)} backend goals probed → {dict(c)}')")
  echo "▸ $PROBED"

  # v2.48.1 (Issue #85) — backfill synthetic goal_sequences[gid] for non-UI
  # goals from probe results so verify-matrix-evidence-link.py (which only
  # inspects RUNTIME-MAP goal_sequences[]) sees backend evidence. Closes the
  # surface-probe schema gap that BLOCKed Phase 3.2 dogfood with 32 non-UI
  # READY goals flagged matrix_status_without_runtime_sequence.
  # Idempotent: re-runs overwrite synthetic entries by gid, never overwrites
  # real browser-recorded sequences.
  if [ -f "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/backfill-surface-probe-runtime.py" ]; then
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/backfill-surface-probe-runtime.py" \
      --phase-dir "$PHASE_DIR" 2>&1 | sed 's/^/▸ /' || true
  fi
fi
```

**Phase 4b integration:** Khi check goal_sequences cho backend goals (surface ≠ ui), trước khi mark NOT_SCANNED hãy check `.surface-probe-results.json`:
- Nếu probe READY → map → STATUS: READY với evidence từ probe (handler path, migration file, caller reference).
- Nếu probe BLOCKED → map → STATUS: BLOCKED với evidence là probe reason.
- Nếu probe INFRA_PENDING → map → STATUS: INFRA_PENDING.
- Nếu probe SKIPPED (can't parse criteria) → fallthrough to NOT_SCANNED branch → buộc user cải thiện TEST-GOALS hoặc override.

**Lifecycle contract integration (v3.6.7):**
- If `LIFECYCLE-SPECS.json.goals[G-XX]` exists and runtime/probe found a real API/render/data blocker → keep `BLOCKED`.
- If runtime/probe is clean but RCRURDR stages, fixture DAG, actor handoff, artifact capture, or cleanup are not proven by review evidence → mark `TEST_PENDING`, not `BLOCKED`.
- If no browser sequence exists for a runner-native lifecycle goal (`family in {mobile, backend, cli, library}`) → mark `TEST_PENDING` with runner/family evidence from `TEST-EXECUTION-PLAN.json`.
- If a web lifecycle goal has no `goal_sequences[G-XX]` → keep `NOT_SCANNED`; review must still discover the route/action before `/vg:test` can generate reliable replay steps.

**Infra dependency filter (config-driven):**

If goal has `**Infra deps:**` field (e.g., `[clickhouse, kafka, pixel_server]`):
```bash
# Check each infra dep against current environment
for dep in goal.infra_deps:
  SERVICE_CHECK=$(read config.infra_deps.services[dep].check_${ENV})
  if ! eval "$SERVICE_CHECK" 2>/dev/null; then
    goal.status = "INFRA_PENDING"
    goal.skip_reason = "${dep} not available on ${ENV}"
  fi
done
```

Goals classified as `INFRA_PENDING` are **excluded from gate calculation** (when `config.infra_deps.unmet_behavior == "skip"`). They don't count as BLOCKED or FAIL — they're simply not testable on current environment.

Display: `INFRA_PENDING ({dep})` in matrix with distinct icon.

**Console noise filter (config-driven):**

When evaluating console errors from Phase 2 discovery, filter against `config.console_noise.patterns`:
```bash
if [ "${config_console_noise_enabled}" = "true" ]; then
  for pattern in config.console_noise.patterns:
    # Remove matching errors from bug list — classify as INFRA_NOISE
    REAL_ERRORS=$(echo "$ALL_CONSOLE_ERRORS" | grep -viE "$pattern")
  done
  NOISE_COUNT=$((TOTAL_ERRORS - REAL_ERROR_COUNT))
  echo "Console: ${REAL_ERROR_COUNT} real errors, ${NOISE_COUNT} infra noise (filtered)"
fi
```

Only REAL_ERRORS (not matching noise patterns) count as view failures.

### 4b: Map Goals to RUNTIME-MAP

For each goal, check goal_sequences in RUNTIME-MAP.json:

```
For each goal:
  IF goal_sequences[goal_id] exists AND result == "passed":
    → STATUS: READY (goal was verified during Pass 2a)

  IF goal_sequences[goal_id] exists AND result == "failed":
    → STATUS: BLOCKED (with specific failure steps from goal_sequence)

  IF goal_sequences[goal_id] does NOT exist:
    # Before marking UNREACHABLE, verify code presence to distinguish
    # true "not built" from "built but not scanned"
    code_exists = check via grep against config.code_patterns:
      - Does goal's expected page file exist? (e.g., FloorRulesListPage.tsx)
      - Is the route registered? (e.g., /floor-rules in router)
      - Do related API endpoints have handlers? (grep API-CONTRACTS vs apps/api/)

    IF code_exists == FALSE:
      → STATUS: UNREACHABLE (feature not built — fix with /vg:build --gaps-only)

    IF code_exists == TRUE:
      → STATUS: NOT_SCANNED (intermediate only — MUST resolve before review exits)
      Root cause likely one of:
        - Multi-step wizard/mutation needs dedicated browser session
        - Goal path not reachable from discovered sidebar (orphan route)
        - Review ran --retry-failed but this goal wasn't in retry set
        - Haiku agent timed out or skipped
        - Goal has no UI surface but TEST-GOALS didn't mark infra_deps
      → RESOLUTION (tightened 2026-04-17 — NOT_SCANNED không được defer sang /vg:test):
        NOT_SCANNED là trạng thái TRUNG GIAN, KHÔNG phải kết luận hợp lệ.
        Review PHẢI resolve thành 1 trong 4 status kết luận: READY | BLOCKED | UNREACHABLE | INFRA_PENDING
        Cách resolve (pick 1):
          a) /vg:review {phase} --retry-failed với deeper probe (nếu timeout/depth issue)
          b) Goal không có UI surface → update TEST-GOALS với `**Infra deps:** [<user-defined no-ui tag>]` → re-classify INFRA_PENDING (tag value do user định nghĩa trong config.infra_deps, workflow không hardcode)
          c) Orphan/hidden route → verify config.code_patterns.frontend_routes đã cover pattern đó
          d) Genuinely unreachable (feature đã build nhưng UX path không exist) → manually mark UNREACHABLE with reason note
```

**Status semantics (tightened 2026-04-17):**

4 **status kết luận hợp lệ** (chỉ 4 status này được write vào GOAL-COVERAGE-MATRIX final):

| Status | Meaning | Fix command |
|---|---|---|
| READY | Goal verified, evidence in goal_sequences | none |
| BLOCKED | View found, scan ran, criteria failed | fix code → `--retry-failed` |
| UNREACHABLE | Code not in repo / UX path không exist | `/vg:build --gaps-only` |
| INFRA_PENDING | Goal needs service/infra not available on ENV | deploy infra or sandbox |

2 **status trung gian** (PHẢI resolve trước khi exit Phase 4):

| Status | Meaning | Action BẮT BUỘC |
|---|---|---|
| NOT_SCANNED | Code exists, review didn't replay | `--retry-failed` HOẶC re-classify thành 1 trong 4 status trên |
| FAILED | Scan timeout/exception | check logs → `--retry-failed` |

**⛔ GLOBAL RULE: KHÔNG được defer NOT_SCANNED sang /vg:test.**

Lý do: `/vg:test` codegen LẤY steps từ `goal_sequences[]` mà review ghi. NOT_SCANNED = review không ghi sequence = codegen không có input. Test không phải fallback cho review miss.

Goals không có UI surface đúng ra phải mark `infra_deps: [<no-ui tag>]` trong TEST-GOALS (tag value do project config quy ước) → skip ở review (INFRA_PENDING) → test qua integration/unit layer ở build phase, KHÔNG qua /vg:test E2E.

### 4c-pre: ⛔ NOT_SCANNED resolution gate (tightened 2026-04-17)

Trước khi chạy weighted gate, PHẢI resolve mọi `NOT_SCANNED` + `FAILED` thành 1 trong 4 kết luận.

```bash
# OHOK-8 round-4 Codex fix: replace pseudocode with real bash grep.
# Previously `count goals where status == "NOT_SCANNED"` was not executable
# → gate couldn't run → NOT_SCANNED goals slipped through unresolved.
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
NOT_SCANNED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*NOT_SCANNED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
FAILED_COUNT=$(grep -cE '^\| G-[0-9]+.*\|[[:space:]]*FAILED[[:space:]]*\|' "$MATRIX" 2>/dev/null || echo 0)
INTERMEDIATE=$((NOT_SCANNED_COUNT + FAILED_COUNT))
# Build the list of intermediate goal IDs (used later in override auto-convert)
INTERMEDIATE_GOALS=$(grep -oE '^\| (G-[0-9]+)[^|]*\|[^|]*\|[^|]*\|[[:space:]]*(NOT_SCANNED|FAILED)[[:space:]]*\|' "$MATRIX" 2>/dev/null \
  | grep -oE 'G-[0-9]+' | sort -u | tr '\n' ' ')

if [ "$INTERMEDIATE" -gt 0 ]; then
  echo "⛔ Review cannot exit Phase 4 — ${INTERMEDIATE} intermediate goals:"
  echo "   NOT_SCANNED: ${NOT_SCANNED_COUNT}"
  echo "   FAILED:      ${FAILED_COUNT}"
  echo ""
  echo "Intermediate ≠ conclusion. Resolve before exit:"
  echo "  a) /vg:review ${PHASE_NUMBER} --retry-failed  (deeper probe)"
  echo "  b) Update TEST-GOALS with 'Infra deps: [backend_only]' nếu goal không có UI"
  echo "     → re-classify INFRA_PENDING"
  echo "  c) Fix config.code_patterns.frontend_routes nếu route ẩn khỏi sidebar"
  echo "  d) Manual re-classify UNREACHABLE (feature không tồn tại) với reason note"
  echo ""
  echo "⛔ KHÔNG ĐƯỢC defer sang /vg:test để 'cover' NOT_SCANNED goals."
  echo "   Test codegen lấy input từ goal_sequences review ghi. NOT_SCANNED = no input."
  echo ""
  echo "Override (NOT RECOMMENDED — creates debt):"
  echo "  /vg:review ${PHASE_NUMBER} --allow-intermediate"
  echo "  → Auto-convert remaining NOT_SCANNED → UNREACHABLE với reason='review-skip'"
  echo "  → Logged to GOAL-COVERAGE-MATRIX.md 'Debt' section"

  if [[ ! "$ARGUMENTS" =~ --allow-intermediate ]]; then
    # v1.9.1 R2+R4: block-resolver — try L1 auto-fix (re-scan failed goals) before demanding user override.
    # If L1 fails, L2 architect proposal is presented through provider-native L3 prompt.
    # L4 only when L2 proposal rejected AND no user direction.
    # See _shared/lib/block-resolver.sh
    source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="review.4c-pre"
      BR_GATE_CONTEXT="NOT_SCANNED/FAILED goals block review exit. ${INTERMEDIATE} intermediate goals need conclusion (READY/BLOCKED/UNREACHABLE/INFRA_PENDING)."
      BR_EVIDENCE=$(printf '{"not_scanned":%d,"failed":%d,"total_intermediate":%d}' "$NOT_SCANNED_COUNT" "$FAILED_COUNT" "$INTERMEDIATE")
      BR_CANDIDATES='[{"id":"retry-failed-scan","cmd":"echo retry-failed auto-fix would re-trigger scanner for FAILED goals only; skipping in safe mode","confidence":0.5,"rationale":"retry-failed probe may reclassify goals without human override"}]'
      BR_RESULT=$(block_resolve "not-scanned-defer" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
      BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LEVEL" = "L1" ]; then
        echo "✓ Block resolver L1 self-resolved — intermediate goals auto-fixed"
      elif [ "$BR_LEVEL" = "L2" ]; then
        block_resolve_l2_handoff "not-scanned-defer" "$BR_RESULT" "$PHASE_DIR"
        echo "  Để proceed sau khi user chấp nhận proposal: re-run /vg:review ${PHASE_NUMBER} --allow-intermediate --reason='<applied proposal>'" >&2
        exit 2
      else
        # L4 truly stuck — print human-direction message
        block_resolve_l4_stuck "not-scanned-defer" "L1 failed + L2 produced no actionable proposal"
        exit 1
      fi
    else
      exit 1
    fi
  else
    # v1.9.0 T1: rationalization guard — NOT_SCANNED defer is a classic rationalization surface.
    RATGUARD_RESULT=$(rationalization_guard_check "not-scanned-defer" \
      "NOT_SCANNED = review didn't replay the goal sequence. Deferring = test codegen has no input. Auto-UNREACHABLE hides coverage debt." \
      "intermediate_goals=${INTERMEDIATE_GOALS} not_scanned=${NOT_SCANNED_COUNT} failed=${FAILED_COUNT}")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "not-scanned-defer" "--allow-intermediate" "$PHASE_NUMBER" "review.4c-pre" "${INTERMEDIATE} intermediate goals"; then
      exit 1
    fi
    # OHOK-8 round-4 Codex fix: update_goal_status was undefined function.
    # Replaced with real bash sed that rewrites matrix row in-place.
    # Auto-convert intermediate → UNREACHABLE với audit trail.
    TS=$(date -u +%FT%TZ)
    for gid in $INTERMEDIATE_GOALS; do
      # Match row `| G-XX |...|...|...| (NOT_SCANNED|FAILED) |`, replace
      # status column only. Preserve other columns. Use | delimiter in sed
      # to avoid conflicts with pipe chars in evidence.
      sed -i -E "s|^(\| ${gid} \|[^|]+\|[^|]+\|[^|]+\|)[[:space:]]*(NOT_SCANNED\|FAILED)[[:space:]]*\|(.*)$|\1 UNREACHABLE |review-skip-\2 @${TS}\3|" \
        "$MATRIX" 2>/dev/null || true
    done
    echo "intermediate-override: ${INTERMEDIATE} goals auto-converted UNREACHABLE ts=$(date -u +%FT%TZ)" \
      >> "${PHASE_DIR}/build-state.log"
  fi
fi
```

### 4c: Write GOAL-COVERAGE-MATRIX.md (v1.9.2.4 runnable merger)

```bash
# Call matrix-merger.sh helper — reads RUNTIME-MAP + probe-results + TEST-GOALS,
# computes per-goal status with priority precedence (browser > probe > code_exists),
# writes canonical GOAL-COVERAGE-MATRIX.md with summary + by-priority + details + gate.
source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/matrix-merger.sh" 2>/dev/null || true
if type -t merge_and_write_matrix >/dev/null 2>&1; then
  MERGE_OUTPUT=$(merge_and_write_matrix "$PHASE_DIR" \
    "${PHASE_DIR}/TEST-GOALS.md" \
    "${PHASE_DIR}/RUNTIME-MAP.json" \
    "${PHASE_DIR}/.surface-probe-results.json" \
    "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" 2>&1)

  # Extract machine-readable counts + verdict
  VERDICT=$(echo "$MERGE_OUTPUT" | grep '^VERDICT=' | cut -d= -f2)
  READY=$(echo "$MERGE_OUTPUT" | grep '^READY=' | cut -d= -f2)
  BLOCKED=$(echo "$MERGE_OUTPUT" | grep '^BLOCKED=' | cut -d= -f2)
  TEST_PENDING=$(echo "$MERGE_OUTPUT" | grep '^TEST_PENDING=' | cut -d= -f2)
  NOT_SCANNED=$(echo "$MERGE_OUTPUT" | grep '^NOT_SCANNED=' | cut -d= -f2)
  INTERMEDIATE=$(echo "$MERGE_OUTPUT" | grep '^INTERMEDIATE=' | cut -d= -f2)
  export VERDICT READY BLOCKED TEST_PENDING NOT_SCANNED INTERMEDIATE

  echo "✓ GOAL-COVERAGE-MATRIX.md: VERDICT=$VERDICT (ready=$READY blocked=$BLOCKED test_pending=$TEST_PENDING not_scanned=$NOT_SCANNED)"
else
  echo "⚠ matrix-merger.sh missing — falling back to manual matrix write (legacy path)"
  # Legacy path: orchestrator writes matrix directly using template below
fi

# Bind GOAL-COVERAGE-MATRIX.md + RUNTIME-MAP.json provenance to both runtime
# evidence and post-build lifecycle artifacts. This makes run-complete catch
# stale matrix reuse, lifecycle-spec drift, AND stale runtime-map reuse after
# review. Closes #175: must_write artifacts existed on disk but had no
# evidence-manifest entries → manual emit-evidence-manifest calls required.
EMIT_MANIFEST="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/emit-evidence-manifest.py"
[ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
if [ -f "$EMIT_MANIFEST" ]; then
  if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
    set +e
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/RUNTIME-MAP.json" \
      --producer "vg:review phase2b3_runtime_map" \
      --source-inputs "${PHASE_DIR}/nav-discovery.json,${PHASE_DIR}/TEST-GOALS.md"
    EMIT_RC=$?
    set -e
    if [ "$EMIT_RC" -ne 0 ]; then
      echo "⚠ manifest emit failed for RUNTIME-MAP.json (rc=${EMIT_RC})" >&2
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "review.manifest_emit_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"path\":\"RUNTIME-MAP.json\",\"rc\":${EMIT_RC}}" >/dev/null 2>&1 || true
    fi
  fi
  if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
    set +e
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" \
      --producer "vg:review step7_matrix_verdict" \
      --source-inputs "${PHASE_DIR}/TEST-GOALS.md,${PHASE_DIR}/RUNTIME-MAP.json,${PHASE_DIR}/.surface-probe-results.json,${PHASE_DIR}/DEEP-TEST-SPECS.md,${PHASE_DIR}/LIFECYCLE-SPECS.json,${PHASE_DIR}/TEST-FIXTURE-DAG.json,${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
    EMIT_RC=$?
    set -e
    if [ "$EMIT_RC" -ne 0 ]; then
      echo "⚠ manifest emit failed for GOAL-COVERAGE-MATRIX.md (rc=${EMIT_RC})" >&2
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "review.manifest_emit_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"path\":\"GOAL-COVERAGE-MATRIX.md\",\"rc\":${EMIT_RC}}" >/dev/null 2>&1 || true
    fi
  fi
fi

# Defense-in-depth: matrix-merger now downgrades shallow mutation sequences, but
# keep an explicit validator so legacy/hand-written RUNTIME-MAP files cannot
# mark create/update/delete goals READY from list-only evidence.
CRUD_DEPTH_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-runtime-map-crud-depth.py"
if [ -f "$CRUD_DEPTH_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp"
  "${PYTHON_BIN:-python3}" "$CRUD_DEPTH_VAL" --phase "${PHASE_NUMBER}" \
    > "${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json" 2>&1
  CRUD_DEPTH_RC=$?
  if [ "$CRUD_DEPTH_RC" != "0" ]; then
    echo "⛔ Runtime map CRUD depth gate failed — see ${PHASE_DIR}/.tmp/runtime-map-crud-depth-review.json"
    echo "   Mutation goals require observed POST/PUT/PATCH/DELETE + persistence proof."
    echo "   Re-run /vg:review ${PHASE_NUMBER} with deeper CRUD interaction before /vg:test."
    exit 1
  fi
fi

# v2.35.0 verdict gate hardening (closes #51) — 3 invariants replacing path-existence checks
# v3.4.0 (#173 Stage 4): verify-route-inventory added — hard-blocks when runtime route
# discovery diverges from UI-RUNTIME-CONTRACT.route_inventory (PASS-skips if contract missing).
# Override per-phase: --skip-content-invariants=<reason> logs OVERRIDE-DEBT
if [[ ! "$ARGUMENTS" =~ --skip-content-invariants ]]; then
  for VALIDATOR in verify-interface-standards verify-goal-security verify-goal-perf verify-security-baseline verify-haiku-scan-completeness verify-runtime-map-coverage verify-crud-runs-coverage verify-error-message-runtime verify-route-inventory; do
    VAL_PATH="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/${VALIDATOR}.py"
    if [ -f "$VAL_PATH" ]; then
      mkdir -p "${PHASE_DIR}/.tmp"
      VAL_OUT="${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic-input.txt"
      case "$VALIDATOR" in
        verify-interface-standards)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" > "$VAL_OUT" 2>&1
          ;;
        verify-error-message-runtime)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-goal-security|verify-goal-perf)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" > "$VAL_OUT" 2>&1
          ;;
        verify-security-baseline)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase "${PHASE_NUMBER}" --scope all > "$VAL_OUT" 2>&1
          ;;
        *)
          ${PYTHON_BIN:-python3} "$VAL_PATH" --phase-dir "$PHASE_DIR" > "$VAL_OUT" 2>&1
          ;;
      esac
      VAL_RC=$?
      cat "$VAL_OUT"
      if [ "$VAL_RC" -ne 0 ]; then
        echo ""
        echo "⛔ Verdict gate invariant FAILED: ${VALIDATOR}"
        echo "   v2.35.0 hardened gate: review cannot PASS with empty/incomplete artifacts."
        echo "   Either re-run /vg:review ${PHASE_NUMBER} with proper scanner/dispatch coverage,"
        echo "   or pass --skip-content-invariants=\"<reason>\" to log OVERRIDE-DEBT."
        DIAG_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-block-diagnostic.py"
        if [ -f "$DIAG_SCRIPT" ]; then
          "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
            --gate-id "review.${VALIDATOR}" \
            --phase-dir "$PHASE_DIR" \
            --input "$VAL_OUT" \
            --out-md "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" \
            >/dev/null 2>&1 || true
          cat "${PHASE_DIR}/.tmp/${VALIDATOR}-diagnostic.md" 2>/dev/null || true
        fi
        emit_telemetry_v2 "review_verdict_invariant_failed" "${PHASE_NUMBER}" \
          "review.4-verdict" "${VALIDATOR}" "BLOCK" "{}" 2>/dev/null || true
        exit 1
      fi
    fi
  done
fi

LENS_PLAN_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-lens-plan.py"
if [ -f "$LENS_PLAN_SCRIPT" ] && [[ ! "$ARGUMENTS" =~ --skip-lens-plan-gate ]]; then
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  "${PYTHON_BIN:-python3}" "$LENS_PLAN_SCRIPT" \
    --phase-dir "$PHASE_DIR" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    --mode "${REVIEW_MODE:-full}" \
    --validate-only \
    --json \
    > "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" 2>&1
  LENS_GATE_RC=$?
  if [ "$LENS_GATE_RC" -ne 0 ]; then
    echo ""
    echo "⛔ Review lens plan gate FAILED — required checklist plugins lack evidence."
    echo "   See ${PHASE_DIR}/.tmp/review-lens-plan-validation.json"
    DIAG_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/review-block-diagnostic.py"
    if [ -f "$DIAG_SCRIPT" ]; then
      "${PYTHON_BIN:-python3}" "$DIAG_SCRIPT" \
        --gate-id "review.lens_plan_gate" \
        --phase-dir "$PHASE_DIR" \
        --input "${PHASE_DIR}/.tmp/review-lens-plan-validation.json" \
        --out-md "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" \
        >/dev/null 2>&1 || true
      cat "${PHASE_DIR}/.tmp/review-lens-plan-diagnostic.md" 2>/dev/null || true
    fi
    echo "   Re-run /vg:review ${PHASE_NUMBER} --mode=full --force so API docs, browser inventory, URL-state/filter/paging, error-message, visual, and findings lenses execute."
    exit 1
  fi
fi

```

**Generated matrix format (canonical, from matrix-merger):**

```markdown
# Goal Coverage Matrix — Phase {phase}
**Generated:** {ISO-timestamp}
**Source:** RUNTIME-MAP.json + .surface-probe-results.json + LIFECYCLE-SPECS.json + TEST-FIXTURE-DAG.json + TEST-EXECUTION-PLAN.json
**Merger:** _shared/lib/matrix-merger.sh v2.65.1
**Lifecycle contracts consumed:** {N} goal(s); fixture nodes={N}; deep_specs_present={true|false}

## Summary
- Total goals: {N}
- READY: {N}
- BLOCKED: {N}
- NOT_SCANNED: {N} (intermediate)
- UNREACHABLE: {N}
- INFRA_PENDING: {N}
- FAILED: {N} (intermediate)

## By Priority
| Priority | Ready | Blocked | Other | Total | Threshold | Pass % | Status |
|----------|-------|---------|-------|-------|-----------|--------|--------|
| critical | {N} | {N} | {N} | {N} | 100% | {X%} | ✅ PASS/⛔ BLOCK |
| important | {N} | {N} | {N} | {N} | 80% | {X%} | ... |
| nice-to-have | {N} | {N} | {N} | {N} | 50% | {X%} | ... |

## Goal Details
| Goal | Priority | Surface | Status | Evidence |
|------|----------|---------|--------|----------|
| G-01 | critical | api | READY | handler=apps/api/src/... |

## Gate: ✅/⛔/⚠️ {VERDICT}
{PASS|BLOCK|INTERMEDIATE message with next-action hints}
```

### 4d: Inline triage + apply scope-tag actions (v1.14.0+ A.2)

Triage chạy **inline** ngay sau matrix ghi, TRƯỚC 100% gate. Mục đích: đọc scope tag (`depends_on_phase`, `verification_strategy`) từ CONTEXT.md, phân loại mỗi UNREACHABLE thành verdict + action_required, rồi áp dụng action nào autonomous được (mark_deferred/mark_manual). Các action cần người quyết định (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) sẽ ghi vào hàng đợi nhưng vẫn BLOCK gate — **không có đường thoát ngụỵ trang**.

```bash
session_mark_step "4d-inline-triage"
echo ""
echo "🔍 Triage + áp dụng action cho UNREACHABLE goals (v1.14.0+)..."

# v1.14.3 H3 — pre-scan test source for @deferred markers so triage sees them
# alongside scope tags. Fixes gap where executor-written it.skip('@deferred X')
# was ignored (tests were skipped but matrix still BLOCKED).
DEFER_SCANNER="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/scan-deferred-tests.py"
if [ -f "$DEFER_SCANNER" ]; then
  echo "▸ Pre-scan: @deferred markers in test source..."
  ${PYTHON_BIN:-python3} "$DEFER_SCANNER" \
    --phase-dir "${PHASE_DIR}" --repo-root "${REPO_ROOT:-.}" 2>&1 | tail -12 || true
  # Writes .deferred-tests.json — consumed by unreachable-triage below
fi

# Chạy triage (sinh .unreachable-triage.json + UNREACHABLE-TRIAGE.md)
source "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/unreachable-triage.sh" 2>/dev/null || true
if type -t triage_unreachable_goals >/dev/null 2>&1; then
  triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
else
  echo "⚠ unreachable-triage.sh missing — triage bị bỏ qua, 100% gate sẽ hard-block mọi UNREACHABLE." >&2
fi

TRIAGE_JSON="${PHASE_DIR}/.unreachable-triage.json"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

if [ -f "$TRIAGE_JSON" ] && [ -f "$MATRIX" ]; then
  # Áp dụng action_required autonomous: mark_deferred, mark_manual
  # Những action còn lại (spawn_fix_agent, draft_amendment_ask, prompt_scope_tag) ghi log + để BLOCK.
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$TRIAGE_JSON" "$MATRIX" "$PHASE_DIR" "$PHASE_NUMBER" <<'PY'
import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

triage_path = Path(sys.argv[1])
matrix_path = Path(sys.argv[2])
phase_dir   = Path(sys.argv[3])
phase_num   = sys.argv[4]

try:
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
except Exception as e:
    print(f"⚠ Không đọc được triage JSON: {e}")
    sys.exit(0)

verdicts = triage.get("verdicts", {})

# v1.14.3 H3 — merge .deferred-tests.json as additional deferral source
# (test files with it.skip('@deferred X') markers that aren't in CONTEXT.md scope tags).
deferred_tests_path = phase_dir / ".deferred-tests.json"
test_deferrals = {}  # ts_id → {reason, kind}
if deferred_tests_path.exists():
    try:
        dt = json.loads(deferred_tests_path.read_text(encoding="utf-8"))
        for entry in dt.get("deferred_tests", []):
            ts = entry.get("ts_id")
            if ts:
                test_deferrals[ts] = entry
    except Exception as e:
        print(f"⚠ Không đọc được .deferred-tests.json: {e}")

if not verdicts and not test_deferrals:
    print("ℹ Không có UNREACHABLE cần triage — skip.")
    sys.exit(0)

matrix_text = matrix_path.read_text(encoding="utf-8")
pending_queue = []   # cho các action chờ user / destructive
applied       = {"mark_deferred": [], "mark_manual": [], "pending": []}

def update_status_in_matrix(text, gid, new_status, note=""):
    # Tìm dòng trong ## Goal Details có `| G-XX | ... | UNREACHABLE | ... |`
    # Thay UNREACHABLE → new_status; append note vào evidence nếu có.
    pat = re.compile(r'^(\| *' + re.escape(gid) + r' *\|[^|]*\|[^|]*\|) *UNREACHABLE *(\|[^\n]*)', re.M)
    def _repl(m):
        prefix = m.group(1)
        suffix = m.group(2)
        if note:
            suffix = suffix.rstrip("|").rstrip() + f" ({note})|"
        return f"{prefix} {new_status} {suffix}"
    return pat.sub(_repl, text, count=1)

for gid, v in verdicts.items():
    action   = v.get("action_required")
    params   = v.get("action_params", {})
    verdict  = v.get("verdict", "")

    if action == "mark_deferred":
        target = params.get("target_phase", "?")
        matrix_text = update_status_in_matrix(matrix_text, gid, "DEFERRED", f"depends_on_phase: {target}")
        applied["mark_deferred"].append((gid, target))
    elif action == "mark_manual":
        strat = params.get("strategy", "manual")
        matrix_text = update_status_in_matrix(matrix_text, gid, "MANUAL", f"verification: {strat}")
        applied["mark_manual"].append((gid, strat))
    elif action in ("spawn_fix_agent", "draft_amendment_ask", "prompt_scope_tag"):
        # Giữ UNREACHABLE — gate sẽ block; ghi vào pending queue
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": verdict,
            "action":  action,
            "params":  params,
            "title":   v.get("title", "(no title)"),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, action))

# v1.14.3 H3 — apply test-level deferrals (fills gap where scope tags missing
# but test source has it.skip('@deferred X')). Status depends on defer_kind:
#   depends_on_phase + test-codegen → DEFERRED
#   manual + faketime               → MANUAL
#   unknown                         → log as pending, leave as UNREACHABLE
for ts_id, entry in test_deferrals.items():
    # ts_id is "TS-XX"; matrix may have goal_ids like "TS-16" or "G-XX" — try TS- first
    gid = ts_id
    kind = entry.get("defer_kind", "unknown")
    reason = entry.get("defer_reason", "")
    if kind in ("depends_on_phase", "test-codegen"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "DEFERRED",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_deferred"].append((gid, f"test-marker:{kind}"))
    elif kind in ("manual", "faketime"):
        matrix_text = update_status_in_matrix(
            matrix_text, gid, "MANUAL",
            f"test.skip @deferred: {reason[:50]}",
        )
        applied["mark_manual"].append((gid, kind))
    else:
        pending_queue.append({
            "phase":   phase_num,
            "goal_id": gid,
            "verdict": "test-level @deferred with unknown kind",
            "action":  "review_test_defer_reason",
            "params":  {"reason": reason, "source": entry.get("source_file", "")},
            "title":   entry.get("test_title", ""),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        applied["pending"].append((gid, "test-defer-unknown"))

# Re-sync header counts trong "## Summary" block nếu có thay đổi
def recount_summary(text):
    details = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
    if not details:
        return text
    body = details.group(1)
    counts = {"READY":0, "BLOCKED":0, "UNREACHABLE":0, "INFRA_PENDING":0,
              "DEFERRED":0, "MANUAL":0, "NOT_SCANNED":0, "FAILED":0}
    for line in body.splitlines():
        for k in counts:
            # Status cell đứng giữa 2 dấu | — tránh match keyword trong evidence
            if re.search(r'\|\s*' + k + r'\s*\|', line):
                counts[k] += 1
                break
    def _rewrite_summary(m):
        total = sum(counts.values())
        new = [
            "## Summary",
            f"- Total goals: {total}",
            f"- READY: {counts['READY']}",
            f"- DEFERRED: {counts['DEFERRED']} (tagged depends_on_phase)",
            f"- MANUAL: {counts['MANUAL']} (tagged verification_strategy)",
            f"- BLOCKED: {counts['BLOCKED']}",
            f"- UNREACHABLE: {counts['UNREACHABLE']}",
            f"- INFRA_PENDING: {counts['INFRA_PENDING']}",
            f"- NOT_SCANNED: {counts['NOT_SCANNED']} (intermediate)",
            f"- FAILED: {counts['FAILED']} (intermediate)",
            ""
        ]
        return "\n".join(new)
    new_text = re.sub(r'^## Summary\n(?:[-*].*\n)+', _rewrite_summary, text, count=1, flags=re.M)
    return new_text

matrix_text = recount_summary(matrix_text)
matrix_path.write_text(matrix_text, encoding="utf-8")

# Ghi pending queue vào .vg/PENDING-USER-REVIEW.md (append-only)
if pending_queue:
    pending_file = Path(".vg/PENDING-USER-REVIEW.md")
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not pending_file.exists()
    with pending_file.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("# Pending user review — hàng đợi quyết định đang chờ\n\n")
            f.write("Mỗi mục là một goal cần quyết định (scope tag / fix / amendment). ")
            f.write("User review xong → duyệt queue thay vì bị hỏi từng cái.\n\n")
            f.write("| Phase | Goal | Verdict | Action cần | Tiêu đề | Queued at |\n")
            f.write("|---|---|---|---|---|---|\n")
        for p in pending_queue:
            f.write(f"| {p['phase']} | {p['goal_id']} | {p['verdict']} | {p['action']} | "
                    f"{p['title'][:60]} | {p['queued_at']} |\n")

# Narration
print(f"▸ Triage applied: "
      f"{len(applied['mark_deferred'])} → DEFERRED, "
      f"{len(applied['mark_manual'])} → MANUAL, "
      f"{len(applied['pending'])} → chờ người duyệt")
for gid, tgt in applied["mark_deferred"]:
    print(f"  🔁 {gid} → DEFERRED (depends_on_phase: {tgt})")
for gid, strat in applied["mark_manual"]:
    print(f"  ✋ {gid} → MANUAL ({strat})")
for gid, act in applied["pending"]:
    print(f"  ⏳ {gid} → {act} (giữ UNREACHABLE, gate sẽ BLOCK đến khi giải quyết)")
PY
else
  [ -f "$TRIAGE_JSON" ] || echo "ℹ Không có triage JSON (không UNREACHABLE goal nào) — skip apply."
fi
```

### 4e: Cổng 100% (hard, v1.14.0+ A.3)

Thay gate trọng số (critical/important/nice-to-have) cũ bằng quy tắc đơn giản:

- **ĐẠT (PASS)** khi `BLOCKED == 0` VÀ `UNREACHABLE == 0` (goals ở trạng thái kết thúc: READY + DEFERRED + MANUAL + INFRA_PENDING).
- **BỊ CHẶN (BLOCK)** khi còn bất kỳ goal `BLOCKED` hoặc `UNREACHABLE`.

Không còn grey zone — DEFERRED và MANUAL là hai đường thoát hợp lệ nhưng phải declare ở `/vg:scope`, không phải review tự gắn.

```bash
session_mark_step "4e-100pct-gate"
MATRIX="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"

# Đọc config gate threshold (default 100, legacy-mode fallback 80)
GATE_THRESHOLD=$(${PYTHON_BIN} -c "
import re, sys
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold\s*:\s*(\d+)', c)
    print(m.group(1) if m else '100')
except Exception:
    print('100')
")

# Legacy-mode override: --legacy-mode flag hoặc config review.gate_threshold_legacy
if [[ "$ARGUMENTS" =~ --legacy-mode ]]; then
  GATE_THRESHOLD_LEGACY=$(${PYTHON_BIN} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'gate_threshold_legacy\s*:\s*(\d+)', c)
    print(m.group(1) if m else '80')
except Exception:
    print('80')
")
  echo "⚠ --legacy-mode: dùng ngưỡng ${GATE_THRESHOLD_LEGACY}% (pre-v1.14). Flag này sẽ hết hạn sau 2 milestones."
  GATE_THRESHOLD="$GATE_THRESHOLD_LEGACY"
fi

# Count statuses từ matrix
if [ -f "$MATRIX" ]; then
  GATE_COUNTS=$(PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$MATRIX" <<'PY'
import re, sys, json
text = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)', text, re.M|re.S)
body = m.group(1) if m else ""
buckets = ["READY","DEFERRED","MANUAL","BLOCKED","UNREACHABLE","INFRA_PENDING","NOT_SCANNED","FAILED"]
counts = {b:0 for b in buckets}
for line in body.splitlines():
    for b in buckets:
        if re.search(r'\|\s*' + b + r'\s*\|', line):
            counts[b] += 1
            break
print(json.dumps(counts))
PY
)
  READY=$(echo "$GATE_COUNTS"        | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['READY'])")
  DEFERRED=$(echo "$GATE_COUNTS"     | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['DEFERRED'])")
  MANUAL=$(echo "$GATE_COUNTS"       | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['MANUAL'])")
  BLOCKED=$(echo "$GATE_COUNTS"      | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['BLOCKED'])")
  UNREACHABLE=$(echo "$GATE_COUNTS"  | ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['UNREACHABLE'])")
  INFRA_PENDING=$(echo "$GATE_COUNTS"| ${PYTHON_BIN} -c "import json,sys;print(json.loads(sys.stdin.read())['INFRA_PENDING'])")

  TOTAL=$((READY + DEFERRED + MANUAL + BLOCKED + UNREACHABLE + INFRA_PENDING))
  # Goals được tính là "kết thúc": READY + DEFERRED + MANUAL + INFRA_PENDING
  PASS_COUNT=$((READY + DEFERRED + MANUAL + INFRA_PENDING))
  FAIL_COUNT=$((BLOCKED + UNREACHABLE))

  if [ "$TOTAL" -gt 0 ]; then
    PASS_PCT=$(( PASS_COUNT * 100 / TOTAL ))
  else
    PASS_PCT=0
  fi

  echo ""
  echo "━━━ Cổng kiểm tra (${GATE_THRESHOLD}%) ━━━"
  echo "  Tổng goals:    $TOTAL"
  echo "  ✅ READY:      $READY"
  echo "  🔁 DEFERRED:   $DEFERRED (tagged depends_on_phase)"
  echo "  ✋ MANUAL:     $MANUAL (tagged verification_strategy)"
  echo "  ♻ INFRA:      $INFRA_PENDING (ngoài ENV hiện tại)"
  echo "  ⛔ BLOCKED:    $BLOCKED"
  echo "  ❓ UNREACHABLE:$UNREACHABLE"
  echo "  Tỉ lệ đạt:    ${PASS_PCT}% (yêu cầu ≥${GATE_THRESHOLD}%)"
  echo ""

  export GATE_THRESHOLD PASS_COUNT FAIL_COUNT PASS_PCT TOTAL
  export READY DEFERRED MANUAL BLOCKED UNREACHABLE INFRA_PENDING
else
  echo "⚠ GOAL-COVERAGE-MATRIX.md không tồn tại — không tính được gate."
  export FAIL_COUNT=999 PASS_PCT=0 GATE_THRESHOLD=100
fi
```

### 4f: Quyết định cổng (100% hard)

```bash
session_mark_step "4f-gate-decision"

# Quy tắc:
#   GATE_THRESHOLD == 100 (default)  → PASS iff FAIL_COUNT == 0
#   GATE_THRESHOLD <  100 (legacy)   → PASS iff PASS_PCT >= threshold
if [ "$GATE_THRESHOLD" = "100" ]; then
  GATE_PASS=$([ "$FAIL_COUNT" -eq 0 ] && echo "true" || echo "false")
else
  GATE_PASS=$([ "$PASS_PCT" -ge "$GATE_THRESHOLD" ] && echo "true" || echo "false")
fi

if [ "$GATE_PASS" = "true" ]; then
  echo "✅ Cổng ĐẠT — phase sẵn sàng cho /vg:test ${PHASE_NUMBER}"
  echo ""

  # v1.14.0+ A.4 — write trigger cho CROSS-PHASE-DEPS aggregator
  # Nếu có goal DEFERRED → append vào .vg/CROSS-PHASE-DEPS.md (idempotent)
  if [ "$DEFERRED" -gt 0 ]; then
    CPD_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg_cross_phase_deps.py"
    if [ -f "$CPD_SCRIPT" ]; then
      PYTHONIOENCODING=utf-8 ${PYTHON_BIN} "$CPD_SCRIPT" append "$PHASE_NUMBER" 2>&1 | sed 's/^/  /'
    else
      echo "⚠ vg_cross_phase_deps.py missing — DEFERRED entries không được aggregate." >&2
    fi
    echo "ℹ Có $DEFERRED goal DEFERRED (chờ phase phụ thuộc). Xem .vg/CROSS-PHASE-DEPS.md"
  fi
  if [ "$MANUAL" -gt 0 ]; then
    echo "ℹ Có $MANUAL goal MANUAL. /vg:accept sẽ prompt checklist người dùng."
  fi
  if [ "$INFRA_PENDING" -gt 0 ]; then
    echo "ℹ Có $INFRA_PENDING goal chờ infra (ngoài ENV). Re-run với --sandbox nếu cần."
  fi
else
  echo "⛔ Cổng BỊ CHẶN — còn $FAIL_COUNT goal chưa kết thúc."
  echo ""

  # Gợi ý hành động theo loại fail
  if [ "$BLOCKED" -gt 0 ]; then
    echo "  🛠 $BLOCKED goal BLOCKED (scan chạy nhưng criteria fail):"
    echo "     → Sửa code → re-run /vg:review ${PHASE_NUMBER} --fix-only"
  fi
  if [ "$UNREACHABLE" -gt 0 ]; then
    echo "  ❓ $UNREACHABLE goal UNREACHABLE (không reach được UI hoặc chưa build):"
    echo "     → Đọc ${PHASE_DIR}/UNREACHABLE-TRIAGE.md — mỗi goal có verdict + action gợi ý"
    echo "     → cross-phase-pending    → /vg:amend ${PHASE_NUMBER} thêm depends_on_phase tag"
    echo "     → bug-this-phase         → /vg:build ${PHASE_NUMBER} --gaps-only"
    echo "     → scope-amend destructive→ user confirm amendment rồi re-run review"

    # Nếu có pending queue, nhắc
    if [ -f ".vg/PENDING-USER-REVIEW.md" ]; then
      PENDING_CNT=$(grep -c "^| ${PHASE_NUMBER} " ".vg/PENDING-USER-REVIEW.md" 2>/dev/null || echo 0)
      [ "$PENDING_CNT" -gt 0 ] && echo "     → $PENDING_CNT mục đang chờ người duyệt (.vg/PENDING-USER-REVIEW.md)"
    fi
  fi

  echo ""
  echo "Không còn đường thoát tự động — scope tag phải declare ở /vg:scope (không phải review tự gán)."

  # Exit với mã lỗi để caller biết gate fail
  exit 1
fi
```
</step>
