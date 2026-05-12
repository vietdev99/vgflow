# Pipeline v4.0 — Test-Spec Codegen + Review-Discovery Refactor

**Date:** 2026-05-12
**Target version:** v4.0.0 (breaking)
**Status:** Design (brainstorm complete, awaiting implementation plan)

## Goal

Refactor VGFlow pipeline so `/vg:test-spec` owns full test artifact generation (8 docs + `.spec.ts` codegen + lens routing), `/vg:review` becomes discovery-only (browser nav + RUNTIME-MAP), and `/vg:test` absorbs fix-loop + matrix verdict. Keep claude + codex CLI mirror parity 100%.

## Architecture

**Current (v3.7.2):**
```
specs → scope → blueprint → build → test-spec → review → test → accept
```
- test-spec: 8 docs only (no codegen)
- review: code-scan + browser discovery + fix-loop + matrix verdict
- test: codegen + execute + security + regression

**New (v4.0.0):**
```
specs → scope → blueprint → build → review → test-spec → test → accept
```
- review: code-scan + browser discovery + matrix INTENT (discovery-only)
- test-spec: 8 docs + codegen + lens routing + self-review
- test: execute + fix-loop + security + regression + matrix VERDICT

**Key shifts:**
1. Order change: `review` now runs BEFORE `test-spec` (review feeds RUNTIME-MAP to test-spec)
2. Codegen ownership: `vg-test-codegen` subagent spawn moves `/vg:test STEP 5` → `/vg:test-spec STEP 4_codegen`
3. Lens application: smart-routing per `goal_type` happens at codegen-time (not review-time)
4. Fix-loop ownership: moves from `/vg:review` Phase 3 → `/vg:test` Step 3
5. Matrix verdict ownership: moves from `/vg:review` Phase 4 → `/vg:test` Step 5
6. CLI parity: full codex mirror for all 3 skills, no `--cli` flag (user picks CLI when typing)

## Tech Stack

- Claude commands: `commands/vg/*.md`
- Codex skill mirror: `codex-skills/*/SKILL.md`
- Generator: `scripts/generate-codex-skills.sh --force`
- CI gate: `scripts/verify-codex-mirror-equivalence.py`
- Subagent: `agents/vg-test-codegen/SKILL.md` (existing)
- Test framework: Playwright (`@playwright/test`)
- Lens prompts: `commands/vg/_shared/lens-prompts/lens-*.md` (19 lenses)

---

## Section 1 — Pipeline diff overview

| Stage v4.0 | Claude canonical | Codex mirror | Auto-sync |
|---|---|---|---|
| review (discovery-only) | `commands/vg/review.md` | `codex-skills/vg-review/SKILL.md` | `generate-codex-skills.sh` |
| test-spec (codegen + docs) | `commands/vg/test-spec.md` | `codex-skills/vg-test-spec/SKILL.md` | `generate-codex-skills.sh` |
| test (execute + fix-loop + verdict) | `commands/vg/test.md` | `codex-skills/vg-test/SKILL.md` | `generate-codex-skills.sh` |
| phase (chain orchestrator) | `commands/vg/phase.md` | `codex-skills/vg-phase/SKILL.md` | `generate-codex-skills.sh` |

Every PR touching any of these 4 source files must:
1. Regen codex skill via `scripts/generate-codex-skills.sh --force`
2. Pass `scripts/verify-codex-mirror-equivalence.py` (strict structural)
3. Commit both source + generated

---

## Section 2 — test-spec new responsibilities

```
/vg:test-spec
├── Step 1: load context (RUNTIME-MAP from review)
├── Step 2: gen 8 docs (preserved from v3.7.2)
│   ├── DEEP-TEST-SPECS.md (≥400 bytes)
│   ├── LIFECYCLE-SPECS.json (≥80 bytes)
│   ├── TEST-FIXTURE-DAG.json (≥80 bytes)
│   ├── TEST-EXECUTION-PLAN.json (≥80 bytes)
│   ├── TEST-SPEC-LOCALIZER/REQUEST.json + PROMPT.md
│   ├── PLAYWRIGHT-SPEC-PLAN.md
│   └── TEST-SPEC-GAPS.md
├── Step 3: validate deep specs
├── Step 3.5: CrossAI sweep (existing, commit 1cf431e)
├── Step 4_codegen: vg-test-codegen subagent ★ NEW
│   ├── Input: phase_dir, RUNTIME-MAP, GOAL-COVERAGE-MATRIX
│   ├── Smart-routing lens per goal_type:
│   │   ├── mutation → idor + mass-assignment + authz-negative + business-logic
│   │   ├── read → authz + info-disclosure + tenant-boundary
│   │   └── auth → auth-jwt + csrf + duplicate-submit
│   ├── L1/L2 selector binding gate (in subagent)
│   └── Output: tests/e2e/lifecycle/G-XX.{lens}.spec.ts per goal
├── Step 4.5_self_review ★ NEW
│   ├── Run: npx playwright --list tests/e2e/lifecycle/
│   ├── PASS → continue Step 5
│   ├── FAIL syntax → re-gen (max 2 retry)
│   └── FAIL × 2 → block, escalate to user
└── Step 5: complete
```

