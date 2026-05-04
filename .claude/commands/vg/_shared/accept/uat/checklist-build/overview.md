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
    { "name": "B.1", "title": "CRUD surfaces", "items": [
      { "id": "users", "summary": "...", "source_file": "CRUD-SURFACES.md" },
      { "id": "RCRURD-G-04", "summary": "Goal G-04 — Full RCRURDR lifecycle attestation",
        "source_file": "RCRURD-INVARIANTS/G-04.yaml", "kind": "rcrurdr-attestation",
        "critical": true, "goal_id": "G-04" }
    ] },
    { "name": "C", "title": "Ripple HIGH", "items": [...] },
    { "name": "D", "title": "Design refs", "items": [...] },
    { "name": "E", "title": "Deliverables", "items": [...] },
    { "name": "F", "title": "Mobile gates", "items": [...] }
  ],
  "total_items": <int>,
  "verdict_inputs": { "test_verdict": "...", "ripple_skipped": false }
}
```

**R8-D RCRURDR attestation items (Section B.1):** items with `id` matching
`^RCRURD-G-\d+$` are mutation-lifecycle attestation rows (one per
TEST-GOAL with `lifecycle: rcrurdr`). They MUST carry `critical: true` +
`kind: "rcrurdr-attestation"` so STEP 5 (interactive) renders the full
7-phase question, and STEP 6 (quorum gate) blocks the verdict on a failed
attestation regardless of other section passes.

After return, validate:
1. `checklist_path` exists and is non-empty
2. **Canonical 6-section enum check (ISTQB CT-AcT)** — pipe `SUBAGENT_OUTPUT`
   into `scripts/validators/verify-uat-checklist-sections.py --stdin`. The
   validator BLOCKs unless every canonical letter (A/B/C/D/E/F) is present.
   Sections A.1 + B.1 are allowed sub-sections. Section F may be `status:
   "N/A"` on non-mobile profiles, but the SECTION KEY must exist:
   ```bash
   echo "$SUBAGENT_OUTPUT" | "${PYTHON_BIN:-python3}" \
     .claude/scripts/validators/verify-uat-checklist-sections.py --stdin
   if [ $? -ne 0 ]; then
     # subagent returned weak payload — block + surface 3-line diagnostic
     echo "⛔ UAT checklist failed canonical 6-section enforcement"
     exit 1
   fi
   ```
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

If user aborts → execute the **abort short-circuit block** below. This
satisfies the full `runtime_contract` (must_write + must_touch_markers +
must_emit_telemetry) without running steps 4b/5/5_quorum/6b/6c/6/7. The
prior "remaining steps short-circuit on their own" claim was wrong — those
markers were never touched, and `.uat-responses.json` was never written, so
`run-complete` BLOCKed with missing markers + missing must_write paths.

```bash
# --- Abort short-circuit block (R6 Task 6) ---------------------------------
# Trigger: user answered `abort` to "Proceed with interactive UAT? (y/n/abort)".
# Goal: write minimal artifacts + touch all downstream markers + emit canonical
# events so accept run-complete sees a clean ABORTED run.

mkdir -p "${PHASE_DIR}/.step-markers"

# 1) Minimal `.uat-responses.json` (must_write contract)
cat > "${PHASE_DIR}/.uat-responses.json" <<'JSON'
{
  "aborted": true,
  "verdict": "ABORTED",
  "reason": "user-abort-at-step-3",
  "sections": {
    "A":   { "status": "aborted" },
    "A.1": { "status": "aborted" },
    "B":   { "status": "aborted" },
    "B.1": { "status": "aborted" },
    "C":   { "status": "aborted" },
    "D":   { "status": "aborted" },
    "E":   { "status": "aborted" },
    "F":   { "status": "aborted" }
  }
}
JSON

# 2) Minimal `${PHASE_NUMBER}-UAT.md` with `Verdict: ABORTED`
#    (must_write contract: content_min_bytes=200 + Verdict: section)
cat > "${PHASE_DIR}/${PHASE_NUMBER}-UAT.md" <<MD
# UAT Acceptance — Phase ${PHASE_NUMBER}

Verdict: ABORTED

User aborted at STEP 3 (\`4_build_uat_checklist\`) before interactive UAT
ran. The downstream steps (4b narrative autofire, 5 interactive UAT,
5 quorum gate, 6b security baseline, 6c learn auto-surface,
6 write UAT, 7 post-accept actions) were short-circuited via the
\`accept.aborted_with_short_circuit\` telemetry event.

No accept artifacts were updated beyond this stub + \`.uat-responses.json\`.
ROADMAP / PIPELINE-STATE / CROSS-PHASE-DEPS were NOT flipped — the phase
remains in its pre-accept state for re-entry on the next \`/vg:accept\` run.

## Reason

User answered \`abort\` to the "Proceed with interactive UAT?" prompt.

## Re-entry

Re-run \`/vg:accept ${PHASE_NUMBER}\` when ready. Existing markers from
this aborted run will be cleared automatically by the gate-integrity
precheck (STEP 1).
MD

# 3) Touch this step's marker
(type -t mark_step >/dev/null 2>&1 \
  && mark_step "${PHASE_NUMBER:-unknown}" "4_build_uat_checklist" "${PHASE_DIR}") \
  || touch "${PHASE_DIR}/.step-markers/4_build_uat_checklist.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step \
  accept 4_build_uat_checklist 2>/dev/null || true

# 4) Touch every downstream profile-applicable marker
#    (must_touch_markers contract: all 17 must be present at run-complete)
for SHORT_CIRCUIT_STEP in \
    4b_uat_narrative_autofire \
    5_interactive_uat \
    5_uat_quorum_gate \
    6b_security_baseline \
    6c_learn_auto_surface \
    6_write_uat_md \
    7_post_accept_actions; do
  (type -t mark_step >/dev/null 2>&1 \
    && mark_step "${PHASE_NUMBER:-unknown}" "${SHORT_CIRCUIT_STEP}" "${PHASE_DIR}") \
    || touch "${PHASE_DIR}/.step-markers/${SHORT_CIRCUIT_STEP}.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step \
    accept "${SHORT_CIRCUIT_STEP}" 2>/dev/null || true
done

# 5) Emit canonical short-circuit event for audit trail
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "accept.aborted_with_short_circuit" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"step\":\"4_build_uat_checklist\",\"reason\":\"user-abort\"}" \
  >/dev/null 2>&1 || true

# 6) Emit terminal `accept.completed` (must_emit_telemetry contract)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "accept.completed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"verdict\":\"ABORTED\"}" \
  >/dev/null 2>&1 || true

# 7) Close the run cleanly via run-complete (verifies contract one last time)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-complete
exit 0
# --- end abort short-circuit block ----------------------------------------
```

## Marker

After validation + user proceed:
```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_build_uat_checklist" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_build_uat_checklist.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 4_build_uat_checklist 2>/dev/null || true
```

</step>
