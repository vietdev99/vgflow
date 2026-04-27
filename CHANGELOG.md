# Changelog

## v2.12.7 (2026-04-28) — Runtime CSS asset verification

Patch release for a real UI failure class: built pages linking CSS URLs that return source code, HTML, or the wrong MIME type.

- Added `verify-static-assets-runtime.py`, a live probe that opens `VG_TARGET_URL`, discovers `<link rel="stylesheet">`, fetches each stylesheet, and blocks if it is not served as `text/css`.
- The validator also blocks stylesheet bodies that look like HTML/JS/TS source even when the header claims `text/css`.
- Wired the validator into `/vg:review`, `/vg:test`, and `/vg:accept`; it auto-skips when no live target URL is available and is unquarantinable when active.
- Added regression tests for valid CSS, wrong `Content-Type`, source-code body, no-target auto-skip, and orchestrator/registry wiring.

## v2.12.6 (2026-04-28) — Context capsules + Codex test-goal lane

Feature release for reducing AI lazy-read/context miss risk before build.

- `/vg:build` now writes a deterministic per-task context capsule from `pre-executor-check.py` and injects it into each executor prompt before the long context blocks.
- Added `verify-task-context-capsule.py` as an unquarantinable build validator so a resolved task/API/goals/CRUD/security context cannot pass unless the executor prompt actually received the capsule.
- `/vg:blueprint` now adds step `2b5a_codex_test_goal_lane`: Codex produces `TEST-GOALS.codex-proposal.md`, then `test-goal-delta.py` compares it against final `TEST-GOALS.md`.
- Added `verify-codex-test-goal-lane.py` so unresolved proposal deltas block blueprint handoff unless explicitly skipped with override debt.
- Regenerated Codex skill mirrors and added regression tests for capsule generation, prompt injection, Codex goal deltas, and workflow wiring.

## v2.12.5 (2026-04-28) — Graphify install/update verification

Patch release for Graphify environment bootstrap.

- Added `ensure-graphify.py` as the shared installer/updater check for Graphify.
- `install.sh`, `sync.sh`, and `/vg:update` now verify/repair Graphify when `graphify.enabled=true`.
- Missing Graphify installs `graphifyy[mcp]`; project `.mcp.json`, `.graphifyignore`, and `.gitignore` are repaired without forcing an initial graph build.
- Added regression tests for helper behavior and install/sync/update wiring.

## v2.12.4 (2026-04-28) — Build Graphify refresh enforcement

Patch release for stale/missing Graphify build context.

- `/vg:build` now cold-builds Graphify when `graphify.enabled=true` but `graphify-out/graph.json` does not exist yet.
- `/vg:build` refreshes Graphify after each successful build wave and once more before final run-complete.
- Graphify rebuilds now emit `graphify_auto_rebuild` into `.vg/events.db`, not only best-effort telemetry.
- Added `build-graphify-required` as an unquarantinable build validator so enabled + installed Graphify cannot pass without current-run rebuild evidence.

## v2.12.3 (2026-04-27) — Playwright MCP install/update verification

Patch release for environment bootstrap reliability.

- Added `verify-playwright-mcp-config.py` to check and repair Claude + Codex Playwright MCP workers (`playwright1`..`playwright5`).
- `install.sh`, `sync.sh`, and `/vg:update` now verify/repair Playwright MCP config instead of assuming user settings are already correct.
- Replaced stale hardcoded Playwright lock-manager paths with runtime `${HOME}` / `VG_PLAYWRIGHT_LOCK_DIR` resolution.
- Added regression tests for stale copied settings, fake-HOME install/sync, and `/vg:update` MCP repair wiring.

## v2.12.2 (2026-04-27) — Review CrossAI evidence gate

Patch release for objective review enforcement.

- `/vg:review` now requires `${PHASE_DIR}/crossai/review-check.xml` when CrossAI is not explicitly skipped.
- `/vg:review` now requires `crossai.verdict` telemetry when CrossAI is not explicitly skipped.
- `--skip-crossai` in review now requires override-debt evidence, matching blueprint behavior.
- Added regression tests so review CrossAI cannot regress to marker-only theatre.

## v2.12.1 (2026-04-27) — Build CrossAI completion semantics

Patch release for a misleading `/vg:build` completion signal.

- Changed `/vg:build` step 9 to report "code execution complete" instead of "build complete" before CrossAI runs.
- Moved `build.completed` telemetry to step 12 after the CrossAI build verification loop reaches an accepted terminal state.
- Kept `PIPELINE-STATE.steps.build` as `in_progress` while CrossAI/run-complete are pending, then marks it `done` only after run-complete passes.
- Added regression tests to prevent future pre-CrossAI completion claims.

## v2.12.0 (2026-04-27) — Platform-aware CRUD Surface Contract

Feature release for the "AI must not lazy-read blueprint" problem.

- Added `CRUD-SURFACES.md` as the parent resource contract for list/read/create/update/delete surfaces. Existing paging/list/filter/security notes now extend this contract instead of living as loose prose.
- Added `schemas/crud-surface.v1.json` and `verify-crud-surface-contract.py`. The gate blocks CRUD/resource phases that miss base business-flow/security/abuse/perf invariants or the required web/mobile/backend overlay.
- Wired blueprint to generate `CRUD-SURFACES.md`; build to inject the relevant resource slice into executor prompts; review/test/accept to validate against the same contract.
- Added platform-aware config defaults. Web phases check table/filter/search/sort/pagination/form/delete behavior, mobile phases check deep-link/pull-to-refresh/tap-target/offline states, backend phases check query allowlists, authz, mass-assignment, idempotency, audit log, and performance budget.
- Added regression tests for validator behavior, executor context injection, and command/orchestrator wiring.

## v2.11.1 (2026-04-27) — Phase 16 hot-fix (cross-AI consensus 6-BLOCKer rework)

Hot-fix release. Phase 16 "Task Fidelity Lock" was shipped at HEAD between
v2.11.0 and v2.12.0 cut, but a 3-way cross-AI review (Claude Opus 4.7
internal + Codex GPT-5.5 peer) found 6 BLOCKers — including a CRITICAL
foundational design flaw that defeated the entire phase goal. Hot-fixed
in 9 atomic commits before any release tag bumped past v2.11.0.

### Cross-AI consensus BLOCKers fixed

**B1 (CRITICAL)** — `verify-task-fidelity.py` only compared LINE COUNTS,
not content hashes. Codex verified: replacing every body line with
"PARAPHRASED LINE N" at identical line count returned PASS. The exact
failure mode Phase 16 was designed to block.

**B2** — `build.md` step 8c persisted UI-MAP+DESIGN-REF wrapper to
`${TASK_NUM}.md`, NOT the task body. Audit compared wrapper line count
vs meta's body line count → false BLOCK on every UI task on first real
`/vg:build`. Test fixture bypassed by writing body directly to disk.

**B3** — Both meta + prompt persist were gated on UI conditional. Backend
tasks (no UI subtree, no design context) got NO meta.json → audit silent
PASS → orchestrator could paraphrase backend task bodies freely.

**B4** — `pre-executor-check.py main()` used legacy v1 extract for
`task_context` while v2 was called separately for meta. XML PLAN tasks
returned `"Task N not found in PLAN files"` sentinel as task_context
while meta reported `source_format=xml`. Two extraction sources → drift.

**B5** — `verify-task-schema.py` + `verify-crossai-output.py` were
registered in `registry.yaml` with `phases_active: [scope, blueprint]`
but NEVER invoked from any skill body. Registry tagging is documentation,
not orchestration. Tests passed because they called validators via
subprocess directly, never via `/vg:blueprint` flow.

**B6** — `verify-crossai-output.py` diff parser only matched XML
`<task id="N">`. SPECS D-02 explicitly says current PLANs are in heading-
format transition. Codex verified: 50-line prose addition to `## Task N:`
heading PLAN without `<context-refs>` returned silent PASS.

### Hot-fix commits (9 atomic, ordered)

- C1 `b70e600` — `pre-executor-check.py main()`: switch to
  `extract_task_section_v2()["body"]` as single source for task_context
  and task_meta. v1 stays as legacy shim.
- C2 `f88853a` — `verify-crossai-output.py`: `_classify_diff_lines_per_task`
  also matches `## Task N:` headings; tracks scope from BOTH formats.
- C3 `f071bd8` — `build.md` step 8c split persist: always write
  `${TASK_NUM}.body.md` + `${TASK_NUM}.meta.json`; UI conditional now
  writes `${TASK_NUM}.uimap.md` separately. `verify-uimap-injection.py`
  glob updated; `verify-task-fidelity.py` reads `*.body.md` primary.
- C4 `2d8d561` (CRITICAL) — `verify-task-fidelity.py` adds
  `task_block_sha256(prompt_text)` compare. Hash mismatch ALWAYS BLOCKs;
  shortfall_pct only classifies the kind (truncation vs paraphrase).
- C5 `f495f0d` — `blueprint.md` sub-step 2d-3c added: invokes
  `verify-task-schema.py` (always) + `verify-crossai-output.py` (gated
  `--crossai`).
- C6 `43149c7` — `scope.md` step 4: invokes `verify-crossai-output.py`
  after CrossAI peer review (gated `--crossai`).
- C7 `ea75c92` — `vg-orchestrator/__main__.py` `COMMAND_VALIDATORS`:
  `vg:blueprint += [verify-task-schema, verify-crossai-output]`,
  `vg:scope += [verify-crossai-output]`. Defense-in-depth alongside
  skill body invocations.
- C8 `d55d2af` — 11 production-path regression tests (5 new test
  classes) covering each of the 6 BLOCKers. Codex's exact paraphrase
  attack now BLOCKed by `test_same_line_paraphrase_blocks_as_content_paraphrase`.
- C9 (this) — VERSION 2.11.0 → 2.11.1, CHANGELOG entry.

### Test count delta

- v2.11.0: 207 passed, 1 skipped (P15: 100, P16: 43, P17: 64)
- v2.11.1: 218 passed, 1 skipped (P15: 100, P16: 54, P17: 64). +11 tests.

### Test semantic update

- `TestPhase16TaskFidelity::test_minor_truncation_passes` was renamed to
  `test_minor_truncation_blocks_by_hash` and the assertion flipped from
  PASS to BLOCK. The original test encoded the buggy line-count-only
  behavior that allowed silent content drift up to 10%. After C4, ANY
  content drift = hash mismatch = BLOCK as content_paraphrase.

### Cross-AI review artifacts

Full review reports kept for audit trail:
- `dev-phases/16-task-fidelity-lock-v1/REVIEW-CROSSAI.md` (Claude Opus 4.7
  internal review — found 3 BLOCKers + 6 WARNs; missed B1 and B6)
- `dev-phases/16-task-fidelity-lock-v1/crossai/result-codex.md` (Codex
  GPT-5.5 peer review — found 5 BLOCKers + 4 WARNs; verified B1 and B6
  with negative tests)
- `dev-phases/16-task-fidelity-lock-v1/crossai/prompt.md` (the prompt
  both reviewers received — for reproducibility)

Gemini 3.1 Pro Preview was attempted as a third reviewer but Cloud Code
Assist OAuth quota retrieve fail (`PERMISSION_DENIED`) blocked invocation.
Skipped without affecting consensus (Claude+Codex agreement was already
HIGH confidence).

### Key takeaway for future phases

Acceptance tests must exercise the actual /vg pipeline path, not just
helper functions in isolation. C8 `TestPhase16Hotfix*` classes are the
new template: assert on production code paths (build.md text, skill
body invocations, orchestrator dispatch dict), not just on validator
behavior in subprocess isolation.

---

## v2.11.0 (2026-04-27) — Phase 17 ship + extraction-quality polish + orphan validator wire

Minor release combining 3 layers of work that surfaced from Phase 15
dogfood + Phase 17 cross-AI review:

### Phase 17 — Test Session Reuse (D-01..D-06)

User observation in Phase 7.14.3 RTB: test dashboard window opens many
times → wall-clock + resource waste. Phase 15 D-16 (10 spec files per
filter+pagination control) multiplies the cost — must fix before
consumer dogfood at scale.

Shipped:
- `commands/vg/_shared/templates/interactive-helpers.template.ts` — extended
  with `loginOnce(role, opts?)` (auto/api/ui strategy with TTL +
  config_hash invalidation) + `useAuth(role)` (Playwright fixture
  override) + `LoginOnceOptions` interface. Backward-compat preserved
  (`loginAs` legacy export untouched).
- `commands/vg/_shared/templates/playwright-global-setup.template.ts` +
  `playwright-config.partial.ts` — global setup template + merge
  fragment so consumer's playwright.config.ts wires globalSetup once.
- 10 Phase 15 D-16 templates updated: `test.use(useAuth(ROLE))` replaces
  `test.beforeEach(loginAs(page, ROLE))`. Login flows go from O(N spec
  files) to O(M roles).
- `vg.config.template.md` extended with `test:` block (storage_state_path,
  ttl_hours, playwright.workers, fully_parallel, login_strategy).
- `commands/vg/test.md` step 5d-pre auto-setup: detect E2E dir, copy
  global-setup.ts, export VG_STORAGE_STATE_PATH/VG_STORAGE_STATE_TTL_HOURS/
  VG_LOGIN_STRATEGY env vars, append `.auth/` to `.gitignore`,
  discover VG_ROLES from vg.config accounts.
- `scripts/validators/verify-test-session-reuse.py` (D-06): WARN on
  generated specs still using legacy beforeEach(loginAs); --strict mode
  escalates to BLOCK.

53 acceptance tests + 18 helper smoke tests across 6 dimensions.

### P17 polish — cross-AI review hotfix (5 WARN findings)

W-1 useAuth pre-check storage state file existence (cryptic ENOENT → console.warn pointing at root cause).
W-2 _loginViaApi validate cookies > 0 (server 200 with no Set-Cookie no longer pollutes 24h cache with empty file).
W-5 broaden cross-phase regression glob `1[57]` → `1[5-9]` (catch P16/P18+ when added).

W-3 (validator backtick edge case) + W-4 (awk YAML indent fragility) deferred — both rare, non-blocking.

### Self-audit hotfix — orphan validators wired + extraction bugs fixed

User raised concern (Q1): "long blueprint → AI lazy-read, miss content
→ build code thiếu". Self-audit found this concern was already addressed
in code BUT validators never fired:

- `verify-blueprint-completeness.py` — META-GATE for GOAL↔PLAN coverage
  (C1) + ENDPOINT↔GOAL coverage (C2 incl auth_path/happy/4xx/401)
- `verify-test-goals-platform-essentials.py` — Phase 7.14.3 retrospective
  gate for filter row + pagination + column visibility persistence +
  mutation 4-layer + state-machine guards

Both pre-existed with explicit Phase 7.14.3 rationale in docstrings,
but were never registered in registry.yaml or wired into any skill.
Wired into `commands/vg/blueprint.md` step 2d-3b (after the existing
bash grep cross-checks pass). Override flags `--skip-blueprint-completeness`
and `--skip-platform-essentials` log override-debt.

Plus 2 silent-truncation bugs in `scripts/pre-executor-check.py`:

- `extract_contract_section`: matched on LAST PATH SEGMENT only
  → `/api/v1/sites` and `/api/v2/sites` collide → executor for v2 task
  could receive v1 contract. Fix: prefer FULL-PATH match first; fall
  back to last-segment only when full path absent. 3000-char silent
  truncate softened with visible HTML comment.
- `extract_goals_context`: 30-line cap on the LAST goal in
  TEST-GOALS.md → Phase 15 D-16 goals (interactive_controls + persistence
  check + criteria, 50-100+ lines) silently truncated → executor missed
  filter/pagination test plans. Fix: take from start to EOF (R4 budget
  caps prompt size downstream as the right place for that policy).

4 regression tests in `test_phase17_extraction_fixes.py`:
v1/v2 disambiguation (both directions) + last-goal-no-truncation
(persistence check + interactive_controls survive) + non-last-goal still
terminates at next ## Goal heading.

### Test infrastructure

- `scripts/tests/root_verifiers/test_phase17_helpers.py` (18 tests)
- `scripts/tests/root_verifiers/test_phase17_acceptance.py` (42 tests)
- `scripts/tests/root_verifiers/test_phase17_extraction_fixes.py` (4 tests)

Total: 164 passed, 1 skipped (cheerio AST conditional).

### Distribution

`install.sh` Phase 15 wildcard for `_shared/templates/*` auto-catches
the 2 new Playwright templates (no install.sh edit needed). Confirmed
via `bash install.sh /tmp/p17-test`.

## v2.10.0 (2026-04-27) — Phase 15 ship: VG Design Fidelity + UAT Narrative + Filter Test Rigor

Minor release shipping the 4 fixes Phase 7.14.3 RTB exposed in the prior
harness: visual fidelity gates, UAT narrative auto-fire, filter+pagination
test rigor pack, and Haiku-spawn audit (phantom-aware). 28 commits across
10 waves (`08b5fd7..2985a47`), +12k lines, 100 acceptance tests passing.

Every D-XX decision in `dev-phases/15-vg-design-fidelity-v1/DECISIONS.md`
maps to a committed deliverable. Cross-AI reviewed (2 BLOCK + 4 WARN
caught + fixed in commit `2985a47` before this release).

### Visual fidelity gate (D-01, D-02, D-03, D-08, D-12, D-15)

- 4 JSON Schema draft-07 contracts (`schemas/`): `slug-registry.v1.json`,
  `structural-json.v1.json`, `ui-map.v1.json` (5-field-per-node lock),
  `narration-strings.v1.json`.
- Extractor handlers (`scripts/design-normalize.{py,js}`):
  HTML cheerio AST + PNG OCR (`.structural.png` marker) + Pencil MCP
  (`mcp__pencil__*`, encrypted .pen files) + Penboard MCP (`mcp__penboard__*`,
  .penboard/.flow workspaces). 2 distinct MCP servers — separate config blocks.
- 8 validators: `verify-design-{extractor-output,ref-required}.py`,
  `verify-uimap-{schema,injection}.py`, `verify-phase-ui-flag.py`,
  `verify-ui-structure.py` (extended `--scope owner-wave-id=`),
  `verify-holistic-drift.py` (D-12e wrapper).
- Threshold helper (`scripts/lib/threshold-resolver.py`) — D-08 profile
  resolution: prototype 0.70 / default 0.85 / production 0.95.
- UI-MAP wave/task ownership tags (`owner_wave_id`, `owner_task_id`)
  enable subtree filtering via `scripts/extract-subtree-haiku.mjs` (D-14).
  Build step 8c persists composed prompts to
  `.vg/phases/<phase>/.build/wave-<N>/executor-prompts/<task>.md` with
  `## UI-MAP-SUBTREE-FOR-THIS-WAVE` + `## DESIGN-REF` H2 headers so
  `verify-uimap-injection.py` can audit them post-wave.
- Skill body wirings: `scope.md` Check B' (D-02 production-grade BLOCK),
  `blueprint.md` step 2_fidelity_profile_lock + 2b6b D-15 schema check,
  `build.md` step 8c UI-MAP subtree inject + D-12a injection audit,
  `review.md` phase2_5_visual_checks §6 (D-12c UI-flag + D-12b wave drift +
  D-12e holistic drift).

### UAT narrative auto-fire (D-05, D-06, D-07, D-10, D-18)

- Generator: `scripts/build-uat-narrative.py` reads TEST-GOALS frontmatter
  (4 mandatory fields per goal: entry_url, navigation_steps, precondition,
  expected_behavior) and renders `${PHASE_DIR}/UAT-NARRATIVE.md` per
  prompt block.
- Templates: `commands/vg/_shared/templates/uat-narrative-prompt.md.tmpl`
  + `uat-narrative-design-ref-block.md.tmpl` (Mustache-lite placeholders).
- 9 new flat keys in `narration-strings.yaml` (vi+en locales): `uat_entry_label`,
  `uat_role_label`, `uat_account_label`, `uat_navigation_label`,
  `uat_precondition_label`, `uat_expected_label`, `uat_region_label`,
  `uat_screenshot_compare`, `uat_prompt_pfs`.
- Validators: `verify-uat-narrative-fields.py` (4-field check per prompt
  block) + `verify-uat-strings-no-hardcode.py` (D-18 strict — no labels
  outside narration-strings.yaml).
- Wired into `accept.md` step 4b_uat_narrative_autofire (auto-fires
  before step 5 interactive UAT).

### Filter + Pagination Test Rigor Pack (D-16)

- Matrix module: `skills/vg-codegen-interactive/filter-test-matrix.mjs`
  — enumerator + Mustache-lite renderer + helpers:
  `enumerateFilterFiles`, `enumeratePaginationFiles`, `renderTemplate`.
- 10 templates @ `commands/vg/_shared/templates/`:
  `filter-{coverage,stress,state-integrity,edge}.test.tmpl` +
  `pagination-{navigation,url-sync,envelope,display,stress,edge}.test.tmpl`.
- Per-control output: 4 filter spec files + 6 pagination spec files
  containing 13 + 18 source-level `test()` blocks.
- Validator: `verify-filter-test-coverage.py` counts blocks (not files)
  whose name contains the control slug AND the kind keyword
  (filter/pagination); thresholds 13/18.
- Wired into `test.md` step 5d_codegen — deterministic pure-JS path,
  zero Sonnet round-trip, byte-for-byte reproducible.

### Haiku-spawn phantom-aware audit (D-17)

- Validator: `verify-haiku-spawn-fired.py` checks events.db for
  `review.haiku_scanner_spawned` events emitted in `review.md` step 2b-2.
- Phantom signature detection: ignores runs matching `args:""` + 0
  step.marked + abort within 60s — the hook-triggered noise pattern
  diagnosed in `dev-phases/15-vg-design-fidelity-v1/INVESTIGATION-D17.md`.
  Initial Phase 15 hypothesis (53s abort = scanner failure) was wrong;
  v2.8.6 hotfix (411a278) had already fixed the entry-pattern bug 4
  hours after the phantom event — what was missing was *evidence-of-
  firing*, which the new emit + phantom-aware validator now provide.
- Telemetry emit moved to BEFORE Agent() call (commit `4edbaa2`) so
  spawn audit survives even if the Agent crashes mid-spawn.

### Test infrastructure

- `scripts/tests/root_verifiers/test_phase15_design_extractors.py` (3 tests + 1 skip).
- `scripts/tests/root_verifiers/test_phase15_validators_and_matrix.py` (17 tests
  including 7 regression tests added for B1/B2 cross-AI findings).
- `scripts/tests/root_verifiers/test_phase15_acceptance.py` (80 tests across 8
  acceptance dimensions: schemas, validators, scripts, templates, skill
  integrations, config, i18n, regression-green).
- Total: 100 passed, 1 skipped (cheerio AST conditional — runs in consumer).

### Distribution updates (`install.sh`)

- New paths covered: `schemas/*.json`, `scripts/*.mjs`, `scripts/lib/*.py`,
  `commands/vg/_shared/templates/*`, `skills/vg-codegen-interactive/`.

### Deferred to follow-up (cross-AI WARN/INFO list)

W3 path interpolation hardening (Windows backslash escape risk in
`${PYTHON_BIN} -c "...open('${VG_TMP}/...')..."` patterns), W4 events.db
path mismatch (`.vg/events.db` vs `.claude/state/events.db`), I1
WAVE-DRIFT-HISTORY.md aggregator, I2 phantom timing guarded behavior,
I3-I5 informational confirmations.

## v2.9.0 (2026-04-27) — v2.7 Phase A/B/D/E ship + v2.8.6 hotfix bundle

Minor release bundling 4 v2.7 hardening phases (runtime probe, codegen
interactive_controls, orphan triage, artifact JSON schemas) plus the
v2.8.6 hotfix triplet (entry-hook paste-back, argparse prefix-match,
test pollution). Closes the v2.7 hardening epic. Also resolves the
long-stale `VGFLOW-VERSION` file (last bumped at v2.5.2.10) — now
synchronized with `VERSION` going forward.

### v2.7 Phase A — Runtime probe URL state validator

New validator `verify-url-state-runtime.py` reads `${PHASE_DIR}/url-runtime-probe.json`,
validates declared `url_param` in `url_params_after`. WARN on coverage gap,
BLOCK on declaration drift. Wired into `/vg:review` step `phase2_8_url_state_runtime`
(profile-gated: `web-fullstack`, `web-frontend-only`).

### v2.7 Phase B — Codegen interactive_controls skill + output validator

New skill `vg-codegen-interactive` (model: sonnet, user-invocable: false)
generates Playwright `.spec.ts` for `interactive_controls` goals with
deterministic test count formula per filter/sort/pagination declaration.
Reference template `interactive-helpers.template.ts` (~280 LOC) provides
DSL evaluator (`expectAssertion` with 5 grammar forms: `===`, `includes`,
`in`, `monotonic`, `length<=`).

Validator `verify-codegen-output.py` runs 9 checks: AUTO-GENERATED header,
helper imports, no raw `locator()`, deterministic count, no `networkidle`,
no `page.evaluate()` (warn), ROUTE match, DSL grammar conformance, file
naming. Wired into `/vg:test` step `5d_codegen` (BLOCK on violation).

