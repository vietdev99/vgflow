---
name: vg:prioritize
description: Analyze ROADMAP.md + phase artifacts — rank phases by impact, readiness, and recommend next action
argument-hint: ""
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
observation_only: true
contract_exempt_reason: "read-only: analyzes ROADMAP.md + phase artifacts, prints ranked recommendations — pure analysis"
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths.
3. **Read-only** — this command does NOT modify any files. Pure analysis and display.
4. **Artifact-based classification** — phase status derived from actual file presence, not metadata.
5. **Score transparency** — every score component shown so user understands the ranking.
6. **Legacy detection** — identify phases built outside VG pipeline (missing VG artifacts despite having code).
</rules>

<objective>
Analyze ROADMAP.md and scan all phase directories to classify each phase by status, score by impact, and recommend the highest-value next action. Read-only command — outputs a ranked priority table.

Output: terminal display only (no files written)

Pipeline: project → roadmap → map → **prioritize** → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
## Step 0: Load Config

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

```bash
ROADMAP_FILE="${PLANNING_DIR}/ROADMAP.md"
```

**Validate:**
- If `${ROADMAP_FILE}` does not exist:
  → "ROADMAP.md not found. Run `/vg:roadmap` to derive phases from requirements."
  → STOP.
</step>

<step name="1_parse_roadmap">
## Step 1: Parse ROADMAP.md

Extract all phases:

```
For each "## Phase {NN}: {Name}" section:
  phase_number = NN
  phase_name = Name
  goal = text after "**Goal:**"
  requirements = REQ-IDs after "**Requirements:**"
  depends_on = phase numbers after "**Depends on:**" (or empty if "None")
  success_criteria = list after "**Success criteria:**"
  plans_count = parse "**Plans:** X/Y" → (completed, total)
  status_declared = text after "**Status:**" (planned, in-progress, accepted, etc.)
```

Build:
- `phases[]` — array of all phase objects
- `dependency_graph{}` — { phase_number: [depends_on_numbers] }
- `downstream_map{}` — { phase_number: [phases that depend on this one] }
</step>

<step name="2_scan_artifacts">
## Step 2: Scan Phase Directories for Artifacts

For each phase, determine its directory and check artifact presence:

```bash
# For each phase directory in ${PHASES_DIR}/
for phase_dir in ${PHASES_DIR}/*/; do
  phase_num = extract from dir name
  
  # VG pipeline artifacts
  HAS_SPECS=$(test -f "${phase_dir}/SPECS.md" && echo "true" || echo "false")
  HAS_CONTEXT=$(test -f "${phase_dir}/CONTEXT.md" && echo "true" || echo "false")
  HAS_PLAN=$(ls ${phase_dir}/*PLAN*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_API_CONTRACTS=$(test -f "${phase_dir}/API-CONTRACTS.md" && echo "true" || echo "false")
  HAS_TEST_GOALS=$(test -f "${phase_dir}/TEST-GOALS.md" && echo "true" || echo "false")
  HAS_SUMMARY=$(ls ${phase_dir}/*SUMMARY*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_RUNTIME_MAP=$(test -f "${phase_dir}/RUNTIME-MAP.json" && echo "true" || echo "false")
  HAS_GOAL_MATRIX=$(test -f "${phase_dir}/GOAL-COVERAGE-MATRIX.md" && echo "true" || echo "false")
  HAS_SANDBOX_TEST=$(ls ${phase_dir}/*SANDBOX-TEST*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  HAS_UAT=$(ls ${phase_dir}/*UAT*.md 2>/dev/null | head -1 && echo "true" || echo "false")
  
  # Pipeline state (if exists)
  HAS_PIPELINE_STATE=$(test -f "${phase_dir}/PIPELINE-STATE.json" && echo "true" || echo "false")
done
```

**Also check for GOAL-COVERAGE-MATRIX gate status (if file exists):**

```bash
if [ "$HAS_GOAL_MATRIX" = "true" ]; then
  # Read gate status from GOAL-COVERAGE-MATRIX.md
  # Look for "Gate: PASS" or "Gate: BLOCK" or percentage
  GOAL_GATE=$(grep -i "gate:" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" | head -1)
  # Count READY vs total goals
  GOALS_READY=$(grep -c "READY" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo "0")
  GOALS_TOTAL=$(grep -cE "^\|.*\|.*(READY|BLOCKED|FAILED|UNREACHABLE|NOT_SCANNED)" "${phase_dir}/GOAL-COVERAGE-MATRIX.md" 2>/dev/null || echo "0")
fi
```

**Check for UAT verdict (if file exists):**

```bash
if [ "$HAS_UAT" = "true" ]; then
  UAT_VERDICT=$(grep -i "verdict:" ${phase_dir}/*UAT*.md | head -1)
  # ACCEPTED, REJECTED, PARTIAL
fi
```
</step>

<step name="3_classify_phases">
## Step 3: Classify Each Phase

Apply classification rules IN THIS ORDER (first match wins):

```
DONE:
  - HAS_UAT=true AND UAT_VERDICT contains "ACCEPTED"
  - OR status_declared == "accepted"

NEEDS_FIX:
  - HAS_GOAL_MATRIX=true AND gate != PASS (goals < 100% READY)
  - OR HAS_SANDBOX_TEST=true AND verdict contains "FAILED" or "GAPS"
  - OR HAS_RUNTIME_MAP=true AND GOALS_READY < GOALS_TOTAL

READY:
  - All dependency phases are DONE
  - AND HAS_CONTEXT=true (scope is done)
  - AND NOT HAS_PLAN (blueprint not started yet — ready to plan)

IN_PROGRESS:
  - Has some VG artifacts but not complete
  - Not blocked by dependencies
  - (Catch-all for phases mid-pipeline)

BLOCKED:
  - At least one dependency phase is NOT DONE
  - AND phase itself is not DONE

STALE:
  - HAS_SUMMARY=true (was built)
  - BUT missing VG-specific artifacts: no RUNTIME-MAP.json AND no GOAL-COVERAGE-MATRIX.md
  - (Built outside VG pipeline — legacy GSD build)

PLANNED:
  - In ROADMAP but no artifacts at all (or only SPECS.md)
  - Dependencies may or may not be met
```

