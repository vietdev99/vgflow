---
name: vg:remove-phase
description: Remove phase from ROADMAP.md + archive/delete phase directory
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
    - event_type: "remove_phase.started"
    - event_type: "remove_phase.completed"
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **ROADMAP.md required** — must exist. Missing = suggest `/vg:roadmap` first.
4. **No renumbering** — removing a phase NEVER changes existing phase numbers. Gap in numbering is acceptable.
5. **Dependency safety** — warn (not block) if other phases depend on the one being removed.
6. **Archive by default** — recommend archiving over permanent deletion. Data loss is irreversible.
</rules>

<objective>
Remove a phase from the project roadmap. Inverse of `/vg:add-phase`. Shows phase info, checks downstream dependencies, confirms action, then archives or deletes the phase directory and updates ROADMAP.md + REQUIREMENTS.md traceability.

Not part of the main pipeline — utility command run anytime.
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_validate">
## Step 0: Parse phase argument + validate state

```bash
PHASE_NUMBER="$1"
ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
REQUIREMENTS_FILE="${PLANNING_DIR}/REQUIREMENTS.md"

# Validate ROADMAP exists
if [ ! -f "$ROADMAP_FILE" ]; then
  echo "BLOCK: ROADMAP.md not found. Nothing to remove from."
  exit 1
fi

# Resolve phase directory
PHASE_DIR=$(find ${PHASES_DIR} -maxdepth 1 -type d \( -name "${PHASE_NUMBER}*" -o -name "0${PHASE_NUMBER}*" \) 2>/dev/null | head -1)

if [ -z "$PHASE_DIR" ] || [ ! -d "$PHASE_DIR" ]; then
  echo "BLOCK: Phase ${PHASE_NUMBER} directory not found in ${PHASES_DIR}/"
  exit 1
fi

PHASE_NAME=$(basename "$PHASE_DIR")
```
</step>

<step name="1_show_phase_info">
## Step 1: Show phase info

Read ROADMAP.md and extract the phase block. Read phase directory to inventory artifacts.

```bash
# Count artifacts
ARTIFACT_COUNT=$(ls "${PHASE_DIR}"/*.md "${PHASE_DIR}"/*.json 2>/dev/null | wc -l)

# List key artifacts
ARTIFACTS=$(ls "${PHASE_DIR}"/*.md "${PHASE_DIR}"/*.json 2>/dev/null | xargs -I{} basename {})

# Check pipeline status by artifact presence
PIPELINE_STATUS="empty"
[ -f "${PHASE_DIR}/SPECS.md" ]          && PIPELINE_STATUS="specced"
[ -f "${PHASE_DIR}/CONTEXT.md" ]        && PIPELINE_STATUS="scoped"
[ -f "${PHASE_DIR}/PLAN.md" ]           && PIPELINE_STATUS="planned"
[ -f "${PHASE_DIR}/SUMMARY.md" -o -f "${PHASE_DIR}/SUMMARY-wave1.md" ] && PIPELINE_STATUS="built"
[ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]  && PIPELINE_STATUS="reviewed"
[ -f "${PHASE_DIR}/SANDBOX-TEST.md" ]   && PIPELINE_STATUS="tested"
[ -f "${PHASE_DIR}/UAT.md" ]            && PIPELINE_STATUS="accepted"
```

Display:
```
Phase ${PHASE_NUMBER}: ${PHASE_NAME}
  Directory: ${PHASE_DIR}/
  Pipeline status: ${PIPELINE_STATUS}
  Artifacts: ${ARTIFACT_COUNT} files
  ${ARTIFACTS}
```

Extract dependencies from ROADMAP.md (the "Depends on" field for this phase).
</step>

<step name="2_check_dependencies">
## Step 2: Check downstream dependencies

Grep ROADMAP.md for phases that list this phase in their "Depends on" field.

```bash
# Find phases that depend on the phase being removed
DEPENDENTS=$(grep -B5 "Depends on:.*${PHASE_NUMBER}" "$ROADMAP_FILE" | grep -oP 'Phase \K[\d.]+' | grep -v "^${PHASE_NUMBER}$")
```

If dependents found:
```
WARNING: The following phases depend on Phase ${PHASE_NUMBER}:
  ${DEPENDENTS}

Removing Phase ${PHASE_NUMBER} will break their dependency chain.
These phases' "Depends on" field will be updated to remove the reference.
```

If no dependents:
```
No downstream dependencies found. Safe to remove.
```
</step>

<step name="3_confirm">
## Step 3: Confirm removal action

