---
name: "vg-add-phase"
description: "Add a new phase to ROADMAP.md — gather info, calculate numbering, create directory, update traceability"
metadata:
  short-description: "Add a new phase to ROADMAP.md — gather info, calculate numbering, create directory, update traceability"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use `codex exec --model <model>` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | `curl -sfL` or `gh api` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning `$vg-add-phase`. Treat all user text after `$vg-add-phase` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **ROADMAP.md required** — must exist. Missing = suggest `/vg:roadmap` first.
4. **REQUIREMENTS.md required** — must exist for REQ-ID mapping. Missing = suggest `/vg:project` first.
5. **No renumbering** — adding a phase NEVER changes existing phase numbers. Use decimal for insertion.
6. **Traceability** — every new phase must map to at least one REQ-ID or explicitly state "no requirement mapping".
</rules>

<objective>
Add a new phase to the project roadmap. Gathers phase name, goal, requirement mapping, and dependencies through structured questions. Creates the phase directory and updates both ROADMAP.md and REQUIREMENTS.md traceability.

Not part of the main pipeline — utility command run anytime after `/vg:roadmap` exists.
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

<step name="0_parse_and_validate">
## Step 0: Parse arguments + validate state

```bash
# Parse flags
INSERT_AFTER=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --after) shift; INSERT_AFTER="$1" ;;
    --after=*) INSERT_AFTER="${arg#--after=}" ;;
  esac
done

ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
REQUIREMENTS_FILE="${PLANNING_DIR}/REQUIREMENTS.md"

# Validate
if [ ! -f "$ROADMAP_FILE" ]; then
  echo "BLOCK: ROADMAP.md not found. Run /vg:roadmap first."
  exit 1
fi

if [ ! -f "$REQUIREMENTS_FILE" ]; then
  echo "BLOCK: REQUIREMENTS.md not found. Run /vg:project first."
  exit 1
fi
```

Read ROADMAP.md:
- Parse all existing phase entries (number, name, status, dependencies)
- Find max phase number (integer part)
- List all existing phases for dependency picker

Read REQUIREMENTS.md:
- Parse all REQ-IDs with their current Phase column
- Identify unmapped REQs (Phase = "---" or empty)

Display:
```
Current roadmap: {N} phases (max number: {max})
Unmapped requirements: {M} REQ-IDs available
```
</step>

<step name="1_gather_info">
## Step 1: Gather phase info (3 questions)

### Question 1: Name and goal

```
AskUserQuestion:
  header: "New Phase"
  question: "Phase name and goal?"
  (open text — e.g., "Video Ads — VAST tag support for video ad units")
```

AI extracts:
- **Phase name** — short label (e.g., "Video Ads VAST")
- **Goal** — 1-2 sentence description
- **Slug** — kebab-case for directory name (e.g., "video-ads-vast")

### Question 2: Requirement mapping

```
AskUserQuestion:
  header: "Requirements"
  question: "Which requirements does this phase cover?"
  options:
    - Show unmapped REQ-IDs first (highlighted as available)
    - Show already-mapped REQ-IDs (dimmed, can still be selected for shared coverage)
    - "None — this phase has no requirement mapping" (allowed but flagged)
  (multiSelect)
```

Store: `$SELECTED_REQS[]`

### Question 3: Dependencies

```
AskUserQuestion:
  header: "Dependencies"
  question: "Which phases must complete before this one can start?"
  options:
    - Show existing phases with status (completed phases dimmed, active/planned highlighted)
    - "None — no dependencies"
  (multiSelect)
```

Store: `$DEPENDS_ON[]`
</step>

<step name="1b_foundation_drift_check">
## Step 1b: Foundation drift check (soft warning, added v1.6.0)

Scan new phase title + requirements text for keywords hint platform shift away from FOUNDATION.md. Soft warning only — does NOT block.

```bash
FOUNDATION_FILE=".planning/FOUNDATION.md"
if [ -f "$FOUNDATION_FILE" ]; then
  SCAN_TEXT="${PHASE_NAME} ${SELECTED_REQS[*]}"
  # Source helper from _shared/foundation-drift.md (conceptual)
  foundation_drift_check "$SCAN_TEXT" "add-phase:${PHASE_NAME}"
fi
# Continue regardless. Use --no-drift-check to silence.
```
</step>

<step name="2_calculate_phase_number">
## Step 2: Calculate phase number

**Default (append to end):**
- `NEW_NUMBER = floor(max_existing) + 1`
- Example: max is 8 (or 8.3) -> new phase = 9