### v2.7 Phase D — Orphan validator triage orchestrator

`_orphans.py` orchestrator with 3 subcommands (`orphans-list`, `orphans-collect`,
`orphans-apply`) for 3-agent partition triage. Canonicalizes IDs across
script-glob, registry, and dispatch sources via `_canonical_id()` (strips
`verify-`/`validate-` prefix). `_resolve_script_path()` tolerates both
naming conventions (`verify-foo.py` and `foo.py`).

Pre-shipped fix: glob changed from `verify-*.py` to `*.py` with non-validator
blocklist (`audit-rule-cards`, `edit-rule-cards`, etc.) — catches bare-stem
files like `acceptance-reconciliation.py` that the old pattern missed.

### v2.7 Phase E — Artifact JSON schemas + write-time validator

7 schemas in `.claude/schemas/{specs,context,plan,test-goals,summary,uat,interactive-controls}.v1.json`
(JSON Schema draft-07, `$id: https://vgflow.dev/schemas/{name}.v1.json`).
Strict frontmatter, lenient body H2 regex.

Single validator `verify-artifact-schema.py` (~340 LOC) handles 6 artifact
types via hand-rolled minimal JSON Schema walker — no external schema lib.
Supports `VG_SCHEMA_GRANDFATHER_BEFORE` env var for legacy phases below
the cutoff. Dual-fire write+read invocation across 6 skill bodies
(specs/scope/blueprint/build/accept).

### v2.8.6 hotfix bundle

Triplet of harness-discipline fixes:
- **Entry-hook paste-back heuristic** — extended `/vg:` literal detection
  to recognize SPEC document content + prose references (4 phantom
  run-starts incidents during v2.7 ship session traced to this gap).
- **argparse prefix-match bug** — `argparse` defaulted to
  `allow_abbrev=True`; `--phase` was silently mapped to `--phase-dir`
  in `verify-runtime-evidence.py`. All validators now use
  `argparse.ArgumentParser(allow_abbrev=False)` defensively.
- **Test pollution** — added `autouse` pytest fixture cleaning
  `VG_REPO_ROOT` env var across tests; eliminates state leak between
  test files that breaks CI ordering.

### `VGFLOW-VERSION` synchronization

The metadata file at `vgflow-repo/VGFLOW-VERSION` (and mirrored
`.claude/VGFLOW-VERSION` in installer projects) was last bumped at
`820b0cd release v2.5.2.10` and skipped in every release pipeline since
v2.6.1 — a 4-tag drift. Reading current `cat .claude/VGFLOW-VERSION`
gave `2.5.2.10` while `VERSION` reported `2.8.5`. Telemetry events
in `install.sh` reported the wrong version.

This release:
- Syncs `VGFLOW-VERSION` ← `VERSION` ← `2.9.0`.
- Going forward, `VGFLOW-VERSION` is bumped lockstep with `VERSION` in
  each release (until/unless we deprecate one of the two files).

### Migration notes

No behavioral changes for existing consumers. Telemetry emitted by
`install.sh` will now report version `2.9.0` instead of `2.5.2.10`
(historical events keep their old version values; only new events affected).

Projects pinning a specific VG version via `.claude/VGFLOW-VERSION` should
update the file to `2.9.0` after pulling.

### Decisions deferred to next release

- v2.7 Phase C (skill invariants), Phase F (marker tracking) already shipped
  pre-v2.9.0 (in v2.8.3 + v2.8.5 respectively); no Phase C/F work in this
  release.
- VGFLOW-VERSION deprecation discussion: tracked but not acted on. Both
  files remain present and synchronized.

---

## v2.8.5 (2026-04-26) — v2.7 Phase F: Marker tracking hooks layer 1+2

Companion to v2.8.3 hybrid Stop-hook (reactive recovery). Layers 1+2
catch marker activity **DURING** work instead of after-the-fact at Stop,
giving observability into step transitions for `/vg:gate-stats` analytics.

### Layer 1 — `vg-entry-hook.py` extension

After successful `run-start`, seed `.vg/.session-context.json`:
```json
{
  "run_id": "...",
  "command": "vg:build",
  "phase": "7.14.3",
  "started_at": "ISO-8601",
  "current_step": null,
  "step_history": [],
  "telemetry_emitted": []
}
```

Best-effort write; never fails `run-start` on session-context error.

### Layer 2 — `vg-step-tracker.py` (NEW PostToolUse Bash hook)

Detects 3 marker write patterns:
- `touch <path>/.step-markers/<step>.{start,done}`
- `mark_step <phase> <step> [<dir>]`
- `vg-orchestrator mark-step <namespace> <step>`

