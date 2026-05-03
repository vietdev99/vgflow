<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 10: L3 — Auto-fix loop STEP 5.5

**Files:**
- Create: `commands/vg/_shared/build/in-scope-fix-loop.md` (orchestrator-side)
- Create: `commands/vg/_shared/build/in-scope-fix-loop-delegation.md` (subagent prompt)
- Modify: `commands/vg/build.md` (wire STEP 5.5 between STEP 5 and STEP 6)

- [ ] **Step 1: Create the orchestrator step ref**

Create `commands/vg/_shared/build/in-scope-fix-loop.md`:

```markdown
# build in-scope-fix-loop (STEP 5.5 — HEAVY, conditional)

This step runs ONLY when STEP 5 (post-execution) emits
`build.l4a_violations_detected` OR /vg:review Phase 2 emits warnings with
machine-readable evidence files. Otherwise the step exits silently.

<HARD-GATE>
Auto-fix subagent MUST honor `phase_ownership` allowlist (B6). Touching
files outside ownership = subagent error JSON {"error":"out_of_scope_edit"}
+ orchestrator reverts the fix attempt and reclassifies warning as
NEEDS_TRIAGE.

Fix-loop iteration cap: max 3 attempts per warning. Stop early when:
- Same gate fails twice with materially same evidence (regression detect)
- Fix scope expands outside phase-owned files (ownership violation)
- Migration / schema / API behavior change required (cross-phase impact)
- Auto-fix subagent returns {"error":"requires_product_decision"}

NO AskUserQuestion mid-build. Build fails with precise repair packet,
does NOT hang.
</HARD-GATE>

## STEP 5.5 — orchestration

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 8_5_in_scope_fix_loop || true

EVIDENCE_DIR="${PHASE_DIR}/.evidence"
if [ ! -d "$EVIDENCE_DIR" ] || [ -z "$(ls -A "$EVIDENCE_DIR"/*.json 2>/dev/null)" ]; then
  echo "▸ STEP 5.5: no evidence files — skipping (build is clean OR L4a not triggered)"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 8_5_in_scope_fix_loop || true
  exit 0
fi

# Classify each evidence file
mkdir -p "${EVIDENCE_DIR}/classified"
TOTAL_IN_SCOPE=0
TOTAL_FORWARD=0
TOTAL_TRIAGE=0

for ev in "${EVIDENCE_DIR}"/*.json; do
  [ "$(basename "$ev")" = "classified" ] && continue
  [ -d "$ev" ] && continue

  CLS=$("${PYTHON_BIN:-python3}" .claude/scripts/classify-build-warning.py \
    --phase-dir "${PHASE_DIR}" --warning "$ev" 2>/dev/null) || continue

  CLASSIFICATION=$(echo "$CLS" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(json.load(sys.stdin)['classification'])")

  case "$CLASSIFICATION" in
    IN_SCOPE)        TOTAL_IN_SCOPE=$((TOTAL_IN_SCOPE+1))
                     mv "$ev" "${EVIDENCE_DIR}/classified/in-scope.$(basename "$ev")" ;;
    NEEDS_TRIAGE)    TOTAL_TRIAGE=$((TOTAL_TRIAGE+1))
                     mv "$ev" "${EVIDENCE_DIR}/classified/triage.$(basename "$ev")" ;;
    FORWARD_DEP)     TOTAL_FORWARD=$((TOTAL_FORWARD+1))
                     mv "$ev" "${EVIDENCE_DIR}/classified/forward.$(basename "$ev")" ;;
    *)               mv "$ev" "${EVIDENCE_DIR}/classified/advisory.$(basename "$ev")" ;;
  esac
done

echo "▸ STEP 5.5: classified — IN_SCOPE=${TOTAL_IN_SCOPE}, NEEDS_TRIAGE=${TOTAL_TRIAGE}, FORWARD_DEP=${TOTAL_FORWARD}"

# Append FORWARD_DEPs to .vg/FORWARD-DEPS.md (consumed by next phase /vg:scope)
if [ "$TOTAL_FORWARD" -gt 0 ]; then
  FWD="${PLANNING_DIR:-.vg}/FORWARD-DEPS.md"
  {
    echo "## Forward deps from phase ${PHASE_NUMBER} ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
    for f in "${EVIDENCE_DIR}/classified/forward."*.json; do
      "${PYTHON_BIN:-python3}" -c "
import json, sys
d = json.load(open('$f'))
print(f\"- [{d['severity']}] {d['summary']}\")
print(f\"  Source: {d['detected_by']}; phase {d['phase']}\")
print(f\"  Recommended: {d.get('recommended_action','(none)')}\")
"
    done
  } >> "$FWD"
fi

# Spawn fix-loop for each IN_SCOPE warning (max 3 attempts each)
if [ "$TOTAL_IN_SCOPE" -gt 0 ]; then
  echo "▸ STEP 5.5: dispatching auto-fix subagent for ${TOTAL_IN_SCOPE} IN_SCOPE warning(s)"
  for ev in "${EVIDENCE_DIR}/classified/in-scope."*.json; do
    bash scripts/vg-narrate-spawn.sh general-purpose spawning "in-scope-fix $(basename "$ev")"

    # Agent(subagent_type="general-purpose", prompt=<from in-scope-fix-loop-delegation.md>):
    #   reads: $ev (warning evidence), PHASE_DIR/PLAN/, source files referenced
    #   writes: code edits (within phase ownership), commit per fix
    #   returns: {"status":"FIXED|UNRESOLVED|OUT_OF_SCOPE", "iterations":N, "summary":"..."}

    bash scripts/vg-narrate-spawn.sh general-purpose returned "$(basename "$ev")"

    # B7 regression smoke after fix
    "${PYTHON_BIN:-python3}" -c "
import json, sys
sys.path.insert(0, '.claude/scripts/lib')
from regression_smoke import detect_runner, select_smoke_tests, run_smoke
from pathlib import Path
ev = json.load(open('$ev'))
runner = detect_runner(Path('.'))
patterns = select_smoke_tests(Path('.'), ev.get('evidence_refs', []))
ok, output = run_smoke(Path('.'), runner, patterns) if runner and patterns else (True, 'no runner/patterns')
print(json.dumps({'ok': ok, 'patterns': patterns, 'output_tail': output[-500:] if output else ''}))
" > "${EVIDENCE_DIR}/classified/$(basename "$ev").smoke.json"
  done
fi

# Block build if any IN_SCOPE remains UNRESOLVED, or NEEDS_TRIAGE > 0
UNRESOLVED=$(grep -l '"status":"UNRESOLVED"' "${EVIDENCE_DIR}/classified/in-scope."*.fixed.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$TOTAL_TRIAGE" -gt 0 ] || [ "${UNRESOLVED:-0}" -gt 0 ]; then
  echo "⛔ STEP 5.5: ${UNRESOLVED} IN_SCOPE_UNRESOLVED + ${TOTAL_TRIAGE} NEEDS_TRIAGE — build BLOCKED"
  echo "   Repair packets: ${EVIDENCE_DIR}/classified/"
  echo "   Run /vg:debug to handle, OR /vg:amend if scope change is appropriate."
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "build.in_scope_fix_loop_blocked" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"unresolved\":${UNRESOLVED:-0},\"triage\":${TOTAL_TRIAGE}}" \
    2>/dev/null || true
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "build.in_scope_fix_loop_complete" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\",\"fixed\":${TOTAL_IN_SCOPE},\"forward\":${TOTAL_FORWARD}}" \
  2>/dev/null || true

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 8_5_in_scope_fix_loop || true
```
```

- [ ] **Step 2: Create the subagent delegation prompt**

Create `commands/vg/_shared/build/in-scope-fix-loop-delegation.md`:

```markdown
# in-scope-fix-loop delegation contract (general-purpose subagent)

