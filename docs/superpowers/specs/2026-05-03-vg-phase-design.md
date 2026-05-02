# VG Phase — Pipeline Orchestrator Cleanup

**Status:** Design (pending implementation plan)
**Date:** 2026-05-03
**Replication round:** R1.5 (immediately after blueprint pilot R1, before R2 — phase orchestrator must coordinate refactored sub-commands)
**Inherits from:** `2026-05-03-vg-blueprint-pilot-design.md`

---

## 1. Background

`commands/vg/phase.md` is **240 lines, 7 steps**. Pipeline orchestrator wrapping 6 execution commands (scope → blueprint → build → review → test → accept). Already small, **does NOT need shrink**. Refactor scope: imperative cleanup + tasklist-contract alignment + per-sub-command lifecycle clarification.

### 1.1 Current state

Phase already has:
- 6-task TaskCreate/TodoWrite tasklist (1 per pipeline step)
- replace-on-start at phase entry, close-on-complete at phase exit
- Per-step status update (pending → in_progress → completed)
- SlashCommand-based sub-command invocation
- Failure stop with `--from={step}` resume hint
- Frontmatter runtime_contract (minimal: phase.started + phase.completed)

### 1.2 Issues identified

1. **Per-sub-command lifecycle ambiguity** — when phase invokes `/vg:scope` then `/vg:blueprint`, does each sub-command run its OWN replace-on-start? If so, scope's tasklist replaces phase's tasklist mid-flight. Bug confirmed by recon: phase tasklist lifecycle is OWNED by phase, not subordinate to sub-commands.
2. **Missing per-step events** — phase only emits `phase.started` + `phase.completed`. No `phase.step_started`, `phase.step_completed`, `phase.step_failed`. Stop hook cannot detect mid-flight abort granularity.
3. **No imperative tasklist policy** — currently descriptive language about lifecycle, not enforced.

### 1.3 Audit findings

| # | Mechanism | Verdict | Action |
|---|---|---|---|
| 1 | 6-task tasklist creation | PASS | Preserve as-is |
| 2 | replace-on-start at phase entry | PASS | Preserve as-is |
| 3 | close-on-complete at phase exit | PASS | Preserve as-is |
| 4 | SlashCommand sub-command invocation | PASS | Preserve as-is |
| 5 | Per-sub-command lifecycle conflict (sub-command's own tasklist replaces phase's) | **FAIL** | **Strengthen** — see §3.1 |
| 6 | Per-step phase event emission | **FAIL** | **Strengthen** — add phase.step_started + phase.step_completed |
| 7 | `phase.native_tasklist_projected` emission | **FAIL** (only 2 events declared) | **Strengthen** (inherit blueprint pilot fix) |
| 8 | Imperative language for lifecycle | **PARTIAL** | Tighten to imperative |

**Summary:** 4/8 PASS, 3/8 FAIL, 1/8 PARTIAL. Architecture is sound; gaps are in coordination + observability.

### 1.4 Goals

- Keep `commands/vg/phase.md` ≤ 300 lines (already 240, small refactor)
- Apply imperative + HARD-GATE + Red Flags
- **Strengthen sub-command lifecycle coordination** — sub-commands invoked via SlashCommand from phase context MUST detect they're inside a phase orchestrator and NOT replace phase's tasklist
- **Add per-step events** — `phase.step_started`, `phase.step_completed`, `phase.step_failed` for each of 6 sub-commands
- Inherit blueprint pilot's tasklist projection fix

### 1.5 Non-goals

- Major restructuring (file already small)
- Replacing SlashCommand with Bash subprocess
- Codex mirror (defer)

---

## 2. Inheritance from blueprint pilot

Same as build/test/review/accept/project/scope.

---

## 3. Components

### 3.1 Strengthen sub-command lifecycle coordination (audit FAIL #5)

**Problem:** When phase invokes `/vg:scope`, scope's slim entry SKILL.md says "STEP 1: Bash emit-tasklist.py NOW" + "STEP 2: Call TodoWrite NOW with these items..." — which would REPLACE phase's 6-task tasklist with scope's checklist groups.

**Solution:** Add `VG_PARENT_RUN_ID` environment variable when phase invokes sub-command. Sub-command's slim entry SKILL.md + emit-tasklist.py detect this and:
- Skip TodoWrite replace (phase owns tasklist)
- Update phase's tasklist item: `Step 1/6: scope` → status=in_progress
- Continue with own internal step markers + telemetry (events still flow normally)
- At sub-command end, update phase's tasklist item to status=completed

**Implementation:**
- `phase.md` step 3 (execute_pipeline) sets `VG_PARENT_RUN_ID=$(vg-orchestrator current-run-id)` before SlashCommand
- `emit-tasklist.py` detects `$VG_PARENT_RUN_ID` and emits an "embedded mode" tasklist contract (no replace, just step markers)
- Slim entry SKILL.md of sub-commands has conditional: "If VG_PARENT_RUN_ID is set, skip the TodoWrite replace and use TaskUpdate to update parent's tasklist item instead"

This requires touching all sub-command slim entries during their refactor (R1, R2, R3, R4) — should be added to each spec's implementation plan.