Updates session-context:
- `current_step` ← latest detected step
- `step_history` ← append `{step, transition, ts}` (dedup'd)

Emits `hook.step_active` telemetry per `(run_id, step, transition)`,
dedup'd via `telemetry_emitted` set to avoid event flood.

**Always exits 0** — never blocks bash execution. No-op when:
- Tool is not Bash
- No active `/vg:*` run (no session-context.json)
- Bash command doesn't match marker patterns

### Settings.local.json registration

```jsonc
"PostToolUse": [
  { "matcher": "Edit|Write|...", "hooks": [...] },   // existing
  { "matcher": "Bash",
    "hooks": [{ "command": "python ${CLAUDE_PROJECT_DIR}/.claude/scripts/vg-step-tracker.py" }]
  }
]
```

### Why this matters

v2.8.3 hybrid Stop-hook auto-recovers from marker drift but only **after** the run ends. Phase F lets us:
- See step transitions live in `.vg/.session-context.json`
- Query `hook.step_active` events via `/vg:gate-stats` to find skills with
  high drift (steps the AI consistently misses)
- Future v2.9 — proactive Stop hook can use step_history to detect drift
  earlier and route to migrate-state proactively

### Tests

- `test_step_tracker_hook.py` — 12 cases (pattern detection + state updates +
  dedup behavior)
- Regression: 42/42 pass (url-state, hybrid, migrate-state, contract-pins, codex-mirror)
- **Total: 54/54 pass**


## v2.8.4 (2026-04-26) — Phase J: Interactive Controls (URL state + pagination UI)

Closes blind spot in `/vg:review` and `/vg:test` for list/table/grid views.
6-layer enforcement stack ensures AI executors ship dashboard list views
with proper URL state sync + correct pagination UI pattern.

### Layers

1. **TEST-GOAL schema** — `interactive_controls` block (filters / pagination /
   search / sort + `url_sync` flag) with assertion fields per control.
2. **FOUNDATION §9.9 + `vg.config.md` `ui_state_conventions`** — locks
   project convention (kebab/csv/300ms/page-size 20 + pagination UI pattern).
3. **Executor R7** — MANDATORY at `/vg:build`: list view state MUST sync URL
   via framework router (Next `useSearchParams`, React Router, etc.).
   Pagination UI MUST be `<<  <  N±5  >  >>` + "Showing X-Y of Z" + "Page N of M".
   Plain prev-next-only is BANNED.
4. **Blueprint generator (step 2b5 rule 7)** — auto-populates
   `interactive_controls` for list view goals based on main_steps signals.
5. **Static validator `verify-url-state-sync.py`** — BLOCKs missing block;
   rejects banned `ui_pattern` values; severity follows phase cutover.
6. **Review gate (phase 2.7)** — invokes validator with `--allow-no-url-sync`
   override path → soft OD debt.

### Migration

| Phase | Mode |
|-------|------|
| Phase < 14 (legacy) | WARN (grandfather) |
| Phase ≥ 14 (cutover) | HARD BLOCK (mandatory) |
| Override per-goal | `interactive_controls.url_sync: false` + `url_sync_waive_reason` |
| Override per-phase | CLI flag `--allow-no-url-sync` → soft OD debt |

`severity_phase_cutover` configurable in `vg.config.md` (default 14).

### Pagination UI rule (locked)

```
[<<]  [<]  [N-5] [N-4] [N-3] [N-2] [N-1] [N] [N+1] [N+2] [N+3] [N+4] [N+5]  [>]  [>>]

Showing 21–40 of 1,247 records          Page 2 of 63
```

Defaults (`vg.config.md` `ui_state_conventions.pagination_ui`):
- `pattern: "first-prev-numbered-window-next-last"` (locked)
- `window_radius: 5`
- `show_total_records: true`, `show_total_pages: true`
- `truncate_with_ellipsis: true`

Override only with explicit infinite-scroll declaration in FOUNDATION §9.9.

### Tests

- `test_url_state_sync_validator.py` — 12 cases
- Regression: 30/30 (hybrid hook, migrate-state, contract-pins, codex-mirror)
- Codex mirror equivalence: 44/44 functionally equivalent

---

## v2.8.3 (2026-04-26) — Hybrid Stop-hook marker-drift auto-recovery

Tier C complement to Tier A (`/vg:migrate-state`) and Tier B (contract pins).
When `run-complete` BLOCKs purely on `must_touch_markers` (no `must_write`,
no `must_emit_telemetry` violations), drift is tracked per-`run_id` in
`.vg/.session-drift.json`:

  - 1st drift in session → BLOCK with hint, increment counter
  - 2nd+ drift → auto-fire `migrate-state {phase} --apply`, retry
    `run-complete`; on PASS approve + emit `hook.marker_drift_recovered`
    telemetry event

### Anti-forge contract

`AUTO_FIRE_ELIGIBLE_TYPES` is hard-coded to `{must_touch_markers}`.
Mixed violations always BLOCK because telemetry/file gaps signal real
pipeline issues, not paperwork drift. `must_write` (artifacts) and
`must_emit_telemetry` (events) cannot be backfilled without proof.

### Why hybrid instead of always-block / always-auto-fire

- **Always-block**: forces session restart for skill-cache, infinite loop pain.
- **Always-auto-fire**: AI learns marker discipline doesn't matter, kỷ luật loãng.
- **Hybrid**: 1st miss = lesson, 2nd+ = recover (no value in repeating same hint).

### Drift state schema

`.vg/.session-drift.json`:
```json
{
  "<run_id>": {
    "drift_count": 1,
    "first_drift_at": "ISO",
    "last_drift_at": "ISO",
    "violations_seen": ["must_touch_markers"]
  }
}
```

GC'd after 120 minutes of inactivity per run_id.

### Tests

- `test_verify_claim_hybrid.py` — 9 cases
- Regression: 21/21 (migrate-state, contract-pins, codex-mirror)


## v2.8.2 (2026-04-26) — Skill-version drift permanently solved

### Tier A — `/vg:migrate-state` (commit 6324c2fd in source)
New command for retroactive marker drift repair. Idempotent scan + apply
based on artifact evidence. Logs single override-debt entry per applied
phase (no register bloat). Multi-plan phases (07.13-style with 07.13-NN-PLAN.md
naming) handled via glob evidence patterns.

Modes: `--scan`, `{phase}` shorthand, `--apply-all`, `--dry-run`, `--json`.

### Tier B — Per-phase contract pinning (commit 227ea852 in source)
`.vg/phases/{phase}/.contract-pins.json` written at `/vg:scope`,
snapshotting `must_touch_markers` + `must_emit_telemetry` for all 6
tracked commands. Subsequent runs validate against the pinned contract,
not the live skill body. Harness upgrades that mutate marker contracts
no longer retroactively invalidate already-shipped phases.

`/vg:migrate-state --apply` writes pins for legacy phases at current
harness version (best-effort retroactive lock).

### Bug fix — orchestrator tolerates non-JSON validator stdout (commit 9515cd86)
11 validators that emit human-friendly text by default (e.g. "✓ All good",
"⛔ Drift") were crashing the validator dispatcher with
`Expecting value: line 1 column 1 (char 0)`. Orchestrator now synthesizes
verdict from exit code when stdout has no `{`: 0 → PASS, 1 → WARN, 2+ → SKIP.
Validators still preferred to emit JSON when invoked with `--json`.

### Audit fixups — N9 + N10 (commit a44503c0)
- N9: `/vg:blueprint` commit step now tracks every blueprint output
  (TEST-GOALS.md unconditionally + UI-SPEC/UI-MAP/UI-MAP-AS-IS/FLOW-SPEC
  via existence guards). Prevents silent orphan files.
- N10: `/vg:sync --verify` mode hashes post-`</codex_skill_adapter>` mirror
  content vs post-frontmatter source content. Catches functional drift
  invisible in the line-level `sync.sh --check` diff.

### Verification
55/55 regression tests pass (idempotency, no-no-verify, orchestrator
dispatch, mirror equivalence, validator non-JSON tolerance, migrate-state,
contract pins).

## v2.8.1 (2026-04-26) — Hotfix

Audit-driven fixups against `/vg:build` vs `/vg:blueprint` artifact flow.

### Critical fixes
- **C1** — `build.md` 3c_amendment_freshness sub-step: builder re-reads `AMENDMENT-LOG.md` mid-build and rebinds contract/goal/context-refs (prevents stale-state drift after `/vg:amend`).
- **C2** — Pinned architectural invariant via smoke test `test_orchestrator_dispatches_blueprint_validators.py` — orchestrator dispatches blueprint validators by COMMAND key (not step), preventing future refactor regression.

### Major fixes
- **M3** — Contract dedup: build skips contract injection if symbol already exists in target schemas file (prevents duplicate identifier collisions).
- **M4** — CONTEXT.md mtime gate: build aborts if CONTEXT.md modified after blueprint completion stamp (forces re-blueprint).
- **M5** — Removed stale `RIPPLE-ANALYSIS.md` reference from `R5_FILES` list (artifact deprecated in v2.6).
- **M6** — Build reads pre-build CrossAI verdict from `crossai/blueprint-review.xml` and surfaces BLOCK findings before wave dispatch.
- **M7** — Documented blueprint vs Gate U utility check intent (clarifies overlap is intentional defense-in-depth, not redundancy).
- **M8** — Removed dead `--skip-design-check` flag from blueprint command-line list (kept doc-comment refs at lines 67, 72).

### Audit transparency
This release includes the full audit cycle commits (revert + surgical re-do for M5+M8) so operators can trace the regression detection that prevented the original M5+M8 commit from over-deleting 79 lines including `Platform Essentials` and `Blueprint Completeness` UNQUARANTINABLE gate blocks.

### Verification
- 29/29 tests pass (`test_idempotency_coverage.py`, `test_no_no_verify.py`, `test_orchestrator_dispatches_blueprint_validators.py`)
- Pre-commit RULES-CARDS drift gate enforced
- `Platform Essentials` invariant grep = 3 hits intact in source `.codex/skills/vg-blueprint/RULES-CARDS.md`

## [2.8.0] - 2026-04-26

VG workflow-hardening v2.7 plan — 8 phases shipped covering forward-gap closure from v2.7.0 ship + audit dim-3/4/6/7 HIGH+MEDIUM closure.

### Added
- **Phase J** (OS-keychain integration) — `verify_human_operator()` HMAC token now stored in OS keychain (Keychain Access macOS, Credential Manager Windows, Secret Service Linux). Migration script + per-OS onboarding doc. File fallback retained for headless CI.
- **Phase K** (Hardcode refactor) — 34→5 occurrences (-85%). HARDCODE-REGISTER.md + drift gate. `verify-no-hardcoded-paths.py` extended with line-level INTENTIONAL_HARDCODE annotation support.
- **Phase M** (Hotfix override extension) — 5 new gate_ids auto-resolve via `override_auto_resolve_clean_run`: allow-orthogonal-hotfix, allow-no-bugref, allow-empty-hotfix, allow-empty-bugfix, allow-unresolved-overrides. Resolution events emitted from /vg:review phase1_code_scan.
- **Phase N** (Manual rule-card breadth) — 110 entries across 12 mid-traffic skills (vg-blueprint, vg-scope, vg-specs, vg-amend, vg-design-extract, vg-design-system, vg-init, vg-project, vg-roadmap, vg-prioritize, vg-haiku-scanner, vg-reflector). 26.5% validator-linked. AUDIT.md dim-4 closure: 13.3% → 35.6%.
- **Phase O** (Root-verifier test breadth) — 12 verifier tests + bootstrap-loader meta-test. AUDIT.md dim-7 closure: validator coverage in `.claude/scripts/validators/` from 80% → **100%** (51/51).
- **Phase P** (Skill invariants + manual-card schema validator) — single UNQUARANTINABLE validator covers SKILL.md structural invariants (step numbering, frontmatter, marker presence, sync gate) + RULES-CARDS-MANUAL.md schema (body length, tag enum, validator-link existence, anti-pattern incident reference). Phase L (skill invariant contracts) merged into P.
- **Phase Q-decay sub-deliverable** (Calibration decay policy) — `registry-calibrate.py --apply-decay` flag with TTY/HMAC + audit emit. Suggestions older than configurable threshold without confirming evidence auto-retire RETIRED-in-place. Phase Q full re-eval calendar-gated, deferred to v2.9.
- **Phase R** (Cross-platform CI parity + pre-commit drift hook) — CI matrix on ubuntu-latest + macos-latest + windows-latest. UTF-8 subprocess helper. `.githooks/pre-commit` blocks RULES-CARDS drift when SKILL.md changes without re-running `extract-rule-cards.py`. 28 documented test failures closed (21 Linux + 7 Windows-encoding).

### Changed
- `.claude/scripts/vg-orchestrator/__main__.py` — UNQUARANTINABLE allowlist grew 34 → 35 (verify-skill-invariants added)
- `.claude/scripts/registry-calibrate.py` — `apply-decay` action added with TTY/HMAC + min-50-char reason gate (matches override-resolve and calibrate apply patterns from v2.7.0)
- `.claude/commands/vg/_shared/lib/override-debt.sh` — `auto_resolve_clean_run` gate_id table extended with 5 new entries
- `.claude/scripts/validators/audit-rule-cards.py` — `--check-schema` flag delegates to verify-skill-invariants for schema portion (avoid duplicate parsers)
- `.claude/vg.config.md` — added 3 new sections: `security_keychain.*`, `validators_skill_invariants.*`, `calibration.decay_after_phases`. Commit-msg pattern widened to accept `feat(harness-vN.M-XX):` style.

### Tests
- ~1240 cumulative tests passing (38 v2.7 phase tests + 19 v2.6.1 security regression + 1183 carried-forward).

### Migration
Backward compatible. Existing `.approver-key` files continue working via fallback. Existing 783 auto-extracted rules unchanged. Existing config keys unchanged. Operator runs migration scripts opt-in.

## [2.7.0] - 2026-04-26

VG workflow-hardening v2.6 plan — 8 phases shipped in atomic commits with goal-backward verification.
Cumulative: 180 tests passing on source repo (45 v2.6 phase tests + 19 v2.6.1 security regression + 112 root-verifier backfill + 4 learn TTY).

### Added
- **Phase A** (Bootstrap shadow evaluator + critic merged) — adaptive rule promotion replacing fixed `tier_a_auto_promote_after_confirms=3`. Reads `.vg/events.jsonl`, computes correctness rate per candidate via commit-msg citation parser. Optional `--critic` flag emits Haiku LLM advisory verdict per Tier-B candidate.
- **Phase C** (Conflict auto-retire) — pairwise Jaccard + opposing-verb conflict detection, reuses `learn-dedupe.py` similarity. New `RETIRED_BY_CONFLICT` candidate status, `conflict_winner` field. Surfaces in same accept.md step 6c y/n/e/s loop.
- **Phase D** (Phase-scoped rules) — `phase_pattern` regex field per rule. `inject-rule-cards.sh --current-phase X.Y` filters rules whose pattern doesn't match. New `verify-rule-phase-scope.py` validator.
- **Phase E** (Dogfood metrics dashboard) — single-file HTML aggregator. 5 panels: autonomy %, override rate, friction time per skill, shadow correctness, conflict + quarantine snapshot. Reuses existing `vg-orchestrator quarantine status --json` and `query-events`. Stdlib-only.
- **Phase F** (Auto-severity calibration) — `registry-calibrate.py` + `vg-orchestrator calibrate` subcommand. Computes severity downgrade/upgrade suggestions (BLOCK→WARN if override > 60%, WARN→BLOCK if downstream-correlation > 80%). UNQUARANTINABLE list (34 entries) hard-exempt from downgrade. TTY/HMAC + min-50-char reason gate on apply.
- **Phase G** (`/vg:learn` TTY/HMAC parity) — promote/reject mutating ops now require TTY OR HMAC-signed token. Audit events on success + on blocked-attempt forensic trail. Closes parity gap with `--override-reason` and `cmd_calibrate apply`.
- **Phase H** (Manual rule-card adoption) — 50 operator-curated `RULES-CARDS-MANUAL.md` entries across 4 high-traffic skills (vg-build, vg-review, vg-test, vg-accept). 14 validator-linked. Closes AUDIT.md dim-4 finding 4 (manual adoption: 4.5% → 13.3%).
- **Phase I** (Root-verifier test backfill) — 112 unit tests across 13 root verifiers (10 UNQUARANTINABLE, 3 BLOCK-severity high-LOC) + bootstrap-test-runner meta-test. Closes AUDIT.md dim-7 HIGH gap.

### Changed
- `learn-tier-classify.py` accepts `--shadow-jsonl` for adaptive threshold (grandfathers v2.5 behavior when absent)
- `vg-reflector/SKILL.md` candidate emit adds `shadow_mode: true` + `confirmed_by_telemetry` + `phase_pattern` suggestion
- `accept.md` step 6c surface accommodates 3 sources: shadow-evaluator promotions (A), conflict pairs (C), phase_pattern proposals (D)
- `.claude/vg.config.md` + 4 new key groups: `bootstrap.shadow.*`, `bootstrap.critic.*`, `telemetry.dashboard_lookback_phases`, `calibration.*`

### Migration
Backward compatible. Existing 783 rules without `phase_pattern` continue injecting unchanged. Existing event types preserved. Operator runs `python3 .claude/scripts/validators/extract-rule-cards.py` separately if RULES-CARDS regen wanted.

## [2.6.1] - 2026-04-26

### 7-dimension audit + 7-batch fix release — closes 13 CRITICAL + most HIGH findings

Comprehensive harness audit (`.vg/harness-audit-2026-04-26/`) ran 7 parallel
Explore agents covering: validator wiring, override/bypass surfaces,
migration debt, memory mechanism, step sync, config drift, self-test
coverage. **125 findings** total: 13 CRITICAL, 43 HIGH, 37 MEDIUM, 32 LOW.

Three most surprising discoveries:
1. `inject_rule_cards` helper was 0/44 invoked — 783 extracted rules were
   dead code, AI never read them at runtime
2. 22 bypass flags (`--override-reason`, `--allow-*`, `--skip-*`), zero
   had TTY/HMAC caller authentication — AI subagent could self-inject
3. CI never ran harness Python tests — regressions in `.claude/scripts/*`
   merged silently for months

### Batch A — UNQUARANTINABLE protect 5 security validators (commit d541dc86)

Wires 5 wired-but-unprotected validators into UNQUARANTINABLE allowlist:
verify-authz-declared, verify-auth-flow-smoke, verify-oauth-pkce-enforcement,
verify-rollback-procedure, verify-2fa-gate (severity bumped WARN→BLOCK).

### Batch B — Activate rule card injection (commit 9415a755)

Wires `inject_rule_cards` at first step of 7 high-traffic skills (vg-scope,
specs, blueprint, build, review, test, accept). 783 rules + 331 anti-
patterns now actually emitted to AI context at step start. Adds
`verify-rule-cards-fresh` drift gate to `/vg:accept` step 1.

### Batch C — Override caller-auth + quarantine recovery (commit a009dc2d)

Closes the AI self-injection class of bugs:
- `--override-reason` now requires TTY OR signed HMAC approver token
  (`verify_human_operator()` reused from v2.5.2.1 `--allow-*` path)
- Rubber-stamp escalator: same reason fingerprint copy-pasted across ≥2
  prior phases → BLOCK
- Stale-quarantine cleanup: validators promoted to UNQUARANTINABLE AFTER
  being disabled never got a chance to recover. New helper +
  `vg-orchestrator quarantine status / re-enable / force-enable-stale`
  CLI subcommands.

### Batch D — CI pytest gate + 19 critical security tests (commit 7dd9d650)

`.github/workflows/ci.yml` adds harness-tests job:
- Full suite warn-only (21 pre-existing Linux/Windows failures need v2.6.2)
- Hard gate for `test_idempotency_coverage.py` (9 tests) +
  `test_no_no_verify.py` (10 tests) — anti retry-storm/double-charge +
  pre-commit hook bypass

### Batch E — Schema drift canonicalization (commit 2524614d)

6 validators canonicalize FAIL/OK/SKIP → BLOCK/PASS/SKIP at output point.
Plus REAL bug: `verify-artifact-freshness` and `verify-command-contract-
coverage` emitted JSON without top-level verdict field → orchestrator
shim defaulted to PASS regardless of internal failures. Now emit
"verdict": BLOCK when failures.

### Batch F — UNQUARANTINABLE protect 11 more validators (commit fef97811)

Closer inspection of D1 audit's 30 "orphan" validators: 29/30 were
actually wired in COMMAND_VALIDATORS dict (audit grepped only `.md` files).
1 genuine orphan (verify-design-gap-hunter — that's a SKILL not a validator).

Of the 29 wired BLOCK validators, 11 security/integrity-critical were
missing UNQUARANTINABLE protection. Added: container-hardening,
cookie-flags-runtime, dast-waive-approver, dependency-vuln-budget,
no-hardcoded-paths, no-no-verify, security-baseline-project, security-
headers-runtime, allow-flag-audit, vps-deploy-evidence, clean-failure-state.

### Batch G — Hotfix override resolution event correlation (commit 449ccdb7)

Fixes 3 review.md `log_override_debt` calls that had positional args
mis-ordered (flag-as-name, phase-dir-as-reason, gate_id always missing).
New gate_id taxonomy: review-goal-coverage, bugfix-bugref-required,
bugfix-code-delta-required.

New `override_auto_resolve_clean_run` helper + wired into `/vg:review`
step "complete". When current phase review runs clean, prior phases'
matching debt entries auto-resolve. Closes the "hotfix debt piles up
forever" pattern.

### Net state v2.6.1

- UNQUARANTINABLE: 18 → 34 entries (manifest)
- Memory mechanism: dead → live (783 rules + 331 anti-patterns active)
- CI: 3 jobs (build-ts, build-rust, audit) → 4 jobs (+ harness-tests)
- Override surface: 22 flags w/o auth → all gated by TTY/HMAC + min-50
  char + placeholder + rubber-stamp escalator

### Deferred to v2.7 (genuine reasons)

- 52 untested scripts (volume — ~26h work)
- 21 pre-existing Linux CI failures (need Linux env to validate fixes)
- 22 hardcoded SSH/path/port instances (touches deployment, needs phase)

## [2.5.2.1] - 2026-04-24

### Hotfix — close 3 major findings from v2.5.2 CrossAI round-3

CrossAI round-3 consensus on v2.5.2 (Codex 7.9/10 FLAG, Claude 8.0/10 FLAG,
Gemini 9.2/10 PASS; consensus FLAG ship_with_changes). 3 MAJOR findings
consensus-flagged by Codex + Claude are closed in this patch.

### Fix 1 — HMAC-signed allow-flag tokens (closes Codex+Claude major)

**Problem:** v2.5.2 `VG_HUMAN_OPERATOR` env was a raw handle string.
AI subprocess could `os.environ["VG_HUMAN_OPERATOR"] = "real-human"`
before exec and bypass Phase O's allow-flag gate — same "narrated vs
behavioral" forge surface v2.5.2 was meant to close, just shifted from
validators to the gate itself.

**Fix:**
- `allow_flag_gate.py` now supports HMAC-SHA256 signed tokens. Token format:
  `b64url(payload_json).b64url(sig)` where payload = `{handle, flag,
  issued_at, expires_at}`. Signing key at `~/.vg/.approver-key` (0600 POSIX,
  user-profile protected Windows). Wildcard flag `*` permitted for short-
  lived session tokens.
- Strict mode (via `allow_flags.strict_mode=true` config OR
  `VG_ALLOW_FLAGS_STRICT_MODE=true` env) rejects raw-string env entirely.
  Non-strict mode accepts raw string with `[unsigned-warning]` suffix in
  approver (audit visibility).
- New CLI `.claude/scripts/vg-auth.py`:
  - `approve --flag X --ttl-days N` — TTY-only; mints token
  - `verify --token T --flag X` — explicit verification (debugging)
  - `init` — force-create signing key (idempotent)
- Negative test: AI subprocess with different key dir → signature
  invalid → blocked.

**Residual risk:** same-user AI can read `~/.vg/.approver-key` file
directly (file permissions don't isolate same-user processes). Mitigation:
`strict_mode=true` + TTY-only approval at time of use.

### Fix 2 — Full registry catalog + drift coverage (closes Codex+Claude major)

**Problem:** Phase S shipped 24-entry registry covering v2.5.2 validators
only. ~36 legacy pre-v2.5.2 validators stayed uncataloged. `verify-
validator-drift` was blind to them — defeated the "close opacity gap"
problem statement.

**Fix:**
- New `.claude/scripts/backfill-registry.py`: auto-discovers all
  `validators/*.py`, parses docstring first line for description,
  appends entries with placeholder metadata (`severity: warn`,
  `domain: uncategorized`, `phases_active: [all]`,
  `added_in: pre-v2.5.2`) for reviewer to tighten.
- `registry.yaml` now has **60 entries** (was 24). Backfilled legacy
  validators: acceptance-reconciliation, accessibility-scan, build-crossai-
  required, build-telemetry-surface, check-override-events, commit-
  attribution, context-structure, dast-scan-report, deferred-evidence,
  deps-security-scan, event-reconciliation, goal-coverage, i18n-coverage,
  mutation-layers, not-scanned-replay, override-debt-balance, runtime-
  evidence, skill-runtime-contract, and 18+ more.
- `verify-validator-drift.py` extended with
  `_detect_registry_coverage()` that fires `missing_from_registry`
  finding for any `*.py` file in validators/ without registry entry —
  ops sees catalog gaps first before behavioral drift checks.

### Fix 3 — `bootstrap-legacy-artifacts.py` shipped (closes Codex+Claude major)

**Problem:** Phase K `verify-artifact-freshness` requires manifest entries
with `creator_run_id == current_run_id`. Grandfathered phases 0-16 had
no manifest → Phase 17+ cutover forced projects into
`--allow-legacy-manifest-accept` flag whose env-approver path was the
Fix 1 forge surface. Two weak gates compounded.

**Fix:**
- New `.claude/scripts/bootstrap-legacy-artifacts.py`: walks
  `.vg/phases/*/`, discovers must_write artifacts (PLAN.md, API-CONTRACTS.md,
  SPECS.md, CONTEXT.md, SUMMARY*.md, RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md,
  SANDBOX-TEST.md, UAT.md, FOUNDATION.md, ROADMAP.md, crossai/*.xml),
  writes entries with `creator_run_id: "legacy-bootstrap"`,
  `grandfathered: true`, `phase: <phase-name>`. `--dry-run` default;
  `--apply` commits; `--phase FILTER` for single-phase mode.
- New `verify-no-legacy-manifest-creation.py`: scans the legacy-bootstrap
  manifest for entries with `phase > cutover_phase` (default 17) → BLOCK
  (AI forging grandfather marker past cutover). Also scans all other run
  manifests for `creator_run_id: "legacy-bootstrap"` OR `grandfathered:
  true` → BLOCK (only bootstrap tool may emit those).

### Test results

- Fix 1: 19 new test cases (sign/verify, strict mode, AI forge attempts) + existing Phase O suite 12/12 green
- Fix 2: 7 new test cases (backfill + drift) + existing Phase S 12/12 green
- Fix 3: 10 new test cases (bootstrap + cutover enforcement)
- **36 new tests, all pass + no existing regression.**

### Schema / config additions

- Config key `allow_flags.strict_mode: bool` (Fix 1)
- Env vars: `VG_APPROVER_KEY_DIR` (test override),
  `VG_ALLOW_FLAGS_STRICT_MODE` (runtime override)
- Manifest fields: `grandfathered: true`, `phase: <phase-name>` (Fix 3)

### Files new / modified

New:
- `.claude/scripts/vg-auth.py`
- `.claude/scripts/backfill-registry.py`
- `.claude/scripts/bootstrap-legacy-artifacts.py`
- `.claude/scripts/validators/verify-no-legacy-manifest-creation.py`
- `.claude/scripts/tests/test_allow_flag_signed_tokens.py`
- `.claude/scripts/tests/test_registry_backfill.py`
- `.claude/scripts/tests/test_bootstrap_legacy.py`

Modified:
- `.claude/scripts/vg-orchestrator/allow_flag_gate.py`
- `.claude/scripts/validators/verify-validator-drift.py`
- `.claude/scripts/validators/registry.yaml` (36 entries appended)

## [2.5.2] - 2026-04-24

### Deep harness hardening — 8 phases (0, J, K, L, M, N, O, P, R, S)

Post-v2.5.1 CrossAI round (Codex 7.2/10, Claude 7.2/10, both FLAG with
`ship_with_changes`) surfaced 13 findings across consensus + individual
reviewer flags. v2.5.2 ships hardening for each.

### New contract schema fields (runtime-contract.json)

- `mutates_repo`: bool — mutating commands must declare
- `observation_only`: bool — read-only commands exempt from evidence checks
- `contract_exempt_reason`: str — required when observation_only=true
- `must_be_created_in_run`: bool — artifact's manifest entry must have
  `creator_run_id == current run_id` (Phase K stale-artifact gate)
- `check_provenance`: bool — also verify `source_inputs` haven't drifted
- `validate_crossai_xml`: bool — invoke XML validator on crossai outputs
- `must_have_consensus: N` — N CLI results must agree on verdict
- `security_runtime`: object — runtime security validator dispatch
- `mutation_journal`: object — require rollback-able mutation logging

### Phase 0 — Codex mirror sync preflight (continuous, not release-gate-only)

- `verify-codex-skill-mirror-sync.py` — SHA256 parity across
  `.claude/commands/vg/` ↔ `.codex/skills/` ↔ `~/.codex/skills/` ↔
  `vgflow-repo/` with CRLF/LF normalization for Windows
- `sync-vg-skills.py` — orchestrated sync + version bump + commit+tag
- `premutation-sync-check.sh` — 24h-cached pre-command hook
- Orchestrator preflight wired in `cmd_run_start`

### Phase J — Command contract coverage (34 commands backfilled)

- `verify-command-contract-coverage.py` — catches skills missing
  runtime_contract on mutating commands
- 26 mutating commands: `mutates_repo: true` + `must_emit_telemetry`
- 8 observation-only: `observation_only: true` + `contract_exempt_reason`

### Phase K — Artifact-run binding + provenance chain

- `emit-evidence-manifest.py` — writes sha256 + creator_run_id per
  artifact to `.vg/runs/{run_id}/evidence-manifest.json`
- `verify-artifact-freshness.py` — blocks stale artifacts from prior
  runs satisfying must_write (prevents Codex-identified forge surface)

### Phase L — Trust-anchor XML validation + CrossAI multi-CLI consensus

- `validate-crossai-review-xml.py` — XPath checks: verdict in
  {pass,flag,block}, score 0-10, reviewer non-empty, handles preamble
- `verify-crossai-multi-cli.py` — N CLIs agreeing + reviewer diversity
  (blocks single-reviewer spoofing)

### Phase M — Security runtime enforcement (10 validators)

**Infrastructure (6):** `verify-security-baseline-project.py` (orchestrator),
`verify-cookie-flags-runtime.py`, `verify-security-headers-runtime.py`
(HSTS/CSP/X-Frame/nosniff), `verify-authz-negative-paths.py`
(cross-tenant IDOR probes), `verify-dependency-vuln-budget.py`
(CVE budget per severity), `verify-container-hardening.py`
(non-root + HEALTHCHECK + pinned tag).

**Application auth (4):** `verify-jwt-session-policy.py` (RS256/ES256,
≤15min access, ≤7d refresh, revocation path), `verify-oauth-pkce-enforcement.py`
(PKCE S256 + state + nonce), `verify-2fa-gate.py` (TOTP/WebAuthn),
`verify-log-hygiene.py` (SAST + runtime log scan for leaked
Authorization/password/token/secret/email).

### Phase N — DAST waive approver gate

- `verify-dast-waive-approver.py` — each waived finding MUST have:
  approver in allowlist, non-expired `waive_until`, 100+ char reason,
  rubber-stamp detection (same approver+reason ≥3× → flag),
  ratio gate (waived/total > 0.3 → warn)

### Phase O — Orchestrator lock + journal + allow-flag human-only gate

- `vg-orchestrator/lock.py` — repo-level advisory lock with stale-break
  on dead pid OR ttl elapsed
- `vg-orchestrator/journal.py` — append-only JSONL mutation journal +
  `rollback_run()` for file_write/file_delete/config_change actions
- `vg-orchestrator/allow_flag_gate.py` — TTY check + `VG_HUMAN_OPERATOR`
  env override + rubber-stamp detection
- 3 new validators: `verify-clean-failure-state.py`,
  `verify-override-debt-sla.py`, `verify-allow-flag-audit.py`
- `__main__.py` acquires lock in `cmd_run_start`, blocks `--allow-*`
  flags for non-TTY/non-env-approver sessions

### Phase P — Behavioral bootstrap verify

- `vg-orchestrator/prompt_capture.py` — captures actual executor
  prompts to `.vg/runs/{run_id}/executor-prompts/task-{N}.prompt.txt`
  with sha256 manifest (AI cannot forge — capture is in orchestrator
  path before subagent spawn)
- `verify-bootstrap-carryforward.py` — greps active LEARN-RULES.md
  rule text in captured prompts (behavioral — not event log)
- `verify-learn-promotion.py` — Tier-A promotions must appear in
  first subsequent-run prompts

### Phase R — Prose-to-PY behavioral validators

- `verify-executor-context-scope.py` — D-XX IDs in prompt MUST match
  declared `<context-refs>` (blocks full-mode silent fallback)
- `verify-review-loop-evidence.py` — consecutive review iterations
  MUST show git file delta OR explicit `resolution: "no_fix_needed"`
- `evaluate-test-requirements.py` — automated critical/important
  goals must have test with ≥2 assertions + E2E if user-flow goal

### Phase S — Validator registry + drift detection

- `validators/registry.yaml` — catalog of 24 v2.5.2 validators
- `validator-registry.py` — CLI: list/describe/missing/orphans/
  validate/disable/enable
- `verify-validator-drift.py` — detect never_fires / always_pass /
  high_block_rate / perf_regression patterns over events.db
- `/vg:validators` slash command (observation_only contract)

### Test results

- 214/214 v2.5.2 phase tests pass (8 test files, 29.7s)
- Batch M1: 45/45 infra tests pass
- Batch M2: 24/24 app-auth tests pass
- Batch O: 45/45 orchestrator tests pass
- Batch P+R+S: 14+26+12 = 52/52 behavioral tests pass
- Batch N: 12/12 waive approver tests pass

### Migration strategy

- Grandfather phases 0-16, cutover phase 17+ hard enforce
- Cold-start manifest bootstrap for grandfathered artifacts
- `--allow-*` flags require TTY OR `VG_HUMAN_OPERATOR` env (human-only)
- Rubber-stamp detection after 3× same-approver-same-flag usage

## [2.5.1] - 2026-04-24

### Anti-Forge Hardening — evidence-backed contracts

v2.5.1 closes the forge surface where `/vg:blueprint 7.14` reported PASS but
CrossAI never actually ran (only the marker file was touched — empty
`crossai/` dir, 0 `crossai.*` events). Marker alone is forgeable; evidence
must bind to (artifact presence) + (telemetry event) pairs with optional
flag waiver.

### Schema extensions (runtime-contract.json)

- `glob_min_count: N` — path treated as glob, require ≥N matches
- `required_unless_flag: "--flag"` — waiver mechanism; logs
  `contract.artifact_waived` / `contract.telemetry_waived` INFO events

### Task-list visibility gate

Every pipeline command entry step now invokes `emit-tasklist.py` helper
(authoritative step list from `filter-steps.py`) + emits `{cmd}.tasklist_shown`
event so AI cannot start a flow silently without showing the user the plan.

Wired into: `specs`, `scope`, `blueprint`, `build`, `review`, `test`, `accept`.

### Prose cleanup — gsd-executor tag removal

3 skill files had lingering `gsd-executor` prose references that caused
orchestrator to spawn wrong agent type despite explicit `subagent_type=
"general-purpose"` declaration:
- `build.md:503` — resume-safe note
- `design-extract.md:36` — available_agent_types block
- `_shared/vg-executor-rules.md:4` — header comment

Cleaned → VG-native "no external workflow dependency" language.

### New files

- `.claude/scripts/emit-tasklist.py` — tasklist visibility helper
- `.claude/scripts/tests/test_contract_antiforge.py` — 13 cases
- `.claude/scripts/tests/test_tasklist_visibility.py` — 28 cases

### Enforcement proof

- Forge attempt WITHOUT `--skip-crossai` + no real crossai/*.xml → Stop hook
  BLOCK with `[must_write] crossai/result-*.xml (glob matches 0 < required 1)`
  + `[must_emit_telemetry] crossai.verdict (expected ≥1, got 0)`
- Waiver path WITH `--skip-crossai` + override 50+ chars + commit SHA →
  PASS, emits `contract.*_waived` INFO events + OD-XXXX debt entry

### Codex skill mirror sync restored

`.codex/skills/` and `~/.codex/skills/` had drifted pre-v2.5.0. Full sync
restored parity across 4 locations (RTB source, vgflow-repo, .codex local,
~/.codex global). All 41 skills hash-match.

---

## [2.5.0] - 2026-04-23

### Workflow Hardening — 8 phases closing B+ → Best-in-class workflow discipline

v2.5 implements the approved 8-phase hardening plan. Goal: move VG from a
B+ harness into **best-in-class workflow discipline for structured-domain
Claude Code projects** — verifiable autonomy with auditable gate enforcement,
cross-phase artifact integrity, and model-portable executor contracts.

### Phase A — Post-wave independent verification

Post-wave-complete subprocess re-runs typecheck + affected tests + contract
verify OUTSIDE commit mutex. Divergence → soft reset + escalate. Wave-level
(not per-task) to avoid 5× mutex pressure. `--allow-verify-divergence`
override logs to debt register.

### Phase B — Security 3-tier + Perf Budget + DAST

**Tier 1 static (per-endpoint, inline TEST-GOALS frontmatter):** full OWASP
Top 10 2021 coverage + ASVS Level 2 per goal; mutation endpoints require
CSRF + rate_limit; auth_model cross-check against API-CONTRACTS.

**Tier 2 dynamic (DAST at /vg:test step 5h):** ZAP/Nuclei cascade spawns
active scan against deployed sandbox. Risk-profile-aware severity gate:
`critical` = High finding BLOCKs, `low` = all advisory. `--skip-dast` +
`--allow-dast-findings` overrides log to debt.

**Tier 3 project-wide baseline (`verify-security-baseline.py`):** grep
codebase + deploy scripts for TLS version / HSTS header / wildcard CORS +
credentials / real secrets in .env.example / cookie flags / lockfile
integrity. Fires at /vg:review phase 1 + /vg:accept step 6b. HARD BLOCK at
accept on critical drift.

**Perf budget:** `verify-goal-perf.py` enforces p95_ms per tier declared in
TEST-GOALS `perf_budget:` block. Mutation endpoint missing budget = BLOCK.

### Phase C — Executor context isolation

`context_injection.mode: full | scoped` in config. Scoped mode extracts only
decisions listed in task's `<context-refs>P{phase}.D-XX</context-refs>`
attribute. Blueprint planner instructed to emit refs per task; executor
reads `<decision_context>` block, MUST NOT read CONTEXT.md directly.
`phase_cutover=14` auto-upgrades scoped for new phases. New validator
`verify-context-refs.py` WARNs on missing refs (advisory).

### Phase D — FOUNDATION §9 architecture lock + SECURITY-TEST-PLAN

`/vg:project` round 7 locks 8 architectural subsections in FOUNDATION.md §9
(tech stack, module boundary, folder convention, cross-cutting concerns,
security baseline, performance baseline, testing baseline, model-portable
code style). Round 8 writes `.vg/SECURITY-TEST-PLAN.md` via 4 strategic Q&A
(risk profile, DAST tool, pen-test strategy, compliance framework).
New validators `verify-foundation-architecture.py` + `verify-security-test-plan.py`
(both UNQUARANTINABLE).

Blueprint planner prompt injected with `<architecture_context>` +
`<security_test_plan>` blocks — planner sees the authoritative contract.

### Phase E — Reactive telemetry suggestions

`telemetry-suggest.py` emits 3 advisory types from events.db + telemetry.jsonl:
skip candidates (pass_rate>=0.98 + samples>=10), expensive reorder
(p95>threshold → late in sequence), override abuse warning (flag used
>=3× in 30 days → gate may need tuning).

**UNQUARANTINABLE safety:** security validators NEVER suggested for skip,
regardless of pass rate. Hardcoded safety baseline union-merged with parsed
set — parsing failure can never remove a security validator from protected
set. `--apply skip X` hard-refuses UNQUARANTINABLE. Closes "AI gaming via
reactive skip suggestions" surface.

### Phase F — Build-progress task checkpoint extension

`.build-progress.json` per-task entry now carries optional verification
fields (typecheck/test_summary/wave_verify/run_id). New helper
`vg_build_progress_is_task_fully_verified` — `/vg:recover` skips tasks with
full verification record (no re-run after compact). Backward compat:
legacy commits without these fields treated as "not fully verified"
(safer default).

### Phase G — Cost budget tracker + model portability guide

`cost-tracker.py` aggregates token_usage events per phase or milestone,
compares against config budgets (phase=500k, milestone=5M default), warns
at 80%, blocks over hard budget. Consumable by accept gate.

`.vg/MODEL-PORTABILITY.md` — doc-only artifact on cross-model consistency.
Points to FOUNDATION §9.8 model-portable style rules + CrossAI 2d-6 as
multi-model review mechanism (no new diff tool, per plan consensus).

### Phase H — Learn auto-surface + tier (UX fatigue fix)

Closes bootstrap learning loop by eliminating review-fatigue anti-pattern.
New step `6c_learn_auto_surface` at end of /vg:accept. Tiered candidates:

- **Tier A** (conf≥0.85 + impact=critical): auto-promote after 3 phase
  confirms, 1-line notification only
- **Tier B** (conf 0.6-0.85): surfaced MAX 2 per phase, 3-line y/n/e/s
  prompt each
- **Tier C** (conf<0.6): silent parking, access via `/vg:learn --review --all`
- **RETIRED** (reject_count≥2): never surfaced again

`learn-tier-classify.py` computes tier from confidence + impact + history.
`learn-dedupe.py` merges title-similar candidates (difflib ≥ 0.8) before
surface. Reflector schema extended with `impact` + `first_seen` + `reject_count`
fields.

### Phase I — Milestone pentest checklist generator

`/vg:security-audit-milestone` step 5 generates
`.vg/milestones/{M}/SECURITY-PENTEST-CHECKLIST.md` — human-curated
artifact for pentesters. Aggregates SECURITY-TEST-PLAN risk profile +
endpoints grouped by auth model + OPEN threats carry-over from
SECURITY-REGISTER + risk-profile-aware priority vectors + compliance
control mapping (SOC2 / ISO 27001 / HIPAA / GDPR / PCI-DSS predefined).
VG does NOT run pentests — curates info so humans can.

### Migration

- Phase 0-13: grandfather on all new gates (warn/skip), `context_injection.mode=full`
- Phase 14+: hard enforcement, `scoped` mode auto-upgrade via `phase_cutover=14`
- Override handlers: `--allow-verify-divergence`, `--allow-missing-security`,
  `--allow-missing-perf`, `--allow-missing-architecture`, `--allow-full-context-mode`,
  `--allow-baseline-drift`, `--skip-dast`, `--allow-dast-findings`

### Test coverage

- 198 new integration tests across 12 test files
- 530/530 regression pass (A-I cumulative, skipping 16 WSL-broken pre-existing)

### Files changed

**17 new scripts:** wave-verify-isolated, verify-goal-security, verify-goal-perf,
verify-security-baseline, verify-context-refs, verify-foundation-architecture,
verify-security-test-plan, dast-scan-report, telemetry-suggest, cost-tracker,
learn-tier-classify, learn-dedupe, generate-pentest-checklist, _i18n helper,
dast-runner.sh, etc.

**3 new templates:** SECURITY-TEST-PLAN, SECURITY-PENTEST-CHECKLIST,
TEST-GOAL-enriched (extended with security_checks + perf_budget blocks).

**1 new doc:** MODEL-PORTABILITY.md

**Skill files edited:** build.md, blueprint.md, review.md, test.md,
accept.md, project.md, learn.md, security-audit-milestone.md,
vg-executor-rules.md, vg-reflector/SKILL.md, 4 narration string keys.

**Config new keys:** `context_injection`, `cost`, `bootstrap` (auto-surface
+ tier thresholds), `security_testing.dast_*`, `visual_regression` (already
present, no change).

### Drops (out of scope per CrossAI consensus)

- Cross-model build comparison tool (reuse CrossAI 2d-6)
- `/vg:architect` new command (extended `/vg:project` round 7 instead)
- `ARCHITECTURE.md` new artifact (FOUNDATION §9 instead)
- `task-frame.json` new file (extended `.build-progress.json` instead)
- R8 commit-message citation rule (conflict with R1)

## [2.3.1] - 2026-04-23

### Level 5 push — close 3 autonomy gaps from v2.3 review

v2.3.1 closes the remaining gaps preventing VG from being classified as **Level 5 Autonomous Workflow Engineering**:

### Gap 1 — Dead Python scripts wired or deleted

- `bootstrap-conflict.py` (128 LoC) — now called by `/vg:learn --promote` as mandatory pre-check. Candidates with scope conflicting with active ACCEPTED rules are rejected before overlay write.
- `bootstrap-hygiene.py` (470+ LoC) — `/vg:bootstrap --health`, `--trace`, and new `--efficacy` subcommands all route here. Was previously hitting `bootstrap-loader.py` which didn't have this logic.
- `compat-check.py` (159 LoC) — wired into `/vg:update` step `4_breaking_gate`. Surfaces breaking changes within a major (renamed step markers, dropped contract fields, removed scripts).
- `vg_sync_codex.py` — **deleted.** Superseded by `generate-codex-skills.sh` (v2.3) which is now called automatically by `sync.sh`.
- `phase-metadata.py` (188 LoC) — confirmed referenced by `bootstrap-test-runner.py` + `bootstrap.md`; kept.
- `vg_migrate_goal_tags.py` — kept as one-shot migration utility (no runtime invocation by design).

### Gap 2 — Codex skill drift loop closed

- `sync.sh` now runs `generate-codex-skills.sh --force` automatically in step `1b` of every sync. Previously codex-skills were manually regenerated and drifted up to 400 lines behind Claude source (observed on `review.md` pre-2.3).
- Next sync emits `REGENERATED: codex-skills (41 skills from Claude source)` in summary.

### Gap 3 — Bootstrap outcome tracking functional

- `cmd_efficacy` in `bootstrap-hygiene.py` now **surgically mutates ACCEPTED.md** in place: rule blocks get their `hits`, `hit_outcomes.success_count`, `hit_outcomes.fail_count`, and `last_hit` timestamp updated from events.jsonl + events.db.
- Previously `--apply` only wrote to `.efficacy-log.md`; ACCEPTED.md stayed at `hits: 0` forever → self-learning system was mute.
- `accept.md` post-UAT now queries events.db for `bootstrap.rule_fired` events in the phase, emits `bootstrap.outcome_recorded` with phase verdict per rule, then auto-runs `bootstrap-hygiene.py efficacy --apply`.
- Phase success/fail attribution: derived from final UAT verdict (DEFER|REJECTED|FAILED → fail, else success).

### Tests

- `test_bootstrap_efficacy.py` +6 cases (dry-run no-mutation, --apply updates hits, multiple rules, audit log, empty events no-op, idempotent)
- **Total 77/77 targeted tests pass** (71 from v2.3 + 6 new).

### Engineering level

v2.3.1 reaches **Level 5 — Autonomous Workflow Engineering**:
1. ✅ Self-healing: dead scripts wired or deleted, distribution integrity via auto-regen
2. ✅ Auto-bootstrap learning feedback loop: rule fire → outcome attribution → efficacy → ACCEPTED.md update
3. ✅ Zero-drift distribution: sync.sh single source of truth

---

## [2.3.0] - 2026-04-23

### OHOK hardening — close 6 performative gaps + marker forgery attack surface

v2.3 finishes the "One Hit One Kill" (OHOK) pass: specs → accept now runs end-to-end without human intervention (except UAT), with every gate backed by **actual runtime enforcement** instead of prose "AI MUST do X" with no runtime hook.

Triggered by 6 adversarial audits (2 CrossAI rounds, Codex + Gemini independent review). Prior audits found **~17 performative steps** where AI could read the rule, understand it, then silently skip. Those are all closed now.

### Added

**Forgery-resistant step markers** (Batch 5b / E1):
- `_shared/lib/marker-schema.sh` — `mark_step()` writes content `v1|{phase}|{step}|{git_sha}|{iso_ts}|{run_id}` instead of empty `touch .done`.
- `verify_marker()` checks 5 invariants: schema version, phase match, step match, `git_sha` IS ancestor of HEAD (blocks after-the-fact `touch` forgery), `iso_ts` within 30 days (blocks stale marker reuse).
- `verify_all_markers()` iterates phase dir, returns BLOCK on any forged/mismatched/schema-bad marker.
- `scripts/marker-migrate.py` one-time migration rewrites legacy empty markers with synthetic content; idempotent.
- 73 `touch` calls across 8 skill files converted to `mark_step` with graceful fallback (`|| touch …`).
- `accept.md` step `2_marker_precheck` now hard-blocks on `rc=3/4/5/6/7` (forgery/mismatch/stale), WARNs on legacy empty (configurable strict mode via `VG_MARKER_STRICT=1`).

**Batch 1 — `specs.md` 0% → 85% enforced:**
- Runtime contract frontmatter (7 markers, 2 telemetry events, forbidden flags).
- `parse_args` bash gate: `grep` ROADMAP in 3 formats (heading / table / checkbox-list `- [x] **Phase N**`).
- `generate_draft` bash gate: `case $USER_APPROVAL` with `approve`/`edit`/`discard`/unset → exit 2 on discard or unset.

**Batch 2 — `review.md` phaseP_delta/regression real verification:**
- Previously wrote PASS stubs. Now parses parent `GOAL-COVERAGE-MATRIX.md`, extracts FAILED/BLOCKED goals, computes **per-goal** git overlap (CrossAI R6 fix: previously ONE global file set — any touched parent file false-PASSed ALL unrelated failed goals).
- Per-goal: `git log --grep=G-XX` → files → overlap check with hotfix delta. BLOCK if any failed goal with known commits has zero per-goal overlap.
- `phaseP_regression` requires `bug_ref` in SPECS + ≥1 code commit + test linkage check.
- Contract 4 → 25 markers (4 block + 21 warn via `required_unless_flag`).
- 4 new override flags: `--allow-empty-hotfix`, `--allow-orthogonal-hotfix`, `--allow-no-bugref`, `--allow-empty-bugfix`.

**Batch 3 — `accept.md` UAT quorum gate:**
- Previously `[s] Skip` on every `AskUserQuestion` → DEFERRED verdict shipped → next phase proceeds anyway. Pure theatre.
- New step `5_uat_quorum_gate` requires `.uat-responses.json`, counts critical_skips (decisions + READY goals).
- **UAT coverage cross-check (CrossAI R6 fix)**: expected decisions count from `### D-XX` headings in CONTEXT.md + expected READY goals from GOAL-COVERAGE-MATRIX.md, responses must cover all. Prevents attacker writing `{decisions: {skip: 0, total: 0}}` to trivially pass quorum.
- `--allow-uat-skips` override forces `verdict=DEFER` (propagates — next phase blocks).
- Contract 3 → 12 markers + 4 new override flags.

**Batch 4 — `build.md` real branching + context enforcement:**
- step `5_handle_branching` now real bash: `case $BRANCH_STRATEGY` phase/milestone/none with `git checkout -b` + **worktree + index** uncommitted-changes precheck (CrossAI R6: `git diff --quiet` alone missed index-only staged changes).
- step `4c` tracks `SIBLINGS_FAILED` array per-task; systemic failure (all fail) → exit 1 with diagnostic.
- Contract 8 → 18 markers.

**Batch 5 — `test.md` fix-loop counter persist + override-debt validator:**
- `5c_auto_escalate` previously had prose "max 3 iterations" with no state. Now persists `${PHASE_DIR}/.fix-loop-state.json` with `iteration_count` + `first_run_ts`. `MAX_ITER` via `vg_config_get test.max_fix_loop_iterations`. Exhausted → `test.fix_loop_exhausted` telemetry + exit.
- New `scripts/validators/check-override-events.py`:
  - Event store indexed by event_id (dict, not set) — includes gate_id metadata.
  - **gate_id binding** (CrossAI R6 critical): `resolved_by_event_id` event's gate_id must match override's gate_id. Previously: any unrelated real event could "resolve" any override.
  - `legacy: true` now requires non-empty `legacy_reason` field (previously: unconditional bypass for all pre-v1.8.0 entries).
  - Reads both `telemetry.jsonl` + `events.db` (hash-chained).

### Added — Concrete bug fixes from CrossAI Round 6

| # | Gap | File |
|---|-----|------|
| 1 | Missing ROADMAP format `- [x] **Phase N: ...**` | `specs.md` parse_args |
| 2 | `${AUTO_MODE:+auto}${AUTO_MODE:-guided}` emitted junk like `autofalse` | `specs.md` telemetry payload |
| 3 | `git diff --quiet` missed staged-only changes | `build.md` step 5 branching |
| 4 | phaseP_delta one global overlap → false-PASS all unrelated failed goals | `review.md` phaseP_delta |
| 5 | UAT responses JSON self-report trusted → trivial bypass | `accept.md` quorum gate |
| 6 | `legacy: true` = unconditional bypass | `check-override-events.py` |
| 7 | `resolved_by_event_id` didn't check gate_id | `check-override-events.py` |

### Tests

- `test_marker_forgery.py` — 16 cases (mark_step writes schema, verify rejects forgery/mismatch/stale/schema-bad, legacy lenient/strict mode, migrate script writes + idempotent)
- `test_batch5_integrity.py` — +2 (legacy_without_reason BLOCK, gate_id_mismatch BLOCK); 15/15 pass
- `test_phaseP_real_verification.py` — 15/15 pass after per-goal rewrite
- `test_uat_quorum_gate.py` — 17/17 pass after coverage gate addition
- `test_specs_contract.py` — 11/11 pass
- `test_build_gap_closure.py` — 13/13 pass
- **Total targeted: 71/71 pass.**

### Migration

One-time per project:
```bash
python .claude/scripts/marker-migrate.py --planning .vg
```

Rewrites legacy empty markers with synthetic content (phase from path, step from filename, git_sha = HEAD, iso_ts = now, run_id = `legacy-migration-{date}`). Idempotent. Backward compat: lenient mode accepts legacy empties by default; set `VG_MARKER_STRICT=1` to hard-block them.

### CrossAI Round 6 verdict

Both Codex + Gemini agreed: **BLOCK → must do Batch 5b before ship** (empty `.done` markers forgeable via synthetic `touch` sweep). v2.3 closes this. Post-migration, forged/mismatched/stale markers trigger BLOCK at accept gate with diagnostic per-step.

---

## [2.2.0] - 2026-04-21

### Major — Orchestrator + runtime contract + anti-rationalization enforcement

v2.2 đóng gap lớn nhất của VG: AI tự-chứng thực "done" qua rationalization. Ship **trust-boundary layer** giữa AI và pipeline — AI không advance pipeline được nếu thiếu evidence runtime.

### Added

**Orchestrator layer** (`scripts/vg-orchestrator/`):
- Python CLI binary với 20+ subcommands: `run-start`, `run-complete`, `run-abort`, `run-resume`, `run-repair`, `mark-step`, `emit-event`, `wave-start`, `wave-complete`, `override`, `validate`, `verify-hash-chain`, `query-events`.
- SQLite `events.db` với hash chain (tamper-evident event log, WAL + flock concurrency).
- 5 JSON schemas: event, evidence-json, runtime-contract, override-debt-entry, validator-output.
- Runtime contract parsed từ skill-MD frontmatter (must_write, must_touch_markers, must_emit_telemetry, forbidden_without_override).

**9 validators** (`scripts/validators/`):
- `phase-exists`, `context-structure`, `plan-granularity`, `wave-attribution`, `goal-coverage`, `task-goal-binding`, `test-first`, `override-debt-balance`, `event-reconciliation`.
- **`runtime-evidence`** (v2.2 hallmark) — chặn AI mark goals READY dựa "code evidence". Yêu cầu Playwright spec phải **đã chạy** (report newer than SPECS.md mtime). Critical goals có code nhưng không runtime proof → BLOCK.
- **Validator quarantine**: 3 consecutive fails → auto-disable, emit `validation.warned` reason=quarantined. Một PASS/WARN re-enable. Safety net chống 1 validator broken stall pipeline.

**Schema validation** (`scripts/vg-orchestrator/contracts.py`): jsonschema validate runtime_contract at parse-time. Typo/structural errors surface ở load, không runtime.

**Hooks 3-layer**:
- `UserPromptSubmit`: vg-entry-hook.py registers run BEFORE skill-MD loads (AI can't skip init).
- `Stop`: vg-verify-claim.py checks runtime_contract, exit 2 = force AI continue if evidence missing.
- `PostToolUse`: existing hook preserved.

**Skill-MD v2 rewrites** (all 6 pipeline commands):
- scope.md, blueprint.md, build.md, review.md, test.md, accept.md.
- Pattern: entry block `run-start` (idempotent) + emit `{cmd}.started` + inline `mark-step` at each step + terminal block emit `{cmd}.completed` + `run-complete` gate.
- Inline commands (no bash functions — they don't persist across Claude Code Bash tool calls).

**`/vg:doctor stack`** subcommand: diagnostic script check orchestrator reachable, events.db integrity, schemas valid, validators present, hooks wired, bootstrap consistent.

### Workflow fixes

- **`--wave N` contract exemption**: partial-run mode không ép full pipeline markers (8_execute_waves, 9_post_execution, 10_postmortem_sanity, complete) + `{cmd}.completed`. Wave-by-wave checkpoint clean, không override debt.
- **Goal-coverage pipeline ordering**: gate ở review downgraded BLOCK→WARN. Validator dispatch removed from `vg:review` (runs `vg:test` + `vg:accept` where tests exist). Prevents backend-only phase deadlock.
- **Validation verdict mapping**: PASS→validation.passed, WARN→validation.warned (new event type), BLOCK→validation.failed. Prior code collapsed WARN+BLOCK misleading audit.
- **`${PHASE_DIR}` substitution**: when phase_dir=None (phase not on disk), fallback to readable `.vg/phases/{phase}-<missing>` instead of literal `${PHASE_DIR}`.
- **Literal `\n` bug** (Python injection script artifact): replaced 3 broken commands in build.md với single-line form. Same fix applied to review.md + scope.md via pattern.
- **Dedup `{cmd}.started` event**: 5 manual emits removed from skill-MDs. Orchestrator run-start auto-emit = single source.

### Changed

- All 6 pipeline skill-MDs require orchestrator subprocess at entry + exit (idempotent with UserPromptSubmit hook).
- COMMAND_VALIDATORS dispatch mapping added runtime-evidence to review + test + accept.
- Schema regex allows digits in flag names (`--allow-r5-violation` etc).

### Deprecated / Removed

- Bash function helpers `_mark()` / `_emit()` in skill-MDs — not persistent across Claude Code Bash invocations, replaced with inline commands.

### Fixed

- `validation.warned` vs `validation.failed` event distinction (phase-exists validator returned WARN was marked failed).
- `--wave N` declared but unimplemented in build.md — now gates in step 8.
- Stop hook false-fire on aborted runs (test via orchestrator state clear).

### Tests

- `scripts/tests/test_bypass_negative.py`: 10 scenarios AI could bypass orchestrator. All BLOCK correctly.
- `scripts/vg-stack-health.py`: 8-check diagnostic, exit 0 healthy / 1 warn / 2 block.

### Migration from v1.14.x

- Skill-MDs auto-upgraded via install/sync — no user action needed.
- Existing phases keep working (runtime_contract optional — old skill-MDs that lack it skip the check).
- `events.db` auto-created on first v2.2 run.
- Quarantine file `.vg/validator-quarantine.json` auto-gitignored.

### Breaking? No

- Backward-compatible: pre-v2.2 phases still process via v2 skill-MD.
- All `/vg:*` commands preserve argument-hint; added flags are opt-in.
- Hooks fail-open: if orchestrator missing, skill-MD proceeds (degraded-correct).

## [1.14.0] - 2026-04-20

### Added — Migrate semantic gates (real enforcement, no decoration)
- **Migrate VG semantic gates** (`commands/vg/migrate.md` step 9): enforces 4 downstream blueprint/build/test requirements:
  - CONTEXT 3-section coverage (Endpoints + UI Components + Test Scenarios per decision)
  - TEST-GOALS Rule 3b (every mutation goal has Persistence check block)
  - Surface classification (ui/api/data/integration/time-driven/custom per goal)
  - PLAN ↔ TEST-GOALS bidirectional linkage (`<goals-covered>` per task)
- **Standalone validator** (`scripts/verify-migrate-output.py`): reusable gate validator. Used by step 9 + `--self-test` + CI tooling.
- **Self-test fixture** (`fixtures/migrate/legacy-sample/`): generic legacy GSD sample with golden post-migration output. Verifies gate logic deterministically without AI agent spawn.
- **`/vg:migrate --self-test` mode**: runs validator on golden fixture, diffs vs expected report. Exit 0 = gate logic correct.
- **Step 4 strengthened**: Gate 3 now requires count-match for ALL 3 sub-sections (was Endpoints only — silent miss for Test Scenarios was downstream blocker).
- **Step 6 strengthened**: agent prompt explicitly requires Persistence check + Surface classification. Post-staging Python gate validates before promotion.
- **Step 6.5 NEW**: bidirectional PLAN ↔ TEST-GOALS linkage (mirrors blueprint step 2b5 logic).
- **Override flags**: `--allow-semantic-gaps` (emergency bypass, logs override-debt).
- **Telemetry events**: `migrate_semantic_pass`, `migrate_semantic_fail`, `migrate_self_test_pass`, `migrate_self_test_fail` visible in `/vg:gate-stats`.

### Fixed
- **Mutation evidence regex**: previously `^-` matched markdown bullet `- DOM:` as placeholder dash → real mutations counted as N/A. Fix strips bullet prefix before placeholder check.
- **Goal header pattern**: 2-4 hash levels supported (matches both `## Goal G-XX` legacy and `#### G-XX:` convention).

### Migration guidance
- Existing legacy phases (without enrichment): gates correctly identify gaps. Verified on real project: 50 missing Persistence on a single phase.
- Re-run `/vg:migrate <phase> --force` to apply enrichment with full semantic gates.
- Override path: `--allow-semantic-gaps` for known-incomplete phases (logs override-debt, surfaces in `/vg:gate-stats`).

## [1.13.2] - 2026-04-20

Thêm công cụ **UI Component Map** — vẽ cây component dạng ASCII + JSON từ code React/Vue/Svelte, dùng cho 2 mục đích:

### Mục đích

1. **Bản đồ hiện trạng (As-is map)** — khi phase sửa view đã có, script quét code hiện tại sinh `UI-MAP-AS-IS.md` để planner hiểu cấu trúc trước khi viết plan.
2. **Bản vẽ đích (To-be blueprint)** — planner viết `UI-MAP.md` chứa cây component mong muốn + JSON tree. Executor bám theo khi build. Post-wave script sinh cây thực tế → diff với UI-MAP.md → phát hiện lệch (drift) → BLOCK nếu vượt ngưỡng.

### Added

- **`scripts/generate-ui-map.mjs`** — port từ gist TongDucThanhNam (đã audit clean: chỉ đọc AST + xuất ASCII, không network/file write/exec/eval). Port từ Bun → Node 20+, bỏ hardcode `apps/mobile` + expo-router, config-driven qua `ui_map:` section trong vg.config.md. Hỗ trợ React, React Native, Vue, Svelte (qua extension detection). Auto-detect router: expo-router / next-app / react-router / tanstack-router / none.

- **`scripts/verify-ui-structure.py`** — cổng kiểm tra (gate) so sánh UI-MAP.md (kế hoạch đích) với cây thực tế. Phân loại lệch thành MISSING (thiếu), UNEXPECTED (dư thừa), LAYOUT_SHIFT (lệch bố cục). Ngưỡng cấu hình qua `ui_map.max_missing` / `max_unexpected` / `layout_advisory`.

- **`commands/vg/_shared/templates/UI-MAP-template.md`** — mẫu cho planner viết UI-MAP.md với cây ASCII (người đọc) + JSON tree (máy so sánh).

### Wired vào pipeline

- **`blueprint.md`** sub-step mới `2b6b_ui_map` (profile web-fullstack/web-frontend-only): nếu phase có task FE, sinh UI-MAP-AS-IS.md (nếu sửa view cũ) → planner viết UI-MAP.md (to-be).
- **`build.md`** step 10 bổ sung drift check: sau post-mortem + goal coverage, chạy generate-ui-map.mjs trên code vừa build → verify-ui-structure.py diff với UI-MAP.md → warn nếu lệch.
- **`templates/vg/vg.config.template.md`** thêm section `ui_map:` (enabled, src, entry, router, aliases, max_missing, max_unexpected, layout_advisory).

### Rule tiếng Việt tăng cường (term-glossary.md)

User báo "AI không tuân theo" rule v1.14.0+ về VN-first narration. Nguyên nhân: rule viết cho command output, AI hiểu nhầm không áp dụng chat reply.

Thêm section mới "RULE v1.14.0+ R2 (2026-04-20 reinforce — AI narration)":
- Áp dụng cho mọi reply của AI trong session VG (không chỉ command output)
- Bảng 15 term hay vi phạm với bản thay tiếng Việt (CONFIRMED→XÁC NHẬN, Verdict→Kết luận, Audit→Rà soát, Drift→Lệch hướng, Root cause→Nguyên nhân gốc, v.v.)
- Yêu cầu cứng: trước khi gửi reply > 50 từ hoặc có bảng markdown, AI tự đếm term EN, > 2 → rewrite
- Kèm 2 ví dụ AI đã vi phạm trong session 2026-04-19 → sửa đúng

### Relation với artifacts UI hiện có (không đè)

- `design-normalized/` (từ `/vg:design-extract`) = nguồn thiết kế gốc (screenshots + DOM raw)
- `DESIGN.md` (từ `/vg:design-system`) = quy chuẩn style (color/typography/spacing)
- `UI-SPEC.md` (từ blueprint step 2b6_ui_spec) = spec design token cấp phase
- **`UI-MAP.md` (MỚI)** = cây component cụ thể cho từng view — contract cho executor
- **`UI-MAP-AS-IS.md` (MỚI)** = cây hiện trạng của code cũ (generated)

Bốn artifact bổ sung nhau.

## [1.13.1] - 2026-04-19

Post-Phase-10 adversarial audit fixes. User feedback: "code chưa gọn, không dùng graphify, sinh duplicate, sai goals". Audit confirmed graphify stale 10h during Phase 10 build + 0 telemetry events + goals declared without test traceability. Root cause: `(recovered)` commits from manual recovery bypassed skill framework entirely.

### Added (observability + enforcement)

- **`commands/vg/_shared/lib/graphify-safe.sh`** — hardened graphify rebuild wrapper. `vg_graphify_rebuild_safe()` records mtime before rebuild, verifies mtime advanced after, retries once on stuck. Previous silent failures (audit observed graph.json unchanged despite rebuild call) now emit LOUD warnings + `graphify_rebuild_failed` telemetry. `vg_graphify_assert_rebuilt_since()` checkpoint helper for call sites that expect rebuild to have occurred.

- **`commands/vg/_shared/lib/build-postmortem.sh`** — end-of-build sanity gate. `vg_build_postmortem_check()` verifies: (a) telemetry events exist for phase, (b) wave-start tags present, (c) no `(recovered)` commits bypassing gates, (d) step markers written. Emits `build_postmortem_ok` or `build_postmortem_issues` event. Warns, doesn't block (review is enforcement point).

- **`scripts/verify-goal-coverage-phase.py`** — phase-level goal→test binding audit. Complements existing per-task `verify-goal-test-binding.py` by scanning ALL test files (not just per-commit diff) for `TS-XX` markers and cross-referencing TEST-GOALS.md. Catches: goals declared but never tested, orphan TS markers (tests for removed goals), deferred goal handling via `verification: deferred|manual` annotation.

### Wired into existing commands

- **`commands/vg/build.md`** step 4 — replaces direct `_rebuild_code` call with `vg_graphify_rebuild_safe`. Step 4 rebuild silent-fail bug closed.
- **`commands/vg/build.md`** new step 10 (`10_postmortem_sanity`) — runs post-mortem + phase-level goal coverage audit. Advisory at build end, flags for review.
- **`commands/vg/blueprint.md`** step 2a — same safe wrapper replaces direct rebuild call.
- **`commands/vg/review.md`** step 0b (`0b_goal_coverage_gate`) — enforces goal coverage gate. BLOCK unless `--skip-goal-coverage` override (which logs to OVERRIDE-DEBT register).
- **`commands/vg/review.md`** Phase 1.5 — safe wrapper before ripple analysis.

### Deployed into RTB, verified against Phase 10

Ran `verify-goal-coverage-phase.py --phase-dir .vg/phases/10-deal-management-dsp-partners`:
- 14/15 goals bound to `apps/api/src/modules/deals/__tests__/deal-integration.test.ts`
- 1 unbound: `G-00` (typically inherited/milestone-level, should be `verification: deferred`)
- 3 orphan: `TS-15`, `TS-16`, `TS-17` (tests for non-declared goals)

Confirms audit findings: Phase 10 had real goal-test traceability gaps that would've been caught if gates weren't bypassed via recovery.

## [1.13.0] - 2026-04-19

Major workflow upgrade: adaptive typecheck + generic cache bootstrap + tsgo integration + Utility Contract Layer 2+3 + agent resilience. Hardened via real-run test on RTB apps/web (1157-file TS project) that exposed 807 pre-existing errors previously invisible due to tsc OOM.

### Added (features)

- **Adaptive typecheck strategy** (`_shared/lib/typecheck-light.sh`) — cache-first decision tree: OOM history → narrow; warm → incremental; cold small → incremental direct; cold medium/large → bootstrap first → incremental warm. Auto-selects based on file count + cache presence + OOM history (7-day window). Portable knobs in config: `typecheck_adaptive.{smallThreshold,largeThreshold,heapMB}`.
- **Generic cache bootstrap** (`vg_typecheck_cache_bootstrap`) — 3 strategies auto-selected by detection chain:
  1. **tsgo** — if `@typescript/native-preview` on PATH (Rust re-impl, 10-20x faster, 1/5 RAM). Strategy fires first in both adaptive incremental AND bootstrap paths.
  2. **watch** — spawn `tsc -w` background, poll for `.tsbuildinfo` write every 5s, Windows `_vg_kill_tree` cleanup.
  3. **chunked** — split tsconfig.include into N-file chunks with auto-fit (÷4 when total ≤ original chunk_size).
  Portable via `templates/vg/vg.config.template.md` new `typecheck_adaptive:` section.
- **`/vg:extract-utils` command** — one-shot duplicate helper extraction. Modes: `--scan` (default read-only), `--extract <name>`, `--interactive` (multi-select), `--all`. Reads canonical package from PROJECT.md Shared Utility Contract table, extracts atomically with per-commit rollback on typecheck fail.
- **Utility Contract System Layer 2+3** — prevents new duplicates:
  - Layer 2a: `/vg:scope` Round 2 utility classifier (REUSE/EXTEND/NEW)
  - Layer 2b: `scripts/verify-utility-reuse.py` blueprint gate (BLOCKs if task redeclares contract name)
  - Layer 3a: executor grep-before-declare rule in `vg-executor-rules.md`
  - Layer 3b: `scripts/verify-utility-duplication.py` post-wave scan (AST, weighted .ts/.tsx*3, skips handle*/on*/render* prefixes)
- **Agent resilience M2+M3** — `build-progress.sh` self-register (agents check `.build-progress.json` + self-call start if missing) + stuck-agent detection (>600s in-flight OR >120s critical section).
- **H3 @deferred test markers** — `scripts/scan-deferred-tests.py` parses `it.skip('TS-XX ...', () => { // @deferred reason })` in 4 variants → appends "Deferred tests" section to GOAL-COVERAGE-MATRIX.md so tests marked deferred don't silently drop goals.

### Fixed (gaps)

- **H1 integrity auto-run post-wave** — `verify-wave-integrity.py` now invoked automatically at build step 0c (previously had to be run manually).
- **H2 wave override → OVERRIDE-DEBT register** — 6 new call sites log overrides (attribution, integrity, hard-gate, final-unit-suite, regression, missing-summaries). Audit trail for every skip decision.
- **L1 plan package-scope check** — `scripts/verify-plan-paths.py` greps PLAN for `@scope/name`, cross-refs repo package.json, flags mismatches with nearest-match suggestions.
- **L2 registration list expansion** — `scripts/verify-commit-attribution.py` REGISTRATION_FILENAMES extended: routes.ts, plugins.ts, schema.ts, types.ts, api.rs, routes.rs, handlers.rs, main.go, main.py.
- **Cache bootstrap hardening** — caught in real run:
  - Windows orphan `tsc -w` process (15GB RAM) — `kill $!` hit npx wrapper not grandchild. Fix: `_vg_kill_tree` using `taskkill //F //PID` scanning node.exe >2GB.
  - Chunked degenerate case: 381 files with chunk=400 = 1 chunk = OOM. Fix: auto-fit `(total + 3) / 4` when total ≤ original chunk_size.
  - OOM detection gap: rc 134/137 in chunked loop not recognized → never logged. Fix: explicit rc check per chunk, append to `.tsbuildinfo-oom-log`.

### Real-run validation

Battle-tested on RTB apps/web:
- Before: tsc cold OOM forever at 32GB heap, narrow-mode only saw 10 errors.
- After: tsgo cold ~2min (48GB peak, writes .tsbuildinfo), **warm 1 second full type check**, exposed 807 real errors (previously invisible tech debt).
- Zero config change beyond 2 tsconfig lines (remove baseUrl, prefix paths with `./`).
- Backward compat with tsc 5.9 verified.

### Install hint for VG projects

`npm install -g @typescript/native-preview` — workflow auto-detects via `_vg_cache_detect_tsgo`. Template config lists tsgo as preferred strategy out of the box.

## [1.12.6] - 2026-04-18

### Fixed (config audit stop-gap)
- **Patched 10 missing config fields** workflow reads but `/vg:project` doesn't generate. Without these, dotted notation `${config.X.Y}` returns empty string in awk parser → silent fallback to defaults that may not match user environment. Added with sensible defaults:
  - `db_name`, `dev_failure_log_tail`, `dev_failure_patterns`, `dev_os_limits`, `dev_process_markers` (dev-server startup detection)
  - `error_response_shape` (flat alias for skills not using `contract_format.` prefix)
  - `i18n.{enabled,default_locale,key_function,locale_dir}` (translation key extraction)
  - `ports.database` (flat alias for worktree_ports)
  - `rationalization_guard.model` (gate-skip subagent model)
  - `surfaces.web` (multi-surface routing default — single-surface fallback)

### Audit doc
`.vg/CONFIG-AUDIT.md` — full analysis: 44 keys workflow READS vs 43 keys current config WRITES. Diff shows 11 read-but-missing (10 real + 1 false positive `template.md` = file path).

### Planned for v1.13.0
- **Template-based config generation** — `/vg:project` reads `vgflow/vg.config.template.md` (754 lines, full schema) as source-of-truth, substitutes only foundation-derived fields. Replaces current placeholder heredoc + 12-row derivation table that covers ~25% of schema. Result: 100% schema coverage on fresh project init.

### User-reported issue
"file config của vg nhiều thông số thế, khi chạy project xong, nó có tạo đủ field không, hay lại lỗi" — confirmed: project skill at line 887-892 uses placeholder `# Write ...` heredoc with no concrete schema, relies on AI to derive from 12 rules covering ~25% of fields. Stop-gap patches current project + plan v1.13.0 fix.

## [1.12.5] - 2026-04-18

### Fixed (graphify integrity audit)
- **BUG #1: blueprint 2a5 missing --graphify-graph flag** — `build-caller-graph.py` was called without graphify, falling back to grep-only (misses path-alias imports like `@/hooks/X`, misses cross-monorepo callers). Now passes `--graphify-graph $GRAPHIFY_GRAPH_PATH` when active + warns if enrichment unexpectedly fails.
- **BUG #2: blueprint never auto-rebuilt graphify** — only `/vg:build` did. Planner planned against stale graph (we observed 46h / 140 commits stale at audit) → references symbols that no longer exist. Now mirrors build's auto-rebuild block at start of step 2a (before planner spawn).
- **BUG #3: review Phase 1.5 ripple ran on stale graph** — no rebuild check before ripple analysis → false "0 callers affected" verdicts. Now always rebuilds before ripple (review = safety net, must be accurate).
- **BUG #4: stale warning was fire-and-forget** — `echo "⚠ Graph stale"` only, no telemetry, no block. Now emits `graphify_stale_detected` telemetry event + adds `graphify.block_on_stale: false` config knob (opt-in fail-closed mode).

### Added
- **graphify_auto_rebuild telemetry event** — emitted by blueprint step 2a + review Phase 1.5 when auto-rebuild fires. Consumable by `/vg:health` and `/vg:telemetry`.
- **graphify.block_on_stale config knob** — when `true`, config-loader exits 1 if graph stale (commits_since > staleness_warn_commits). Default `false` for backward compat.

### Audit doc
`.vg/GRAPHIFY-AUDIT.md` — full per-consumer audit (build / blueprint / review / accept / scope / migrate) with severity-ranked fix priority. Surfaces 6 issues remaining as MED/LOW priority for v1.12.6+:
- GAP: scope round 2 (technical) doesn't query graph for module impact
- GAP: /vg:health doesn't surface graphify staleness section
- LOW: planner-rules.md should require `<edits-*>` annotations on every code-touching task (Phase 13 retro: 22 tasks, only 3 had edits annotations → 19 tasks had zero blast-radius coverage)

### User-reported issue
"dữ liệu graphify thì bị out date, rất nguy hiểm" — confirmed: graph was 46 hours / 140 commits stale during phase 13 blueprint, planner had no graphify context at all (just grep). All 4 critical+high fixes patch the silent-staleness anti-pattern.

## [1.12.4] - 2026-04-18

### Added
- **review: VERDICT-AWARE next-steps block (mandatory)** — `/vg:review` close-out message MUST include verdict-specific actionable commands (PASS / FLAG / BLOCK paths). Per-finding format MUST be `[Severity] one-line + ↳ Fix + ↳ Verify + ↳ Refs`. Closing MUST list 2+ labeled options (A/B/C: re-review after fix / amend scope / fix infra / dispute verdict).
- **review: Hard rules for AI orchestrator (Claude/Codex/Gemini)** — never end BLOCK without per-finding fixes. Use RELATIVE paths in narration (absolute paths waste 60% terminal width). Surface "executor cannot run X" failures explicitly, not buried.

Reason: user reported Codex /vg:review output for Phase 08 listed 7 BLOCK findings + wrote 2 artifact files but had NO actionable next steps — just bare list. User had to re-derive what to fix and how. Closing message now mandates concrete commands per finding + per-verdict routing.

Source: vietdev99/vgflow user feedback (image-cache attachment, session 2026-04-18)
## [1.12.3] - 2026-04-18

### Fixed (bug-reporter delivery)
- **bug-reporter: gh CLI hard requirement** — removed misleading URL fallback. Previously when labels missing or gh auth failing, bug-reporter generated a github.com/issues/new URL and marked the bug as "sent" in cache. Result: bugs never reached GitHub but appeared delivered. Now: gh missing → consent prompt auto-disables bug_reporting + recommends install. gh present + create fails → bug stays in queue (not silently lost).
- **bug-reporter: auto-create labels** — `bug_reporter_ensure_labels` creates `bug-auto`/`needs-triage` labels on first issue create failure (404 label not found), then retries.
- **bug-reporter: report_bug arg-shape guard** — validates severity arg against `info|minor|medium|high|critical` enum + warns on non-standard type. Previously: arg-order swap silently passed long context as severity → `_severity_gte` failed → bug queued never sent. Reported as issue #7 (sig 3aba6b9d).
- **bug-reporter: `report_bug` doc comments** — clarified positional arg semantics with examples of correct vs wrong call patterns.

### Added
- **blueprint: Recommended-pattern requirement** — when escalating CrossAI concerns to user via AskUserQuestion, orchestrator MUST present recommended option first with " (Recommended)" suffix + WHY explanation in description. Stops "list 3 options, force user to re-derive analysis CrossAI just did" anti-pattern.

### Bug telemetry
Self-reported bugs from this session (vietdev99/vgflow):
- #3 install-missing-lib (sig 68724e27, v1.11.1)
- #4 vg-still-uses-planning-not-vg (sig ee869e02, v1.12.1)
- #6 config-paths-missing-parent (sig f993b787, v1.12.2)
- #7 report-bug-api-misuse-orchestrator (sig 3aba6b9d, v1.12.2)
- #9 bug-reporter-labels-not-auto-created (sig ba0c86e9, v1.12.2)

All notable changes to VG workflow documented here. Format follows [Keep a Changelog](https://keepachangelog.com/), adheres to [SemVer](https://semver.org/).

## [1.11.0] - 2026-04-18

### R5 — Auto Bug Reporting + Codex skills full sync (31 missing skills generated)

**Motivation 1:** User feedback: "có cách nào để chúng ta phát triển hệ thống tự phát hiện lỗi của workflow, và đẩy về git issue được không nhỉ" — distributed bug collection. When other users run VG on different projects/envs, AI-detected bugs (like dim-expander schema bug found in v1.10.0 live test) auto-report to vietdev99/vgflow GitHub issues.

**Motivation 2:** "cập nhật vào codex skill cho tôi nhé, hình như chưa cập nhật đâu" — codex-skills folder lagged: only 5 skills (accept/next/progress/review/test). Missing 31 commands including ALL v1.9-v1.10 features.

### Features

**1. `/vg:bug-report` command** — lifecycle (flush/queue/disable/enable/stats/test)

**2. `bug-reporter.sh` lib** (~370 LOC, 15 functions):
- Consent flow + 3-tier send (gh CLI → URL fallback → silent queue)
- Generic event reporting + bug + telemetry types
- Schema validators for dim-expander + answer-challenger output
- User pushback detector (keywords: nhầm/sai/bug/wrong/không đúng)
- Redaction (paths/project name/emails/phase IDs)
- Dedup (local cache + GitHub issue search)
- Rate limit (max 5 events/session)
- Auto-assign vietdev99 + label `bug-auto`/`needs-triage`

**3. Install/update tracing** — `install.sh` prompts consent at end, writes config block, sends `install_success` event

**4. Detection types (broader scope)**:
- `schema_violation` — JSON output mismatch
- `helper_error` — bash exit ≠ 0 (v1.11.1 trap ERR integration)
- `user_pushback` — AskUserQuestion answer keywords
- `gate_loop` — challenger/expander max_rounds (v1.11.2)
- `ai_inconsistency` — same input → different output (v1.11.2)

**5. Privacy** — opt-out default + auto-redact PII before upload:
- `D:/.../RTB/...` → `{project_path}/...`
- "VollxSSP" → `<project-name>`
- `phase-13-dsp-...` → `phase-{id}`
- email → `<email>`

### Codex skills full sync

**`scripts/generate-codex-skills.sh`** — auto-generates `codex-skills/vg-X/SKILL.md` from `commands/vg/X.md`:
- Wraps with `<codex_skill_adapter>` prelude (Claude→Codex tool mapping)
- Run: `bash scripts/generate-codex-skills.sh [--force]`

**Generated 31 skills** (was 5, now 36 total):
add-phase, amend, blueprint, bug-report, build, design-extract, design-system, doctor, gate-stats, health, init, integrity, map, migrate, override-resolve, phase, prioritize, project, reapply-patches, recover, regression, remove-phase, roadmap, scope, scope-review, security-audit-milestone, setup-mobile, specs, sync, telemetry, update.

Deployed to `~/.codex/skills/` (global) + project `.codex/skills/` via `vgflow/sync.sh`.

### Files

- **NEW** `commands/vg/bug-report.md`
- **NEW** `commands/vg/_shared/lib/bug-reporter.sh` (~370 LOC, 15 functions)
- **NEW** `scripts/generate-codex-skills.sh`
- **NEW** `codex-skills/vg-{31 dirs}/SKILL.md`
- **MODIFIED** `install.sh` — consent prompt + config block + install event
- **BUMP** `VERSION` 1.10.1 → 1.11.0

### Migration

Existing projects:
- Run `/vg:bug-report` to trigger consent prompt + populate config
- Or manually add `bug_reporting:` block

Re-installs:
- `install.sh` prompts consent at install end
- Default opt-IN, easy disable: `/vg:bug-report --disable-all`

### Known Limitations (defer v1.11.x)

- Helper error trap auto-integration (v1.11.1)
- AI orchestrator inline pushback detection prompts (v1.11.2)
- Telemetry weekly batch aggregator (v1.12.0)

## [1.10.0] - 2026-04-18

### R4 — Design System integration + Multi-surface project support

**Motivation:** UI của các phase hay bị drift — mỗi phase AI tự ý pick tokens/colors/fonts khác nhau → inconsistent look across project. User request: tích hợp [getdesign.md](https://getdesign.md/) ecosystem (58 brand DESIGN.md variants) để chuẩn hoá UI theo design system chọn.

Phát sinh thêm requirement trong discussion:
1. **Multi-design** — project có nhiều role (SSP Admin, DSP Admin, Publisher, Advertiser) có thể có design khác nhau
2. **Multi-surface** — 1 dự án có cả webserver + webclient + iOS + Android, workflow cần phân biệt phase theo surface

### Features

**1. `/vg:design-system` command (NEW)**

Lifecycle management for DESIGN.md files:
- `--browse` — list 58 brands grouped into 9 categories (AI/LLM, DevTools, Backend, Productivity, Design, Fintech, E-commerce, Media, Automotive)
- `--import <brand> [--role=<name>]` — download brand DESIGN.md to project/role location
- `--create [--role=<name>]` — guided discussion to build custom DESIGN.md (8 questions: personality, primary color, typography, radius, shadow, spacing, motion, component style)
- `--view [--role=<name>]` — print current DESIGN.md (resolved by priority)
- `--edit [--role=<name>]` — open in $EDITOR
- `--validate [--scan=<path>]` — check code hex codes vs DESIGN.md palette, report drift

**2. Multi-design resolution (4-tier priority)**

```
1. Phase-level:    .planning/phases/XX/DESIGN.md   ← highest priority
2. Role-level:     .planning/design/{role}/DESIGN.md
3. Project default: .planning/design/DESIGN.md
4. None:           scope Round 4 prompts user to pick/import/create
```

Helper `design_system_resolve PHASE_DIR ROLE` returns applicable path, respecting priority.

**3. Multi-surface project config**

New `surfaces:` block in vg.config.md for projects với nhiều platform:

```yaml
surfaces:
  api:     { type: "web-backend-only",  stack: "fastify", paths: ["apps/api"] }
  web:     { type: "web-frontend-only", stack: "react",   paths: ["apps/web"],
             design: "default" }
  ios:     { type: "mobile-native-ios", stack: "swift",   paths: ["apps/ios"],
             design: "ios-native" }
  android: { type: "mobile-native-android", stack: "kotlin", paths: ["apps/android"],
             design: "android-native" }
```

Scope Round 2 new gate: if `surfaces:` declared → user multi-select which surfaces phase touches. Lock as `P{phase}.D-surfaces: [web, api]` decision. Design resolution picks design from surface's `design:` field.

**4. Scope Round 4 integration**

Before asking UI questions:
```bash
source design-system.sh
DESIGN_RESOLVED=$(design_system_resolve "$PHASE_DIR" "$SURFACE_ROLE")
```

- **Resolved** → inject DESIGN.md content into Round 4 AskUserQuestion. User pages/components follow palette + typography + spacing
- **Not resolved** → offer 3 options:
  1. Pick from 58 brands
  2. Import existing
  3. Create from scratch
  4. Skip (flag as "design-debt")

**5. Build integration (enabled via config `inject_on_build: true`)**

`/vg:build` detects UI tasks → injects resolved DESIGN.md into task prompt. Agent must respect palette — commit body cites "Per DESIGN.md Section 2 — Primary Purple #533afd".

**6. Review Phase 2.5 integration (enabled via `validate_on_review: true`)**

`design_system_validate_tokens` scans `apps/web/src` for hex codes, compares against DESIGN.md palette, reports drift (code uses color not in palette). Non-blocking warn.

### Dimension-expander cap fix (v1.9.6 observation)

**Problem:** During live v1.9.5 test, dimension-expander generated 6-10 critical items per round → user fatigue risk for full 5-round scope + deep probe.

**Fix:** Prompt updated with explicit CAP RULE:
> Cap critical_missing at MAX 4 items. Pick the 4 MOST impactful ship-blockers. Push others to nice_to_have_missing. Rationale: avoid decision fatigue.

Verified during live scope Round 4 test — Opus respected cap (4 critical + 11 nice-to-have vs earlier 10+ critical unbounded).

### Source: Meliwat/awesome-design-md-pre-paywall

Official `VoltAgent/awesome-design-md` (getdesign.md) moved content behind paywall. Workflow defaults to `Meliwat/awesome-design-md-pre-paywall` fork (free, 58 brands snapshot pre-2026-04). User can override `config.design_system.source_repo` to use official or custom fork.

### Files

- **NEW** `commands/vg/design-system.md` (256 LOC) — lifecycle command
- **NEW** `commands/vg/_shared/lib/design-system.sh` (250 LOC) — 8 functions (resolve/browse/fetch/list_roles/inject_context/validate_tokens/browse_grouped/enabled)
- **MODIFIED** `commands/vg/scope.md` — Round 2 multi-surface gate + Round 4 DESIGN.md injection
- **MODIFIED** `commands/vg/_shared/lib/dimension-expander.sh` — prompt CAP RULE
- **MODIFIED** `vg.config.template.md` — `surfaces:` + `design_system:` + `review.scanner_spawn_mode` blocks
- **BUMP** `VERSION` 1.9.5 → 1.10.0 (minor bump — new feature)

### Migration

Auto via `/vg:update` (3-way merge). Existing projects without multi-surface will keep `profile:` single-value behavior. Projects adopting design system:
1. Run `/vg:design-system --browse` to see brands
2. Pick brand: `/vg:design-system --import linear`
3. Existing phases automatically detect `.planning/design/DESIGN.md` on next `/vg:scope` run

### Example workflow

```bash
# Multi-role project (VollxSSP-style with 4 dashboards)
/vg:design-system --import stripe --role=ssp-admin       # SSP Admin → Stripe
/vg:design-system --import linear --role=dsp-admin       # DSP Admin → Linear
/vg:design-system --import notion --role=publisher       # Publisher → Notion
/vg:design-system --import vercel --role=advertiser      # Advertiser → Vercel

# Multi-platform project (web + mobile)
# Edit vg.config.md to declare surfaces with design mapping
# Scope each phase picks correct DESIGN.md based on surface/role
```

## [1.9.5] - 2026-04-18

### R3.4 — Subagent sandbox isolation fix (BUG phát hiện qua live test v1.9.3)

**Bug:** Khi test v1.9.3 adversarial challenger + dimension expander trong `/vg:scope 13`, phát hiện rằng Task subagents (spawned qua Agent tool) có **sandbox isolation** — không đọc được `/tmp` files của parent process. Workflow v1.9.3 documented pattern: "helper writes prompt to /tmp, orchestrator reads path, passes path to Task tool". Subagent receives path nhưng không thể đọc file → fail với "Prompt file not found".

**Impact:** Cả 2 v1.9.3 features (8-lens adversarial + dimension-expander) không hoạt động nếu orchestrator follow documented pattern literally. Workaround: orchestrator phải đọc file content via Read tool FIRST, then pass content inline. Nhưng docs không nói rõ step này → dev sẽ fail khi dispatch Task với path.

### Fix

**answer-challenger.sh + dimension-expander.sh — emit prompt CONTENT on fd 3 (không phải path):**

Helper vẫn write tmp file (để audit/debug), nhưng fd 3 giờ emit FULL PROMPT CONTENT thay vì path:

```bash
# Before (v1.9.3):
echo "$prompt_path" >&3

# After (v1.9.5):
cat "$prompt_path" >&3
```

Orchestrator pattern đổi từ:
```bash
# OLD (broken)
PATH=$(challenge_answer ... 3>&1 1>/dev/null)
# Then: Read file at PATH, pass to Agent
```

Sang:
```bash
# NEW (works)
PROMPT=$(challenge_answer "$answer" "$round" "$scope" "$acc" 3>&1 1>/dev/null 2>/dev/null)
# $PROMPT = full inline content, pass directly to Agent(prompt=$PROMPT)
```

**scope.md docs updated:** Explicit bash pattern + explanation "subagent sandbox can't read /tmp" + thay tất cả "Read the prompt file" references bằng "Capture fd 3 via pattern".

### Test verification

```bash
source answer-challenger.sh
PROMPT=$(challenge_answer "test" "r1" "phase-scope" "acc" 3>&1 1>/dev/null 2>/dev/null)
echo "${#PROMPT}"  # → 6473 chars (full prompt content)
echo "${PROMPT:0:80}"  # → "You are an Adversarial Answer Challenger. You have ZERO context..."

source dimension-expander.sh
PROMPT=$(expand_dimensions "1" "Domain" "acc" ".planning/FOUNDATION.md" 3>&1 1>/dev/null 2>/dev/null)
echo "${#PROMPT}"  # → 6010 chars
```

### Files

- **MODIFIED** `commands/vg/_shared/lib/answer-challenger.sh` — fd 3 emits CONTENT via `cat "$prompt_path" >&3` (was path)
- **MODIFIED** `commands/vg/_shared/lib/dimension-expander.sh` — same pattern
- **MODIFIED** `commands/vg/scope.md` — updated orchestrator instructions with explicit bash capture pattern + subagent sandbox explanation
- **BUMP** `VERSION` 1.9.4 → 1.9.5

### Migration

Auto via `/vg:update` (3-way merge). Projects với custom scope orchestration phải update pattern từ path-based sang content-based. Recommend re-read updated scope.md.

### Lesson learned

**Test v1.9.3 features end-to-end là cần thiết.** Unit test passing không đảm bảo orchestration pattern works trong real Claude Code harness. Live scope test phát hiện bug ngay round 2 — shipped v1.9.5 trong 15 min sau phát hiện.

## [1.9.4] - 2026-04-18

### R3.3 — Scanner spawn mode (mobile sequential gate) + README rewrite

**Problem:** `/vg:review` Phase 2b-2 luôn spawn N Haiku scanner agents parallel (1 per view). Với mobile apps (iOS simulator, Android emulator, physical device), chỉ có ONE instance chạy được tại một thời điểm — parallel spawn gây state corruption / crash / conflicting app state. Với CLI/library projects, spawn UI scan là waste hoàn toàn (không có UI).

**Fix: `review.scanner_spawn_mode` config — 4 modes:**

| Mode         | Behavior                                              | Use case                         |
|--------------|-------------------------------------------------------|----------------------------------|
| `auto`       | Derive từ profile (default)                           | Let workflow decide              |
| `parallel`   | Tất cả Agent() calls trong ONE tool_use block        | web-* (multi-browser contexts)   |
| `sequential` | Mỗi Agent() call trong SEPARATE message, await each  | mobile-* (single-emulator/device)|
| `none`       | Skip entire spawn loop, write empty scan-manifest    | cli-tool, library (no UI)        |

**Auto-derivation logic (profile → mode):**
- `mobile-rn` / `mobile-flutter` / `mobile-native-ios` / `mobile-native-android` / `mobile-hybrid` → **sequential**
- `cli-tool` / `library` → **none**
- `web-fullstack` / `web-frontend-only` / `web-backend-only` / default → **parallel**

Override: user set `scanner_spawn_mode: "sequential"` force serialize even on web (e.g., CI with constrained browser resources).

**Narration updated:**
- `parallel`: "🌐 Parallel mode — up to 5 Haiku agents concurrent"
- `sequential`: "📱 Sequential mode — 1 Haiku agent at a time (mobile/single-window constraint). Tổng N view sẽ scan tuần tự"
- `none`: "⏭  Spawn mode=none — skipping Phase 2b-2 entirely (profile has no UI scan). Backend goals resolved via surface probes in Phase 4a instead."

### README rewrite — heavy-workflow positioning

Both `README.md` và `README.vi.md` được rewrite để phản ánh đúng vị thế của VGFlow:

- **Heavy AI Workflow** banner — không phải "hỏi AI sửa file", mà pipeline production-grade
- **Supported project types** clear: Web apps / Web servers / CLI tools / Mobile apps (RN/Flutter/native)
- **Token cost transparency**: `/vg:scope` $0.15-0.30, `/vg:build` $0.50-2.00, `/vg:review` $0.30-0.80, `/vg:test` $0.20-0.50
- **When VGFlow shine / KHÔNG phù hợp** sections — honest positioning
- **14 power features** detail:
  1. Multi-tier AI Orchestration (Opus/Sonnet/Haiku)
  2. CrossAI N-reviewer Consensus (Claude/Codex GPT/Gemini)
  3. Contract-Aware Wave Parallel Execution
  4. Goal-Backward Verification với Weighted Gates
  5. 8-Lens Adversarial Scope + Dimension Expander (v1.9.3)
  6. Phase Profile System (6 types)
  7. Block Resolver 4 Levels (L1→L4)
  8. Live Browser Discovery (MCP Playwright) — mobile-aware
  9. 3-Way Git Merge Updates
  10. SHA256 Artifact Manifest + Atomic Commits
  11. Structured Telemetry + Override Debt Register
  12. Rationalization Guard (anti-corner-cutting)
  13. Visual Regression + Security Register (STRIDE+OWASP)
  14. Foundation Drift Detection + Incremental Graphify

### Files

- **MODIFIED** `commands/vg/review.md` — SPAWN_MODE_RESOLUTION block + branch logic (parallel/sequential/none) + SPAWN_MODE aware Limits section
- **MODIFIED** `vg.config.template.md` — `review.scanner_spawn_mode: "auto"` key added
- **REWRITE** `README.md` — heavy workflow positioning, 14-feature highlight, mobile/cli support section
- **REWRITE** `README.vi.md` — mirror of English rewrite, Vietnamese translation
- **BUMP** `VERSION` 1.9.3 → 1.9.4

### Migration

Auto via `/vg:update` (3-way merge). Existing `review:` section in user config gets `scanner_spawn_mode` key added to new block; existing `fix_routing` block preserved. Fresh install defaults to `auto` which is safe for all profiles.

## [1.9.3] - 2026-04-18

### R3.2 — Scope Adversarial Upgrade + Dimension Expander

**Problem:** v1.9.1 R3 shipped `answer-challenger` với default model `haiku`. User phản hồi: scope là nơi tìm gap + critique, cần reasoning cao nhất mới phát hiện được gap thật (security threat, failure mode, integration break). Haiku reasoning depth không đủ → challenges nông, dễ miss.

**Problem 2:** Challenger trả lời câu hỏi "is this answer wrong?" nhưng thiếu câu hỏi quan trọng khác: "what haven't we discussed yet?". Proactive dimension expansion bị miss — user phải tự nhớ hỏi security/perf/failure mode cho mỗi round.

### 2 fixes shipped cùng release

**Fix A: answer-challenger — Haiku → Opus + 4→8 lenses**

- Default `scope.adversarial_model`: `haiku` → `opus` (user có thể override về haiku nếu quota căng)
- Prompt mở rộng từ 4 → 8 lenses:
  - L1 Contradiction (giữ)
  - L2 Hidden assumption (giữ)
  - L3 Edge case (giữ)
  - L4 Foundation conflict (giữ)
  - **L5 Security threat NEW** — auth/authz bypass, data leak, injection, CSRF, rate-limit bypass
  - **L6 Performance budget NEW** — unbounded query, blocking call, cache miss cost, p95 latency
  - **L7 Failure mode NEW** — idempotency, timeout, circuit breaker, partial failure, poison message, retry storm
  - **L8 Integration chain NEW** — downstream caller contract, upstream dep guarantee, webhook retry, data contract, schema migration
- Priority order when multiple fire: Security > Failure > Contradiction > Foundation > Integration > Edge > Hidden > Performance
- `issue_kind` enum mở rộng: `security | performance | failure_mode | integration_chain` (ngoài 4 cũ)
- Dispatcher narration Vietnamese cho 4 kind mới (bảo mật/perf budget/failure mode/integration chain)

**Fix B: dimension-expander NEW — proactive per-round gap finding**

NEW `_shared/lib/dimension-expander.sh` (~350 LOC, `bash -n` clean):

- Trigger: END của mỗi round (1-5 + deep probe) sau khi Q&A + adversarial challenges complete
- Model: Opus (config `scope.dimension_expand_model`, default `opus`)
- Prompt: zero-context subagent nhận ROUND_TOPIC + accumulated answers + FOUNDATION → tự derive 8-12 dimensions cho topic → classify ADDRESSED/PARTIAL/MISSING → phân loại CRITICAL vs NICE-TO-HAVE
- Output JSON: `dimensions_total`, `dimensions_addressed`, `critical_missing[]`, `nice_to_have_missing[]`
- Dispatcher: narrate gaps trong VN, AskUserQuestion 3 options (Address/Acknowledge/Defer), telemetry event `scope_dimension_expanded`
- Loop guard: `dimension_expand_max: 6` (5 rounds + 1 deep probe)
- **Complementary, not redundant** với answer-challenger:
  - Challenger: per-answer, "is this specific answer wrong?"
  - Expander: per-round, "what dimensions haven't we discussed?"

### Config changes

Thêm vào `scope:` section:
```yaml
scope:
  adversarial_model: "opus"              # was "haiku"
  dimension_expand_check: true           # NEW master switch
  dimension_expand_model: "opus"         # NEW
  dimension_expand_max: 6                # NEW loop guard
```

Thêm `review:` section (v1.9.1 R2 đã có trong code nhưng config chưa):
```yaml
review:
  fix_routing:
    inline_threshold_loc: 20
    spawn_threshold_loc: 150
    escalate_threshold_loc: 500
    escalate_on_contract_change: true
    escalate_on_critical_domain: true
    max_iterations: 3
```

### Cost impact

Scope cost tăng ~20x (Haiku → Opus cho answer-challenger) + ~$0.03/round cho dimension-expander.
Estimated: $0.15-0.30/phase scope (vs $0.01 trước). Acceptable vì scope là decision-critical step.
Override: user set `adversarial_model: "haiku"` hoặc `adversarial_check: false` để về cost cũ.

### Files

- **MODIFIED** `_shared/lib/answer-challenger.sh` — default model + 8-lens prompt + 4 new issue_kind
- **NEW** `_shared/lib/dimension-expander.sh` (~350 LOC) — per-round gap-finding subagent protocol
- **MODIFIED** `commands/vg/scope.md` — dimension-expander hook in `<process>` header + per-round narration
- **MODIFIED** `vg.config.template.md` — scope section rewrite + review section NEW

### Migration

Auto via `/vg:update` (3-way merge). User keeping custom `adversarial_model: "haiku"` sẽ stay (config preservation).
Fresh install gets Opus default. `dimension_expand_check: true` enabled by default — set `false` to disable completely.

## [1.9.2.6] - 2026-04-18

### 2 bugs dò được qua 9 smoke tests — shipped

**Bug #1: unreachable-triage extraction missed in v1.9.0 T3**

v1.9.0 T3 extracted bash from 4 shared libs (artifact-manifest, telemetry, override-debt, foundation-drift) to `lib/*.sh` NHƯNG MISSED `unreachable-triage.md`. `review.md:2948` calls `triage_unreachable_goals()` WITHOUT source statement → function undefined → silent skip → UNREACHABLE goals never classified → `/vg:accept` hard-gate can't enforce `bug-this-phase` / `cross-phase-pending`.

Fix: NEW `_shared/lib/unreachable-triage.sh` (~362 LOC) with both functions (`triage_unreachable_goals` + `unreachable_triage_accept_gate`). Patched `review.md` step `unreachable_triage` to source + invoke.

**Bug #2: v1.9.x config drift undetected**

v1.9.0-v1.9.2 added 6 new config sections (`review.fix_routing`, `phase_profiles`, `test_strategy`, `scope`, `models.review_fix_inline`, `models.review_fix_spawn`) nhưng workflow không check user config có những sections này chưa. Projects update v1.9.x via `/vg:update` nhận .sh/.md mới nhưng `vg.config.md` vẫn ở schema cũ → workflow fallback silent → features như 3-tier fix routing không hoạt động.

Fix: `config-loader.md` thêm schema drift detection — scan vg.config.md cho 6 sections v1.9.x. Missing → WARN với tên section + purpose + impact + fix command (`/vg:init` hoặc manual add từ template).

### Smoke test results (9 areas tested)

| Area | Verdict |
|------|---------|
| Phase 0 session + profile | ✅ |
| Phase 1 code scan | ✅ |
| Phase 3 fix routing config | ⚠️ drift detected → fix #2 |
| Phase 4b code_exists fallback | ✅ |
| unreachable_triage helper | 🐛 extraction missed → fix #1 |
| Block resolver L2 architect fd3 | ✅ pattern OK |
| vg-haiku-scanner skill | ✅ present |
| Playwright lock manager | ✅ claim+release clean |
| env-commands.md | ⚠️ documented convention (not bug) |

### Files

- **NEW** `_shared/lib/unreachable-triage.sh` (362 LOC, `bash -n` clean)
- **MODIFIED** `review.md` step `unreachable_triage` — source helper, graceful fallback
- **MODIFIED** `_shared/config-loader.md` — CONFIG DRIFT scan block emits WARN for each missing v1.9.x section

### Migration v1.9.2.5 → v1.9.2.6

- Review unreachable triage: transparent — was silent-skipping before, now runs real classification
- Config drift: warns on next command. User runs `/vg:init` to regenerate OR manually adds sections from `vg.config.template.md`. No block — fallback safe.

## [1.9.2.5] - 2026-04-18

### probe_api substring match — eliminate false BLOCKED

**Bug discovered live running review 7.12 Phase 4d with v1.9.2.4 matrix:**

Phase 7.12 GOAL-COVERAGE-MATRIX showed 15 BLOCKED for API goals. Spot check G-02:

```
G-02 BLOCKED | no_handler_for:POST /conversion-goals
```

But the handler EXISTS:
```
apps/api/src/modules/conversion/conversion.plugin.ts:21:
  await fastify.register(conversionRoutes(service), { prefix: '/api/v1/conversion-goals' })
```

Root cause: probe_api extracted `tail -1` path fragment → `/conversion-goals`. Then grepped `['"\\`]/conversion-goals['"\\`]` — required fragment as standalone quoted string. But code has `'/api/v1/conversion-goals'` — fragment in middle of longer literal → no match → false BLOCKED.

### Fix — 2-tier fragment + substring match

Try full path first, then last segment as fallback. Grep pattern allows substring within quoted literal: `['"\\`][^'"\\`]*${frag}[^'"\\`]*['"\\`]`

### Phase 7.12 live result (v1.9.2.4 → v1.9.2.5)

| Metric | v1.9.2.4 | v1.9.2.5 |
|--------|----------|----------|
| READY | 10 | **24** |
| BLOCKED | 15 | **1** |
| NOT_SCANNED | 14 | 14 |

14 previously-false BLOCKED → correctly READY with evidence. Only 1 genuine BLOCKED remains. 14 NOT_SCANNED = 6 UI goals (need browser) + 8 probe-unparseable criteria.

Priority pass %:
- critical: 8/12 (66.7%) — need browser for 4 UI goals
- important: 14/20 (70%) — need browser for 2 UI + fix 4 probe-unparseable
- nice-to-have: 2/7 (28.6%) — mostly UI + unparseable

### Migration v1.9.2.4 → v1.9.2.5

Transparent. Re-run `/vg:review` on phases with previous false BLOCKED → now mostly READY.

## [1.9.2.4] - 2026-04-18

### Phase 4b/4d matrix merger runnable

**Gap discovered post-v1.9.2.3:** v1.9.2.3 added surface probe execution in Phase 4a (writes `.surface-probe-results.json`). But Phase 4b/4d "integration" was prose-only — no runnable bash to merge RUNTIME-MAP.goal_sequences + probe-results → unified GOAL-COVERAGE-MATRIX.md.

Result: even after probes ran, backend goals fell back to NOT_SCANNED because matrix generation was pseudo-code template.

### Fix — `_shared/lib/matrix-merger.sh` (new ~150 LOC)

`merge_and_write_matrix(phase_dir, test_goals, runtime_map, probe_results, output_md)`:

**Merge precedence:**
- UI goals (surface=ui/ui-mobile) → RUNTIME-MAP.goal_sequences[gid].result → READY/BLOCKED/FAILED/NOT_SCANNED
- Backend goals (api/data/integration/time-driven) → probe_results[gid].status → READY/BLOCKED/INFRA_PENDING/SKIPPED (SKIPPED maps to NOT_SCANNED)

**Output:** canonical GOAL-COVERAGE-MATRIX.md with:
1. Summary (all 6 statuses counted)
2. By Priority table (critical=100%/important=80%/nice-to-have=50% thresholds + pass % + gate verdict per priority)
3. Goal Details table (each goal with surface + status + evidence)
4. Gate verdict (✅ PASS / ⛔ BLOCK / ⚠️ INTERMEDIATE) with next-action hints

**Verdict logic:** Intermediate (NOT_SCANNED+FAILED>0) → INTERMEDIATE; else any priority under threshold → BLOCK; else PASS.

### Phase 7.12 live result (after v1.9.2.4)

```
VERDICT=INTERMEDIATE
TOTAL=39
READY=10
BLOCKED=15
NOT_SCANNED=14 (6 UI no browser + 8 probe SKIPPED)
```

Priority breakdown:
- critical: 2/12 ready (16.7%) ⛔
- important: 7/20 ready (35.0%) ⛔
- nice-to-have: 1/7 ready (14.3%) ⛔

Each goal row has concrete evidence: `handler=apps/pixel/src/routes/event.route.ts/event`, `migration=infra/clickhouse/migrations/007_conversion_events.sql|table=conversion_events`, etc. No more "??? reason unknown" — users can act on each BLOCKED.

### review.md patch

Phase 4d section replaces prose template with `merge_and_write_matrix` invocation. Exports `$VERDICT $READY $BLOCKED $NOT_SCANNED $INTERMEDIATE` env vars for 4c-pre gate + write-artifacts step.

### Bug fixed during implementation

Priority regex `(\w+)` stopped at dash → "nice-to-have" captured as "nice" → by-priority table showed 0 nice-to-have. Fixed to `(\w[\w-]*)`.

### Migration v1.9.2.3 → v1.9.2.4

Transparent. Review now writes real matrix with real evidence instead of pseudo-template. Legacy phases re-run review to regenerate.

## [1.9.2.3] - 2026-04-17

### Mixed-phase surface probes — fix NOT_SCANNED black hole for backend goals

**Bug discovered running `/vg:review 7.12` post-v1.9.2.2:**

v1.9.1 R1 shipped surface classification (26 api + 6 data + 6 ui + 1 integration goals tagged correctly). v1.9.2 shipped phase profile system. BUT for **mixed phase** (UI + backend goals cùng tồn tại), only pure-backend fast-path (UI_GOAL_COUNT==0) được implement thực sự. Surface probes cho `api/data/integration/time-driven` trong mixed phase chỉ có pseudo-code docs — KHÔNG có bash thực.

**Hệ quả 7.12**:
- 6 UI goals → browser scan cover được
- 33 backend goals → KHÔNG có sequence → rơi vào "NOT_SCANNED" branch
- 4c-pre gate BLOCK với 33 intermediate goals → block_resolve L2 architect
- User bị đẩy vào loop 33 goals "cần resolve trước exit"

### Fix — `_shared/lib/surface-probe.sh` (new ~250 LOC helper)

**4 probe functions**:
- `probe_api(gid, block)` — extract HTTP method + path, grep handler trong `apps/*/src/**` → READY hoặc BLOCKED
- `probe_data(gid, block)` — extract table/collection name (3 strategies: backtick, SQL keyword, bare snake_case fallback) + grep migrations + check `infra_deps` → READY/BLOCKED/INFRA_PENDING
- `probe_integration(gid, block, phase_dir)` — check fixture file OR grep keyword (postback/webhook/kafka/etc) trong source
- `probe_time_driven(gid, block)` — grep cron/setInterval/BullQueue/Agenda registration

**Dispatcher** `run_surface_probe(gid, surface, phase_dir, test_goals_file)` — routes per surface, normalizes CRLF (Windows git-bash bug fix), returns `STATUS|EVIDENCE`.

### Review.md patch

Phase 4a được mở rộng với **"Mixed-phase surface probe execution"** section — chạy probes cho mọi goal surface ≠ ui, ghi `.surface-probe-results.json`. Phase 4b integration: check probe result TRƯỚC khi rơi vào NOT_SCANNED branch.

### Phase 7.12 dry-run results

```
33 backend goals probed:
  READY:         10  ← handler/migration/caller found
  BLOCKED:       15  ← pattern mismatch or missing
  INFRA_PENDING:  0
  SKIPPED:        8  ← can't parse endpoint/table from criteria
```

10 READY > 0 NOT_SCANNED (previous behavior) — probes actually execute. 15 BLOCKED là false-positives do heuristic endpoint extraction chưa handle subdomain paths (`pixel.vollx.com/event`) — future iteration improves.

### Bugs fixed during implementation

1. `awk` reserved word `in` conflict → renamed variable `inside`
2. Windows CRLF (`\r`) from `python -c` output → `tr -d '\r'` normalization in `run_surface_probe`
3. Table identifier extraction too narrow (backtick-only) → 3-tier fallback (backtick → SQL keyword → bare snake_case)

### Known limitations

- Endpoint pattern extraction simple (regex on criteria text) — 15/33 BLOCKED là tune-able
- Config-driven paths hardcoded hiện tại (`apps/api/src`, etc.) — next iteration will read from `config.code_patterns.backend_src`

### Migration v1.9.2.2 → v1.9.2.3

Transparent. Review trên mixed phase tự động chạy probes thay vì mark NOT_SCANNED. Không cần user action.

## [1.9.2.2] - 2026-04-17

### Hotfix — Phase directory lookup with zero-padding

**Bug discovered live while running `/vg:review 7.12`:**

User typed `7.12`. Phase directory is `.planning/phases/07.12-conversion-tracking-pixel/` (zero-padded). Naive glob `ls -d .planning/phases/${PHASE_NUMBER}*` = `ls -d .planning/phases/7.12*` → no match → PHASE_DIR empty → entire review pipeline silent-fails with cryptic generic errors (no "phase not found" message).

Confirmed in 3 runnable sites:
- `review.md:107`
- `test.md:92`
- `build.md:90`

### Fix — `_shared/lib/phase-resolver.sh` (new helper)

`resolve_phase_dir PHASE_NUMBER` — returns directory path, handles:

1. **Exact match with dash suffix**: `07.12-*` (prevents matching sub-phases like `07.12.1-*`)
2. **Zero-pad integer part**: `7.12` → `07.12-*` (fixes the reported bug)
3. **Fallback boundary-aware prefix**: only `-` or `.` as boundary (prevents `99` matching `999.1-*`)
4. **Clear error on miss**: lists available phases + tips

**Verification**:
```
resolve_phase_dir 7.12     → .planning/phases/07.12-conversion-tracking-pixel/  ✓
resolve_phase_dir 07.12    → .planning/phases/07.12-conversion-tracking-pixel/  ✓
resolve_phase_dir 07.12.1  → .planning/phases/07.12.1-pixel-infra-provisioning/ ✓
resolve_phase_dir 99       → stderr error + list, rc=1  ✓
```

### Patched commands

- `commands/vg/review.md` step `00_session_lifecycle`
- `commands/vg/test.md` step `00_session_lifecycle`
- `commands/vg/build.md` step `00_session_lifecycle`

All 3 now source `phase-resolver.sh` and call `resolve_phase_dir`. Fallback to old logic if helper missing (backward-compat).

### Migration v1.9.2.1 → v1.9.2.2

No user action needed. Transparent fix. Users typing phase numbers without zero-padding (`7.12`, `5.3`) will now correctly resolve to padded directories.

### Known limitation

Other 7 files that reference `${PHASE_NUMBER}*` pattern (specs.md, project.md, migrate.md, session-lifecycle.md, vg-executor-rules.md, visual-regression.md, architect-prompt-template.md) — not runnable code, just documentation examples. No fix needed.

## [1.9.2.1] - 2026-04-17

### Hotfix — `feature-legacy` profile for phases without SPECS.md

**Bug discovered while testing `/vg:review 7.12` post-v1.9.2 ship:**

Phase 7.12 (conversion-tracking-pixel) was built before VG required SPECS.md as part of the feature pipeline. It has:
- ✅ PLAN.md, CONTEXT.md, API-CONTRACTS.md, TEST-GOALS.md (39 goals), SUMMARY.md
- ✅ RUNTIME-MAP.json, GOAL-COVERAGE-MATRIX.md (from prior review)
- ❌ SPECS.md (convention not enforced at phase creation time)

**v1.9.2 behavior:** `detect_phase_profile` rule 1 returned `"unknown"` when SPECS.md missing → `required_artifacts` = only `SPECS.md` → review BLOCKED at prerequisite gate. Block_resolver L2 architect would propose "run `/vg:specs` first" — which is wrong for a phase already built past specs stage.

### Fix — Rule 1b: legacy feature fallback

`detect_phase_profile` now returns `"feature-legacy"` when:
- SPECS.md is missing **AND**
- PLAN.md + TEST-GOALS.md + API-CONTRACTS.md all present

Profile table additions:
- `feature-legacy`:
  - `required_artifacts` = `CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md SUMMARY.md` (no SPECS)
  - `skip_artifacts` = `SPECS.md`
  - `review_mode` = `full` (same as feature)
  - `test_mode` = `full`
  - `goal_coverage` = `TEST-GOALS`
- Narration (Vietnamese): "Pha feature legacy... bỏ qua SPECS. Khuyến nghị: tạo SPECS.md retrospective cho audit trail."

### Files

- `_shared/lib/phase-profile.sh` — +8 LOC Rule 1b detection + 2 new case branches in `phase_profile_required_artifacts`, `phase_profile_skip_artifacts`, `phase_profile_review_mode`, `phase_profile_test_mode`, `phase_profile_goal_coverage_source`, plus narration block.

### Verification

- Phase 7.12 (no SPECS, full artifacts): v1.9.2 → `unknown` BLOCK ❌ → v1.9.2.1 → `feature-legacy` PASS ✅
- Phase 07.12.1 (infra hotfix with SPECS + success_criteria bash): `infra` (unchanged) ✅

### Migration v1.9.2 → v1.9.2.1

No user action needed. Pure detection fix — runs on every review, transparent upgrade.

## [1.9.2] - 2026-04-17

### Phase profile system + full block-resolver coverage + sync.sh fix

**User-flagged critical defect**: `/vg:review 07.12.1` (pixel-infra-provisioning — hotfix phase with SPECS success_criteria bash checklist, NO TEST-GOALS) blocked with "BLOCK — prerequisites missing" then fell back to the BANNED anti-pattern "list 3 options A/B/C, stop, wait". 2 root causes:

1. **VG workflow assumed every phase = feature** (needs TEST-GOALS + API-CONTRACTS + full pipeline). Reality: strategic apps have phase types (infra, hotfix, bugfix, migration, docs).
2. **v1.9.1 block_resolve coverage was partial** — only 4 flagship sites, 8+ secondary sites fell back to anti-pattern.

### Added — P5 Phase Profile System

- **NEW** `_shared/lib/phase-profile.sh` (354 LOC, 9 exported functions):
  - `detect_phase_profile(phase_dir)` — 7 rules, stops first match, idempotent pure function
  - `phase_profile_required_artifacts` / `_skip_artifacts` / `_review_mode` / `_test_mode` / `_goal_coverage_source` — static profile tables
  - `parse_success_criteria(specs_path)` — Python JSON array from SPECS `## Success criteria` checklist
  - `phase_profile_summarize` — Vietnamese narration on stderr
  - `phase_profile_check_required` — gate helper

- **6 phase profiles** with distinct artifact requirements + review/test modes:
  - **feature** (default) — full pipeline: SPECS → scope → blueprint → build → review → test → accept
  - **infra** — SPECS success_criteria bash checklist, NO TEST-GOALS/API-CONTRACTS/CONTEXT. review_mode=`infra-smoke` (parse bash → run → READY/FAILED → implicit goals S-01..S-NN)
  - **hotfix** — parent_phase field, small patch, inherits parent goals. ≥3 infra bash cmds promoted to `infra`
  - **bugfix** — issue_id/bug_ref field, regression-focused
  - **migration** — migration keyword + touches schema paths, rollback plan required
  - **docs** — markdown-only file changes

- **`vg.config.md.phase_profiles`** schema (template + project config) — `required_artifacts`, `skip_artifacts`, `review_mode`, `test_mode`, `goal_coverage` per profile

### Added — P4 Block Resolver Full Coverage

**12 block_resolve sites across 5 files** (8 new + 4 pre-existing from v1.9.1):
- `review.md` × 4: prereq-missing (NEW), infra-smoke-not-ready (NEW), infra-unavailable (Scenario F patched), not-scanned-defer
- `test.md` × 3: flow-spec-missing (patched), dynamic-ids (patched), goal-test-binding
- `build.md` × 2: design-missing (patched), test-unit-missing (patched)
- `accept.md` × 2: regression (patched), unreachable (patched)
- `blueprint.md` × 1: no-context (NEW profile-aware)

**Banned anti-pattern eliminated**: no more "list 3 options, stop, wait" without L1 inline / L2 architect Haiku / L3 user choice attempt.

### Fixed — sync.sh missed _shared/lib/ and lib/test-runners/

- v1.9.0–v1.9.1 sync.sh didn't include `*.sh` files under `_shared/lib/` → distributed vgflow tarballs were missing 18 runtime functions → `/vg:doctor` + test runners silently degraded on fresh installs.
- v1.9.2 adds 3 sync_dir calls: `lib/*.sh`, `lib/*.md`, `lib/test-runners/*.sh`.

### Changed

- **`review.md`** — Step 0 profile detection gates ALL subsequent checks. Infra phase: skip browser discover, parse SPECS success_criteria, run each → map implicit goals S-01..S-NN, generate GOAL-COVERAGE-MATRIX.md, PASS without TEST-GOALS.
- **`blueprint.md`** — Profile detection + `skip_artifacts` check → don't generate TEST-GOALS/API-CONTRACTS for infra/docs phases.
- **`scope.md`** — Profile short-circuit for non-feature (infra/hotfix/bugfix/docs skip 5-round discussion, only feature phases need it).
- **`test.md`** — Profile-aware test_mode routing (`infra-smoke` re-runs SPECS bash on sandbox).

### Phase 07.12.1 integration test (dry-run verified)

1. `detect_phase_profile` → `infra` (≥3 infra bash cmds in success_criteria + no TEST-GOALS)
2. `required_artifacts` = [SPECS.md, PLAN.md, SUMMARY.md] — SUMMARY.md missing → block_resolve L2 architect proposal (NOT 3-option stall)
3. `parse_success_criteria` → 6 implicit goals S-01..S-06
4. `review_mode` = `infra-smoke` → browser/TEST-GOALS skipped, bash commands executed, GOAL-COVERAGE-MATRIX.md written

### Backward compatibility

- Phases without detectable profile → default to `feature` (v1.9.1 behavior)
- Phases with `feature` profile → unchanged pipeline
- No migration required — profile detection is read-only + lazy

### Migration v1.9.1 → v1.9.2

**No required actions.** All changes are additive + profile-aware branches.

- Legacy phases auto-detect via SPECS structure → most become `feature`, select few become `infra`/`hotfix`/`bugfix` based on SPECS content.
- Example: phase 07.12.1 → `infra` (has SPECS success_criteria + no TEST-GOALS + parent_phase field).
- Example: phase 07.12 → `feature` (full pipeline artifacts).

### Deferred to v1.9.3

- **R3.2 dimension-expander** — scope adversarial proactive expansion of dimensions (orthogonal to v1.9.1 R3 answer challenger). Ship as enhancement, not critical for 07.12.1 fix.
- **Codex-skills update** — sync structure via sync.sh (new lib sync added), codex-skills prose still v1.9.1 baseline. Update to v1.9.2 behavior (profile routing) in v1.9.3 batch.

## [1.9.1] - 2026-04-17

### Surface-driven testing — VG handle được mọi loại phase (UI / API / data / time-driven / integration / mobile / custom)

User feedback từ phase 7.12 conversion tracking (backend, không UI): workflow hiện tại UI-centric — review browser-discover, test Playwright. Backend phase deadlock: review block goals NOT_SCANNED forever, no UI to discover. Đề xuất 3 options đều "bàn lùi" việc test. **Đây là defect, không phải feature**.

v1.9.1 ship 4 nguyên tắc thành workflow rules — generic, no project hardcode:

### Added — R1: Surface-driven test taxonomy

- **NEW** `_shared/lib/goal-classifier.sh` (355 LOC) — multi-source classifier (TEST-GOALS text + CONTEXT D-XX + API-CONTRACTS + SUMMARY + RUNTIME-MAP + code grep). Confidence ≥0.80 auto-classify, 0.50-0.80 spawn Haiku tie-break, <0.50 AskUserQuestion. Lazy migration via `schema_version: "1.9.1"` frontmatter stamp. Idempotent.
- **NEW** `_shared/lib/test-runners/dispatch.sh` (59 LOC) + 6 surface runners (~80 LOC each):
  - `ui-playwright.sh` — wraps existing browser test infra
  - `ui-mobile-maestro.sh` — wraps mobile-deploy.md infra
  - `api-curl.sh` — bash + curl + jq pattern
  - `data-dbquery.sh` — bash + DB client lookup (psql/sqlite3/clickhouse-client/mongosh) per `vg.config.md`
  - `time-faketime.sh` — bash + faketime + invoke + assert
  - `integration-mock.sh` — spin mock receiver (HTTP server random port), assert request received
- **NEW** `vg.config.md.test_strategy` schema — 5 default surfaces với `runner` + `detect_keywords`. Project tự extend (rtb-engine, ml-model, blockchain, etc.). VG core không biết RTB là gì.
- **PATCH** `blueprint.md` — call classify_goals_if_needed sau TEST-GOALS write
- **PATCH** `review.md` — step 4a: classify + per-surface routing. **Pure-backend phase (zero ui goals) → skip browser discover entirely** (fixes 7.12 deadlock)
- **PATCH** `test.md` — step 5c: classify + dispatch_test_runner per goal surface. Results merge vào TEST-RESULTS.md
- **Phase 7.12 dry-run**: 17/39 goals auto-classify, 22 vào Haiku tie-break — confirms backend classification works

### Added — R2+R4: Block resolver 4-level (agency)

User feedback: "review/test khi block toàn list 3 options A/B/C dừng chờ. AI biết hướng nhưng vẫn dừng. Phải tự nghĩ → quyết → làm; chỉ stop khi thực sự không biết rẽ."

- **NEW** `_shared/lib/block-resolver.sh` (344 LOC) — 4 levels:
  - **L1 inline auto-fix** — try fix candidates, score, rationalization-guard check. Confidence ≥0.7 + guard PASS → ACT. Telemetry `block_self_resolved_inline`
  - **L2 architect Haiku** — spawn Haiku subagent với FULL phase context (SPECS+CONTEXT+PLAN+TEST-GOALS+SUMMARY+API-CONTRACTS+RUNTIME-MAP+code+infra). Returns structured proposal `{type: sub-phase|refactor|new-artifact|config-change, summary, file_structure, framework_choice, decision_questions, confidence}`. Telemetry `block_architect_proposed`
  - **L3 user choice** — AskUserQuestion present proposal với recommendation. Telemetry `block_user_chose_proposal`
  - **L4 stuck escalate** — only after L1+L2+L3 exhausted. Telemetry `block_truly_stuck`
- **NEW** `_shared/lib/architect-prompt-template.md` (~110 lines) — reusable Haiku prompt
- **PATCH** flagship gate sites in review/test/build/accept (4 sites). 8 secondary sites noted for future sweep (same template).
- **Banned anti-pattern**: "list 3 options stop wait" without trying any. Every block MUST attempt L1 → L2 → L3 → L4.
- **Example trace (phase 7.12 review block)**:
  ```
  L1 retry-failed-scan → confidence 0.5 < 0.7 → skip
  L2 Haiku architect → proposal: {type: sub-phase, summary: "Create 07.12.2 Test Harness", file_structure: "apps/api/test/e2e/{fixtures,helpers,specs}", framework_choice: "vitest + supertest", confidence: 0.82}
  L3 AskUserQuestion → user accepts → emit telemetry → continue
  ```

### Added — R3: Scope adversarial answer challenger

User feedback: "Trong /vg:scope, mỗi câu trả lời của user, AI nên tự phản biện xem có vấn đề gì không. Nếu có thì hỏi tiếp."

- **NEW** `_shared/lib/answer-challenger.sh` (205 LOC) — sau mỗi user answer trong scope/project round:
  - Spawn Haiku subagent (zero parent context) với 4 lenses:
    1. Mâu thuẫn với D-XX/F-XX prior?
    2. Hidden assumption?
    3. Edge case missed (failure / scale / concurrency / timezone / unicode / multi-tenancy)?
    4. FOUNDATION conflict (platform / compliance / scale)?
  - Returns `{has_issue, issue_kind, evidence, follow_up_question, proposed_alternative}`
  - If issue → AskUserQuestion 3 options: Address (rephrase) / Acknowledge (accept tradeoff) / Defer (track in CONTEXT.md "Open questions")
- **PATCH** `scope.md` 5-round loop + `project.md` 7-round adaptive discussion
- **Loop guard**: max 3 challenges per phase; trivial answers (Y/N, ≤3 chars) skip; config `scope.adversarial_check: true` (default)
- **Telemetry event** `scope_answer_challenged` với `{round_id, issue_kind, user_chose}`

### Changed

- **`vg.config.md`** — new sections:
  - `test_strategy:` — surface taxonomy với detect_keywords + runners (R1)
  - `scope:` — `adversarial_check`, `adversarial_model`, `adversarial_max_rounds`, `adversarial_skip_trivial` (R3)
- **`telemetry.md`** — registered events: `goals_classified`, `block_self_resolved_inline`, `block_architect_proposed`, `block_user_chose_proposal`, `block_truly_stuck`, `scope_answer_challenged`

### v1.9.1 vs Round 2 score targets (expected)

Round 2 baseline: overall 6.75, robustness 7.0, consistency 6.0, onboarding 3.25 (flat).

Expected v1.9.1 movement:
- **Strategic fit ↑↑** — workflow handle được mọi loại phase (không còn UI-centric defect)
- **Robustness ↑** — block resolver 4-level removes "list 3 options stop" anti-pattern
- **Consistency ↑** — surface taxonomy makes review/test routing deterministic
- **Onboarding ↑** — backend phase no longer requires user workaround (tag tricks)

### Migration v1.9.0 → v1.9.1

**No required actions** — all changes additive + lazy migration.

- Phase cũ (e.g., 7.12) lần đầu chạy `/vg:review` → goal-classifier auto-classify từ artifacts → stamp `schema_version: "1.9.1"` → continue. Không cần command migration riêng.
- Phase mới: `/vg:blueprint` tự classify khi sinh TEST-GOALS lần đầu.
- Block resolver 4-level transparent — gates vẫn trigger như cũ, chỉ thêm L1/L2/L3 trước khi L4 escalate.
- Scope answer challenger: enabled by default; disable nếu prototype nhanh: `scope.adversarial_check: false` trong vg.config.md.

### Cross-AI evaluation context

v1.9.1 addresses user-flagged workflow defect not captured in Round 2 SYNTHESIS (UI-centricity assumption).
- Strategic application can have arbitrary phase types — workflow must NOT assume UI default.
- Block agency: AI must think → decide → act, not list options and stop.
- Adversarial scope: AI must challenge own assumptions during design, not record passively.

Tier B remaining (wave checkpoints, /vg:amend propagation, telemetry sqlite, foundation BLOCK, gate-manifest signing) deferred to v1.9.2+.

## [1.9.0] - 2026-04-17

### Tier A discipline batch — closing v1.8.0 residual gaps

Cross-AI Round 2 evaluation (codex/gemini/claude/opus) verdict CONCERNS — overall **6.75** (+1.0 vs v1.7.1), robustness **+2.25**, consistency **+1.5**, but onboarding flat **3.25/10** and AI-failure surface GREW (more gates × same self-rationalizing executor). v1.9.0 ships 5 discipline-focused fixes (T1–T5) consensus-flagged at Tier A.

### Added

- **T1. Rationalization-guard Haiku subagent** — `_shared/rationalization-guard.md` (REWRITTEN 61 → 235 LOC)
  - Replaces same-model self-check (CRITICAL Round 2 finding 4/4 consensus)
  - `rationalization_guard_check(gate_id, gate_spec, skip_reason)` spawns isolated Haiku subagent via Task tool with **zero parent context**
  - Returns PASS / FLAG / ESCALATE — caller acts: PASS continue, FLAG log critical debt, ESCALATE block + AskUserQuestion
  - Fail-closed: if subagent unavailable → ESCALATE (safe default)
  - Integrated at 8 gate-skip sites: `build.md` × 3 (wave-commits, design-check, build-hard-gate), `review.md` × 1 (NOT_SCANNED defer), `test.md` × 1 (dynamic-ids), `accept.md` × 2 (unreachable-triage, override-resolution-gate)
  - Telemetry event: `rationalization_guard_check` (subagent_model, verdict, confidence)
  - Deprecated alias `rationalization_guard()` retained with WARN

- **T2. `/vg:override-resolve --wont-fix` command** — `commands/vg/override-resolve.md` NEW (132 LOC)
  - Unblocks intentional permanent overrides at `/vg:accept` (claude CRITICAL finding)
  - Args: `<DEBT-ID> --reason='...' [--wont-fix]`
  - `--wont-fix` requires AskUserQuestion confirmation (audit safety)
  - Emits `override_resolved` telemetry event with `status=WONT_FIX`, `manual=true`, `reason=...`
  - `accept.md` step 3c filters WONT_FIX entries from blocking check

- **T2 (extension). Override status WONT_FIX** — `_shared/override-debt.md`
  - `override_resolve()` accepts optional `status` arg (RESOLVED|WONT_FIX, default RESOLVED)
  - New helper `override_resolve_by_id(debt_id, status, reason)` — patches single row, merges audit trail
  - `override_list_unresolved()` excludes WONT_FIX from blocking accept

- **T3. Bash extraction `_shared/*.md` → `_shared/lib/*.sh`** — NEW `_shared/lib/` directory
  - Fixes CRITICAL bug (claude+opus): `/vg:doctor` was `source .md` files which silently failed (YAML frontmatter `---` = bash syntax error). Functions undefined → false confidence
  - Created 4 .sh files (all `bash -n` syntax-clean):
    - `lib/artifact-manifest.sh` (185 LOC) — 3 functions
    - `lib/telemetry.sh` (206 LOC) — 8 functions
    - `lib/override-debt.sh` (242 LOC) — 5 functions
    - `lib/foundation-drift.sh` (436 LOC) — 4 functions
  - 18 functions extracted total
  - Markdown stays as docs with "Runtime note" callout pointing to .sh
  - Patched call sites: `doctor.md`, `accept.md` step 3c, `_shared/foundation-drift.md` examples

- **T5 (extension). `_shared/lib/namespace-validator.sh`** — NEW (105 LOC)
  - `validate_d_xx_namespace(file_path, scope_kind)` — scope_kind ∈ {"foundation"|"phase:N"}
  - `validate_d_xx_namespace_stdin(scope_kind)` — pipeline-friendly variant
  - Tolerates D-XX inside fenced code, blockquotes, inline backticks (false-positive guard)

### Changed

- **T4. `/vg:doctor` split into 4 focused commands** (Round 2 4/4 consensus: god-command anti-pattern)
  - **NEW** `commands/vg/health.md` (315 LOC) — full project health + per-phase deep inspect (was doctor "full" + "phase" modes)
  - **NEW** `commands/vg/integrity.md` (194 LOC) — manifest validation across all phases (was doctor `--integrity`)
  - **NEW** `commands/vg/gate-stats.md` (179 LOC) — telemetry query API (was doctor `--gates`)
  - **NEW** `commands/vg/recover.md` (272 LOC) — guided recovery for stuck phases (was doctor `--recover`)
  - **REWRITTEN** `commands/vg/doctor.md` (673 → 115 LOC) — thin dispatcher routing to 4 sub-commands
  - Total 1075 LOC across 5 files (was 673 mono) — 60% increase justified by clearer modularity + unambiguous argument grammar
  - Backward compat: legacy `--integrity`, `--gates`, `--recover` flags still work with WARN deprecation

- **T5. Telemetry write-strict / read-tolerant** — `_shared/lib/telemetry.sh` + `_shared/telemetry.md`
  - **READ tolerant:** legacy 4-arg `emit_telemetry()` call still accepted (back-compat shim)
  - **WRITE strict:** shim now logs WARN to stderr with caller stack hint, marks event with `legacy_call:true` payload
  - `telemetry_step_start()` / `telemetry_step_end()` updated to call `emit_telemetry_v2()` directly (was using shim — gate_id was empty in majority events)
  - Integration pattern examples in telemetry.md updated to use `emit_telemetry_v2`
  - Added config `telemetry.strict_write: true` (default v1.9.0); v2.0 will hard-fail
  - Bash bug fix: `${4:-{}}` parsing was appending stray `}`

- **T5. D-XX namespace write-strict** — `scope.md`, `project.md`, `_shared/vg-executor-rules.md`
  - **READ tolerant:** legacy bare D-XX accepted in old files (commit-msg hook WARN, not BLOCK)
  - **WRITE strict:** `scope.md` blocks `CONTEXT.md.staged` write if generated text contains bare D-XX outside fenced code → forces `P{phase}.D-XX`
  - Same gate in `project.md` for `FOUNDATION.md.staged` → forces `F-XX`
  - Validator tolerates fenced code/blockquotes/inline backticks (no false positives)

### v1.9.0 vs Round 2 score targets

Round 2 baseline: overall 6.75, robustness 7.0, consistency 6.0, onboarding **3.25** (flat).

Expected v1.9.0 movement:
- **AI failure surface ↓** — rationalization-guard now Haiku-isolated, can't be self-rationalized
- **Onboarding ↑** — `/vg:doctor` 5-mode god command split into 4 focused commands with clear verbs
- **Consistency ↑** — telemetry write-strict ensures gate_id populated; D-XX namespace enforced at write-time
- **Robustness ↑** — `.sh` extraction fixes silent function-loading failure that made T2 (Round 1) theater

### Migration v1.8.0 → v1.9.0

**Required actions:**

1. **Backup** (always): `git commit -am "pre-v1.9.0"`
2. **No data migration needed** — all changes additive or back-compat
3. **Sub-command discovery**: `/vg:health`, `/vg:integrity`, `/vg:gate-stats`, `/vg:recover` are new top-level commands. Use them directly. `/vg:doctor` still works as dispatcher.
4. **Override --wont-fix**: any pre-existing override entries marked OPEN can now be resolved manually via `/vg:override-resolve <DEBT-ID> --wont-fix --reason='...'`
5. **Telemetry**: any custom code calling `emit_telemetry()` 4-arg signature will see WARN in stderr — migrate to `emit_telemetry_v2(event_type, phase, step, gate_id, outcome, payload, correlation_id, command)`. Old code keeps working through v1.10.0.
6. **D-XX**: continue to accept legacy bare D-XX on read; new `/vg:scope` and `/vg:project` runs will refuse to WRITE bare D-XX. Use `migrate-d-xx-namespace.py --apply` (v1.8.0+) if not done.

**No breaking changes** — all v1.8.0 code paths continue to work; new gates are additive.

### Cross-AI evaluation context

v1.9.0 addresses Tier A from `.planning/vg-eval/SYNTHESIS-r2.md`:
- C1 Rationalization-guard deferral (4/4 consensus) → T1
- M1 /vg:doctor god-command (4/4) → T4
- M3 Backward-compat windows AI rationalization (4/4) → T5 (write-strict)
- M4 Override --wont-fix missing (claude critical) → T2
- M8 /vg:doctor source-chain bug (claude+opus) → T3

Tier B (wave checkpoints, /vg:amend propagation, telemetry sqlite, foundation BLOCK, gate-manifest signing) deferred to v1.9.x. Tier C deferred to v2.0.

## [1.8.0] - 2026-04-17

### Tier 2 fixes batch — closing AI corner-cutting surface

Sau cross-AI evaluation 4 reviewers (codex, gemini, claude, opus) — verdict CONCERNS với onboarding 3.25/10, consistency/robustness 4.5–4.75/10. v1.8.0 ship 8 cải tiến (T1–T8) đóng các lỗ hổng "soft policy" và "observability theater" được consensus flag.

### Added

- **T1. Structured telemetry schema (v2)** — `_shared/telemetry.md`
  - `emit_telemetry_v2(event_type, phase, step, gate_id, outcome, payload, correlation_id, command)` với uuid `event_id`
  - `telemetry_query --gate-id=X --outcome=Y --since=Z` để root-cause analysis thực sự
  - `telemetry_warn_overrides` auto-WARN khi 1 gate bị OVERRIDE > N lần trong milestone
  - Event types mới: `override_resolved`, `artifact_written`, `artifact_read_validated`, `drift_detected`
  - Back-compat shim: `emit_telemetry()` cũ vẫn work, map sang v2

- **T2. `/vg:doctor` command** — `commands/vg/doctor.md` (NEW, 673 LOC)
  - 5 modes: bare (project health), `{phase}` (deep inspect), `--integrity` (hash validate), `--gates` (gate audit), `--recover {phase}` (6 corruption recovery flows)
  - Replaces "fix manually + grep telemetry.jsonl" pattern

- **T3. Artifact manifest với SHA256** — `_shared/artifact-manifest.md` (NEW)
  - `artifact_manifest_write(phase_dir, command, ...paths)` ghi `.artifact-manifest.json` LAST sau khi all artifacts complete
  - `artifact_manifest_validate(phase_dir)` → 0=valid, 1=missing, 2=corruption
  - `artifact_manifest_backfill(phase_dir, command)` migrate phase legacy
  - Chống multi-file atomicity gap (crash mid-write)

- **T8. `/vg:update` gate-integrity verify** — `scripts/vg_update.py`, `commands/vg/update.md`, `reapply-patches.md`
  - GitHub Action publish `gate-manifest.json` per release
  - `update.md` step `6b_verify_gate_integrity` so sánh hash gate blocks vs manifest
  - `/vg:reapply-patches --verify-gates` mode bắt buộc trước /vg:build sau update
  - Build/review/test/accept: early hard gate block nếu unverified gates

### Changed (BREAKING — migration required)

- **T4. D-XX namespace migration (MANDATORY)** — split namespace:
  - **F-XX** = FOUNDATION decisions (project-wide)
  - **P{phase}.D-XX** = per-phase decisions (e.g., `P7.6.D-12`)
  - Migration script: `scripts/migrate-d-xx-namespace.py` (450 LOC, idempotent, atomic backup)
    - `--dry-run` (default) → preview changes
    - `--apply` → commit + backup to `.planning/.archive/{ts}/pre-migration/`
    - Negative-lookbehind regex `(?<![\w.])D-(\d+)(?!\d)` (no false-positive)
  - **Backward compat window:** legacy `D-XX` accepted with WARN through v1.10.0; HARD-REJECT v1.10.1+
  - Files updated: `project.md`, `scope.md`, `blueprint.md`, `accept.md` (Section A.1 for F-XX), `vg-executor-rules.md`, `vg-planner-rules.md`, `templates/vg/commit-msg`

- **T5. Override expiry contract (BREAKING)** — `_shared/override-debt.md`, `accept.md`
  - **Time-based expiry BANNED** — overrides chỉ resolve khi gate bypassed RE-RUN clean
  - New field: `resolved_by_event_id` (telemetry event ID, kiểm chứng được)
  - New API: `override_resolve()`, `override_list_unresolved()`, `override_migrate_legacy()`
  - `/vg:accept` step `3c_override_resolution_gate` — block accept nếu override unresolved

### Improved

- **T6. Foundation semantic drift + notify-and-track** — `_shared/foundation-drift.md`, `.planning/.drift-register.md`
  - 8 structured claim families (mobile/desktop/serverless/PCI/GDPR/HIPAA/SOC2/high-QPS) thay regex on prose
  - 3 tiers: INFO (log), WARN (notify user + track register), BLOCK-deferred
  - **`.drift-register.md`** — dedup tracking, không quên drift đã flag
  - `drift_detected` telemetry event tự động emit

- **T7. `/vg:scope-review` incremental mode** — `commands/vg/scope-review.md` (385 → 665 LOC)
  - `.scope-review-baseline.json` — chỉ re-compare phases changed since baseline
  - `--full` flag để full O(n²) scan (default = incremental)
  - Delta summary + telemetry emit cho audit
  - Khử O(n²) scaling failure ở milestone 50+ phases

### Migration guide v1.7.1 → v1.8.0

**Required actions:**

1. **Backup**: `git commit -am "pre-v1.8.0"` hoặc `cp -r .planning .planning.bak`
2. **Run D-XX migration (dry-run first)**:
   ```bash
   python3 .claude/scripts/migrate-d-xx-namespace.py --dry-run
   # Review preview, sau đó:
   python3 .claude/scripts/migrate-d-xx-namespace.py --apply
   ```
3. **Backfill artifact manifests** (legacy phases):
   ```bash
   /vg:doctor --integrity   # detect missing manifests
   # For each phase: artifact_manifest_backfill called via /vg:doctor --recover
   ```
4. **Migrate legacy overrides** (loại bỏ time-based expiry):
   ```bash
   # /vg:accept tự gọi override_migrate_legacy() lần đầu
   ```
5. **Drift register init**: `.planning/.drift-register.md` tự tạo lần đầu chạy `/vg:scope-review` hoặc khi drift detected.

**Backward compatibility:**
- Legacy `D-XX` (không namespace) — WARN nhưng vẫn pass qua v1.10.0
- Legacy telemetry events thiếu `event_id` — `emit_telemetry()` shim auto-fill
- Phase artifacts chưa có manifest — `/vg:doctor --recover` backfill được

**Breaking only at v1.10.1+:**
- D-XX không namespace → HARD-REJECT
- Override không có `resolved_by_event_id` → HARD-REJECT

### Cross-AI evaluation context

v1.8.0 đáp ứng Tier 2 priorities từ `.planning/vg-eval/SYNTHESIS.md`:
- M4 (Observability theater) → T1 + T2
- M5 (`scope-review` O(n²)) → T7
- M6 (Foundation drift wording-only) → T6
- M7 (`/vg:update` gate-integrity) → T8
- M8 (D-XX namespace collision) → T4
- M9 (Override expiry undefined) → T5
- M10 (Multi-file atomicity gap) → T3

Tier 1 (wave checkpoints, command consolidation, rationalization-guard subagent, /vg:amend propagation, CrossAI domain disclaimer) — deferred sang v2.0 (breaking).

## [1.7.1] - 2026-04-17

### Added — Term glossary RULE (Vietnamese explanation for English terms)

User feedback: Khi narration tiếng Việt có nhiều thuật ngữ tiếng Anh (BLOCK, drift, foundation, legacy, MERGE NOT OVERWRITE...), user khó đoán nghĩa khi xem log/discussion/UAT artifact.

**RULE mới:** Mọi thuật ngữ tiếng Anh trong user-facing output PHẢI có giải thích VN trong dấu ngoặc đơn ở lần xuất hiện đầu tiên trong cùng message/section.

Ví dụ:
- ❌ Sai: `Goal G-05 status: BLOCKED — required dependency missing`
- ✅ Đúng: `Goal G-05 status: BLOCKED (bị chặn) — required dependency (phụ thuộc) missing`

### Files

- **NEW** `commands/vg/_shared/term-glossary.md` — RULE đầy đủ + 7 nhóm glossary (Pipeline state, Foundation states, Workflow, Tech, Test, Identifiers, Action verbs) với 100+ thuật ngữ phổ biến
- **MODIFIED** `commands/vg/review.md`, `test.md`, `build.md`, `project.md` — thêm rule #5 vào NARRATION_POLICY block tham chiếu term-glossary.md

### Scope

- ✅ Apply: narration, status messages, error messages, summary, log files, UAT.md, AskUserQuestion options/labels
- ❌ Không apply: file path, code identifier (`D-XX`, `git`, `pnpm`), config tag values (`web-saas`, `monolith`), lần lặp lại trong cùng message, file tiếng Anh thuần (CHANGELOG)

### Subagent inheritance

Khi orchestrator spawn subagent (`Task` tool) sinh narration cho user, prompt phải include hint: "Output user-facing text bằng tiếng Việt; thuật ngữ tiếng Anh phải có gloss VN trong ngoặc lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`."

## [1.7.0] - 2026-04-17

### Added — Pre-discussion doc scan (auto-fill foundation từ existing docs)

User feedback: Khi `/vg:project` chạy, phải scan tất cả docs hiện có để auto-fill PROJECT/FOUNDATION artifacts. Chỉ coi là "project mới" khi 100% trống — README/CLAUDE.md/package.json/.planning đều bị bỏ qua trước đây.

v1.7.0 thêm step `0c_scan_existing_docs` chạy sau state detection, **luôn** scan trừ khi đã có FOUNDATION.md authoritative hoặc đang resume draft. Output: `.planning/.project-scan.json` + console summary.

### Scan sources (10 nhóm)

1. **README** — `README.md`, `README.vi.md`, `readme.md` (extract title + first paragraph)
2. **package.json** — name, description, dependencies → infer React/Vite/Next/Vue/Svelte/Fastify/Express/MongoDB/Postgres/Prisma/Playwright/Vitest/Expo/Electron/etc.
3. **Other manifests** — Cargo.toml (Rust), go.mod (Go), pubspec.yaml (Flutter), requirements.txt/pyproject.toml (Python), Gemfile (Ruby)
4. **Monorepo** — pnpm-workspace.yaml + turbo.json, nx.json, lerna.json, rush.json
5. **Infra/hosting** — infra/ansible/, Dockerfile, vercel.json, netlify.toml, fly.toml, render.yaml, railway.json, serverless.yml, AWS SAM, wrangler.toml (Cloudflare), .github/workflows/, .gitlab-ci.yml
6. **Auth code** — apps/*/src/**/auth*, src/**/auth* directory detection
7. **CLAUDE.md** — extract `## Project` / `## Overview` / `## About` section as description (per VG convention)
8. **Brief/spec docs** — docs/**/*.md, BRIEF.md, SPEC.md, RFC*.md, *-brief.md, *-spec.md
9. **`.planning/` deep scan** (NEW per user request):
   - PROJECT.md (legacy v1) → name + description fallback
   - REQUIREMENTS.md → count REQ-XX items
   - ROADMAP.md → count phases
   - STATE.md → pipeline progress snapshot
   - SCOPE.md / PROJECT-SCOPE.md
   - **phases/** → count dirs + classify (accepted = has UAT.md, in-progress = has SUMMARY.md but no UAT.md), list latest 3 phase titles
   - intel/, codebase/, research/, design-normalized/, milestones/ → file counts
   - All loose `.planning/*.md` files
10. **vg.config.md** — already-confirmed config (highest trust signal)

### State upgrades

If scan results are "rich" (name + description + ≥2 tech buckets + ≥1 doc):
- `greenfield` → `greenfield-with-docs` (skip pure first-time, jump to confirm/adjust scan results)
- `brownfield-fresh` → `brownfield-with-docs`

This means project có README + package.json không còn bị treat như "blank slate".

### Files

- `commands/vg/project.md` — step `0c_scan_existing_docs` (NEW, ~150 lines Python in heredoc)
- Output artifact: `.planning/.project-scan.json` (machine-readable scan results, consumed by Round 2 to pre-populate foundation table)

### Migration

Existing v1.6.x users: no breaking change. Next `/vg:project` invocation will scan + show richer info, but artifacts unchanged unless user explicitly chooses update/migrate/rewrite.

## [1.6.1] - 2026-04-17

### Changed (UX — auto-scan + state-tailored menu)

User feedback: "không nhớ nên gõ args nào đâu" — `/vg:project --view` / `--migrate` / `--update` etc. requires user to remember flag names. v1.6.0's mode menu only fired when artifacts exist + no flag passed.

v1.6.1 makes auto-scan and proactive suggestion the **default behavior** for every `/vg:project` invocation, regardless of args:

- **Always print state summary table FIRST** — files exist (with mtime age), draft status, codebase detection, classified state category (greenfield / brownfield-fresh / legacy-v1 / fully-initialized / draft-in-progress).
- **State-tailored menus** — different option sets shown per state, with ⭐ RECOMMENDED action highlighted:
  - `legacy-v1` → recommend `[m] Migrate`, alt: view/rewrite/cancel
  - `brownfield-fresh` → recommend `[f] First-time với codebase scan`, alt: pure-text/cancel
  - `fully-initialized` → full menu: view/update/milestone/rewrite/cancel
  - `greenfield` → straight to Round 1 capture (no menu — most common new case)
  - `draft-in-progress` → resume/discard/view-draft (priority)
- **Flag mismatch validation** — explicit flags validated against state. `--migrate` on greenfield → friendly hint to use first-time instead, exit 0 (no error).
- User chỉ cần gõ `/vg:project` — workflow tự dẫn dắt, không cần đoán flag.

### Files

- `commands/vg/project.md` — step `0b_print_state_summary` (NEW) + `1_route_mode` rewritten with state-tailored menus

## [1.6.0] - 2026-04-17

### Changed (BREAKING UX — entry point flow rebuild)

User feedback identified chicken-and-egg in old pipeline: `/vg:init` ran first asking for tech config (build commands, ports, framework markers) before `/vg:project` defined what the project is. Greenfield projects had to guess; brownfield felt redundant.

**v1.6.0 swaps the order: `/vg:project` is now the entry point.** It captures user's natural-language description, derives FOUNDATION (8 platform/runtime/data/auth/hosting/distribution/scale/compliance dimensions), then auto-generates `vg.config.md` from foundation. Config is downstream of foundation, not upstream.

### Added — `/vg:project` 7-round adaptive discussion + 6 modes

- **First-time flow** (7 rounds, adaptive — skip rounds without ambiguity, never skip Round 4 high-cost gate):
  1. Capture (free-form description or template-guided)
  2. Parse + present overview table (8 dimensions with status flags ✓/?/⚠/🔒)
  3. Targeted dialog on `?` ambiguous items
  4. **High-cost confirmation gate** (mandatory — platform/backend/deploy/DB)
  5. Constraints fill-in (scale/latency/compliance/budget/team)
  6. Auto-derive `vg.config.md` from foundation (90% silent, only `<ASK>` fields prompted)
  7. Atomic write 3 files: `PROJECT.md` + `FOUNDATION.md` + `vg.config.md`

- **Re-run modes** (when artifacts exist):
  - `--view` — Pretty-print, read-only (default safe)
  - `--update` — MERGE-preserving update (covers refine + amend, adaptive scope)
  - `--milestone` — Append milestone (foundation untouched, drift warning if shift)
  - `--rewrite` — Destructive reset with backup → `.archive/{ts}/`
  - `--migrate` — Extract FOUNDATION.md from legacy v1 PROJECT.md + codebase scan
  - `--init-only` — Re-derive vg.config.md from existing FOUNDATION.md

- **Resumable drafts** — `.planning/.project-draft.json` checkpointed every round, interrupt-safe.

### Added — `/vg:_shared/foundation-drift.md` (soft warning helper)

Wired into `/vg:roadmap` (step 4b) and `/vg:add-phase` (step 1b). Scans phase title/description for keywords (mobile/iOS/Android/serverless/desktop/embedded/...) that suggest platform shift away from FOUNDATION.md. Soft warning only — does NOT block. User proceeds with acknowledgment, drift entry logged for milestone audit. Silence with `--no-drift-check`.

### Changed — `/vg:init` is now SOFT ALIAS

`/vg:init` no longer creates `vg.config.md` from scratch. It detects state and redirects:

| State | Redirect |
|-------|----------|
| No artifacts | Suggest `/vg:project` (first-time) |
| Legacy PROJECT.md only | Suggest `/vg:project --migrate` |
| FOUNDATION.md present | Confirm + auto-chain `/vg:project --init-only` |

Backward-compat preserved — old workflows still work, just with redirect notice.

### Files

- **NEW** `commands/vg/_shared/foundation-drift.md` (drift detection helper)
- **REWRITTEN** `commands/vg/project.md` (~520 lines — 7-round + 6 modes + atomic writes)
- **REWRITTEN** `commands/vg/init.md` (~80 lines — soft alias only)
- **MODIFIED** `commands/vg/roadmap.md` (+ step 4b foundation drift check)
- **MODIFIED** `commands/vg/add-phase.md` (+ step 1b foundation drift check)

### Migration

Existing projects with `PROJECT.md` but no `FOUNDATION.md`:
```
/vg:project --migrate
```
Auto-extracts foundation from existing PROJECT.md + codebase scan, slim down PROJECT.md, backup v1 to `.planning/.archive/{ts}/`.

### Known limitations

- 7-round flow is heavy by design (high-precision projects). No `--quick` mode in this release.
- Drift detection regex-based (keyword match), not semantic. May miss subtle shifts (e.g., "Progressive Web App" with PWA-specific tooling).
- Codex skill (`vg-project`) NOT updated in this release — Codex parity will land in v1.6.1+.

## [1.5.1] - 2026-04-17

### Added — Codex parity for UNREACHABLE triage (v1.4.0 backport to Codex skills)

v1.4.0 added UNREACHABLE triage to Claude commands (`/vg:review` + `/vg:accept`) but Codex skills (`$vg-review` + `$vg-accept`) were not updated. v1.5.1 closes the gap so phases reviewed/accepted under either harness get the same gate.

- **`codex-skills/vg-review/SKILL.md`** step 4e: UNREACHABLE triage runs after gate evaluation, produces `UNREACHABLE-TRIAGE.md` + `.unreachable-triage.json` (same Python helper as Claude).
- **`codex-skills/vg-accept/SKILL.md`** step 3 (after sandbox verdict gate): hard gate blocks accept if any verdict is `bug-this-phase`, `cross-phase-pending`, or `scope-amend`. Override via `--allow-unreachable --reason='...'` (logged to `build-state.log`).

Note: v1.5.0's TodoWrite ban does NOT apply to Codex (Codex CLI has no TodoWrite tool — different harness, different tail UI).

## [1.5.0] - 2026-04-17

### Changed (BREAKING UX — show-step mechanism rebuild)

End-to-end re-evaluation of progress narration found 8 bugs across 4 layered mechanisms (TodoWrite, session_start banner, session_mark_step, narrate_phase). v1.3.3's TODOWRITE_POLICY softfix was insufficient because it was conditional ("if you use TodoWrite") — model rationalized opt-out, items still got stuck.

**TodoWrite/TaskCreate/TaskUpdate are now BANNED in `/vg:review`, `/vg:test`, `/vg:build`.**

Why TodoWrite was the wrong abstraction:
1. Persists across sessions until next TodoWrite call (stuck-tail symptom)
2. Long Task subagent (30 min) blocks all updates → Ctrl+C = items stuck forever
3. Bash echo / EXIT trap can't reach TodoWrite (model-only tool)
4. Subagent's TodoWrite goes to its own conversation, not parent UI
5. Conditional policy gets skipped by model

### Added — replacement narration

- **Markdown headers in model text output** between tool calls (e.g. `## ━━━ Phase 2b-1: Navigator ━━━`). Visible in message stream, does NOT persist after session.
- **`run_in_background: true` + `BashOutput` polling** for any Bash > 30s — user sees stdout live instead of blank wait.
- **1-line text BEFORE + 1-line summary AFTER** for any `Task` subagent > 2 min.
- **Bash echo / `session_start` banner** demoted to audit-log role only — useful for run history, NOT live UX (lands in tool result block, only visible after Bash returns).

### Modified

- `commands/vg/review.md`, `test.md`, `build.md`:
  - Removed `<TODOWRITE_POLICY>` block, replaced with `<NARRATION_POLICY>` block at top
  - Removed `TaskCreate`, `TaskUpdate` from `allowed-tools`; added `BashOutput`
- `commands/vg/_shared/session-lifecycle.md`:
  - Replaced TodoWrite policy section with full bug map (8 bugs) + narration replacement table
  - `session_start` / EXIT trap retained but documented as audit log, not live UX

### Migration

Existing stuck TodoWrite items will clear once a v1.5.0 `/vg:review` (or `/vg:test`, `/vg:build`) runs in the session — orchestrator no longer creates new TodoWrite items, so the status tail naturally empties as Claude Code GC's stale state at next session restart.

## [1.4.0] - 2026-04-17

### Added — UNREACHABLE Triage (closes silent-debt loophole)

UNREACHABLE goals from `/vg:review` were previously "tracked separately" and accepted silently. They are bugs (or fictional roadmap entries) until proven otherwise. New triage system classifies each one and gates accept on unresolved verdicts.

- **New shared helper `_shared/unreachable-triage.md`**:
  - `triage_unreachable_goals()` — for each UNREACHABLE goal, extract distinctive keywords (route paths, PascalCase symbols, quoted UI labels), scan all other phase artifacts (PLAN/SUMMARY/RUNTIME-MAP/TEST-GOALS/SPECS/CONTEXT/API-CONTRACTS), classify into one of 4 verdicts:
    - `cross-phase:{X.Y}` — owning phase exists, accepted, AND verified in its RUNTIME-MAP.json (proof of reachability)
    - `cross-phase-pending:{X.Y}` — owning phase exists but not yet accepted → BLOCK current accept
    - `bug-this-phase` — current SPECS/CONTEXT mentions the keywords but no phase claims it → **BUG**, BLOCK accept
    - `scope-amend` — no phase claims it AND current SPECS doesn't mention → BLOCK accept (`/vg:amend` to remove or `/vg:add-phase` to create owner)
  - `unreachable_triage_accept_gate()` — read `.unreachable-triage.json`, exit 1 if any blocking verdict outstanding
- **`/vg:review` step `unreachable_triage`** (after gate evaluation, before crossai_review): runs triage, writes `UNREACHABLE-TRIAGE.md` (human-readable, evidence per goal) + `.unreachable-triage.json` (machine-readable). Does NOT block review exit — only `/vg:accept` enforces.
- **`/vg:accept` step `3b_unreachable_triage_gate`**: hard gate before UAT checklist. Blocks unless `--allow-unreachable --reason='<why>'` provided. Override is logged to override-debt register and surfaces in UAT.md "Unreachable Debt" section + `/vg:telemetry`.
- **UAT.md template** gains `## B.1 UNREACHABLE Triage` section: Resolved (cross-phase) entries plus Unreachable Debt table when override was used.
- Cross-phase verification reads target phase's RUNTIME-MAP.json (proof of runtime reachability), not just claims in PLAN.md — prevents fictional cross-phase citations.

## [1.3.3] - 2026-04-17

### Fixed (UX — stuck UI tail across runs)
- **Stuck TodoWrite items hanging in Claude Code's "Baking…" / "Hullaballooing…" status box across `/vg:review`, `/vg:test`, `/vg:build` runs** — items like "Phase 2b-1: Navigator", "Start pnpm dev + wait health" persisted from interrupted previous runs because TodoWrite list wasn't reset/cleared.
- **Root cause:** v1.3.0 session lifecycle banner only displaces `echo` narration tail, not TodoWrite items (which are model-only, bash trap can't touch them).
- **Fix:** Added `<TODOWRITE_POLICY>` directive block at top of `commands/vg/review.md`, `test.md`, `build.md`. Tells executing model:
  1. FIRST tool call MUST be a TodoWrite that REPLACES stale items (overwrites entire list)
  2. Mark each item `completed` immediately when done — don't batch
  3. Exit path (success OR error) MUST leave NO `pending`/`in_progress` items
  4. Better default: prefer `narrate_phase` (echo) over TodoWrite for granular per-step progress
- Companion update in `_shared/session-lifecycle.md` documents the symptom + recommended pattern (≤7 top-level milestones max for TodoWrite, echo for everything else).

## [1.3.2] - 2026-04-17

### Fixed (CRITICAL — extend preservation gate to all migrate steps)
- **`/vg:migrate` steps 5, 6, 7 also had overwrite-without-diff risk** (v1.3.1 only fixed step 4 CONTEXT.md):
  - Step 5 **API-CONTRACTS.md**: `--force` case overwrote existing without preserving endpoint paths
  - Step 6 **TEST-GOALS.md**: `--force` case overwrote existing without preserving G-XX goals + bodies
  - Step 7 **PLAN.md attribution**: Agent trusted to "only add attributes" but no verification — task descriptions could be silently rewritten/dropped
- **Fix:** All 4 mutation steps (4/5/6/7) now write to `{file}.staged` first. Preservation gates before promote:
  - IDs preserved (D-XX, G-XX, Task N, endpoint paths — depending on artifact type)
  - Body similarity ≥ 80% (difflib.SequenceMatcher) — attribute-stripped for PLAN.md
  - On fail: original untouched, staging kept at `{file}.staged`, backup in `.gsd-backup/`
- **Universal rule added to `<rules>` block**: "MERGE, DO NOT OVERWRITE" — codifies staging+diff+gate pattern for any future migrate step or similar mutation command.

## [1.3.1] - 2026-04-17

### Fixed (CRITICAL — data safety)
- **`/vg:migrate` step 4 `_enrich_context` was losing decisions silently** — agent wrote directly to `CONTEXT.md`, overwriting original. If agent dropped or merged D-XX decisions, they were **permanently lost** (backup in `.gsd-backup/` but no automatic diff/rollback).
- **Fix:** Agent now writes to `CONTEXT.md.enriched` staging file. Three gates run before promoting to `CONTEXT.md`:
  1. **Decision-ID preservation**: every `D-XX` in original must exist in staging (missing → abort, no overwrite)
  2. **Body-preservation**: each decision body must be ≥ 80% similar to original (rewritten prose → abort)
  3. **Sub-section coverage**: warns if `**Endpoints:**` count ≠ decision count (non-fatal)
- Only if all 3 gates pass → staging promoted to `CONTEXT.md` atomically. On failure, staging preserved for user review; original CONTEXT.md untouched.

## [1.3.0] - 2026-04-17

### Added
- **Session lifecycle helper** (`_shared/session-lifecycle.md`) wired into `/vg:review`, `/vg:test`, `/vg:build` — emits session-start banner + EXIT trap for clean tail UI across runs
- Stale state auto-sweep (configurable `session.stale_hours`, default 1h) — removes leftover `.review-state.json` / `.test-state.json` from previous interrupted runs
- Cross-platform port sweep (Windows netstat/taskkill + Linux lsof/kill) — kills orphan dev servers before new run
- Config: `session.stale_hours`, `session.port_sweep_on_start`

### Fixed
- Stuck "Phase 2b-1 / Phase 2b-2" items in Claude Code tail UI after interrupted `/vg:review` runs — EXIT trap now emits `━━━ EXITED at step=X ━━━` terminal marker

## [1.2.0] - 2026-04-17

### Fixed
- **Phase pipeline accuracy:** commands/docs consistently reference the correct 7-step pipeline `specs → scope → blueprint → build → review → test → accept` (was showing 6 steps, missing `specs` at front)
- `next.md` PIPELINE_STEPS order now includes `specs` — `/vg:next` can advance from specs-only state to scope
- `scripts/phase-recon.py` PIPELINE_STEPS now includes `specs` — phase reconnaissance detects specs-only phase correctly
- `phase.md` description, args, and inline docs reflect 7 steps
- `amend.md`, `blueprint.md`, `build.md`, `review.md`, `test.md` header pipelines include `specs` prefix
- `init.md` help text reflects 7-step phase pipeline

### Added
- `README.vi.md` — Vietnamese translation of README with cross-link back to English
- `README.md` — rewritten with clear 2-tier pipeline explanation (project setup + per-phase execution)
- Both READMEs now show the project-level setup chain (`/vg:init → /vg:project → /vg:roadmap → /vg:map → /vg:prioritize`) before the per-phase pipeline

## [1.1.0] - 2026-04-17

### Added
- `/vg:update` command — pull latest release from GitHub, 3-way merge with local edits, park conflicts in `.claude/vgflow-patches/`
- `/vg:reapply-patches` command — interactive per-conflict resolution (edit / keep-upstream / restore-local / skip)
- `scripts/vg_update.py` — Python helper implementing SemVer compare, SHA256 verify, 3-way merge via `git merge-file`, patches manifest persistence, GitHub release API query
- `/vg:progress` version banner — shows installed VG version + daily update check (lazy-cached)
- `migrations/template.md` — template for breaking-change migration guides
- Release tarball auto-build: GitHub Action builds + attaches `vgflow-vX.Y.Z.tar.gz` + `.sha256` per tag

### Fixed
- Windows Python text mode CRLF translation in 3-way merge tmp file (caused false conflicts against LF-terminated ancestor files)

## [1.0.0] - 2026-04-17

### Added
- Initial public release of VGFlow
- 6-step pipeline: scope → blueprint → build → review → test → accept
- Config-driven engine via `vg.config.md` — zero hardcoded stack values
- `install.sh` for fresh project install
- `sync.sh` for dev-side source↔mirror sync
- Claude Code commands (`commands/vg/`) + shared helpers
- Codex CLI skills parity (`codex-skills/vg-review`, `vg-test`)
- Gemini CLI skills parity (`gemini-skills/`)
- Python scripts for graphify, caller graph, visual diff, phase recon
- Commit-msg hook template enforcing citation + SemVer task IDs
- Infrastructure: override debt register, i18n narration, telemetry, security register, visual regression, incremental graphify
