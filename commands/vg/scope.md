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

**Adversarial challenger (v1.9.1 R3, v1.9.3 R3.2 upgraded — 8 lenses + Opus, v1.9.5 R3.4 fd-3 content fix):** Source `.claude/commands/vg/_shared/lib/answer-challenger.sh` at top of command. After EVERY user answer in Rounds 1-5 AND in the Deep Probe Loop, invoke `challenge_answer "$user_answer" "round-$ROUND" "phase-scope" "$accumulated_draft"`.

**v1.9.5 R3.4 FIX — subagent sandbox isolation:** Helper emits prompt CONTENT (not path) on fd 3. Tmp file kept for audit only. Orchestrator MUST use this exact bash pattern to capture:
```bash
PROMPT=$(challenge_answer "$user_answer" "round-$ROUND" "phase-scope" "$accumulated" 3>&1 1>/dev/null 2>/dev/null)
```
(Prior docs said "Read the prompt file" — that failed because Task subagents can't access parent's /tmp.)

Orchestrator MUST:
1. Capture fd 3 via `3>&1 1>/dev/null 2>/dev/null` pattern → `$PROMPT` contains full inline content
2. Dispatch Task tool (subagent_type=general-purpose, model=`${config.scope.adversarial_model:-opus}` — v1.9.3 default Opus, zero parent context) with `prompt=$PROMPT` parameter
3. Parse subagent stdout (one JSON line)
4. Call `challenger_dispatch "$subagent_json" "round-$ROUND" "phase-scope" "$PHASE_NUMBER"`
5. If `has_issue=true` → AskUserQuestion with 3 options:
   - **Address** → re-enter Q for that round (don't advance); merge user's revised answer
   - **Acknowledge** → record tradeoff under `## Acknowledged tradeoffs` in CONTEXT.md staged
   - **Defer** → record under `## Open questions` in CONTEXT.md staged
6. Call `challenger_record_user_choice "$PHASE_NUMBER" "round-$ROUND" "phase-scope" "$choice"` to resolve telemetry
7. If `challenger_count_for_phase` reaches `config.scope.adversarial_max_rounds` (default 3) → helper auto-skips remaining challenges (loop guard)

Skip challenger when `config.scope.adversarial_check: false` (rapid prototyping) or answer is trivial (Y/N, single-word confirm — helper auto-detects via `challenger_is_trivial`).

**Dimension Expander (v1.9.3 R3.2 — NEW, proactive gap finding, v1.9.5 R3.4 fd-3 content fix):** Source `.claude/commands/vg/_shared/lib/dimension-expander.sh` at top of command. At the END of EACH round (Rounds 1-5) and at the END of the Deep Probe Loop, AFTER the adversarial challenger loop concludes and BEFORE advancing to next round, invoke `expand_dimensions "$ROUND" "$ROUND_TOPIC" "$round_qa_accumulated" ".planning/FOUNDATION.md"`.

**v1.9.5 R3.4 FIX — same pattern as challenger:** Helper emits prompt CONTENT on fd 3. Orchestrator capture pattern:
```bash
PROMPT=$(expand_dimensions "$ROUND" "$ROUND_TOPIC" "$accumulated" ".planning/FOUNDATION.md" 3>&1 1>/dev/null 2>/dev/null)
```

Orchestrator MUST:
1. Capture fd 3 via `3>&1 1>/dev/null 2>/dev/null` → `$PROMPT` = full inline prompt content
2. Dispatch Task tool (subagent_type=general-purpose, model=`${config.scope.dimension_expand_model:-opus}`, zero parent context) with `prompt=$PROMPT`
3. Parse subagent stdout (one JSON line)
4. Call `expander_dispatch "$subagent_json" "round-$ROUND" "$PHASE_NUMBER"`
5. If `critical_missing[] > 0` OR `nice_to_have_missing[] > 0` → AskUserQuestion with 3 options:
   - **Address critical** → re-enter round with each CRITICAL missing dimension added as new Q (append to round-$ROUND-followups.md)
   - **Acknowledge** → record dimensions under `## Acknowledged gaps` in CONTEXT.md staged
   - **Defer to open questions** → record under `## Open questions` in CONTEXT.md staged (will be re-raised in blueprint)
6. Call `expander_record_user_choice "$PHASE_NUMBER" "round-$ROUND" "$choice"` to resolve telemetry
7. If `expander_count_for_phase` reaches `config.scope.dimension_expand_max` (default 6 = 5 rounds + 1 deep probe) → helper auto-skips remaining expansions (loop guard)

Skip dimension-expander when `config.scope.dimension_expand_check: false` (rapid prototyping). Unlike challenger, expander runs ONCE per round (not per answer) — cost is bounded.

**Two helpers, complementary scope:**
- `answer-challenger` (per-answer): "is this specific answer wrong?" — 8 lenses on single answer
- `dimension-expander` (per-round): "what haven't we discussed yet?" — gap analysis on whole round

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

**Phase profile detection (P5, v1.9.2) — short-circuit for non-feature phases.**

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/phase-profile.sh" 2>/dev/null || true
if type -t detect_phase_profile >/dev/null 2>&1; then
  PHASE_PROFILE=$(detect_phase_profile "$PHASE_DIR")
  phase_profile_summarize "$PHASE_DIR" "$PHASE_PROFILE"

  case "$PHASE_PROFILE" in
    infra|hotfix|bugfix|migration|docs)
      echo "ℹ Phase profile='${PHASE_PROFILE}' — scope discussion không cần 5 vòng đầy đủ."
      echo "  Tạo CONTEXT.md rút gọn + thoát sớm. Blueprint sẽ chỉ tạo PLAN (+ ROLLBACK nếu migration)."
      # Generate minimal CONTEXT.md if not exists
      if [ ! -f "${PHASE_DIR}/CONTEXT.md" ]; then
        ${PYTHON_BIN} - "${PHASE_DIR}/CONTEXT.md" "$PHASE_NUMBER" "$PHASE_PROFILE" <<'PY'
