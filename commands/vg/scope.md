---
name: vg:scope
description: Deep phase discussion — 5 structured rounds producing enriched CONTEXT.md + DISCUSSION-LOG.md
argument-hint: "<phase> [--skip-crossai] [--auto]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
---

<rules>
1. **VG-native** — no GSD delegation. This command is self-contained. Do NOT call /gsd-discuss-phase.
2. **Config-driven** — read .claude/vg.config.md for project paths, profile, models.
3. **SPECS.md required** — must exist before scoping. No SPECS = BLOCK.
4. **Scope = DISCUSSION only** — do NOT create API-CONTRACTS.md, TEST-GOALS.md, or PLAN.md. Those are blueprint's job.
5. **Enriched CONTEXT.md** — each decision `P{phase}.D-XX` has structured sub-sections (endpoints:, ui_components:, test_scenarios:). Blueprint reads these to generate artifacts accurately.

**Namespace (không gian tên) BREAKING v1.8.0:** CONTEXT.md decisions use `P{phase}.D-XX` format, where `{phase}` is the phase number (e.g., `P7.10.1.D-01` for phase 7.10.1, decision 01). Bare `D-XX` is LEGACY — written by pre-v1.8.0 scope runs, migrated via `.claude/scripts/migrate-d-xx-namespace.py`. Rationale: prevent collision (xung đột) with FOUNDATION.md `F-XX` and with other phases' `D-XX` at phase 15+.
6. **DISCUSSION-LOG.md is APPEND-ONLY** — never overwrite, never delete existing content. Only append new sessions.
7. **Pipeline names** — use V5 names: `/vg:blueprint` (not plan), `/vg:build` (not execute).
8. **5 rounds, then loop** — every round locks decisions. No round is skippable (except Round 4 UI/UX for backend-only profile).
</rules>

<objective>
Step after specs in VG pipeline. Deep structured discussion to extract all decisions for a phase.
Output: CONTEXT.md (enriched with endpoint/UI/test notes per decision) + DISCUSSION-LOG.md (append-only trail).

Pipeline: specs -> **scope** -> blueprint -> build -> review -> test -> accept
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first. Use config variables ($PLANNING_DIR, $PHASES_DIR, $PROFILE).

<step name="0_parse_and_validate">
## Step 0: Parse arguments + validate prerequisites

```bash
# Parse arguments
PHASE_NUMBER=""
SKIP_CROSSAI=false
AUTO_MODE=false

for arg in $ARGUMENTS; do
  case "$arg" in
    --skip-crossai) SKIP_CROSSAI=true ;;
    --auto) AUTO_MODE=true ;;
    *) PHASE_NUMBER="$arg" ;;
  esac
done
```

**Validate:**
1. `$PHASE_NUMBER` is provided. If empty -> BLOCK: "Usage: /vg:scope <phase>"
2. Read `${PLANNING_DIR}/ROADMAP.md` — confirm phase exists
3. Determine `$PHASE_DIR` by scanning `${PHASES_DIR}/` for matching directory
4. Check `${PHASE_DIR}/SPECS.md` exists. Missing -> BLOCK:
   ```
   SPECS.md not found for Phase {N}.
   Run first: /vg:specs {phase}
   ```

**If CONTEXT.md already exists:**
```
AskUserQuestion:
  header: "Existing Scope"
  question: "CONTEXT.md already exists for Phase {N} ({decision_count} decisions). What would you like to do?"
  options:
    - "Update — re-discuss and enrich existing scope"
    - "View — show current CONTEXT.md contents"
    - "Skip — proceed to /vg:blueprint"
```
- "Update" -> continue (will overwrite CONTEXT.md but APPEND to DISCUSSION-LOG.md)
- "View" -> display contents, then re-ask
- "Skip" -> exit with "Next: /vg:blueprint {phase}"