Store: `phase.classification` for each phase.
</step>

<step name="4_score_phases">
## Step 4: Score Each Phase

For phases that are NOT DONE, compute a priority score:

```
score = 0

# Unblocks others: +3 per downstream phase
score += len(downstream_map[phase_number]) * 3

# NEEDS_FIX: +2 (quick win — partially done, fix and close)
if classification == NEEDS_FIX:
  score += 2

# IN_PROGRESS: +1 (momentum — continue what's started)
if classification == IN_PROGRESS:
  score += 1

# READY with full scope: +1 (low friction to start)
if classification == READY:
  score += 1

# Has critical requirements: +2 if any REQ is must-have
if any(req.priority == "must-have" for req in phase.requirements):
  score += 2

# STALE: -1 (needs migration overhead)
if classification == STALE:
  score -= 1

# BLOCKED: -5 (can't start anyway)
if classification == BLOCKED:
  score -= 5
```

**Score breakdown stored per phase** for transparency in output.
</step>

<step name="5_sort_and_display">
## Step 5: Sort and Display Ranked Table

Sort phases by score descending. Display:

```
Phase Priority — {PROJECT_NAME}
Generated: {ISO date}

#1  Phase {NN}: {Name} ({CLASSIFICATION})
    Score: {score} = {breakdown}
    Goal: {goal}
    {status detail}
    Action: {recommended VG command}

#2  Phase {NN}: {Name} ({CLASSIFICATION})
    Score: {score} = {breakdown}
    Goal: {goal}
    {status detail}
    Action: {recommended VG command}

...

--- Completed Phases ---
  Phase {NN}: {Name} (DONE) — accepted {date if available}
  ...

Legend: DONE | NEEDS_FIX | IN_PROGRESS | READY | BLOCKED | STALE | PLANNED
```

**Status detail per classification:**

| Classification | Status detail | Recommended action |
|---|---|---|
| NEEDS_FIX | "{X}/{Y} goals ready, gate BLOCK" or "sandbox test failed" | `/vg:review {phase} --retry-failed` or `/vg:test {phase}` |
| IN_PROGRESS | "Currently at: {current pipeline step}" | `/vg:next` or `/vg:{current_step} {phase}` |
| READY | "All deps done, scope complete, ready to plan" | `/vg:blueprint {phase}` |
| BLOCKED | "Blocked by: Phase {deps not done}" | (show which deps to finish first) |
| STALE | "Built via legacy pipeline, missing VG artifacts" | `/vg:review {phase}` (to generate RUNTIME-MAP + goals) |
| PLANNED | "No artifacts yet" | `/vg:specs {phase}` |

**Recommended action mapping (MANDATORY — always use /vg:* commands):**

| Phase state | Command |
|---|---|
| No SPECS.md | `/vg:specs {phase}` |
| SPECS but no CONTEXT | `/vg:scope {phase}` |
| CONTEXT but no PLAN | `/vg:blueprint {phase}` |
| PLAN but no SUMMARY | `/vg:build {phase}` |
| SUMMARY but no RUNTIME-MAP | `/vg:review {phase}` |
| RUNTIME-MAP but goals failing | `/vg:review {phase} --retry-failed` |
| Goals passing but no SANDBOX-TEST | `/vg:test {phase}` |
| SANDBOX-TEST but no UAT | `/vg:accept {phase}` |
| UAT accepted | (DONE — no action) |

**Forbidden suggestions:**
- NEVER suggest `/gsd-*` or `/gsd:*` commands
- NEVER suggest manually editing artifacts
</step>

<step name="6_legacy_detection">
## Step 6: Legacy Phase Detection

If any phases classified as STALE:

```
--- Legacy Phases Needing VG Migration ---

These phases were built outside the VG pipeline (e.g., legacy GSD).
They have build artifacts (SUMMARY) but are missing VG review/test artifacts.

  Phase {NN}: {Name}
    Has: CONTEXT, PLAN, SUMMARY
    Missing: RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md, SANDBOX-TEST.md
    Migration: /vg:review {phase} → /vg:test {phase} → /vg:accept {phase}

  Phase {NN}: {Name}
    Has: SUMMARY
    Missing: SPECS, CONTEXT (scope never done in VG)
    Migration: /vg:specs {phase} → /vg:scope {phase} → /vg:review {phase}
```

This helps the user understand which phases need VG pipeline retrofit vs which are truly new.
</step>

<step name="7_summary">
## Step 7: Summary

```
Summary:
  Total phases: {N}
  DONE: {count}
  NEEDS_FIX: {count} (quick wins)
  IN_PROGRESS: {count}
  READY: {count}
  BLOCKED: {count}
  STALE: {count} (legacy migration needed)
  PLANNED: {count}

Top recommendation: /vg:{command} {phase} — {reason}
```
</step>

</process>

<success_criteria>
- All phases from ROADMAP.md scanned and classified
- Artifact detection accurate (file existence checked, not assumed)
- Dependency graph correctly identifies BLOCKED phases
- Scoring transparent — breakdown shown per phase
- Ranked output with actionable /vg:* command per phase
- Legacy/STALE phases identified with migration path
- No files written (read-only command)
- No /gsd:* commands suggested
</success_criteria>
</output>
