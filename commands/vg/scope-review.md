---
name: vg:scope-review
description: Cross-phase scope validation — detect conflicts, overlaps, and gaps across all scoped phases
argument-hint: "[--skip-crossai] [--phases=7.6,7.8,7.10] [--full]"
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
    - event_type: "scope_review.started"
    - event_type: "scope_review.completed"
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **Run AFTER scoping, BEFORE blueprint** — this is a cross-phase gate between scope and blueprint.
4. **Automated checks first** — 5 deterministic checks run before any AI review.
5. **DISCUSSION-LOG.md is APPEND-ONLY** — never overwrite, never delete existing content.
6. **Resolution is interactive** — conflicts and gaps require user decision, not AI auto-fix.
7. **Minimum 2 phases** — warn (not block) if only 1 phase scoped.
8. **Incremental by default (tăng cường theo delta)** — scope is narrowed to changed + new + dependent phases via `${PLANNING_DIR}/.scope-review-baseline.json`. Use `--full` for complete rescan (mốc gốc — full baseline rebuild).
</rules>

<objective>
Cross-phase scope validation gate. Run after scoping all (or multiple) phases, before starting blueprint on any of them.
Detects decision conflicts, module overlaps, endpoint collisions, dependency gaps, and scope creep across phases.

Output: ${PLANNING_DIR}/SCOPE-REVIEW.md (report with gate verdict)

Pipeline position: specs -> scope -> **scope-review** -> blueprint -> build -> review -> test -> accept
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR).

### Preflight section (extracted v2.74.0 T1)

Read `_shared/scope-review/preflight.md` and follow it exactly.
Includes 2 steps: 0_parse_and_collect, incremental_check.

Step coverage: 0_parse_and_collect, incremental_check.


<step name="1_cross_reference">
## Step 1: CROSS-REFERENCE (automated, fast)

Run 5 deterministic checks. No AI reasoning — pure string matching and comparison.

### Check A — DECISION CONFLICTS

Compare decisions across phases. Look for:
- Same technology mentioned with different approaches (e.g., Phase 7.6 says "Redis caching", Phase 7.8 says "in-memory caching")
- Same module/service with conflicting architecture (e.g., Phase 7.6 says "monolith handler", Phase 7.8 says "microservice")
- Contradictory business rules (e.g., Phase 7.6 says "admin-only", Phase 7.8 says "public access" for same resource)

For each pair of phases, compare decision text for keyword overlap + contradiction signals.

**Output format:**
```
Check A — Decision Conflicts: {N found | CLEAN}
```
If found, collect: `{ id: "C-XX", phase_a, phase_b, decision_a, decision_b, issue, recommendation }`

### Check B — MODULE OVERLAP

Two or more phases modify the same file or module directory. Compare:
- Endpoint paths: same `/api/v1/{module}/` prefix in 2+ phases
- UI component names: same component name in 2+ phases
- Inferred directories: same `apps/api/src/modules/{name}` or `apps/web/src/pages/{name}`

This is not always a problem (phases can extend the same module), but must be flagged for review.

**Output format:**
```
Check B — Module Overlap: {N found | CLEAN}
```
If found, collect: `{ id: "O-XX", phases: [], shared_resource, recommendation }`

### Check C — ENDPOINT COLLISION

Same HTTP method + path defined in 2 different phases. This is always a conflict.

Compare all extracted endpoints: `${METHOD} ${PATH}` pairs across phases.

**Output format:**
```
Check C — Endpoint Collision: {N found | CLEAN}
```
If found, collect: `{ id: "EC-XX", phase_a, phase_b, method, path, recommendation }`

### Check D — DEPENDENCY GAPS

Phase A assumes output from Phase B, but Phase B's CONTEXT.md doesn't define that output.
Or: Phase A references a module/service that no phase creates.

Check:
- Explicit dependencies ("Depends on Phase X" in CONTEXT.md)
- Implicit dependencies (Phase A endpoint references a collection/service that only Phase B creates)