**If codebase-map.md exists:** Read `.planning/codebase-map.md` silently -> inject god nodes + communities as context for discussion rounds.

**Read SPECS.md:** Extract Goal, In-scope items, Out-of-scope items, Constraints, Success criteria. Hold in memory for all rounds.

**Update PIPELINE-STATE.json:** Set `steps.scope.status = "in_progress"`, `steps.scope.started_at = {now}`.
</step>

<step name="1_deep_discussion">
## Step 1: DEEP DISCUSSION (5 structured rounds)

For each round: AI presents analysis/recommendation FIRST (recommend-first pattern), then asks user to confirm/edit/expand. Each round locks a set of decisions.

Track all Q&A exchanges for DISCUSSION-LOG.md generation in Step 2.

### Round 1 — Domain & Business

AI reads SPECS.md goal + in-scope items. Pre-analyze:
- What user stories does this phase serve?
- Which roles are involved?
- What business rules apply?

Present analysis, then ask:

```
AskUserQuestion:
  header: "Round 1 — Domain & Business"
  question: |
    Based on SPECS.md, here's my understanding:

    **Goal:** {extracted goal}
    **User stories I see:**
    - US-1: {story}
    - US-2: {story}

    **Roles involved:** {roles}
    **Business rules:** {rules}

    Confirm, edit, or add more context?
  (open text)
```

**If --auto mode:** AI picks recommended answers based on SPECS.md + codebase context. Log "[AUTO]" in discussion log.

From response, lock decisions:
- `P${PHASE_NUMBER}.D-01` through `P${PHASE_NUMBER}.D-XX` (category: business)
- Each decision captures: title, decision text, rationale
- **Namespace enforcement:** Always prefix with `P${PHASE_NUMBER}.` (where ${PHASE_NUMBER} is extracted from $ARGUMENTS). If phase is "7.10.1", the decision ID is `P7.10.1.D-01`. Never write bare `D-01` (legacy — blocked by commit-msg hook from v1.10.1).

### Round 2 — Technical Approach

AI pre-analyzes existing code via `config.code_patterns` paths. Identify:
- Which services/modules need changes?
- Database collections/schema shape?
- External dependencies?

Present analysis with code status table:

```
AskUserQuestion:
  header: "Round 2 — Technical Approach"
  question: |
    **Architecture analysis:**
    | Component | Status | Recommendation |
    |-----------|--------|----------------|
    | {module} | {exists/new/partial} | {what to do} |

    **Database:** {collections needed}
    **Dependencies:** {external deps}

    Confirm or adjust?
  (open text)
```

Lock decisions D-XX+1.. (category: technical)

### Round 3 — API Design

AI SUGGESTS endpoints derived from locked decisions:

```
AskUserQuestion:
  header: "Round 3 — API Design"
  question: |
    Based on decisions so far, I suggest these endpoints:

    | # | Endpoint | Method | Auth | Purpose | From Decision |
    |---|----------|--------|------|---------|---------------|
    | 1 | /api/v1/{resource} | POST | {role} | {purpose} | D-{XX} |
    | 2 | /api/v1/{resource} | GET | {role} | {purpose} | D-{XX} |
    ...

    **Request/response shapes (high level):**
    - POST /api/v1/{resource}: body {fields} -> 201 {response}
    - GET /api/v1/{resource}: query {params} -> 200 [{items}]

    Confirm, edit, or add endpoints?
  (open text)
```

User confirms/edits each endpoint. Lock ENDPOINT NOTES embedded within existing decisions.

### Round 4 — UI/UX

**Skip condition:** If `$PROFILE` is "web-backend-only" or "cli-tool" or "library" -> skip this round entirely. Log: "Round 4 skipped (profile: {profile})."

AI suggests pages/components from decisions + endpoint notes:

```
AskUserQuestion:
  header: "Round 4 — UI/UX"
  question: |
    **Pages/views needed:**
    | Page | Components | Maps to Endpoints |
    |------|-----------|-------------------|
    | {PageName} | {component list} | GET/POST /api/... |

    **Key components:**
    - {ComponentName}: {description}

    **Design refs available?** {yes/no — check ${PHASE_DIR}/ for design assets}

    Confirm or adjust?
  (open text)
```

Lock UI COMPONENT NOTES embedded within existing decisions.

### Round 5 — Test Scenarios

AI derives test scenarios from decisions + endpoints + UI components:

```
AskUserQuestion:
  header: "Round 5 — Test Scenarios"
  question: |
    **Happy path scenarios:**
    | ID | Scenario | Endpoint | Expected | Decision |
    |----|----------|----------|----------|----------|
    | TS-01 | {user does X} | POST /api/... | 201 + {result} | D-{XX} |
    | TS-02 | {user does Y} | GET /api/... | 200 + {list} | D-{XX} |

    **Edge cases:**
    | ID | Scenario | Expected |
    |----|----------|----------|
    | TS-{N} | {what can go wrong} | {error code + message} |

    **Mutation evidence:**
    | Action | Verify Where |
    |--------|-------------|
    | Create {X} | Appears in list + DB |
    | Update {X} | Updated fields visible |
    | Delete {X} | Removed from list + DB |

    Confirm, edit, or add more scenarios?
  (open text)
```

Lock TEST SCENARIO NOTES embedded within existing decisions.

### Deep Probe Loop (mandatory — minimum 5 probes after Round 5)

**Purpose:** Rounds 1-5 capture the KNOWN decisions. This loop discovers what's UNKNOWN — gray areas, edge cases, implicit assumptions the AI made, conflicts between decisions.

**Rules:**
1. AI asks ONE focused question per turn, with its own recommendation
2. Do NOT ask "do you have anything else?" — AI drives the investigation, not user
3. Target minimum 10 total probes (5 structured rounds + 5+ deep probes)
4. User adds extra ideas in their answers — AI integrates and continues probing
5. Stop only when AI genuinely cannot find more gray areas (not when user seems done)

**Probe generation strategy — AI self-analyzes locked decisions for:**
```
- CONFLICTS: D-XX says "use Redis cache" but D-YY says "minimize infrastructure" → which wins?
- IMPLICIT ASSUMPTIONS: D-XX assumes "user is logged in" but login flow not in scope → clarify
- MISSING ERROR PATHS: D-XX defines happy path but not what happens on failure
- EDGE CASES: D-XX says "max 20 items" but what about exactly 20? Or migrating from >20?
- PERMISSION GAPS: endpoints have auth but role escalation not discussed
- DATA LIFECYCLE: create and read discussed but archive/purge/retention not
- CONCURRENCY: what if 2 users do the same thing simultaneously?
- MIGRATION: existing data compatibility with new schema
- PERFORMANCE: scaling implications of chosen approach
- SECURITY: input validation, rate limiting, injection risks for this specific phase
```

**Probe format:**
```
AskUserQuestion:
  header: "Deep Probe #{N}"
  question: |
    Analyzing decisions so far, I found a gray area:

    **{specific concern}**

    Context: {D-XX says this, but {what's unclear}}

    **My recommendation:** {AI's suggested resolution}

    Agree with recommendation, or different approach?
  (open text)
```

**After each answer:** Lock/update the affected decision. Generate next probe from remaining gray areas. Continue until:
- AI has probed at least 5 times after Round 5 (10 total interactions minimum)
- AND AI genuinely cannot identify more gray areas in the locked decisions

**When exhausted (no more gray areas):**
AI states: "I've analyzed all {N} decisions for conflicts, edge cases, and gaps. {M} gray areas resolved through probes. Proceeding to artifact generation."
→ Proceed to Step 2. No confirmation question needed — AI decides when scope is thorough enough.
</step>

<step name="2_artifact_generation">
## Step 2: ARTIFACT GENERATION