You are the IN_SCOPE auto-fix subagent. The orchestrator dispatches you per
classified warning. Your job: fix ONE warning within phase ownership, max 3
attempts.

## Input envelope

```json
{
  "warning": { /* full BuildWarningEvidence doc */ },
  "phase_dir": ".vg/phases/4.1-billing",
  "ownership_allowlist_files": ["apps/api/src/billing/invoices.ts", ...],
  "ownership_allowlist_dirs":  ["apps/api/src/billing/"],
  "max_attempts": 3,
  "regression_smoke_runner": "vitest"
}
```

## Procedure

1. Read warning + ownership allowlist.
2. For attempt N in 1..max_attempts:
   a. Analyze warning's evidence_refs to identify affected files.
   b. Each file MUST be in `ownership_allowlist_files` OR have a prefix in
      `ownership_allowlist_dirs`. If not, return:
      ```json
      {"status": "OUT_OF_SCOPE", "iterations": N, "summary": "<file path> not in phase ownership"}
      ```
   c. Apply minimal fix (DRY, YAGNI — change only what's needed for the warning).
   d. Re-run the validator that produced the warning (warning.detected_by).
      Pass `--phase {phase}` to the same script.
   e. If validator returns 0 (PASS): return:
      ```json
      {"status": "FIXED", "iterations": N, "summary": "applied fix to <files>; validator now passes"}
      ```
   f. If validator returns same evidence as previous attempt (no progress):
      stop early.
3. If all 3 attempts fail OR no progress, return:
   ```json
   {"status": "UNRESOLVED", "iterations": 3, "summary": "<root cause analysis>",
    "repair_packet": {"hint": "...", "blocked_by": "..."}}
   ```

## Forbidden

- Editing files outside ownership_allowlist (use OUT_OF_SCOPE).
- Calling AskUserQuestion (build is non-interactive).
- Spawning child agents (this is a leaf subagent).
- Modifying API-CONTRACTS.md (use /vg:amend instead — return UNRESOLVED with
  blocked_by="contract_amendment_required").
- Adding test stubs without implementations (TDD: red first, then green).

## Output

Return JSON to orchestrator. Orchestrator handles regression smoke + commit.
```

- [ ] **Step 3: Wire STEP 5.5 into build.md**

Edit `commands/vg/build.md`. Find `### STEP 6 — crossai loop` and INSERT before it:

```markdown
### STEP 5.5 — In-scope warning auto-fix (HEAVY, conditional)

Read `_shared/build/in-scope-fix-loop.md`. Runs ONLY when STEP 5 emits
`build.l4a_violations_detected` or /vg:review left machine-readable evidence
in `${PHASE_DIR}/.evidence/`. For each IN_SCOPE warning, narrate + spawn:

```bash
bash scripts/vg-narrate-spawn.sh general-purpose spawning "in-scope-fix <warning_id>"
```

Then `Agent(subagent_type="general-purpose", prompt=<from in-scope-fix-loop-delegation.md>)`.

Build BLOCKS at end of STEP 5.5 if any IN_SCOPE remains UNRESOLVED OR any
warning classified NEEDS_TRIAGE.
```

Add to `must_touch_markers:` in build.md frontmatter:

```yaml
    - name: "8_5_in_scope_fix_loop"
      severity: "warn"
```

- [ ] **Step 4: Commit**

```bash
git add commands/vg/_shared/build/in-scope-fix-loop.md commands/vg/_shared/build/in-scope-fix-loop-delegation.md commands/vg/build.md
git commit -m "feat(build-fix-loop): add L3 STEP 5.5 in-scope auto-fix loop with ownership + smoke"
```

---

