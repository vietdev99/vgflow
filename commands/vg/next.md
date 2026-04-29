---
name: vg:next
description: Auto-detect current V5 pipeline step and advance to the next
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - SlashCommand
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "next.started"
    - event_type: "next.completed"
---

<objective>
Detect current position in the 7-step phase pipeline and immediately invoke the next command.

Pipeline order: specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="load_config">
**Config:** Read .claude/commands/vg/_shared/config-loader.md first.
</step>

<step name="detect_state">
Read `${PLANNING_DIR}/STATE.md` and `${PLANNING_DIR}/ROADMAP.md`.

Extract `current_phase` and `phase_dir`.

If `${PLANNING_DIR}/` does not exist or STATE.md is missing:
  - Output: "No VG project detected. Run /vg:project to initialize."
  - STOP.
</step>

<step name="detect_pipeline_position">
**Phase reconnaissance — recon-driven routing (replaces binary file-exists checks).**

Follow `.claude/commands/vg/_shared/phase-recon.md`.

```bash
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet

PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
NEXT_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
HAS_PRE_ACTION=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print('yes' if s['recommended_action'].get('pre_action') else 'no')
")
```

**Route 0 (priority):** `STATE.md` shows `paused_at` field
→ Read PIPELINE-STATE.json. Resume logic (tightened 2026-04-17 — field-specific):

```bash
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
if [ -f "$PIPELINE_STATE" ]; then
  # Priority 1: find first step with status == "in_progress" (explicit pause)
  RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
for st in order:
    if steps.get(st, {}).get('status') == 'in_progress':
        print(st); break
")
  # Priority 2: if no in_progress, find last step with status == "done", resume from next
  if [ -z "$RESUME_STEP" ]; then
    RESUME_STEP=$(${PYTHON_BIN} -c "
import json
s = json.load(open('${PIPELINE_STATE}', encoding='utf-8'))
steps = s.get('steps', {})
order = ['specs','scope','blueprint','build','review','test','accept']
last_done = -1
for i, st in enumerate(order):
    if steps.get(st, {}).get('status') == 'done':
        last_done = i
next_step = order[last_done + 1] if last_done + 1 < len(order) else 'complete'
print(next_step)
")
  fi
else
  RESUME_STEP="scope"  # no state, start from beginning
fi

echo "Resume from: /vg:${RESUME_STEP} {phase}"
```

→ Next: `/vg:${RESUME_STEP} {phase}`

**⛔ Deferred-incomplete gate (tightened 2026-04-17):**

Before advancing to a NEW phase, check current phase for `.deferred-incomplete` marker:

```bash
CURRENT_PHASE_DIR="${PHASE_DIR}"  # from recon
if [ -f "${CURRENT_PHASE_DIR}/.deferred-incomplete" ]; then
  if [[ ! "$ARGUMENTS" =~ --allow-deferred ]]; then
    echo "⛔ Phase ${PHASE_NUMBER} is DEFERRED-INCOMPLETE — cannot advance."
    echo "   Open items in ${CURRENT_PHASE_DIR}/${PHASE_NUMBER}-UAT.md"
    echo "   Resolve with: /vg:accept ${PHASE_NUMBER} --resume"
    echo "   Force advance (creates tech debt): /vg:next --allow-deferred"
    exit 1
  else
    echo "⚠ --allow-deferred set — advancing with ${PHASE_NUMBER} still deferred. Tech debt recorded."
    echo "next-advance-with-deferred: ${PHASE_NUMBER} ts=$(date -u +%FT%TZ)" >> ${PLANNING_DIR}/deferred-debt.log
  fi
fi
```

**Route 0b (legacy/hybrid):** `HAS_PRE_ACTION == "yes"` (recon found legacy artifacts)
→ Display: "Phase {N} has legacy GSD artifacts — run `/vg:migrate {N}` to convert to VG format."
→ Show what's missing: API-CONTRACTS.md, TEST-GOALS.md, enriched CONTEXT.md
→ Do NOT auto-invoke migration. `/vg:next` is fast — migrations require interactive approval via `/vg:migrate`.

**Route 0c (semantic enrichment gap, v1.14.0+):** Phase already migrated (no GSD legacy files) BUT TEST-GOALS missing v1.14.0 semantic fields (Persistence check, Surface classification, Plan-Goal linkage).