import sys
from datetime import datetime
out, phase, profile = sys.argv[1], sys.argv[2], sys.argv[3]
content = f"""# Phase {phase} — Scope context ({profile} profile)

**Profile:** {profile}  
**Generated:** {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}  
**Scope mode:** short-circuit (no 5-round discussion — profile does not require feature-depth scoping)

## Decisions

_Non-feature profiles typically don't have architectural decisions — execution details live in SPECS.md.  
If you discover a decision worth recording, add it here with ID `P{phase}.D-XX`._

## Next

Run `/vg:blueprint {phase}` — will skip scope/contract/test-goals generation for non-feature profile.
"""
open(out, 'w', encoding='utf-8').write(content)
print(f"✓ CONTEXT.md stub written for profile={profile}")
PY
      fi
      echo "✓ Scope short-circuit done. Next: /vg:blueprint ${PHASE_NUMBER}"
      exit 0
      ;;
    feature|*)
      # default path — 5 rounds
      ;;
  esac
fi
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

**Adversarial challenge** (v1.9.1 R3 + v1.9.3 R3.2 upgrade — 8 lenses + Opus, applies to EVERY round including Rounds 2-5 and deep probes): after recording the user answer but BEFORE advancing to the next round, run `challenge_answer` + `challenger_dispatch` per the protocol in `<process>` header. If the challenger flags an issue and user chooses **Address**, re-enter this round with the user's revised answer. If **Acknowledge** → append under `## Acknowledged tradeoffs` in `CONTEXT.md.staged`. If **Defer** → append under `## Open questions`.

**Dimension expansion** (v1.9.3 R3.2 NEW, applies to EVERY round including Rounds 2-5 and deep probes — runs ONCE per round AFTER all Q&A + adversarial challenges complete, BEFORE advancing to next round): Invoke `expand_dimensions "$ROUND" "$ROUND_TOPIC" "$round_qa_accumulated" ".planning/FOUNDATION.md"` where `$round_qa_accumulated` = all user answers of this round merged, `$ROUND_TOPIC` = the round's topic string (e.g., "Domain & Business" for Round 1). Dispatch Task tool (model=`${config.scope.dimension_expand_model:-opus}`, zero parent context) with prompt contents, parse subagent JSON, call `expander_dispatch` per the protocol in `<process>` header. If `critical_missing[]` or `nice_to_have_missing[]` non-empty, user picks: **Address critical** → re-enter round appending each CRITICAL dimension as new Q → merge user's new answers. **Acknowledge** → append dimensions under `## Acknowledged gaps` in `CONTEXT.md.staged`. **Defer** → append under `## Open questions` for blueprint to re-raise.