**If --after flag or inserting between existing phases:**
- Find the target phase number and the next phase number
- Calculate decimal: `target + 0.1 * (count_of_existing_decimals + 1)`
- Example: --after=7, existing 7.1 and 7.2 exist -> new = 7.3
- Example: --after=7, no decimals exist -> new = 7.1

```bash
if [ -n "$INSERT_AFTER" ]; then
  # Find existing decimal phases after INSERT_AFTER
  EXISTING_DECIMALS=$(grep -oP "Phase ${INSERT_AFTER}\.\d+" "$ROADMAP_FILE" | grep -oP '\d+\.\d+' | sort -t. -k2 -n | tail -1)
  if [ -n "$EXISTING_DECIMALS" ]; then
    LAST_DECIMAL=$(echo "$EXISTING_DECIMALS" | grep -oP '\.\K\d+')
    NEW_NUMBER="${INSERT_AFTER}.$((LAST_DECIMAL + 1))"
  else
    NEW_NUMBER="${INSERT_AFTER}.1"
  fi
else
  MAX_INT=$(grep -oP 'Phase \K\d+' "$ROADMAP_FILE" | sort -n | tail -1)
  NEW_NUMBER=$((MAX_INT + 1))
fi

PHASE_SLUG=$(echo "$PHASE_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')
NEW_PHASE_DIR="${PHASES_DIR}/${NEW_NUMBER}-${PHASE_SLUG}"
```

Confirm with user:
```
New phase: Phase ${NEW_NUMBER}: ${PHASE_NAME}
Directory: ${NEW_PHASE_DIR}
Requirements: ${SELECTED_REQS[@]}
Depends on: ${DEPENDS_ON[@]:-None}

Proceed?
```
</step>

<step name="3_create_phase">
## Step 3: Create phase directory + update artifacts

### Create directory:
```bash
mkdir -p "${NEW_PHASE_DIR}"
```

### Derive success criteria from selected requirements:
For each REQ-ID in `$SELECTED_REQS`:
- Read its "Acceptance Criteria" from REQUIREMENTS.md
- Convert to phase success criteria (1 per REQ)

### Append to ROADMAP.md:

Find the correct insertion point:
- If appending (no --after): append before any footer/closing sections
- If inserting (--after): insert after the last decimal phase of that group

Append/insert block:

```markdown

## Phase ${NEW_NUMBER}: ${PHASE_NAME}

**Goal:** ${goal}
**Requirements:** ${SELECTED_REQS[@]}
**Depends on:** ${DEPENDS_ON[@]:-None}
**Success criteria:**
${for each req in SELECTED_REQS: "- ${req}: ${acceptance_criteria}"}
**Plans:** 0/0
**Status:** planned
```

### Update REQUIREMENTS.md traceability:

For each REQ-ID in `$SELECTED_REQS`:
- Find the row in REQUIREMENTS.md
- Set Phase column to `${NEW_NUMBER}`
- Keep Status as "pending"

Use Edit tool for surgical updates — do NOT rewrite the entire file.
</step>

<step name="4_commit_and_next">
## Step 4: Commit + suggest next

```bash
git add "${ROADMAP_FILE}" "${REQUIREMENTS_FILE}" "${NEW_PHASE_DIR}"
git commit -m "roadmap: add phase ${NEW_NUMBER} — ${PHASE_NAME}

Requirements: ${SELECTED_REQS[@]}
Depends on: ${DEPENDS_ON[@]:-None}

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Display:
```
Phase ${NEW_NUMBER} added: ${PHASE_NAME}
  Directory: ${NEW_PHASE_DIR}/
  Requirements: ${SELECTED_REQS[@]}
  Depends on: ${DEPENDS_ON[@]:-None}
  Success criteria: ${criteria_count} items
  
  ROADMAP.md updated
  REQUIREMENTS.md traceability updated
  
  Next: /vg:specs ${NEW_NUMBER} — start the pipeline for this phase
```
</step>

</process>

<success_criteria>
- Phase directory created at ${PHASES_DIR}/${NEW_NUMBER}-${slug}/
- ROADMAP.md contains new phase block with goal, requirements, dependencies, success criteria, status=planned
- REQUIREMENTS.md Phase column updated for all selected REQ-IDs
- No existing phase numbers changed
- All artifacts committed to git
- Next step guidance shows /vg:specs ${NEW_NUMBER}
</success_criteria>