```bash
VERIFY_SCRIPT=""
[ -f "${REPO_ROOT}/.claude/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
[ -f "${REPO_ROOT}/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"

if [ -n "$VERIFY_SCRIPT" ] && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  SEMANTIC_JSON=$(${PYTHON_BIN:-python3} "$VERIFY_SCRIPT" --json "$PHASE_DIR" 2>/dev/null)
  FAIL_GATES=$(echo "$SEMANTIC_JSON" | ${PYTHON_BIN:-python3} -c "import sys,json; d=json.loads(sys.stdin.read()); print(','.join(r['name'] for r in d.get('results',[]) if r.get('status')=='FAIL'))" 2>/dev/null)
  if [ -n "$FAIL_GATES" ]; then
    echo "⚠ Phase ${PHASE_NUMBER}: v1.14.0 semantic gaps detected — ${FAIL_GATES}"
    echo "  Re-run /vg:migrate ${PHASE_NUMBER} --force để enrich (preserves existing decisions/goals)."
    echo "  Skip để continue pipeline với debt — but blueprint/build sẽ block khi gặp Rule 3b/Surface gates."
  fi
fi
```

Display only — không block. User decision: re-migrate (recommended) hay skip.

**Recon routes** (derived from `NEXT_STEP`):
- `NEXT_STEP == "scope"` → Next: `/vg:scope {phase}`
- `NEXT_STEP == "blueprint"` → Next: `/vg:blueprint {phase}`
- `NEXT_STEP == "build"` → Next: `/vg:build {phase}`
- `NEXT_STEP == "review"` → Next: `/vg:review {phase}` (see Cross-CLI option below)
- `NEXT_STEP == "test"` → Next: `/vg:test {phase}`
- `NEXT_STEP == "accept"` → Next: `/vg:accept {phase}`
- `NEXT_STEP == "complete"` → Phase done (check Route 8/9)

**Review cross-CLI option** (only when NEXT_STEP == "review"):
Display cross-CLI option:
→ Display cross-CLI option:
```
  **Review options:**
  A) Standard:  `/vg:review {phase}` — Claude does full review (discovery + evaluate + fix)
  B) Cross-CLI: Split work across AI CLIs for lower cost:
     1. Codex:  `$vg-review {phase} --discovery-only`  — Codex does discovery (cheap, has MCP browser)
     2. Claude: `/vg:review {phase} --evaluate-only`   — Claude reads scan results, evaluates + fixes
     
     Or Gemini: `/vg-review {phase} --discovery-only`  — same flow, Gemini does discovery
  
  Option B saves ~60-70% tokens on Claude (no browser interaction).
  
  Flag: add `--full-scan` to disable snapshot pruning (default: pruning ON, saves 50-70% tokens).
  Use --full-scan only when app has non-standard layout or no <main> selector.
```

**Route 5b:** `RUNTIME-MAP.json` exists + `GOAL-COVERAGE-MATRIX.md` exists + gate = BLOCK (goals < 100%)
→ Review ran but goals not met. Auto-detect cause from artifacts:

```
Read discovery-state.json → completed_phase field
Read GOAL-COVERAGE-MATRIX.md → goal statuses (READY / BLOCKED / UNREACHABLE / FAILED)
Read RUNTIME-MAP.json → goal_sequences[goal_id].start_view for each failed goal

SIGNAL 1 — discovery-state.json.completed_phase ≠ "investigate":
  → Review was INTERRUPTED (token exhaustion / session died mid-scan)
  → Auto-invoke: /vg:review {phase} --resume
  → No user choice needed.

SIGNAL 2 — completed_phase == "investigate" (review fully completed):
  Classify failed goals (4 distinct statuses — verify code presence before assuming):
    UNREACHABLE = goal has no start_view AND code for page/route NOT found in repo
                  (feature genuinely not built — grep config.code_patterns returns nothing)
    NOT_SCANNED = goal has no start_view BUT code for page/route DOES exist
                  (review didn't replay — multi-step wizard, orphan route, timeout, retry-scope miss)
    BLOCKED/FAILED = goal has start_view but result=failed
                     (view found, scan ran, criteria not met → code bug)
```

**Display to user (explain, then action):**

```
⚠ Phase {N} gate BLOCKED — {X}/{total} goals failed.

┌─ What the failure types mean ─────────────────────────────────┐
│ UNREACHABLE ({N})  Code for page/route NOT in repo (verified) │
│                    → Feature not built yet                    │
│                    → Fix: /vg:build {phase} --gaps-only       │
│                                                               │
│ NOT_SCANNED ({N})  Code EXISTS but review didn't replay       │
│                    (multi-step wizard/mutation, orphan route, │
│                     Haiku timeout, retry scope missed goal)   │
│                    → Fix: /vg:test {phase} (codegen walks)    │
│                         or --retry-failed (re-scan only)      │
│                                                               │
│ BLOCKED ({N})      View found, but goal criteria not met      │
│                    (form didn't submit, API error, etc.)      │
│                    → Code has a bug — fix and re-scan         │
│                                                               │
│ INTERRUPTED        Review died mid-scan (token/timeout)       │
│                    → Just resume where it left off            │
└───────────────────────────────────────────────────────────────┘

Failed goals:
  [UNREACHABLE] {goal_id}: {goal_desc}
  [NOT_SCANNED] {goal_id}: {goal_desc} (code: {path/to/page.tsx})
  [BLOCKED]     {goal_id}: {goal_desc} (view: {start_view})
  ...
```

