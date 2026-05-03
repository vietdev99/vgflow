---
name: vg:amend
description: Mid-phase change request — discuss changes, update CONTEXT.md decisions, cascade impact analysis
argument-hint: "<phase>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "amend.started"
    - event_type: "amend.completed"
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **AMENDMENT-LOG is append-only** — never overwrite previous amendments, only append.
4. **CONTEXT.md patch, not regenerate** — apply surgical edits to decision list, do NOT rewrite the file.
5. **Git tag before modify** — always create a rollback tag before touching CONTEXT.md.
6. **Impact is informational** — cascade analysis warns but does NOT auto-modify PLAN.md or API-CONTRACTS.md.
</rules>

<objective>
Mid-pipeline change request handler. When requirements shift or decisions need revision during an active phase, this command:
1. Detects current pipeline step
2. Discusses changes with user
3. Writes AMENDMENT-LOG.md (append)
4. Patches CONTEXT.md decisions
5. Analyzes cascade impact on downstream artifacts
6. Tags + commits

Pipeline: specs → scope → blueprint → build → review → test → accept
Amend can run at ANY point after scope.
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_detect">
## Step 0: Parse phase argument + detect current pipeline step

```bash
PHASE_NUMBER="$1"
PHASE_DIR="${PHASES_DIR}/${PHASE_NUMBER}-*"
# Resolve glob to actual directory
PHASE_DIR=$(ls -d ${PHASES_DIR}/${PHASE_NUMBER}-* 2>/dev/null | head -1)

if [ -z "$PHASE_DIR" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "BLOCK: Phase ${PHASE_NUMBER} directory not found in ${PHASES_DIR}/"
  exit 1
fi
```

Detect current step by checking which artifacts exist (ordered latest → earliest):

```bash
CURRENT_STEP="unknown"
[ -f "${PHASE_DIR}/UAT.md" ]              && CURRENT_STEP="accepted"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SANDBOX-TEST.md" ]    && CURRENT_STEP="tested"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]   && CURRENT_STEP="reviewed"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SUMMARY.md" -o -f "${PHASE_DIR}/SUMMARY-wave1.md" ] && CURRENT_STEP="built"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/PLAN.md" ]            && CURRENT_STEP="blueprinted"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/CONTEXT.md" ]         && CURRENT_STEP="scoped"
[ "$CURRENT_STEP" = "unknown" ] && [ -f "${PHASE_DIR}/SPECS.md" ]           && CURRENT_STEP="specced"
```

Validate: CONTEXT.md MUST exist (amend modifies decisions — no decisions = nothing to amend).
Missing → BLOCK: "Phase ${PHASE_NUMBER} has no CONTEXT.md. Run `/vg:scope ${PHASE_NUMBER}` first."

Display: `"Phase ${PHASE_NUMBER} — current step: ${CURRENT_STEP}"`

Count existing amendments:
```bash
AMENDMENT_COUNT=0
if [ -f "${PHASE_DIR}/AMENDMENT-LOG.md" ]; then
  AMENDMENT_COUNT=$(grep -c '^## Amendment #' "${PHASE_DIR}/AMENDMENT-LOG.md" 2>/dev/null || echo 0)
fi
NEXT_AMENDMENT=$((AMENDMENT_COUNT + 1))
```
</step>

<step name="1_change_type">
## Step 1: What to change?

```
AskUserQuestion:
  header: "Amendment #${NEXT_AMENDMENT} — Phase ${PHASE_NUMBER} (step: ${CURRENT_STEP})"
  question: "What kind of change?"
  options:
    - "Add feature/endpoint" — new functionality not in original scope
    - "Modify decision" — change an existing D-XX decision
    - "Remove feature" — descope something (defer to later phase or drop)
    - "Change technical approach" — different implementation for same goal
```

Store: `$CHANGE_TYPE` = selected option.
</step>

<step name="2_discussion">
## Step 2: Discuss change details

Read current CONTEXT.md → extract all D-XX decisions into memory.

```
AskUserQuestion:
  header: "Change Details"
  question: "Describe the change. I'll show which decisions (D-XX) are affected."
  (open text)
```