**must_write contract additions:**
```yaml
must_write:
  # existing 8 docs preserved
  - path: "tests/e2e/lifecycle/"  (≥1 .spec.ts file per goal)
  - path: "${PHASE_DIR}/CODEGEN-MANIFEST.json"  (subagent output)
```

**Codex parity:** `codex-skills/vg-test-spec/SKILL.md` regen with Step 4_codegen + Step 4.5_self_review prompt structure.

---

## Section 3 — review (discovery-only)

```
/vg:review (name preserved, scope shrunk)
├── Phase 1: code scan (preserved — security/SAST static lenses)
├── Phase 2: browser discovery ★ canonical RUNTIME-MAP producer
│   ├── playwright nav per PRODUCT-FLOWS
│   ├── api_contract_probe (BE endpoint check)
│   ├── localStorage scrape
│   └── output: RUNTIME-MAP.json
├── Phase 2.5: matrix INTENT (3 verdicts: READY / BLOCKED / NOT_SCANNED)
│   └── No TEST_PENDING (deferred to /vg:test final verdict)
└── Phase complete → auto-chain to /vg:test-spec
```

**Removed:**
- Phase 3 fix-loop → moved to `/vg:test`
- Phase 4 matrix VERDICT → moved to `/vg:test` (Phase 2.5 above is INTENT not VERDICT)

**Auto-chain prompt change:**
- Old: `--auto-chain` → `/vg:test`
- New: `--auto-chain` → `/vg:test-spec`

**Naming decision:** keep `/vg:review` command name. Internal doc clarifies "discovery-only from v4.0". No alias, no rename. Backward-compat preserved for user shortcuts + PIPELINE-STATE.next_command.

**Codex parity:** `codex-skills/vg-review/SKILL.md` regen — strip fix-loop + verdict prompts.

---

## Section 4 — /vg:test new responsibilities

```
/vg:test
├── Step 1: load context
│   ├── RUNTIME-MAP (from review)
│   ├── tests/e2e/lifecycle/*.spec.ts (from test-spec codegen)
│   └── GOAL-COVERAGE-MATRIX
├── Step 2: execute tests
│   ├── npx playwright test --reporter=json
│   └── output: TEST-RESULTS.json (per-goal pass/fail)
├── Step 3: fix-loop ★ moved from review
│   ├── compute failing_goals
│   ├── if failing_goals > 0:
│   │   AskUserQuestion:
│   │     A) Auto-fix (spawn subagent)
│   │     B) Manual fix (block, wait for user)
│   │     C) Skip fix-loop, emit debt
│   ├── on auto-fix: spawn vg-test-fixer subagent
│   ├── re-run test
│   └── max 3 retry per goal, fail × 3 → escalate
├── Step 4: security regression
│   ├── lens .spec.ts already embedded (test-spec gen)
│   └── execute playwright tag @security
├── Step 5: matrix verdict ★ moved from review
│   ├── compute READY/BLOCKED/TEST_PENDING/NOT_SCANNED
│   ├── write MATRIX-VERDICT.json
│   └── flip PIPELINE-STATE.next_command → /vg:accept
└── Step 6: complete
```

**Removed from current /vg:test:**
- Step 5 codegen → moved to `/vg:test-spec`
- vg-test-codegen spawn → moved to `/vg:test-spec`
- L1/L2 binding gate → moved to `/vg:test-spec` subagent

**Codex parity:** `codex-skills/vg-test/SKILL.md` regen — strip codegen prompt, add fix-loop user-confirm gate + matrix verdict prompts.

---

## Section 5 — /vg:phase chain v4.0

**New chain order:**
```
/vg:phase --phase=N
├── /vg:specs --phase=N
├── /vg:scope --phase=N
├── /vg:blueprint --phase=N
├── /vg:build --phase=N
├── /vg:review --phase=N        ← discovery-only, auto-chain → test-spec
├── /vg:test-spec --phase=N     ← codegen + docs, auto-chain → test
├── /vg:test --phase=N          ← execute + fix-loop + verdict, auto-chain → accept
└── /vg:accept --phase=N
```

**New flags:**
- `--skip-test` → stop after test-spec, manual UAT
- `--skip-codegen` → test-spec gens only 8 docs (no .spec.ts files)

**Removed/rejected:**
- `--cli=codex|claude` REJECTED — user picks CLI at terminal (no flag needed). Simplifies mirror parity (SKILL.md identical, no CLI-routing logic).

**Auto-chain default:** AskUserQuestion at each transition (chain / skip / inspect) — pattern from commit 5bd3fdb.

**Codex parity:** `codex-skills/vg-phase/SKILL.md` regen with new chain order + new flag handling.

---

## Section 6 — Codex sync + verify-mirror

**Affected codex skills (4):**

