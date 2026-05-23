# Codex Investigation Prompt — UAT bug root-cause analysis

## Context

VGFlow is a deterministic harness running this pipeline:

`/vg:specs → /vg:scope → /vg:blueprint → /vg:build → /vg:review → /vg:test-spec → /vg:test → /vg:accept`

Operator reports: after `/vg:build` + `/vg:test` PASS, UAT phase (final human step) still
finds many runtime bugs — form submit errors (red banners), missing success
messages, broken redirects, empty dropdowns, validation 4xx silently swallowed.

## Your task

**Independent root-cause analysis.** Read the repo + git log + CHANGELOG +
dogfood reports. Identify WHY this pattern recurs. Confirm or refute the
findings already gathered from 3 prior Explore agents (below). Add new
patterns you find. Rank highest-impact fixes by ROI.

## Existing Explore findings (cross-check these)

### Pipeline timeline (Explore A)

NO stage exercises FE form submit against real backend before UAT:

| Stage | UI exercised? | Form submit tested? | File |
|-------|--------------|---------------------|------|
| build/close 10+ validators | NO (static) | NO | commands/vg/_shared/build/close.md:31-842 |
| build/close PR-E truthcheck | NO (curl) | BACKEND POST only | close.md:445-714 |
| build/close B95 FE-BE shape | NO (static heuristic) | NO | scripts/validators/verify-fe-be-shape-coherence.py |
| test/runtime curl+jq | NO | GET only | commands/vg/_shared/test/runtime.md:73-99 |
| test smoke+flow Playwright | YES (~3 paths) | minimal happy | commands/vg/_shared/test/runtime.md |
| test goal-verifier replay | YES per goal | read_after_* = GET only | scripts/generate-lifecycle-specs.py:1283-1287 |
| UAT STEP 5 Interactive | FIRST human submit | FIRST 4xx/422 catch | commands/vg/_shared/accept/interactive.md |

### Top UAT failure classes (Explore C estimates ~48-58% catchable)

1. Form 4xx/422 silently swallowed — no `page.on('response')` capture
2. Success message/toast missing — codegen doesn't parse `mutation_evidence` keyword
3. Redirect-after-submit broken — no `waitForNavigation()` assertion
4. Dropdown empty — XHR fail not asserted
5. Conditional field visibility — role swap not replayed

### Historical pattern (Explore B)

- **F-ROAM-01..06** (B95 shipped): FE-BE shape drift, all caught only at `/vg:roam`
- **F-CAI-01..10** (B90-B95): generator correctness gaps, silent failures
- **Form/submission tests**: `negative_specs` advisory only, codegen doesn't enforce

## Required output

Write to `dev-phases/uat-bug-rootcause/POSTMORTEM.html` — self-contained HTML with
embedded CSS. Required sections:

1. **Executive summary** (≤200 words) — top 5 bug classes ranked by frequency
2. **Gate gap analysis** — table: existing gate | what catches | what misses
3. **Three highest-impact fix recommendations** — ROI ranked, each with:
   - Specific file:line to modify
   - Expected % UAT bugs caught
   - Implementation effort estimate (days)
4. **Cross-check with Explore findings**:
   - Where you AGREE (high confidence — both came to same conclusion)
   - Where you DISAGREE or find NEW patterns (require operator triage)
5. **References** — file:line citations for every claim

## Constraints

- Use `html.parser`-valid HTML5 (no JS, no external CSS)
- Cite repo paths with line numbers (`file.py:42-67` style)
- Be specific — "more tests" is not a recommendation; "inject page.on('response')
  capture into generate-lifecycle-specs.py:_step() for create/update/delete stages" is
- If you cannot verify a claim from the codebase, mark it `[UNVERIFIED]`
- Length target: 1500-3000 words rendered

## Repository orientation

- Canonical scripts: `scripts/`
- Codex/Claude mirrors: `.claude/scripts/`, `codex-skills/`
- Skills/agents: `commands/vg/`, `agents/`, `skills/`
- Validators: `scripts/validators/`
- Tests: `tests/`
- Recent changes: read `CHANGELOG.md` (last 30 days = v4.6x range)
- Per-phase artifacts under `.vg/phases/` (in dogfood projects, not here)