**Output format:**
```
Check D — Dependency Gaps: {N found | CLEAN}
```
If found, collect: `{ id: "DG-XX", phase, missing_dependency, recommendation }`

### Check E — SCOPE CREEP

Decisions in scoped phases overlap with already-DONE phases.
Compare decision endpoints and module names against shipped phases.

Check:
- Endpoint in a new phase already exists in a DONE phase (re-implementation risk)
- UI component in a new phase duplicates one from a DONE phase
- Business rule contradicts a shipped decision

**Output format:**
```
Check E — Scope Creep: {N found | CLEAN}
```
If found, collect: `{ id: "SC-XX", new_phase, done_phase, overlap, recommendation }`

### Summary after all checks:
```
Cross-Reference Results:
  Check A (decision conflicts):  {N} found
  Check B (module overlap):      {N} found
  Check C (endpoint collision):  {N} found
  Check D (dependency gaps):     {N} found
  Check E (scope creep):         {N} found
  Total issues: {sum}
```
</step>

<step name="2_crossai_review">
## Step 2: CROSSAI REVIEW (config-driven)

**Skip if:** `$SKIP_CROSSAI` flag is set, OR `config.crossai_clis` is empty, OR only 1 phase scoped.

Prepare context file at `${VG_TMP}/vg-crossai-scope-review.md`:

```markdown
# CrossAI Cross-Phase Scope Review

Review these {N} phase scopes for conflicts, overlaps, gaps, and inconsistencies.

## Focus Areas
1. Architectural consistency across phases
2. Data model evolution (does Phase B's schema break Phase A's assumptions?)
3. Auth model consistency (same role, same permissions across phases?)
4. Integration points (do phases that must connect actually define compatible interfaces?)
5. Ordering risks (does Phase B NEED Phase A to ship first? Is that captured?)

## Verdict Rules
- pass: no critical conflicts, all integration points compatible
- flag: minor inconsistencies that are manageable
- block: critical conflict or missing dependency that will cause build failure

## Phase Artifacts
---
{For each scoped phase: include full CONTEXT.md content, separated by phase headers}
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PLANNING_DIR}/crossai"`, `$LABEL="scope-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

Collect CrossAI findings into the report.
</step>

<step name="3_write_report">
## Step 3: WRITE REPORT

Write to `${PLANNING_DIR}/SCOPE-REVIEW.md`:

```markdown
# Scope Review — {ISO date}

**Mode:** {INCREMENTAL (tăng cường theo delta) | FULL (quét toàn bộ)}
{If incremental:}
📊 Incremental scan: {CHANGED_COUNT} phases changed since {BASELINE_TS}, {NEW_COUNT} new
   Scope this run: [{SCAN_LIST}]
   Skipped (unchanged — bỏ qua vì không đổi): {len(SKIPPED_SET)} phases
   {If REMOVED_COUNT>0:}Removed from disk (xoá khỏi đĩa): {REMOVED_LIST}

Phases reviewed: {phase list with names}
Total decisions across phases: {N}
Total endpoints across phases: {N}

## Conflicts (MUST RESOLVE)

| ID | Phase A | Phase B | Issue | Recommendation |
|----|---------|---------|-------|----------------|
| C-01 | {phase} D-{XX} | {phase} D-{XX} | {description} | {recommendation} |

{If no conflicts: "No decision conflicts found."}

## Endpoint Collisions (MUST RESOLVE)

| ID | Phase A | Phase B | Endpoint | Recommendation |
|----|---------|---------|----------|----------------|
| EC-01 | {phase} | {phase} | {METHOD /path} | {recommendation} |

{If no collisions: "No endpoint collisions found."}

## Overlaps (REVIEW)

| ID | Phases | Shared Resource | Recommendation |
|----|--------|-----------------|----------------|
| O-01 | {phases} | {module/file/component} | {recommendation} |

{If no overlaps: "No module overlaps found."}