Write ONLY 2 files. No API-CONTRACTS.md, no TEST-GOALS.md, no PLAN.md.

### CONTEXT.md

Write to `${PHASE_DIR}/CONTEXT.md`:

```markdown
# Phase {N} — {Name} — CONTEXT

Generated: {ISO date}
Source: /vg:scope structured discussion (5 rounds)

## Decisions

**Namespace:** IDs are `P{phase}.D-XX` where `{phase}` = `${PHASE_NUMBER}` (this phase's identifier from ROADMAP). Example below uses phase 7.10.1 → IDs like `P7.10.1.D-01`. Substitute actual phase number when generating.

### P${PHASE_NUMBER}.D-01: {decision title}
**Category:** business | technical
**Decision:** {what was decided}
**Rationale:** {why}
**Endpoints:**
- POST /api/v1/{resource} (auth: {role}, purpose: {description})
- GET /api/v1/{resource} (auth: {role}, purpose: {description})
**UI Components:**
- {ComponentName}: {description of what it shows/does}
- {ComponentName}: {description}
**Test Scenarios:**
- TS-01: {user does X} -> {expected result}
- TS-02: {edge case} -> {expected error}
**Constraints:** {if any, else omit this line}

### P${PHASE_NUMBER}.D-02: {decision title}
**Category:** ...
...

{repeat for all decisions}

## Summary
- Total decisions: {N}
- Endpoints noted: {N}
- UI components noted: {N}
- Test scenarios noted: {N}
- Categories: {business: N, technical: N}

## Deferred Ideas
- {ideas captured during discussion but explicitly out of scope}
- {or "None" if no deferred ideas}
```

**Rules for CONTEXT.md:**
- Decisions MUST be numbered sequentially: `P{phase}.D-01`, `P{phase}.D-02`, ... (phase prefix MANDATORY — see namespace rule in command header)
- Every decision with endpoints MUST have at least 1 test scenario
- Endpoint format: `METHOD /path (auth: role, purpose: description)`
- UI component format: `ComponentName: description`
- Test scenario format: `TS-XX: action -> expected result`
- Omit empty sub-sections (e.g., if a technical decision has no endpoints, omit **Endpoints:** entirely)

**Write-strict gate (v1.9.0 T5 — HARD BLOCK):**
Before promoting `CONTEXT.md.staged` to `CONTEXT.md`, run the namespace validator:

```bash
# shellcheck disable=SC1091
source .claude/commands/vg/_shared/lib/namespace-validator.sh

STAGED="${PHASE_DIR}/CONTEXT.md.staged"
if ! validate_d_xx_namespace "$STAGED" "phase:${PHASE_NUMBER}"; then
  echo ""
  echo "⛔ Scope gate chặn: CONTEXT.md.staged còn chứa bare D-XX. Sửa hết rồi chạy lại /vg:scope ${PHASE_NUMBER} --continue."
  exit 1
fi
mv "$STAGED" "${PHASE_DIR}/CONTEXT.md"
```

The validator tolerates legacy `D-XX` inside fenced code blocks and blockquotes (cho phép example/migration docs). Live decisions outside code fences MUST use `P${PHASE_NUMBER}.D-XX`.

### DISCUSSION-LOG.md

**APPEND-ONLY.** If file already exists, append a new session block. Never overwrite existing content.

Append to `${PHASE_DIR}/DISCUSSION-LOG.md`:

```markdown
# Discussion Log — Phase {N}

## Session {ISO date} — {Initial Scope | Re-scope | Update}

### Round 1: Domain & Business
**Q:** {AI's question/analysis — abbreviated}
**A:** {user's response — full text}
**Locked:** D-01, D-02, D-03

### Round 2: Technical Approach
**Q:** {AI's analysis}
**A:** {user's response}
**Locked:** D-04, D-05

### Round 3: API Design
**Q:** {AI's endpoint suggestions}
**A:** {user's edits/confirmations}
**Locked:** Endpoint notes added to D-01, D-03, D-05

### Round 4: UI/UX
**Q:** {AI's component suggestions}
**A:** {user's response}
**Locked:** UI notes added to D-01, D-02

### Round 5: Test Scenarios
**Q:** {AI's scenario suggestions}
**A:** {user's response}
**Locked:** TS-01 through TS-{N}

### Loop: Additional Discussion
{if any additional rounds occurred, log them here}
{or omit this section if user chose "Done" after Round 5}
```

**If file already exists (re-scope):** Read existing content, then append new session with incremented session label. Preserve all previous sessions verbatim.
</step>

<step name="3_completeness_validation">
## Step 3: COMPLETENESS VALIDATION (automated)

Run automated checks on the generated CONTEXT.md.

**Check A — Endpoint Coverage (⛔ BLOCK if any gaps — tightened 2026-04-17):**
For every decision D-XX that has **Endpoints:** section, verify at least 1 test scenario references that endpoint. Downstream `blueprint.md` 2b5 parses these test scenarios to generate TEST-GOALS — missing coverage = orphan goals that fail phase-end binding gate.
Gap -> ⛔ BLOCK: "D-{XX} has endpoints but no test scenario covering them."

**Check B — Design Ref Coverage (WARN):**
If `config.design_assets` is configured, for every decision with **UI Components:** section, check if a design-ref exists in `${PHASE_DIR}/` or `config.design_assets.output_dir`.
Gap -> WARN: "D-{XX} has UI components but no design reference found. Consider running /vg:design-extract."

**Check C — Decision Completeness (⛔ BLOCK if gap ratio > 10% — tightened 2026-04-17):**
Compare SPECS.md in-scope items against CONTEXT.md decisions. Every in-scope item should map to at least 1 decision.
Gap -> ⛔ BLOCK if >10% of specs items lack decisions: "SPECS in-scope item '{item}' has no corresponding decision in CONTEXT.md." Downstream blueprint generates orphan tasks that have no decision trace → citation gate fails.

**Check D — Orphan Detection (WARN):**
Check for decisions that don't trace back to any SPECS.md in-scope item (potential scope creep).
Found -> WARN: "D-{XX} doesn't map to any SPECS in-scope item. Intentional addition or scope creep?"

**Report:**
```
Completeness Validation:
  Check A (endpoint coverage):  {PASS | ⛔ N blockers}
  Check B (design ref):         {PASS | N warnings | N/A (no design assets)}
  Check C (specs coverage):     {PASS | ⛔ N blockers (>10% ratio) | N warnings}
  Check D (orphan detection):   {PASS | N warnings}
```

```bash
# HARD BLOCK enforcement
if [ "$CHECK_A_BLOCKERS" -gt 0 ] || [ "$CHECK_C_BLOCKERS" -gt 0 ]; then
  echo "⛔ Completeness gate FAILED. Resolve blockers before blueprint."
  echo "   Fix: /vg:scope ${PHASE_NUMBER} --continue  (adds missing test scenarios / decisions)"
  echo "   Or:  edit CONTEXT.md manually, then re-run /vg:scope ${PHASE_NUMBER} --validate-only"
  if [[ ! "$ARGUMENTS" =~ --allow-incomplete ]]; then
    exit 1
  else
    echo "⚠ --allow-incomplete set — recording gap in CONTEXT.md 'Known Gaps' section."
  fi
fi
```

Check B and D still WARN (softer signals). Check A and C are structural — block downstream errors.
</step>

<step name="4_crossai_review">
## Step 4: CROSSAI REVIEW (optional, config-driven)

**Skip if:** `$SKIP_CROSSAI` flag is set, OR `config.crossai_clis` is empty.

Prepare context file at `${VG_TMP}/vg-crossai-${PHASE_NUMBER}-scope-review.md`:

```markdown
# CrossAI Scope Review — Phase {PHASE_NUMBER}

Review the discussion output. Find gaps between SPECS requirements and CONTEXT decisions.

## Checklist
1. Every SPECS in-scope item has a corresponding CONTEXT decision
2. No CONTEXT decision contradicts a SPECS constraint
3. Success criteria achievable given decisions
4. No critical ambiguity unresolved
5. Out-of-scope items not accidentally addressed (scope creep)
6. Endpoint notes are complete (method, auth, purpose)
7. Test scenarios cover happy path AND edge cases for every endpoint

## Verdict Rules
- pass: coverage >=90%, no critical findings, score >=7
- flag: coverage >=70%, no critical findings, score >=5
- block: coverage <70%, OR any critical finding, OR score <5

## Artifacts
---
[SPECS.md full content]
---
[CONTEXT.md full content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="scope-review"`.
Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

**Handle results:**
- **Minor findings:** Log only, no action needed.
- **Major/Critical findings:** Present table to user:
  ```
  | # | Finding | Severity | CLI Source | Action |
  |---|---------|----------|------------|--------|
  | 1 | {issue} | major | Codex+Gemini | Re-discuss / Note / Ignore |
  ```
  For each major/critical finding:
  ```
  AskUserQuestion:
    header: "CrossAI Finding"
    question: "{finding description}"
    options:
      - "Re-discuss — open additional round to address this"
      - "Note — acknowledge and add to CONTEXT.md deferred section"
      - "Ignore — false positive, skip"
  ```
  If "Re-discuss" -> open free-form round focused on that finding, then re-run validation (Step 3) on updated CONTEXT.md.
  If "Note" -> append to CONTEXT.md ## Deferred Ideas section.
  If "Ignore" -> log in DISCUSSION-LOG.md as "CrossAI finding ignored: {reason}".
</step>

<step name="5_commit_and_next">
## Step 5: Commit + suggest next

**Update PIPELINE-STATE.json:** Set `steps.scope.status = "done"`, `steps.scope.finished_at = {now}`, `last_action = "scope: {N} decisions, {M} endpoints, {K} test scenarios"`.

```bash
# Count from CONTEXT.md — supports both new P{phase}.D-XX and legacy D-XX headers
DECISION_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")
ENDPOINT_COUNT=$(grep -c '^\- .* /api/' "${PHASE_DIR}/CONTEXT.md" || echo 0)
TEST_SCENARIO_COUNT=$(grep -c '^\- TS-' "${PHASE_DIR}/CONTEXT.md" || echo 0)

git add "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/DISCUSSION-LOG.md" "${PHASE_DIR}/PIPELINE-STATE.json"
git commit -m "scope(${PHASE_NUMBER}): ${DECISION_COUNT} decisions, ${ENDPOINT_COUNT} endpoints, ${TEST_SCENARIO_COUNT} test scenarios"
```

**Display summary:**
```
Scope complete for Phase {N}.
  Decisions: {N} ({business} business, {technical} technical)
  Endpoints: {M} noted
  UI Components: {K} noted
  Test Scenarios: {J} noted
  CrossAI: {verdict} ({score}/10) | skipped
  Validation: {pass_count}/4 checks passed, {warn_count} warnings

  Next: /vg:blueprint {phase}
```
</step>

</process>

<success_criteria>
- SPECS.md was read and all in-scope items are mapped to decisions
- 5 structured rounds completed (Round 4 skipped only for non-UI profiles)
- CONTEXT.md created with enriched decisions (endpoints, UI components, test scenarios per decision)
- DISCUSSION-LOG.md appended with full Q&A trail for this session
- Completeness validation ran (4 checks) and warnings surfaced
- CrossAI gap review ran (or skipped if flagged/no CLIs)
- All artifacts committed to git
- PIPELINE-STATE.json updated
- Next step guidance shows /vg:blueprint
</success_criteria>