AI analyzes user's description against existing decisions:
- List D-XX decisions that this change touches (show current text)
- Identify new decisions needed (propose D-XX IDs continuing from max)
- Identify decisions to remove/defer (show what will be dropped)
- Flag any contradictions with remaining decisions

Present summary:
```
Amendment #${NEXT_AMENDMENT} impact on decisions:
  MODIFY: D-05 — was: "Use MongoDB aggregation for reports" → proposed: "Use ClickHouse for reports"
  ADD:    D-12 — "Add /api/reports/export endpoint for CSV download"
  REMOVE: D-08 — "Client-side PDF generation" (deferred to phase {X})
  
Confirm these changes?
```

```
AskUserQuestion:
  header: "Confirm"
  question: "Proceed with these decision changes?"
  options:
    - "Yes — apply changes"
    - "Adjust — let me modify"
    - "Cancel — abort amendment"
```

If "Adjust" → loop back to discussion.
If "Cancel" → exit without changes.
</step>

<step name="3_write_amendment_log">
## Step 3: Write AMENDMENT-LOG.md (APPEND)

If file does not exist, create with header:
```markdown
# Amendment Log — Phase ${PHASE_NUMBER}

Append-only record of mid-phase changes. Each amendment references decisions modified in CONTEXT.md.
```

Append new amendment block:

```markdown

---

## Amendment #${NEXT_AMENDMENT} — ${ISO_DATE}

**Trigger:** ${user_description}
**Phase step at time of amendment:** ${CURRENT_STEP}
**Change type:** ${CHANGE_TYPE}

**Changes:**
- ${CHANGE_TYPE === "modify" ? "D-XX updated: was \"${old_text}\" → now \"${new_text}\"" : ""}
- ${CHANGE_TYPE === "add" ? "Added: D-XX \"${new_decision}\"" : ""}
- ${CHANGE_TYPE === "remove" ? "Removed: D-XX \"${removed}\" (deferred to phase ${X})" : ""}

**Impact analysis:**
- PLAN.md: ${has_plan ? "tasks ${affected_task_nums} affected (touch ${affected_files})" : "not yet created"}
- API-CONTRACTS.md: ${has_contracts ? "${N} endpoints added/modified/removed" : "not yet created"}
- TEST-GOALS.md: ${has_goals ? "${N} goals added/invalidated" : "not yet created"}
- Code (SUMMARY): ${has_summary ? "gap-closure build may be needed" : "no code yet"}

**Rollback point:** `git tag vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}`
```
</step>

<step name="4_update_context">
## Step 4: Update CONTEXT.md

**Patch, do NOT regenerate.**

For each change:
- **Modify D-XX**: Edit the specific line in CONTEXT.md, preserve surrounding decisions
- **Add D-XX**: Append new decision at end of decisions section, use next available ID
- **Remove D-XX**: Strike through with reason: `~~D-XX: {text}~~ (removed — amendment #${NEXT_AMENDMENT}, deferred to phase {X})`

Add amendment reference footer at bottom of CONTEXT.md (append, do not overwrite existing footers):

```markdown

---
_Amendment #${NEXT_AMENDMENT} applied ${ISO_DATE} — see AMENDMENT-LOG.md_
```
</step>

<step name="5_cascade_impact">
## Step 5: Cascade impact analysis

Cascade analysis is delegated to `vg-amend-cascade-analyzer` subagent
(read-only). Subagent inspects PLAN/API-CONTRACTS/TEST-GOALS/SUMMARY/
RUNTIME-MAP for references to changed decisions, returns a markdown
impact report. Per rule 6, the report is informational — orchestrator
displays it to user but does NOT auto-modify any artifact.

### 5.1 Pre-spawn narrate

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer spawning "phase=$PHASE_NUMBER decisions=$CHANGED_DECISIONS"
```

### 5.2 Spawn

Construct prompt JSON and call:

```text
Agent(
  subagent_type="vg-amend-cascade-analyzer",
  prompt={
    "phase_dir": "${PHASE_DIR}",
    "changed_decision_ids": <JSON list of D-XX from Step 2>,
    "change_summary": "<one-line from Step 2 user input>"
  }
)
```

### 5.3 Post-spawn narrate

On success (markdown report returned):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer returned "report-len=$(echo "$REPORT" | wc -l)"
```