```
AskUserQuestion:
  header: "Remove Phase ${PHASE_NUMBER}: ${PHASE_NAME}"
  question: "How should this phase be removed?"
  options:
    - "Remove + archive (recommended) — move to ${PLANNING_DIR}/archive/${PHASE_NAME}/"
    - "Remove + delete — permanently delete phase directory"
    - "Cancel — abort removal"
```

If "Cancel" → exit without changes.

Store: `$REMOVAL_MODE` = "archive" | "delete"
</step>

<step name="4_execute">
## Step 4: Execute removal

### 4a: Remove phase entry from ROADMAP.md

Find the phase block in ROADMAP.md (from `## Phase ${PHASE_NUMBER}:` to the next `## Phase` or end of file).
Use Edit tool to remove the entire block. Do NOT rewrite the entire file.

### 4b: Move or delete phase directory

```bash
if [ "$REMOVAL_MODE" = "archive" ]; then
  ARCHIVE_DIR="${PLANNING_DIR}/archive"
  mkdir -p "$ARCHIVE_DIR"
  mv "$PHASE_DIR" "${ARCHIVE_DIR}/${PHASE_NAME}"
  echo "Archived: ${PHASE_DIR} → ${ARCHIVE_DIR}/${PHASE_NAME}/"
else
  rm -rf "$PHASE_DIR"
  echo "Deleted: ${PHASE_DIR}/"
fi
```

### 4c: Update REQUIREMENTS.md traceability

If REQUIREMENTS.md exists:
- Find rows where Phase column = `${PHASE_NUMBER}`
- Set Phase column to `---` (unmap — requirement returns to available pool)
- Use Edit tool for surgical updates

```bash
if [ -f "$REQUIREMENTS_FILE" ]; then
  # For each REQ-ID mapped to this phase, reset Phase column to "---"
  # Use Edit tool — do NOT rewrite entire file
  echo "REQUIREMENTS.md: unmapped REQ-IDs from Phase ${PHASE_NUMBER}"
fi
```

### 4d: Update dependent phases (if any)

If step 2 found dependents:
- For each dependent phase in ROADMAP.md, edit its "Depends on" field to remove `${PHASE_NUMBER}`
- If "Depends on" becomes empty after removal, set to "None"

```bash
if [ -n "$DEPENDENTS" ]; then
  for dep in $DEPENDENTS; do
    # Edit ROADMAP.md: remove PHASE_NUMBER from the "Depends on" field of phase $dep
    echo "Updated Phase ${dep}: removed dependency on Phase ${PHASE_NUMBER}"
  done
fi
```
</step>

<step name="5_commit">
## Step 5: Commit changes

```bash
# Stage all changes
git add "$ROADMAP_FILE"
[ -f "$REQUIREMENTS_FILE" ] && git add "$REQUIREMENTS_FILE"

if [ "$REMOVAL_MODE" = "archive" ]; then
  git add "${PLANNING_DIR}/archive/${PHASE_NAME}"
  # Also stage the removal of the original directory
  git add "$PHASE_DIR"
else
  git add "$PHASE_DIR"
fi

git commit -m "roadmap: remove phase ${PHASE_NUMBER} — ${PHASE_NAME}

Action: ${REMOVAL_MODE}
$([ -n "$DEPENDENTS" ] && echo "Updated dependents: ${DEPENDENTS}")

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Display:
```
Phase ${PHASE_NUMBER} removed: ${PHASE_NAME}
  Action: ${REMOVAL_MODE}
  $([ "$REMOVAL_MODE" = "archive" ] && echo "Archive: ${PLANNING_DIR}/archive/${PHASE_NAME}/")
  ROADMAP.md updated (phase block removed)
  $([ -f "$REQUIREMENTS_FILE" ] && echo "REQUIREMENTS.md updated (REQ-IDs unmapped)")
  $([ -n "$DEPENDENTS" ] && echo "Dependent phases updated: ${DEPENDENTS}")
  
  Committed to git.
```
</step>

</process>

<success_criteria>
- Phase block removed from ROADMAP.md
- Phase directory archived to ${PLANNING_DIR}/archive/ or permanently deleted (per user choice)
- REQUIREMENTS.md Phase column reset to "---" for previously-mapped REQ-IDs
- Dependent phases' "Depends on" field updated to remove reference
- No existing phase numbers changed (gap in numbering is acceptable)
- All changes committed to git
- Clear summary of what was removed and where archive lives (if applicable)
</success_criteria>