### 3.2 Add per-step events (audit FAIL #6)

In phase.md step 3 loop:
```bash
for step in scope blueprint build review test accept; do
  vg-orchestrator emit-event phase.step_started --phase $PHASE_ARG --step $step
  
  # Invoke via SlashCommand
  /vg:$step $PHASE_ARG
  rc=$?
  
  if [ $rc -eq 0 ]; then
    vg-orchestrator emit-event phase.step_completed --phase $PHASE_ARG --step $step
  else
    vg-orchestrator emit-event phase.step_failed --phase $PHASE_ARG --step $step --exit_code $rc
    break
  fi
done
```

Update frontmatter must_emit_telemetry:
```yaml
must_emit_telemetry:
  - "phase.tasklist_shown"
  - "phase.native_tasklist_projected"
  - "phase.started"
  - "phase.completed"
  # New per-step events (warn-severity since failure case may skip remaining)
  - event_type: "phase.step_started"
    min_count: 1   # at least scope must start
  - event_type: "phase.step_completed"
    min_count: 1   # at least scope must complete on success path
```

### 3.3 Apply imperative + HARD-GATE

```markdown
<HARD-GATE>
Phase orchestrates 6 pipeline commands in strict order. You MUST:
- Set VG_PARENT_RUN_ID before invoking each sub-command
- Update tasklist item status (in_progress → completed) per sub-command result
- Emit phase.step_started + phase.step_completed (or phase.step_failed) per sub-command
- STOP on first sub-command failure (do NOT skip to next)
- DO NOT bypass tasklist coordination (sub-commands depend on it)
</HARD-GATE>

## Red Flags (phase-specific)

| Thought | Reality |
|---|---|
| "Sub-command failed but minor, skip to next"          | Phase contract: stop on failure, resume with --from={step} |
| "Tasklist coordination optional"                      | Sub-commands check VG_PARENT_RUN_ID; missing = wrong tasklist replace |
| "Per-step events redundant with phase.completed"     | Granular events let observers (Stop hook, telemetry) detect mid-flight state |
| "Skip task tracker creation, sub-commands handle"     | Phase owns the 6-task model; sub-commands embed within |
```

---

## 4. File and directory layout

```
commands/vg/
  phase.md                                  REFACTOR: 240 → ~300 lines (light refactor, mostly imperative + per-step events)
  _shared/phase/                            NEW dir
    preflight.md                            ~100 lines (parse args, recon, banner)
    tasklist-contract.md                    ~100 lines (6-task model + replace-on-start + close-on-complete + parent-run-id mechanism)
    execute-pipeline.md                     ~150 lines (per-step loop + event emission + fail-stop)
    close.md                                ~50 lines

scripts/
  emit-tasklist.py                          STRENGTHEN — detect VG_PARENT_RUN_ID env, emit embedded-mode contract
```

---

## 5. Error handling, migration, testing, exit criteria

### 5.1 Error handling

All blocks follow blueprint pilot §4.5. Phase-specific:
- **Sub-command failure** → emit `phase.step_failed`, update tasklist item to `pending`, display resume hint, exit. NOT a hook block (legitimate stop).
- **Tasklist coordination conflict** (sub-command tries to replace phase's tasklist without VG_PARENT_RUN_ID) → PostToolUse hook on TodoWrite detects + warns (does not block, but logs `phase.tasklist_coordination_violation` event)

### 5.2 Migration

- Existing phase runs (2 events in PrintwayV3): stand as-is.
- Sub-command refactors (R1-R4) MUST add VG_PARENT_RUN_ID detection.
- Defer: Codex mirror.

### 5.3 Testing

**Static (pytest):**
- `test_phase_slim_size.py` — assert ≤ 350 lines (small refactor)
- `test_phase_references_exist.py` — all `_shared/phase/*.md`
- `test_emit_tasklist_parent_mode.py` — simulate VG_PARENT_RUN_ID set, assert emit-tasklist.py emits embedded-mode contract (no replace)
- `test_phase_per_step_events.py` — simulate full phase run, assert phase.step_started + phase.step_completed events for each of 6 sub-commands

**Empirical dogfood:**
- Run `/vg:phase <phase>` end-to-end on PrintwayV3
- Assert: phase.native_tasklist_projected ≥ 1, all 6 phase.step_started events, all 6 phase.step_completed events on success path

### 5.4 Exit criteria — phase refactor PASS requires ALL of:

1. Tasklist visible immediately (6-task)
2. `phase.native_tasklist_projected` event ≥ 1
3. Sub-commands inside phase context don't replace phase tasklist (verify: TodoWrite called only ONCE at phase start, then TaskUpdate for status changes)
4. Per-step events present: 6× phase.step_started + 6× phase.step_completed (success path)
5. On simulated mid-flight failure: phase.step_failed event present + phase stops + resume hint displayed
6. Stop hook fires without exit 2
7. close-on-complete clears tasklist (or sentinel completed item)

---

## 6. References

- Inherits from: `2026-05-03-vg-blueprint-pilot-design.md`
- Existing phase.md: `commands/vg/phase.md` (240 lines)
- All sub-command specs (R1-R4) must add VG_PARENT_RUN_ID detection in their slim entries