## Dependency Gaps (MUST FILL)

| ID | Phase | Missing Dependency | Recommendation |
|----|-------|--------------------|----------------|
| DG-01 | {phase} | {what's missing} | {recommendation} |

{If no gaps: "No dependency gaps found."}

## Scope Creep (REVIEW)

| ID | New Phase | Done Phase | Overlap | Recommendation |
|----|-----------|------------|---------|----------------|
| SC-01 | {phase} | {done_phase} | {description} | {recommendation} |

{If no creep: "No scope creep detected."}

## CrossAI Findings

{CrossAI consensus results, or "Skipped (--skip-crossai or no CLIs configured)"}

## Gate

**Status: {PASS | BLOCK}**

Criteria:
- Conflicts (Check A): {N} — {MUST be 0 for PASS}
- Endpoint Collisions (Check C): {N} — {MUST be 0 for PASS}
- Dependency Gaps (Check D): {N} — {MUST be 0 for PASS}
- Overlaps (Check B): {N} — {reviewed, may be intentional}
- Scope Creep (Check E): {N} — {reviewed, may be intentional}
- CrossAI: {verdict} — {block verdicts count toward BLOCK}

**Verdict: {PASS — ready for blueprint | BLOCK — resolve {N} issues first}**
```

**Gate logic:**
- PASS if: 0 conflicts (A) + 0 endpoint collisions (C) + 0 dependency gaps (D) + CrossAI not "block"
- BLOCK if: any conflict OR any collision OR any dependency gap OR CrossAI "block"
- Overlaps (B) and Scope Creep (E) are informational — do not block, but must be reviewed
</step>

<step name="4_resolution">
## Step 4: RESOLUTION (if BLOCK)

If gate status is BLOCK, for each blocking issue:

```
AskUserQuestion:
  header: "Resolve: {issue_id} — {short description}"
  question: |
    **Issue:** {full description}
    **Phase A:** {phase} — {decision}
    **Phase B:** {phase} — {decision}
    **Recommendation:** {AI recommendation}

    How to resolve?
  options:
    - "Update Phase A scope — will need /vg:scope {phase_a} to re-discuss"
    - "Update Phase B scope — will need /vg:scope {phase_b} to re-discuss"
    - "Add dependency — update ROADMAP.md with ordering constraint"
    - "Accept as-is — mark as acknowledged risk"
```

Track resolutions:
- "Update Phase X" -> note which phases need re-scoping, suggest commands at end
- "Add dependency" -> append dependency note to ROADMAP.md (if exists)
- "Accept as-is" -> mark issue as "acknowledged" in SCOPE-REVIEW.md, downgrade from BLOCK

**After all resolutions:**
Re-evaluate gate. If all blocking issues resolved (updated scope or acknowledged):
- Update SCOPE-REVIEW.md gate status to PASS (with "acknowledged" notes)
- If any phases need re-scoping, do NOT auto-pass — list them:
  ```
  Gate conditionally PASS. Phases requiring re-scope:
    - /vg:scope {phase_a} (conflict C-01)
    - /vg:scope {phase_b} (gap DG-02)

  After re-scoping, run /vg:scope-review again to verify.
  ```
</step>

<step name="4.5_baseline_write_and_telemetry">
## Step 4.5: WRITE BASELINE + TELEMETRY (baseline = mốc gốc)

After gate verdict settles (PASS, conditional PASS, or even BLOCK — baseline always reflects current disk state so next incremental run has accurate delta), write the updated baseline:

```bash
# Count conflicts detected (sum across checks A..E)
CONFLICTS_FOUND=$(( ${CHECK_A_COUNT:-0} + ${CHECK_C_COUNT:-0} + ${CHECK_D_COUNT:-0} ))

# Write baseline atomically (via .tmp + mv)
BASELINE_PATH="${PLANNING_DIR}/.scope-review-baseline.json"
BASELINE_TMP="${BASELINE_PATH}.tmp"

${PYTHON_BIN:-python3} - "$PHASES_DIR" "$BASELINE_TMP" <<'PY'
import json, hashlib, sys, re, datetime
from pathlib import Path

phases_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def phase_id(name):
    m = re.match(r'^0*([0-9]+(?:\.[0-9]+)*)', name)
    return m.group(1) if m else name

phases = {}
for d in sorted(phases_dir.iterdir()):
    if not d.is_dir(): continue
    ctx = d / "CONTEXT.md"
    if not ctx.exists(): continue
    pid = phase_id(d.name)
    phases[pid] = {
        "context_sha256": sha(ctx),
        "spec_sha256": sha(d / "SPECS.md"),
    }

baseline = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "phases": phases,
}
out_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"✓ Baseline staged: {len(phases)} phases")
PY