On failure (subagent emitted error JSON or no markdown block):

```bash
bash scripts/vg-narrate-spawn.sh vg-amend-cascade-analyzer failed "<one-line cause>"
```

### 5.4 Display report to user

Display the subagent's markdown report block inline in chat. Do NOT
write the report to a file (rule 6: informational only). The
AMENDMENT-LOG.md entry written in Step 3 already captures change context;
the cascade report is for user's pre-commit awareness.

### 5.5 If subagent failed

If the subagent failed (e.g. all artifacts unreadable), surface the
cause to user via:

> Cascade analysis failed: <cause>. Continue to Step 6 commit
> without impact report? (yes/no)

On yes → proceed to Step 6.
On no → abort entry skill (no commit, no telemetry beyond what was emitted).

See `.claude/agents/vg-amend-cascade-analyzer.md` for the full subagent
contract.
</step>

<step name="6_git_tag_and_commit">
## Step 6: Git tag + commit

```bash
# Create rollback tag BEFORE committing changes
git tag "vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}" HEAD

# Stage amended files
git add "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/AMENDMENT-LOG.md"

# Commit
git commit -m "amend(${PHASE_NUMBER}): ${CHANGE_TYPE} — ${short_summary}

Amendment #${NEXT_AMENDMENT}: ${user_description_short}
Decisions changed: ${changed_decision_ids}
Rollback: git checkout vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}

Co-Authored-By: Claude <noreply@anthropic.com>"

# v2.46 Phase 6 — cascade cross-phase validity check
# When this phase amends decisions, walk ALL downstream phases to mark
# goals citing revoked D-XX as STALE so user knows what to re-review.
CROSS_VAL=".claude/scripts/validators/verify-cross-phase-decision-validity.py"
if [ -f "$CROSS_VAL" ] && [ -d ".vg/phases" ]; then
  echo ""
  echo "🔄 v2.46 amend cascade: checking dependent phases for stale D-XX references..."
  STALE_PHASES=()
  for phase_dir in .vg/phases/*/; do
    other_phase_name=$(basename "$phase_dir")
    other_phase_num=$(echo "$other_phase_name" | sed 's/^0*//' | grep -oE '^[0-9]+(\.[0-9]+)?')
    if [ -z "$other_phase_num" ] || [ "$other_phase_num" = "$PHASE_NUMBER" ]; then
      continue
    fi
    OUT=$(${PYTHON_BIN:-python3} "$CROSS_VAL" --phase "$other_phase_num" --severity warn 2>/dev/null)
    BAD=$(echo "$OUT" | python3 -c "import json,sys
try:
  d = json.load(sys.stdin)
  bad = [e for e in d.get('evidence', []) if str(e.get('type','')).startswith('cross_phase')]
  print(len(bad))
except Exception:
  print(0)" 2>/dev/null || echo 0)
    if [ "${BAD:-0}" -gt 0 ]; then
      STALE_PHASES+=("$other_phase_num ($BAD stale)")
    fi
  done
  if [ ${#STALE_PHASES[@]} -gt 0 ]; then
    echo "  ⚠ Stale references in downstream phase(s):"
    for p in "${STALE_PHASES[@]}"; do echo "     - $p"; done
    echo "  Run /vg:review on each to refresh, OR /vg:amend to update goal references."
  else
    echo "  ✓ No downstream phases reference revoked decisions."
  fi
fi
```

Display:
```
Amendment #${NEXT_AMENDMENT} applied to Phase ${PHASE_NUMBER}
  Type: ${CHANGE_TYPE}
  Decisions modified: ${list}
  Rollback tag: vg-amend-${PHASE_NUMBER}-pre-${NEXT_AMENDMENT}
  
  Suggested next: ${suggested_action}
```
</step>

</process>

<success_criteria>
- AMENDMENT-LOG.md exists with new amendment block appended (never overwrites previous)
- CONTEXT.md patched with decision changes (not regenerated)
- Git tag created before changes for rollback safety
- Cascade impact displayed for all existing downstream artifacts
- Commit message references amendment number and changed decisions
- Clear next-action guidance based on current pipeline step
</success_criteria>
