# review fix-loop (STEP 6 — max 3 iterations + L2 diagnostic fallback)

Single step `phase3_fix_loop` covers the iterative fix-route-redeploy-
reverify cycle. 3-tier severity routing (MINOR inline / MODERATE spawn /
MAJOR escalate) with config-driven model selection (no hardcoded
vendor/tier names).

<HARD-GATE>
You MUST cap at 3 iterations. On iter-3 exhaustion with errors still
remaining, do NOT silent-BLOCK — spawn `diagnostic_l2` (RFC v9 D11 + D26
single-advisory pattern). The L2 proposal is user-gated; never auto-
apply (project policy — L2 was wrong in dogfood 3.2).

Spawn tool name is `Agent` (NOT `Task`) per plan §C — Codex correction.
The `model="$SPAWN_MODEL"` argument reads from `config.models.review_fix_spawn`
or falls back to `config.models.executor`. NEVER hardcode "Sonnet" /
"Haiku" / "GPT-4o" / etc.

Tripwire on MINOR-inline fixes >config.review.fix_routing.tripwire.minor_bloat_loc
re-classifies upward (warn or rollback per config) — closes the LLM
"casual MINOR misclassification" gap.

vg-load convention: per-fix context loading (when MODERATE spawn needs
to understand the failed goal) should call `vg-load --phase
${PHASE_NUMBER} --artifact goals --goal G-NN` instead of flat reading
TEST-GOALS.md. Spawned subagent prompts include this hint
(implementation lives inside spawn prompt template — Phase A deferred).
</HARD-GATE>

---

## STEP 6.1 — phase3_fix_loop

<step name="phase3_fix_loop" mode="full">
## Phase 3: FIX LOOP (max 3 iterations)

→ `narrate_phase "Phase 3 — Fix loop (iteration ${I}/3)" "Sửa bug MINOR, escalate MODERATE/MAJOR"`

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active phase3_fix_loop >/dev/null 2>&1 || true
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
```
SPAWN_MODEL="${config.models.review_fix_spawn:-${config.models.executor}}"

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
  - Use vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN for
    goal context instead of cat TEST-GOALS.md

  ## RETURN
  - Files changed (list)
  - LOC delta
  - One-line summary
  """

narrate_fix "[spawn:sonnet] ${severity} ${bug_title}"
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
     ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
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

### 3e: Iterate

Repeat 3a-3d until:
- RUNTIME-MAP is **stable** (no new errors between 2 iterations)
- Zero CODE BUG errors remaining
- Max 3 iterations reached

Display after each iteration:
```
Fix iteration {N}/3:
  Errors fixed: {N}
  Errors remaining: {N} (infra: {N}, spec-gap: {N}, pre-existing: {N})
  Sonnet agents spawned: {N} (re-verified {M} views)
  New errors found: {N}
  Matrix coverage: {review_passed}/{total} goals
  Map stable: {YES|NO}
```

### 3e: Iter limit fallback — Diagnostic L2 (RFC v9 D11 + D26, PR-E)

When iter 3 exits with errors STILL remaining (loop hit cap without
self-resolving), do NOT silent-BLOCK. Spawn diagnostic_l2 single-advisory
fallback:

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
6. User accept → apply fix → re-run iter 4 (one extra iteration grace).
7. User reject → BLOCK with full audit trail in
   `.l2-proposals/{proposal_id}.json` + DEFECT-LOG entry referencing
   the proposal.

```bash
if [ "${ITER:-1}" -eq 3 ] && [ -n "${REMAINING_ERRORS}" ] && \
   { [ -f "${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py" ] || [ -f "${REPO_ROOT}/scripts/spawn-diagnostic-l2.py" ]; }; then
  echo "━━━ Phase 3e — Diagnostic L2 fallback (iter 3 hit cap) ━━━"
  DIAGNOSTIC_L2="${REPO_ROOT}/.claude/scripts/spawn-diagnostic-l2.py"
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
    TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
    [ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
    if [ -f "$TESTER_PRO_CLI" ]; then
      "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" defect new \
        --phase "${PHASE_NUMBER}" \
        --title "[ITER-LIMIT] Fix loop hit max=3, L2 proposal $L2_PROPOSAL_ID" \
        --severity major --found-in review \
        --notes "L2 proposal at .l2-proposals/${L2_PROPOSAL_ID}.json — user decision pending" \
        2>&1 | sed 's/^/  /' || true
    fi
    # User gate is provider-native after spawn-diagnostic-l2.py:
    # Claude Code uses AskUserQuestion; Codex asks in the main thread/UI.
    # On accept → run-complete sees applied; on reject → BLOCK below.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
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