mv "$BASELINE_TMP" "$BASELINE_PATH"
echo "✓ Baseline (mốc gốc) written: ${BASELINE_PATH}"

# Emit telemetry for incremental gate hit
# Reference: .claude/commands/vg/_shared/telemetry.md (emit_telemetry_v2)
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "gate_hit" "" "scope-review.incremental" \
    "scope-review-incremental" "PASS" \
    "{\"changed_count\":${CHANGED_COUNT:-0},\"new_count\":${NEW_COUNT:-0},\"removed_count\":${REMOVED_COUNT:-0},\"incremental\":${INCREMENTAL},\"conflicts_found\":${CONFLICTS_FOUND}}"
fi
```

**Rules:**
- Baseline write is NON-FATAL — if it fails, warn but do not block the gate decision.
- Baseline is always refreshed (even on BLOCK) so user's next re-run with fixes gets accurate delta.
- `.scope-review-baseline.json` should be committed alongside `SCOPE-REVIEW.md` in Step 5.
</step>

<step name="5_commit_and_next">
## Step 5: Commit + suggest next

```bash
git add "${PLANNING_DIR}/SCOPE-REVIEW.md" "${PLANNING_DIR}/.scope-review-baseline.json"
git commit -m "scope-review: ${#SCOPED_PHASES[@]} phases — ${GATE_VERDICT}"
```

**Display:**
```
Scope Review Complete.
  Phases: {N} reviewed
  Conflicts: {N} | Collisions: {N} | Overlaps: {N} | Gaps: {N} | Creep: {N}
  CrossAI: {verdict | skipped}
  Gate: {PASS | BLOCK}
```

**If PASS:**
```
  Ready for blueprint. Start with:
    /vg:blueprint {first-unblueprinted-phase}
```

**If BLOCK (still unresolved):**
```
  Resolve blocking issues before proceeding to blueprint.
  Re-run: /vg:scope-review after fixes.
```

**If conditional PASS (acknowledged risks):**
```
  Proceeding with acknowledged risks.
  {N} issues marked as accepted. See SCOPE-REVIEW.md for details.
  
  Next: /vg:blueprint {first-unblueprinted-phase}
```
</step>

</process>

<success_criteria>
- All phases with CONTEXT.md collected and parsed (or scoped down via incremental delta)
- Incremental mode active by default: baseline read, delta computed, SCAN_SET narrowed to changed + new + dependents
- `--full` flag forces rescan of every scoped phase, bypassing baseline
- 5 automated cross-reference checks executed (A through E) against SCAN_SET
- CrossAI review ran (or skipped if flagged/no CLIs/single phase)
- SCOPE-REVIEW.md written with structured report + delta summary header + gate verdict
- Baseline (`.scope-review-baseline.json`) written atomically after every run (even on BLOCK)
- Telemetry event `scope-review-incremental` emitted with changed/new/conflicts counts
- All blocking issues presented to user with resolution options
- Gate resolves to PASS (clean, conditional, or all-acknowledged) before suggesting blueprint
- Report + baseline committed to git
- Next step guidance shows /vg:blueprint for first unblueprinted phase
</success_criteria>
