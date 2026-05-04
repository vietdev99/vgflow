# accept uat checklist build (STEP 3 — HEAVY, subagent)

Maps to step `4_build_uat_checklist` (291 lines in legacy accept.md).
Builds 6-section data-driven UAT checklist from VG artifacts.

<HARD-GATE>
DO NOT build the checklist inline. You MUST spawn `vg-accept-uat-builder`
via the `Agent` tool. The 291-line step parses 8+ artifact files (CONTEXT,
FOUNDATION, TEST-GOALS, GOAL-COVERAGE-MATRIX, CRUD-SURFACES, RIPPLE,
PLAN.md design-refs, SUMMARY*, build-state.log, mobile-security/report.md).
Inline execution will skim — empirical 96.5% skip rate without subagent.
</HARD-GATE>

<step name="4_build_uat_checklist">

## Pre-spawn narration

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 4_build_uat_checklist 2>/dev/null || true

bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder spawning "phase ${PHASE_NUMBER} UAT checklist"
```

## Spawn

Read `delegation.md` to get the input/output contract. Then call:

```
Agent(subagent_type="vg-accept-uat-builder", prompt=<built from delegation>)
```

### Codex runtime spawn path

If the runtime is Codex, apply
`commands/vg/_shared/codex-spawn-contract.md` instead of calling the
Claude-only `Agent(...)` syntax:

1. Render `delegation.md` into
   `${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-accept-uat-builder.prompt.md`.
2. Run `codex-spawn.sh --tier executor --sandbox workspace-write
   --spawn-role vg-accept-uat-builder --spawn-id vg-accept-uat-builder` with
   `--out ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/vg-accept-uat-builder.json`.
3. Set `SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"` and run output validation
   unchanged.
4. Treat missing helper, missing Codex CLI, non-zero exit, empty output,
   malformed JSON, missing checklist file, or invalid section counts as a
   HARD BLOCK.

Do NOT build the UAT checklist inline on Codex.

The subagent uses `vg-load --phase ${PHASE_NUMBER} --artifact goals --list`
for TEST-GOALS Layer-1 split (NOT flat TEST-GOALS.md — Phase F Task 30
absorption). Other artifacts stay flat (KEEP-FLAT allowlist: CONTEXT.md,
FOUNDATION.md, CRUD-SURFACES.md, RIPPLE-ANALYSIS.md, SUMMARY*.md,
build-state.log — small single-doc files).

## Post-spawn narration

On success:
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder returned "<count> items across 6 sections"
```

On failure (subagent error JSON or empty output):
```bash
bash .claude/scripts/vg-narrate-spawn.sh vg-accept-uat-builder failed "<one-line cause>"
```

## Output validation

The subagent returns:
```json
{
  "checklist_path": "${PHASE_DIR}/uat-checklist.md",
  "sections": [
    { "name": "A", "title": "Decisions", "items": [{ "id": "...", "summary": "...", "source_file": "CONTEXT.md", "source_line": 42 }] },
    { "name": "A.1", "title": "Foundation cites", "items": [...] },
    { "name": "B", "title": "Goals", "items": [...] },
    { "name": "B.1", "title": "CRUD surfaces", "items": [...] },
    { "name": "C", "title": "Ripple HIGH", "items": [...] },
    { "name": "D", "title": "Design refs", "items": [...] },
    { "name": "E", "title": "Deliverables", "items": [...] },
    { "name": "F", "title": "Mobile gates", "items": [...] }
  ],
  "total_items": <int>,
  "verdict_inputs": { "test_verdict": "...", "ripple_skipped": false }
}
```

After return, validate:
1. `checklist_path` exists and is non-empty
2. `sections[]` length ≥ 5 (Sections A, B, B.1, D, E always present; A.1+C+F conditional)
3. `total_items` matches sum of sections[].items[].length

If validation fails, surface a 3-line block:
```
⛔ vg-accept-uat-builder returned malformed checklist
   missing/invalid: <field>
   action: re-spawn with --retry, OR --override-reason="<text>" to log debt
```

## After-spawn user prompt

Present SECTION COUNTS to user (mirror legacy step 4 final block):

```
UAT Checklist for Phase ${PHASE_NUMBER}:
  Section A   — Decisions (P${phase}.D-XX):       {count} items
  Section A.1 — Foundation cites (F-XX):          {count} items
  Section B   — Goals (G-XX):                     {count} items
  Section B.1 — CRUD surfaces:                    {count} rows
  Section C   — Ripple HIGH callers:              {count} acks
  Section D   — Design refs (+mobile shots):      {count} (+{n})
  Section E   — Deliverables:                     {count} tasks
  Section F   — Mobile gates [omitted for web]:   {count} (+{n} sec)
  Test verdict (from Gate 3):                     {VERDICT}

Proceed with interactive UAT? (y/n/abort)
```

If user aborts → write `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` with status
`ABORTED`, mark-step `4_build_uat_checklist`, and exit STEP 3 cleanly. The
remaining steps then short-circuit (UAT.md present + Verdict line satisfies
runtime_contract).

## Marker

After validation + user proceed:
```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_build_uat_checklist" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_build_uat_checklist.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 4_build_uat_checklist 2>/dev/null || true
```

</step>