### Round 2 — Technical Approach

**Multi-surface gate (v1.10.0 R4 NEW):** if `config.surfaces` block declared (multi-platform project), Round 2 MUST first ask user which surfaces this phase touches.

```bash
if grep -qE "^surfaces:" .claude/vg.config.md; then
  # List surfaces from config
  AVAILABLE_SURFACES=$(${PYTHON_BIN} -c "
import re
cfg = open('.claude/vg.config.md', encoding='utf-8').read()
m = re.search(r'^surfaces:\n((?:  [^\n]+\n)+)', cfg, re.M)
if m:
    for line in m.group(1).split('\n'):
        sm = re.match(r'^  (\w[\w-]*):', line)
        if sm: print(sm.group(1))
")
  echo "Multi-surface project detected. Surfaces declared: $AVAILABLE_SURFACES"
  # AskUserQuestion multi-select: which surfaces does this phase touch?
  # Example: phase 13 (DSP admin) touches [web, api] but not [rtb, workers]
  # Lock SURFACE_LIST in CONTEXT.md + pick primary SURFACE_ROLE for design lookup
fi
```

**AskUserQuestion for surfaces** (only when multi-surface config exists):
```
header: "Surfaces touched"
question: "Phase này touch surfaces nào? (multi-select)"
multiSelect: true
options: [<from config.surfaces keys>]
```

Lock `P{phase}.D-surfaces: [api, web]` decision.

**Primary role lookup** — for design resolution, if phase touches `web` surface, read `config.surfaces.web.design` → set `SURFACE_ROLE` var for Round 4 DESIGN.md resolve.

---

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

**Design System integration (v1.10.0 R4 NEW):**

Before asking UI questions, source `design-system.sh` and resolve applicable DESIGN.md:

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh"
if design_system_enabled; then
  # Scope Round 2 should have locked `surface_role` metadata from user answer
  # (multi-surface projects: user declares which role this phase targets)
  DESIGN_RESOLVED=$(design_system_resolve "$PHASE_DIR" "${SURFACE_ROLE:-}")

  if [ -n "$DESIGN_RESOLVED" ]; then
    echo "✓ DESIGN.md resolved: $DESIGN_RESOLVED"
    echo "  Will inject into Round 4 discussion + build task prompts."
    DESIGN_CONTEXT=$(design_system_inject_context "$PHASE_DIR" "${SURFACE_ROLE:-}")
    # Use $DESIGN_CONTEXT in Round 4 AskUserQuestion + lock as decision note
  else
    echo "⚠ No DESIGN.md resolved for phase (role=${SURFACE_ROLE:-<none>})"
    echo "  Round 4 will offer 3 options: pick from library / import existing / create from scratch"
    DESIGN_CONTEXT=""
  fi
fi
```

**If `$DESIGN_CONTEXT` set (DESIGN.md resolved):** Round 4 Q includes "Dùng design này làm base? Hay customize cho phase?" với design reference. Pages/components suggested phải tôn trọng color palette + typography + spacing rules từ DESIGN.md.

**If `$DESIGN_CONTEXT` empty (no DESIGN.md):** Round 4 Q offers 3 options:
1. **Pick from 58 brands** — `/vg:design-system --browse` để list. User pick → auto-run `/vg:design-system --import <brand> --role=<current-role>`.
2. **Import existing** — user paste DESIGN.md content hoặc link URL → save to `.planning/design/DESIGN.md` hoặc `.planning/design/{role}/DESIGN.md`.
3. **Create from scratch** — `/vg:design-system --create --role=<role>` → guided discussion tạo DESIGN.md custom.
4. **Skip (not recommended)** — UI phase without design standards → flag "design-debt" trong CONTEXT.md.

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