| Codex skill | Source | Change |
|---|---|---|
| `codex-skills/vg-review/SKILL.md` | `commands/vg/review.md` | scope discovery-only, strip fix-loop |
| `codex-skills/vg-test-spec/SKILL.md` | `commands/vg/test-spec.md` | add Step 4_codegen + Step 4.5 |
| `codex-skills/vg-test/SKILL.md` | `commands/vg/test.md` | strip codegen, add fix-loop + verdict |
| `codex-skills/vg-phase/SKILL.md` | `commands/vg/phase.md` | new chain order + flags |

**Sync flow per PR:**
1. Edit `commands/vg/{review,test-spec,test,phase}.md`
2. Edit `commands/vg/_shared/**/*.md` (if any)
3. Run `scripts/generate-codex-skills.sh --force`
4. Run `scripts/verify-codex-mirror-equivalence.py` (must pass)
5. Commit source + generated together
6. CI re-verifies on PR

**Equivalence strictness: STRICT STRUCTURAL.**

Strict match required:
- Section count
- Step name
- must_write contract entries
- Flags (`--skip-test`, `--skip-codegen`, `--auto-chain`, `--no-chain`)
- Auto-chain transitions

Differences allowed:
- CLI-specific invocation syntax (codex calls vs claude tool calls)
- Comment style
- File path formatting

**Block PR on drift.** No `[skip-mirror-check]` escape hatch in v4.0 (user requested strict).

**Codex-curated content protection:**
- `--force-overwrite-curated` NOT used for v4.0 migration
- HARD-GATE-CODEX blocks preserved
- Manual mark-step enumerations preserved

---

## Section 7 — Migration + rollback

**Migration strategy: SINGLE PR → v4.0.0.**

No feature flag, no split releases, no beta channel.

Rationale:
- Feature flag = 2 codepaths = maintenance cost
- Pipeline phases short (1-2 days) → in-flight rebuild easily
- Test-spec output v3.7.2 (8 docs) compatible with v4.0 (preserved)
- Only codegen + fix-loop relocate → minor behavior shift

**Affected in-flight phases:**

| In-flight state at v4.0 release | Action |
|---|---|
| Pre-`build` or `build` | No impact, continues normally |
| `review` (v3.7.2 logic) | Finish using v3.7.2 logic 1 last time |
| `test` (v3.7.2 codegen) | Finish using v3.7.2 logic 1 last time |
| Next phase | Use v4.0 chain |

**Rollback strategy:**
- `git revert <v4.0-commit>` → restore v3.7.2
- Codex skills auto-rollback (run generator after revert)
- Document rollback steps in CHANGELOG v4.0.0 entry

**Version bump:**
- 3.7.2 → 4.0.0 (breaking semver)
- CHANGELOG: "BREAKING: pipeline reordered (review→test-spec→test), codegen ownership moved to test-spec, review = discovery-only"

**Test plan:**
- Unit: per-skill smoke test (4 skills changed)
- Integration: full `/vg:phase` chain dry-run on `tests/fixtures/*` fixture
- Regression: existing fixtures not break
- Codex parity: `verify-codex-mirror-equivalence.py` green

---

## Error handling

**Per-step failure modes:**

| Step | Failure | Recovery |
|---|---|---|
| review Phase 2 (browser) | playwright crash | retry × 2, then BLOCKED matrix INTENT |
| test-spec Step 4_codegen | subagent error | re-spawn × 1, then block + escalate |
| test-spec Step 4.5 self-review | syntax fail × 2 | block, user manual fix or rollback codegen |
| test Step 2 execute | playwright crash | retry × 2, then mark all goals TEST_PENDING |
| test Step 3 fix-loop | fix × 3 fail | escalate, debt-emit, mark goal BLOCKED |

**Cross-cutting:**
- Hook protocol: emit `vg.block.fired` on every block; Stop hook validates
- Subagent ceiling: vg-test-codegen and vg-test-fixer cannot spawn nested subagents (HARD-GATE)
- Protected paths: outputs to `${PHASE_DIR}/` must use `vg-orchestrator-emit-evidence-signed.py`

---

## Testing

**Smoke tests:**
- `tests/integration/test_pipeline_v4_chain.sh` — full chain dry-run
- `tests/integration/test_review_discovery_only.sh` — verify review no longer fix-loops
- `tests/integration/test_test_spec_codegen.sh` — verify .spec.ts files generated
- `tests/integration/test_test_fix_loop.sh` — verify fix-loop in /vg:test

**Codex parity tests:**
- `verify-codex-mirror-equivalence.py` run as part of `tests/run-ci.sh`
- New test: `tests/integration/test_codex_mirror_v4.sh` — verify all 4 codex skills regen + match

**Regression:**
- Existing `tests/fixtures/eligibility-fail-rule-1/` not break
- Existing `tests/fixtures/recursive-probe-smoke/` not break

---

## Open questions (deferred to implementation)

1. vg-test-fixer subagent — does it exist or need new agent? Confirm before impl plan.
2. PIPELINE-STATE.next_command keys — need migration script for in-flight phases?
3. CrossAI sweep at test-spec runs before or after Step 4_codegen? (Currently after Step 3 validate, before Step 4. Confirm order.)

---

## Next step

Invoke `superpowers:writing-plans` to convert this design into bite-sized implementation plan at `docs/plans/2026-05-12-pipeline-v4-plan.md`.