**Then route by classification:**

```
IF all UNREACHABLE (code confirmed missing):
  → Auto-invoke: /vg:build {phase} --gaps-only
  Print: "All failures UNREACHABLE — feature missing. Auto-building gaps..."
  After build completes → re-run /vg:review {phase}

IF all NOT_SCANNED (code exists, review skipped):
  Print: "All failures NOT_SCANNED — code built but review didn't replay."
  Display (do NOT auto-invoke — user picks based on root cause):
    Common cause 1: Multi-step wizard/mutation needs dedicated browser session
      → /vg:test {phase}
        (codegen + Playwright auto-walks wizard, fills all steps, verifies goal)
    Common cause 2: Timeout or retry-scope missed the goal
      → /vg:review {phase} --retry-failed
        (fresh re-scan of only failed views)
    DO NOT run /vg:build --gaps-only — code already exists.

IF all BLOCKED (code bugs — user fix required first):
  Print: "All failures BLOCKED — code bugs in {N} views. Workflow:"
  Display (do NOT auto-invoke):
    Step 1: Fix the code (inspect logs/network errors in GOAL-COVERAGE-MATRIX.md)
    Step 2: Re-scan ONLY failed views: /vg:review {phase} --retry-failed
            (~5-10x faster than full review — skips passed views)
    Cross-CLI option: $vg-review {phase} --retry-failed --discovery-only
                    → /vg:review {phase} --evaluate-only

IF mix (any combination):
  Print: "Mixed failures — handle in order:"
  Display (do NOT auto-invoke):
    Step 1: /vg:build {phase} --gaps-only       ← if UNREACHABLE exists, build first
    Step 2: Fix code for BLOCKED goals (list shown above)
    Step 3: /vg:test {phase}                     ← if NOT_SCANNED exists (codegen for complex flows)
    Step 4: /vg:review {phase} --retry-failed   ← re-verify everything
```

**Route 6:** `RUNTIME-MAP.json` + `RUNTIME-MAP.md` exist + GOAL-COVERAGE-MATRIX gate = PASS + no `*-SANDBOX-TEST.md`
→ Next: `/vg:test {phase}`
Note: RUNTIME-MAP.json is the canonical artifact — .md alone is NOT sufficient for /vg:test.

**Route 7:** `*-SANDBOX-TEST.md` exists but no `*-UAT.md` OR UAT status != "complete"
→ Next: `/vg:accept {phase}`

**Route 8:** UAT complete AND next phase exists in ROADMAP.md AND next phase has NO `SPECS.md`
→ Next: `/vg:specs {next_phase}`

**Route 8b:** UAT complete AND next phase has `SPECS.md` but NO `CONTEXT.md`
→ Next: `/vg:scope {next_phase}`

**Route 9:** All phases complete
→ Next: `/vg:complete-milestone {M}` (close + audit + summary + archive — v2.33.0+)
   Then: `/vg:project --milestone` to scope the next milestone
</step>

<step name="show_and_execute">
Display current status with artifact checklist, then IMMEDIATELY invoke.

```
## VG Next (V6)

**Current:** Phase {N} — {name}
**Phase type:** {PHASE_TYPE} (from recon)
**Pipeline position (from .recon-state.json):**
  scope:     {status} {v6_artifacts}
  blueprint: {status} {v6_artifacts}
  build:     {status} {v6_artifacts}
  review:    {status} {v6_artifacts}
  test:      {status} {v6_artifacts}
  accept:    {status} {v6_artifacts}

▶ **Next step:** `/vg:{NEXT_STEP} {phase}`
  {recommended_action.reason from recon}
```

Pipeline position is read from `.recon-state.json` (per-step status: done|partial|missing|legacy_only).
IMMEDIATELY invoke the next command. No confirmation prompt (except legacy migration which redirects to /vg:phase).
</step>

</process>

<success_criteria>
- Config loaded
- State detected from files
- Pipeline position determined
- Status displayed with V5 artifact checklist
- Next command invoked immediately
</success_criteria>
