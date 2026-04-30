# Changelog

## v2.43.0 — `/vg:roam` + `/vg:deploy` + scope step 1b env preference (PR #64)

Bundles five reporter-internal milestones (v2.42.4 → v2.42.8) into a single minor release. Pure addition — 2367 insertions, 0 deletions. All built on top of v2.42.0's HARD env+mode+scanner gate and #63's `enrich-env-question.py` helper.

### Added — `/vg:roam` (NEW skill, 878 lines)

Exploratory CRUD-lifecycle pass that runs **after** `/vg:test` and **before** `/vg:accept`. Lens-driven brief composer + LLM executor + analyzer chain catches silent state-mismatches and lifecycle gaps that scripted tests miss.

- Step `0aa_resume_check` — 4 modes: fresh / `--force` / `--resume` / `--aggregate-only`. Closes the "không cache thì mỗi lần chạy là chạy mới à?" gap.
- Step `0a_env_mode_gate` — wires `enrich-env-question.py` from #63 (B2 roam wiring); env+mode+scanner gate options decorated with DEPLOY-STATE.json evidence.
- Step `0a_pre_prompt_1` — runtime backfill of `preferred_env_for` for phases scoped before step 1b landed (B4 backfill).
- Real dogfood validated: PrintwayV3 phase 03.4a-team-member-rbac-2fa with local Codex executor — 20 surfaces discovered, 20 INSTRUCTION files generated with verbatim creds, 5 min wall, 43k tokens, 9 JSONL events emitted, R1-R8 detectors processed correctly.
- New helpers: `roam-discover-surfaces.py` (145), `roam-compose-brief.py` (283), `roam-analyze.py` (300), `roam-merge-specs.py` (56).

### Added — `/vg:deploy` (NEW skill, 588 lines)

Standalone multi-env deploy command (sandbox/staging/prod) with prod typed-token confirmation. Writes `deployed.{env}` block to DEPLOY-STATE.json — sha, deployed_at, health, deploy_log path, previous_sha (for rollback), dry_run flag.

DEPLOY-STATE.json now drives env-suggestion across review/test/roam/accept.

### Added — `/vg:scope` step `1b_env_preference` (B3, +117 lines)

5-option preset writes `preferred_env_for` to DEPLOY-STATE.json after scope decisions lock:
- `auto` — heuristic per profile (feature → sandbox; security-critical → staging; emergency → prod)
- `all-sandbox` — every step on sandbox
- `most-common` — review/test on sandbox, roam/accept on staging
- `paranoid` — review/test on sandbox, roam on staging, accept on prod
- `all-local` — fastest iteration

### Pipeline (post-v2.43.0)

```
specs → scope (step 1b sets preferred_env_for)
      → blueprint
      → build
      → [/vg:deploy]                                          ← NEW
      → /vg:review  (env gate decorated by enrich-helper)
      → /vg:test    (same)
      → [/vg:roam]  (same; runtime backfill if pref missing)  ← NEW
      → /vg:accept
```

### Pending follow-up (not in this release)
- Wire `enrich-env-question.py` into `/vg:review` step 0a (B2 review part)
- Wire same into `/vg:test`
- `/vg:rollback` consumer reading `deployed.{env}.previous_sha`
- `/vg:next` routing — recommend `/vg:deploy` when user picks sandbox/staging/prod env at /vg:review without prior deploy

### Internal
- 234 tests pass (pure additive; no regressions in existing flow).
- Codex mirrors regenerated — now 69 skills (2 new: `vg-roam`, `vg-deploy`).
- Credit: external dogfood from @vietnhprintway (PrintwayV3, same arc as #57/#58/#60/#61/#62/#63 → v2.41.4/v2.42.0).

## v2.42.0 — HARD env+mode+scanner gate + 5 dogfood-driven fixes (PRs #58–#63)

External dogfood (@vietnhprintway, PrintwayV3) shipped 7 PRs in 24 hours after v2.41.4 — bundling 1 major review-flow gate change + 4 bug fixes + 2 features. v2.42.0 absorbs all of them.

### Major: HARD env+mode+scanner gate (PR #58)

Closes the silent-default gap on `/vg:review`. Pre-v2.42, review used `config.step_env.verify` silently — phases needed 2-3 review re-runs because env wasn't pinned and PIPELINE-STATE.json never recorded the choice. v2.41.2 added `<MANDATORY_GATE>` narrative; AI agents observably skipped it because the marker contract was `severity: warn`. v2.42.0 makes this a HARD `severity: block` gate with required telemetry event, closing the loophole.

- New step `<step name="0a_env_mode_gate">` with single batched `AskUserQuestion` 3-question payload: env (local/sandbox/staging/prod), mode (full/delta/regression/schema-verify/link-check/infra-smoke), scanner (haiku-only/codex-supplement/gemini-supplement/council-all).
- `must_touch_markers`: `0a_env_mode_gate` (default block severity, waiver `--non-interactive`).
- `must_emit_telemetry`: `review.env_mode_confirmed` required unless `--non-interactive` or all 3 axes on CLI.
- CLI flags: `--target-env=`, `--mode=`, `--scanner=` (and shortcuts `--local`/`--sandbox`/`--staging`/`--prod`).
- PIPELINE-STATE.json audit trail: `steps.review.{env, mode, scanner, profile, last_invoked_at, last_args}`.
- Banner echoes choices at start of `phase1_code_scan` so user sees `--scanner` honored.

### Major: Strict per-phase mockup gate (PR #59)

`/vg:blueprint` previously passed scaffold check whenever ANY shared/legacy manifest existed (e.g. `.vg/design-normalized/manifest.json` from initial Phase 1 design extract). Silent-passed every subsequent phase → builds shipped with AI-imagined UI. Now requires per-phase mockups by default; legitimate cross-phase reuse needs `--allow-shared-mockup-reuse`.

### Fixed (PR #60) — surface-probe heading format tolerance + api endpoint fallback chain

Backend-heavy phase hit `surface-probe.sh` regressions during `/vg:review` Phase 4a — every backend goal classified `NOT_SCANNED`, 4c-pre gate hard-blocked phase even though probes would have validated.

- `_surface_probe_get_goal_block`: matches `^## (Goal )?G-XX[^A-Za-z0-9_]` (optional "Goal " word + em-dash/hyphen). Pre-fix only matched canonical `## Goal G-XX:`; older template files using `## G-XX —` returned empty block → SKIPPED.
- `probe_api`: 3-layer endpoint extraction — strict `METHOD path` → path-only fallback (synthesize `ANY <path>`) → API-CONTRACTS.md cross-reference by goal id. Pre-fix required explicit `POST /api/v1/foo` in criteria bullet; natural prose like "Endpoint /api/v1/credits/grant tạo credit" returned SKIPPED.
- New SKIP message: `SKIPPED|no_endpoint_in_criteria_or_contracts` (only after all 3 layers fail).

### Fixed (PR #61) — orphan-run legacy fallback in read/clear_active_run

`run-status` / `run-complete` symmetry break: bash subshell wrote active run with `sid="unknown"` (no `CLAUDE_SESSION_ID` inherited), then Stop hook fired `run-complete` with the real session id and got `⛔ No active run to complete.`. Now `read_active_run` falls back to legacy snapshot when sid mismatches AND the legacy entry has the "unknown" sentinel — Stop hook can clean up orphan runs using the real session id.

### Fixed (PR #62) — zsh wordsplit shim for bash blocks under Claude Code

Claude Code runs bash via `/bin/zsh` on macOS (and Linux when zsh is the user's shell). zsh leaves unquoted `$VAR` unsplit by default — canonical bash patterns like `for a in $REQUIRED; do ...` (whitespace-split string) iterated ONCE with `$a` set to the entire string. 45+ skill bash blocks affected. New `commands/vg/_shared/lib/zsh-compat.sh` enables `setopt SH_WORD_SPLIT` (no-op under bash). Sourced by `block-resolver.sh`, `inject-rule-cards.sh`, `override-debt.sh`, `phase-profile.sh`.

### Feature (PR #63) — `enrich-env-question.py` DEPLOY-STATE-aware option decorator

New helper at `scripts/enrich-env-question.py` (262 lines). Future skill bodies (review/test/roam/accept) call it before their env+mode+scanner `AskUserQuestion` to decorate per-env labels + descriptions with evidence pulled from `${PHASE_DIR}/DEPLOY-STATE.json`. SUGGESTION ONLY — user still picks. 3-signal recommendation (per-phase preference > deploy freshness > profile heuristic).

### Triage
- Closed PR #57 as duplicate of #56 (already in v2.41.4).

### Internal
- 234 tests pass.
- All 6 PRs from external dogfood reporter (@vietnhprintway, PrintwayV3) — same week as #53/#55 reports. Strong signal-to-noise.

### Backward compatibility
- Existing `/vg:review` flags (`--skip-scan`, `--skip-discovery`, `--non-interactive`, etc.) unchanged.
- Phases that already pass all 3 env-mode-scanner axes on CLI (or use `--non-interactive`) skip the prompt — no behavior change for scripted/CI use.
- `--scanner=codex-supplement|gemini-supplement|council-all` records the choice in PIPELINE-STATE.json + emits banner; actual `codex exec` / `gemini` / Claude CLI dispatch wires in v2.42.1 (next iter).

## v2.41.4 — Headed-mode preservation in playwright MCP repair (closes PR #56)

### Fixed
- `verify-playwright-mcp-config.py` `_playwright_entry()` and `_render_codex_sections()` now bake `--no-headless` into the canonical MCP server template for both Claude (`settings.json`) and Codex (`config.toml`). Pre-fix, calling `--repair` (via `/vg:update`, `install.sh`, `sync.sh`) silently stripped any user-added `--no-headless` flag, breaking the documented HEADED-mode contract in `commands/vg/test.md` (lines 564, 650). Result: `/vg:review` Phase 2b Haiku scanners launched invisible browsers — operator couldn't watch the scan progress.

### Internal
- `@playwright/mcp` v0.0.71+ documents `--headless` (default-headed) and `--no-headless` (explicit) as durable flags.
- Existing `test_playwright_mcp_config.py` assertions still pass — `_user_data_dir()` helper locates `--user-data-dir` by name, unaffected by extra flags before it.
- Credit: external dogfood report from @vietnhprintway (PR #56), same reporter as #53 / #55.

## v2.41.3 — `/vg:update` Windows + gate-integrity hotfixes (closes #53, #55)

Bundles four cross-platform `/vg:update` hardening fixes reported by external dogfood (PrintwayV3 on macOS + a Windows install).

### Fixed
- **Issue #53 Bug #1 (CRITICAL)** — `vg_update.py:three_way_merge` now passes `encoding="utf-8"` to `subprocess.run`. Pre-fix, `text=True` defaulted to `locale.getpreferredencoding()` (cp1252 on Windows), which silently mojibake-decoded UTF-8 bytes ≥ 0x80 (`⛔` → `â›"`, `→` → `â†'`, `—` → `â€"`) and re-encoded as UTF-8 — corrupting hundreds of files in a single update run. Reporter measured 373 corrupted files + 134 false-positive conflicts on a v2.27.0 → v2.41.1 update before patching locally.
- **Issue #53 Bug #2 (HIGH)** — `vg_update.py:main()` reconfigures `sys.stdout` / `sys.stderr` to UTF-8 with `errors=replace` when the console default isn't already UTF-8. Pre-fix, `print("⛔ ...")` raised `UnicodeEncodeError` on Windows cp1252 console, breaking caller exit-code logic in `update.md` step 6b. No-op on Linux/macOS.
- **Issue #55 + #53 Bug #3 (MEDIUM, but blocks update flow)** — `_locate_gate_block` now anchors to `<step name="{gate_id}">` directly (gate_id is unique per manifest entry). Pre-fix, the locator used `text.find(fingerprint) + rfind("<step", 0, idx)` heuristic; when the fingerprint substring also appeared inside an unrelated earlier step block (boilerplate like `**Update PIPELINE-STATE.json:**`), it walked back to the wrong step and reported a false-positive `content_hash_mismatch`. Reproducer: `review.md` with both `<step name="0_parse_and_validate">` and `<step name="complete">` sharing common prose. Fingerprint kept as a deprecated fallback for legacy manifests.
- **Issue #53 Bug #4 (LOW but pernicious)** — `reapply-patches.md` patches-mode resolution loop + COUNT/REMAINING captures now pipe Python output through `tr -d '\r'`. Pre-fix on Windows, `python3 -c "print(...)"` emitted `\r\n`; bash `read -r REL` kept the trailing `\r`, so `${PATCHES_DIR}/${REL}\r.conflict` never existed → every entry reported "STALE — conflict file missing", manifest never drained.

### Triage
- Closed #54 (auto-report sig 4a039a9f, empty context block).
- Closed #46 + #40 (auto-reports from v2.31.1 / v2.28.0 — outdated, empty context, no repro).
- Updated #44 (v2.30.0 dogfood checklist superseded by v2.41.x flow).

### Internal
- 234 tests pass.
- `_locate_gate_block` regression test verifies duplicate-fingerprint scenario picks the right step.

### Notes
- No behavior change for healthy installs on Linux/macOS that didn't hit any of these edge cases.
- Windows users who completed a `/vg:update` between v2.40.x and v2.41.2 should run `/vg:update` again on v2.41.3 — the encoding fix only applies to NEW merges; previously corrupted files need to be restored from `.claude/vgflow-ancestor/v{prev}/` (see Issue #53 recovery section).

## v2.41.2 — Phase 2b-2.5 enforcement model fix (regression from v2.40.0)

User report: "/vg:review on another project just runs headless browser and reports bugs — no prompts for recursion / probe-mode / target-env, even after v2.41.1." Cross-AI review traced this to an enforcement-model regression: v2.40.0 introduced Phase 2b-2.5 by **nesting it inside `<step name="phase2_browser_discovery">`** instead of giving it its own step wrapper. v2.39.0 had 24 top-level `<step>` wrappers, each with profile filter + `must_touch_markers` entry + telemetry contract. Phase 2b-2.5 had none of these — orchestrator could (and did) silently skip the entire 142-line block.

### Fixed (root cause: enforcement model)
- `commands/vg/review.md`: split Phase 2b-2.5 into its own `<step name="phase2_5_recursive_lens_probe">` (profile=web-fullstack,web-frontend-only). 2b-3 (collect/merge) split into `<step name="phase2b_collect_merge">`. Both registered in `must_touch_markers` (severity: warn).
- New telemetry contract: `review.recursive_probe.preflight_asked` (required unless --non-interactive) + `review.recursive_probe.eligibility_checked` (always emitted with passed=true|false payload).
- AskUserQuestion pre-flight section now wrapped in `<MANDATORY_GATE>` — orchestrator can no longer lazy-skip.
- Bash anti-forge guard: refuses to launch with bare defaults if all three env vars empty + not in CI mode. Emits `review.recursive_probe.preflight_skipped` block-severity telemetry.

### Fixed (B2: dead lens prompts)
- `scripts/spawn_recursive_probe.py`: workers now actually load the lens markdown body from `commands/vg/_shared/lens-prompts/lens-*.md` (mirrors `spawn-crud-roundtrip.py:load_kit_prompt` pattern). Pre-v2.41.2 the 16 lens prompts sat unused on disk while workers received a 3-line generic prompt — explains why run artifacts came back empty.
- Placeholder substitution: `${VIEW_PATH}`, `${SELECTOR}`, `${ROLE}`, `${TOKEN_REF}`, `${PEER_TOKEN_REF}`, `${BASE_URL}`, `${OUTPUT_PATH}`, `${ACTION_BUDGET}`, etc. resolved before subprocess spawn. Unknown placeholders left as `${VAR}` literal (workers can detect missing context).
- Auth context loaded: `tokens.local.yaml` + `vg.config.md base_url:` injected into context block + lens body.

### Fixed (B3: silent eligibility skip)
- `scripts/spawn_recursive_probe.py:check_eligibility`: skip path now writes a stderr banner with per-rule actionable hints (e.g. "set `phase_profile: feature` in `.phase-profile`"), emits `review.recursive_probe.skipped` telemetry, and points at the `.recursive-probe-skipped.yaml` audit file. Pre-v2.41.2 the skip went silently to stdout mixed with Haiku scanner log → operators thought 2b-2.5 ran when it had failed eligibility silently.

### Internal
- `codex-skills/vg-review/SKILL.md` re-mirrored with new step boundaries + contract entries.
- 234 tests pass.

### Migration note for existing projects
Run `/vg:update` then `/vg:reapply-patches` (if you have local edits to `review.md`). The next `/vg:review` will show three AskUserQuestion prompts before browser probes start.

## v2.41.1 — Phase 2b-2.5 interactive prompt fix (orchestrator-layer)

### Fixed (UX, regression from v2.40.0)
- `/vg:review` under Claude Code now actually prompts for `--recursion`, `--probe-mode`, `--target-env` when the operator omits them.
  - **Root cause:** Claude Code's bash sandbox makes `sys.stdin.isatty()` return `False`, so the script-side `input()` prompts in `spawn_recursive_probe.py` silently fell back to defaults (`light` / `auto` / `sandbox`). Additionally, the bash block hard-coded `RECURSION_MODE="${RECURSION_MODE:-light}"` and `PROBE_MODE="${PROBE_MODE:-auto}"`, so even when the script's TTY check would have fired, the env vars were always pre-set → script defaults won.
  - **Fix:** Phase 2b-2.5 now uses `AskUserQuestion` at the command (review.md) layer, which Claude Code surfaces natively. Bash forwards each axis only when set; argparse defaults apply otherwise. `VG_NON_INTERACTIVE=1` still suppresses prompts for CI.

### Internal
- `commands/vg/review.md` — new "Pre-flight (v2.41.1) — operator config via AskUserQuestion" section before the bash invocation
- Bash block restructured to forward `--mode` / `--probe-mode` / `--target-env` only when corresponding env var is set
- `codex-skills/vg-review/SKILL.md` re-mirrored for parity gate

### Notes
- No behavior change for non-interactive callers (CI, `--non-interactive`, piped runs) — they continue to use script defaults.
- No behavior change for terminal-direct callers (running `python scripts/spawn_recursive_probe.py` outside Claude Code) — script-side TTY prompt still works as fallback.

## v2.41.0 — Backlog Closure (Tier-2 wiring + Telemetry + Hybrid mode)

### Added
- Tier-2 element classifier wiring (5 previously-unreachable lenses now active: open-redirect, ssrf, auth-jwt, business-logic, info-disclosure)
- Hybrid probe-mode actual implementation per `vg.config.md review.recursive_probe.hybrid_routing`
- Telemetry emissions: `recursion.state_hash_hit`, `recursion.mutation_budget_exhausted`

### Fixed
- `/vg:review-batch` production entry point — multi-fallback resolution (VG_REVIEW_CMD env > claude CLI > python -m vg.review > hard-fail)
- Hybrid mode no longer hard-fails — actual per-lens routing implemented

### Internal
- `scripts/identify_interesting_clickables.py` — 6 Tier-2 detectors (replaces stubs from v2.40.0)
- `scripts/_telemetry_helpers.py` — append-only `.vg/telemetry.jsonl` event emitter
- 30 new tests across Tier-2, telemetry, hybrid mode

### Closes
- v2.40 backlog #1 (review_batch entry), #2 (Tier-2 wiring), #4 (telemetry), #5 (hybrid impl)

### Still deferred
- #3 Real LLM dogfood (needs user-supplied phase fixture + GEMINI_API_KEY)
- #6 Codex GPT-5 xhigh re-review (user-driven; prompt parked)

## v2.40.2 — Manual mode per-tool subdirs + minor fixes

### Fixed (UX)
- Manual mode now generates per-tool prompt subdirs (`recursive-prompts/{codex,gemini}/`) — user picks which CLI to paste into without conflicts
- Per-tool output subdirs (`runs/{codex,gemini}/`) — artifacts isolated, no overwrite when running both tools on same phase
- Per-probe paste file shortened ~15 lines (refs lens file by path instead of inlining full text) — easier copy-paste UX
- Tool-specific token env: `GEMINI_PROBE_TOKEN` for gemini, `CODEX_PROBE_TOKEN` for codex

### Fixed (correctness)
- Hybrid mode now hard-fails with clear v2.41 deferred message (was silently falling back to auto, hiding limitation from user)

### Fixed (docs)
- Plan docs updated 14→16 lenses (cosmetic drift from Task 17 reality check)

### Added flags
- `scripts/generate_recursive_prompts.py --tools="gemini,codex"` (default both, single tool OK)
- `scripts/verify_manual_run_artifacts.py --tool={gemini,codex,both}` (default both)

## v2.40.1 — Interactive target_env prompt

### Added
- Interactive target_env selection at Phase 2b-2.5 when `--target-env` flag NOT provided AND `--non-interactive` NOT set
- Prod confirmation: typing exact phase name required to prevent accidental prod targeting (analog to GitHub repo deletion safety)

### UX improvement
Before: user had to remember/type `--target-env=sandbox` every review.
After: VG prompts on each interactive review with 4 clear options + safety confirmation for prod.

### Files
- Modified: scripts/spawn_recursive_probe.py (+~80 LOC — `prompt_target_env`, `confirm_prod_target`, `_config_has_explicit_target_env`, main() wiring)
- Modified: commands/vg/review.md (Phase 2b-2.5 invocation: `--target-env` only forwarded when caller pinned it)
- Added: tests/test_spawn_recursive_probe_target_env_prompt.py (8 tests)

## v2.40.0 — Recursive Lens Probe + Multi-Phase Batch + Sandbox Env

### Added
- Phase 2b-2.5 recursive lens probe layer in `/vg:review` — exploratory deep-scan style (Strix-spider, NOT scripted), 16 bug-class lenses
- 14+2 lens prompts in `commands/vg/_shared/lens-prompts/` covering authz, injection, auth, bizlogic, server-side, ui-mechanic, redirect bug classes
- Phase 0 diagnostic gate — `--debug` flag + base_url multi-location resolver + fail-fast guard + crud-roundtrip kit imperative preamble
- 6-rule eligibility check with auto-skip + override (`--skip-recursive-probe="<reason>"` logs OVERRIDE-DEBT critical)
- 3 probe modes: `auto` (subprocess workers), `manual` (paste prompts in CLI), `hybrid` (split per lens config)
- Interactive prompt at Phase 2b-2.5 (with `--non-interactive` for CI)
- `/vg:review-batch` for multi-phase deep-scan (sequential, aggregates BATCH-FINDINGS-{date}.json)
- Target environment policy: `--target-env={local,sandbox,staging,prod}` with prod read-only safeguard via `--i-know-this-is-prod="<reason>"`
- Per-tool subdir isolation: `runs/{gemini,codex,claude}/recursive-*.json`
- Goal back-flow with canonical-key dedupe: light=50, deep=150, exhaustive=400 caps + recursive-goals-overflow.json
- Mode caps: light/deep/exhaustive (depth 2/3/4, workers ~15/40/100)
- Probe-only contract: workers report facts, no severity/fix/exploit reasoning (delegated to derive-findings.py downstream)

### Fixed
- Phase 0 production bug: base_url silently null when REPO_ROOT/.claude/vg.config.md missing → workers got null URL (H1, commit `2292dc7`)
- Phase 0 production bug: kit prompt advertised legacy field names (route_list/create) but context_block nests under platforms_web.list.route → ambiguous prompt (H3, commit `0323ba0`)
- Auth token leak in --debug log via cmd[:5] slice (commit `28e51c9`) — security fix

### New configs (vg.config.md)
- `review.recursive_probe.{default_mode,default_probe_mode,worker_concurrency,max_depth_overrides,activation_profiles,activation_surfaces,hybrid_routing}`
- `review.target_env: "sandbox"` (default)
- `review.prod_safety.require_reason_flag: true`
- `review.batch.{parallelism,continue_on_phase_fail}`

### New commands
- `/vg:review --recursion={light,deep,exhaustive} --probe-mode={auto,manual,hybrid} --target-env={local,sandbox,staging,prod}`
- `/vg:review-batch --phases <p1,p2,...>` OR `--milestone <M>` OR `--since <git-sha>`

### New scripts
- `scripts/spawn_recursive_probe.py` — manager dispatcher (eligibility + lens map + worker spawn)
- `scripts/generate_recursive_prompts.py` — manual mode template renderer
- `scripts/verify_manual_run_artifacts.py` — BLOCK validator post-manual-paste
- `scripts/identify_interesting_clickables.py` — Tier-1 element classifier
- `scripts/aggregate_recursive_goals.py` — single-writer goal dedupe + overflow
- `scripts/canonicalize_url.py` — URL state-hash memoization
- `scripts/env_policy.py` — per-env constraints (local/sandbox/staging/prod)
- `scripts/review_batch.py` — multi-phase orchestrator

### Internal
- 16 lens prompt files + _TEMPLATE.md + README.md in `commands/vg/_shared/lens-prompts/`
- Manual mode templates in `commands/vg/_shared/templates/MANUAL-PROBE-{MANIFEST,PER-LENS}.tmpl`
- 100+ new tests across 18+ test files
- Pre-existing v2.39 pipeline (findings-broker, derive-findings, replay-finding, route-findings-to-build, challenge-coverage) reused without modification

### Closes
- #50 (review không dò thông minh — recursive layer + 16 bug-class lenses + exploratory style)

### Deferred to v2.41+
- Tier-2 element classifier wiring (currently 5 lenses unreachable: open-redirect, ssrf, auth-jwt, business-logic, info-disclosure)
- State hash actual implementation (test scaffold present, telemetry emit deferred)
- Mutation budget telemetry emission (test scaffold present)
- Hybrid mode per-lens router (currently falls back to auto)
- Real LLM dogfood (mocked in test suite — see `docs/plans/2026-04-30-v2.40-dogfood-deferred.md`)
- Codex GPT-5 xhigh re-review (open question #2 in design doc)

## v2.39.0 (2026-04-30) — Charter-violation closer (Codex review v2.38)

After v2.34→v2.38 arc, asked Codex GPT-5 for adversarial review against VG's specific charter (contract-driven white-box, NOT Strix-style black-box pentest). Verdict was sharp: **"not adequate for first dogfood yet — risk of artifact-driven theater"**. 7 charter violations identified.

This release closes the top 5. No new transition kits — Codex prescribed dogfood-driven hardening only.

### Codex critique #1 — Contract validity not gated → `verify-contract-completeness.py`

Charter says contract-driven, but CRUD-SURFACES.md was treated as ground truth without proof it reflects the actual app domain. If planner missed a sensitive resource, every downstream review passes while reviewing the wrong system.

NEW `scripts/verify-contract-completeness.py` diffs runtime/code inventory against declared resources:
- HTTP routes from `routes-static.json` (v2.35) not mapped to any declared resource → flagged
- DB model class names (Mongoose / SQLAlchemy / Prisma / Django / TypeORM) not in contract → flagged
- Background job patterns (BullMQ Queue, Celery task, cron schedule, agenda) → flagged for explicit declaration
- Webhook handlers (`/webhooks/*`, `/callbacks/*`) → flagged

Wired into `review.md` as new Phase 2c-pre (before worker dispatch — saves token cost when contract obviously incomplete).

### Codex critique #6 — No env contract → `ENV-CONTRACT.md` + preflight gate

Workers spawn against environments with implicit state. Empty seed data → empty list views render gracefully → review passes. Tokens valid but for wrong tenant. Mutations succeed but third-party callbacks live-fired into prod.

NEW required artifact `commands/vg/_shared/templates/ENV-CONTRACT-template.md` declares:
- `target.base_url` + health endpoint
- `seed_users` (with stable user_id + tenant_id for cross-resource auth tests)
- `seed_data` expectations (count_min per resource, must_include_states)
- `feature_flags` expected ON/OFF
- `third_party_stubs` (stripe/sendgrid/s3 mode: stubbed | live | not_used)
- `runtime_state` (migrations applied, search indexes, message queues)
- `preflight_checks[]` — concrete probes verified before workers spawn
- `out_of_scope[]` — explicit exclusions

NEW `scripts/verify-env-contract.py` runs preflight probes pre-spawn. Mandatory for kits crud-roundtrip / approval-flow / bulk-action. Optional for static-sast (no UI runtime).

Override path: `--skip-env-contract="<reason>"` logs OVERRIDE-DEBT critical entry.

### Codex critique #5 — Artifacts pass without reproducibility → replay manifest + `replay-finding.py`

Findings could pass review but couldn't be re-executed during human triage. First dogfood findings would be disputed or impossible to rerun.

UPDATED `crud-roundtrip.md` kit prompt — every finding now MUST include `replay` block:

```json
"replay": {
  "commit_sha": "...",
  "worker_prompt_version": "crud-roundtrip.md@<mtime>",
  "env": {"base_url": "...", "phase_dir": "..."},
  "fixtures_used": {"role": "...", "user_id": "...", "tenant_id": "..."},
  "seed_payload_pattern": "vg-review-{run_id}-create",
  "request_sequence": [{"step": "...", "method": "...", "url": "...", "headers": {}, "body": {}, "expected_status": 201, "observed_status": 201, "response_excerpt": "..."}]
}
```

NEW `scripts/replay-finding.py --finding-id F-001` re-executes the recorded request sequence with fresh tokens (substitutes `${TOKEN}` from `tokens.local.yaml`) and reports REPRODUCES vs DOES_NOT_REPRODUCE. Detects commit drift between recording and replay.

### Codex critique #3 — Auth model too role-table-shaped → object-level steps

"admin/user" matrices miss ownership / tenancy / record state / delegation. PrintwayV3 will likely break here.

UPDATED `crud-roundtrip.md` kit with 4 mandatory steps for `scope: owner-only` / `tenant-scoped` resources:

- **Step 9** — Cross-owner read (IDOR): user_b GETs entity owned by user_a → expect 403/404
- **Step 10** — Cross-tenant read (tenant leakage): user_other_tenant GETs entity → expect 403/404 (THE worst bug class for multi-tenant SaaS)
- **Step 11** — Cross-owner mutation (privilege escalation): user_b PATCH/DELETEs user_a's entity → expect 403/404. Also checks audit log captures correct actor.
- **Step 12** — State-locked operation: mutate entity in `published`/`archived` state → expect 403/409 if state declared read-only

UPDATED `CRUD-SURFACES-template.md` schema — new `expected_behavior.object_level` block declares per-scope expected behavior. UPDATED `spawn-crud-roundtrip.py` injects `lifecycle_states` + `object_level_auth` into worker context.

### Codex critique #7 — Manager synthesis under-specified → `challenge-coverage.py`

Many workers, but no adversarial reducer challenging worker claims. Workers can mark step-3 (read-after-create) PASS because something new appeared in list, without proving it's the just-created entity with submitted values.

NEW `scripts/challenge-coverage.py` — heuristic challenger:
- Samples 25% of run artifacts (configurable)
- Per pass step: requires non-empty `evidence_ref` AND non-empty `observed` block
- Cross-checks observed status numerically against expected status — mismatch → flagged `false-pass`
- Empty evidence/observed → downgraded to `weak-pass`
- Output: `COVERAGE-CHALLENGE.json` + per-run verdict (STRONG / WEAK / DEGRADED)

Wired into `review.md` as Phase 2e-post (after findings derive, before auto-fix routing).

v2.40 may extend with LLM-driven challenge for ambiguous claims (cheap Sonnet pass).

### Charter compliance — what this DOESN'T fix

Codex critiques #2 (negative-space verification beyond routes) and #4 (data lifecycle coverage: audit logs, soft deletes, orphan files, background job side effects) are partially addressed:

- #2: contract completeness checks routes + DB models + jobs + webhooks. Does NOT yet check: feature-flag-gated paths, server-rendered SSR routes, GraphQL schema, gRPC services.
- #4: object-level Step 9-12 catch some side-effect classes (audit log actor mismatch, state lock). Does NOT yet check: orphan file cleanup, search index invalidation, billing counter drift, queue consumer lag.

These are **opt-in v2.40+** territory — first dogfood data on PrintwayV3 should drive priority.

### Files

- **NEW** `scripts/verify-contract-completeness.py`
- **NEW** `scripts/verify-env-contract.py`
- **NEW** `scripts/replay-finding.py`
- **NEW** `scripts/challenge-coverage.py`
- **NEW** `commands/vg/_shared/templates/ENV-CONTRACT-template.md`
- **MODIFIED** `commands/vg/_shared/transition-kits/crud-roundtrip.md` — Steps 9–12 + replay manifest schema
- **MODIFIED** `commands/vg/_shared/templates/CRUD-SURFACES-template.md` — `expected_behavior.object_level` schema
- **MODIFIED** `scripts/spawn-crud-roundtrip.py` — inject lifecycle_states + object_level_auth
- **MODIFIED** `commands/vg/review.md` — new Phase 2c-pre + Phase 2e-post
- **MODIFIED** `vg.config.template.md` — 3 new gate config blocks

### Sequence

- v2.34–v2.38: 5-release "review hời hợt" arc (closes #49, #50, #51, #52)
- **v2.39.0 (this)**: Codex charter-violation closer (5 of 7 critiques addressed)
- v2.40+: dogfood-driven (negative-space verification, data lifecycle, LLM-challenge)

This release puts review at "ready for first dogfood on PrintwayV3" per Codex's verdict criteria.

---

## v2.38.1 (2026-04-30) — fix changelog preview + GH release notes auto-extract

User reported on a different machine running `/vg:update`:

> "CHANGELOG không có entry giữa v2.31.1 → v2.38.0 (chắc CHANGELOG.md chưa cập nhật trên main branch). Release notes chỉ ghi 'Automated release. Gate-manifest published for /vg:update T8 integrity verification.'"

Two converging bugs:

### 1. `commands/vg/update.md:146` regex format mismatch

`/vg:update` step 3 (changelog preview) used regex:

```python
re.compile(r'## \[(\d+\.\d+\.\d+)\].*?(?=## \[|\Z)', re.S)
```

Expected `## [2.38.0]` (Keep-a-Changelog bracketed format), but VG's CHANGELOG uses `## v2.38.0 (date) — title` (no brackets, leading `v`). Regex never matched → preview always printed `(no changelog entries between versions)`.

**Fix:** updated regex to support both formats:

```python
re.compile(
    r'^## (?:\[)?v?(\d+\.\d+\.\d+)(?:\])?[^\n]*\n.*?(?=^## (?:\[)?v?\d+\.\d+\.\d+|\Z)',
    re.S | re.M,
)
```

Smoke verified: 8 entries (v2.32.0, 2.32.1, 2.33.0, 2.34.0, 2.35.0, 2.36.0, 2.37.0, 2.38.0) all matched against current CHANGELOG.md.

### 2. `.github/workflows/release.yml` hardcoded notes placeholder

The release workflow used a static `--notes "Automated release. See CHANGELOG..."` string for every release. CHANGELOG section was never extracted into the GitHub UI release notes body.

**Fix:** new "Extract CHANGELOG section for release notes" step parses `CHANGELOG.md` for the section matching the version tag and feeds it via `--notes-file release-notes.md`. The footer line ("Gate-manifest published for /vg:update T8 integrity verification.") is appended below the changelog body.

Also: existing-release path now calls `gh release edit --notes-file` to update notes if the workflow is re-run on an existing tag.

### 3. Backfilled release notes for v2.32.0 → v2.38.0

8 releases had the placeholder notes shipped before this fix. Manual backfill via `gh release edit --notes-file` ran today; user can refresh GH page to see proper changelog content for each release. Going forward, releases use auto-extract via the workflow change.

### Files

- **MODIFIED** `commands/vg/update.md` — line 146 regex fixed
- **MODIFIED** `.github/workflows/release.yml` — new notes-extract step + edit existing notes path

### Self-bootstrap awareness

This is exactly the kind of bug v2.29.0's update self-bootstrap (#42) was designed for. Users on stale `/vg:update` get the broken regex behavior on the FIRST update run after this fix lands, but `commands/vg/update.md` ships in the tarball; subsequent runs use the fixed regex.

---

## v2.38.0 (2026-04-30) — Flow compliance auditor (per-step verifier)

User feedback: with override flags like `--skip-discovery`, `--evaluate-only`, `--retry-failed`, AI can silently bypass required steps in any flow. The verdict gate (v2.35) catches missing artifact content, but it doesn't catch "AI ran a degraded path that produces *some* artifacts but skipped critical steps".

This release adds an end-of-flow auditor: after every `/vg:blueprint`, `/vg:build`, `/vg:review`, `/vg:test`, `/vg:accept`, verify that the AI executed all required evidence-producing steps for the phase profile.

### How it works (evidence-based, not marker-based)

VG's existing `.step-markers/{step}.done` mechanism has inconsistent naming across commands. v2.38 uses **artifact evidence** instead — file presence proves a step ran:

| Step semantically | Evidence file pattern |
|---|---|
| `phase1_code_scan` | (no required evidence — internal state) |
| `phase2_browser_discovery` | `nav-discovery.json` + `scan-*.json` |
| `phase2c_enrich` | `TEST-GOALS-DISCOVERED.md` (optional v2.34) |
| `phase2d_crud_dispatch` | `runs/INDEX.json` (optional v2.35) |
| `phase2e_findings` | `REVIEW-FINDINGS.json` (optional v2.35) |
| `phase4_goal_comparison` | `GOAL-COVERAGE-MATRIX.md` |
| `build_executor` | `SUMMARY.md` |
| `test_codegen` | `SANDBOX-TEST.md`, `GENERATED_TESTS_DIR/*.spec.ts` |
| `accept_uat` | `UAT.md` |

Each (command × phase profile) pair declares `evidence_required` (must exist) and `evidence_optional` (don't fail if missing) in `commands/vg/_shared/templates/FLOW-COMPLIANCE.yaml`.

### Profile-aware

Phase profile detected from `SPECS.md` frontmatter (`phase_profile: feature|infra|hotfix|bugfix|migration|docs|feature-legacy`) or `vg.config.md → default_profile`.

Different profiles → different required evidence:

```yaml
review:
  feature:
    evidence_required:
      - nav-discovery.json
      - scan-*.json
      - GOAL-COVERAGE-MATRIX.md
  feature-legacy:
    evidence_required:
      - GOAL-COVERAGE-MATRIX.md     # no browser scan required
  infra:
    evidence_required:
      - SUMMARY.md                   # phaseP_infra_smoke writes here
  docs:
    evidence_required:
      - SUMMARY.md                   # phaseP_link_check writes here
```

### Override path (consistent with rest of pipeline)

Flag `--skip-compliance="<reason>"` logs OVERRIDE-DEBT critical entry, allows flow to proceed. Reviewer must triage at next `/vg:accept`.

### Aggregated at accept

`/vg:accept` runs `verify-flow-compliance.py --command accept` which:
1. Audits accept's own evidence (`UAT.md`)
2. Aggregates `.flow-compliance-{blueprint,build,review,test}.yaml` from prior flows
3. Reports any flow that ran non-compliant without override
4. BLOCK if cross-flow compliance failed (or WARN per config)

This is the cross-flow gate: bắt patterns where AI bypassed required steps anywhere in pipeline, surfaced at accept time.

### Severity ramp

v2.38 ships with `severity: warn` default for dogfood. Promote to `block` via `vg.config.md → flow_compliance.severity: "block"` after observing real-world false-positive rate.

### Files

- **NEW** `commands/vg/_shared/templates/FLOW-COMPLIANCE.yaml` — profile × command × evidence matrix
- **NEW** `scripts/verify-flow-compliance.py` — auditor script
- **MODIFIED** `commands/vg/build.md` — post-flow compliance check before run-complete
- **MODIFIED** `commands/vg/review.md` — same
- **MODIFIED** `commands/vg/test.md` — same
- **MODIFIED** `commands/vg/accept.md` — aggregate cross-flow check before mark-step accept
- **MODIFIED** `vg.config.template.md` — `flow_compliance: { enabled, severity, template_path }` block

### Smoke verified

- Phase missing required evidence → exit 1 with concrete missing list
- Same with `--skip-compliance="<reason>"` → exit 0 with WARN logged
- Phase with all required → exit 0 COMPLIANT

### Sequence — arc + post-arc complete

- v2.34 — review→test back-flow (#52)
- v2.35 — CRUD round-trip + scanner invariants (#50, #51)
- v2.36 — TEST-GOALS expansion + 2 kits (#49)
- v2.37 — auto-fix loop + code-only SAST + inter-worker broker
- **v2.38 (this)** — flow compliance auditor (post-arc gap closer)

This closes the last category of "AI bypass step" risk. The remaining 20% gap to Strix parity (specialized vuln skills, external recon tools, OAST) is opt-in expansion territory, not architectural.

---

## v2.37.0 (2026-04-30) — Auto-fix loop + code-only SAST + inter-worker broker

Final piece of the 4-release "review hời hợt" remediation arc. Closes the remaining gaps from the v2.35 Codex review:

- **Auto-fix feedback loop** — review findings can flow into `/vg:build` as remediation tasks (opt-in)
- **Code-only review path** — phases without UI runtime (backend-only, CLI, library) get static SAST kit
- **Inter-worker context sharing** — Strix's "real-time finding broadcast" pattern for parallel CRUD round-trip workers

### W1 — Auto-fix loop

`scripts/route-findings-to-build.py` reads `REVIEW-FINDINGS.json` (v2.35) and emits `AUTO-FIX-TASKS.md` with /vg:build-consumable task entries. Conservative gate per Codex feedback:

- Severity ≥ high
- Confidence == high
- cleanup_status == completed (data integrity)
- Group by dedupe_key (1 fix can address N occurrences)

Wired into `commands/vg/review.md` as new Phase 2f after findings derivation. Opt-in: `/vg:build {phase} --include-auto-fix` consumes (default off in v2.37; may flip to default-on in v2.38 after dogfood).

Each task entry includes:
- Severity, confidence, security_impact, CWE
- Affected resources × roles
- Dedupe key + occurrence count
- Remediation steps (from finding)
- Repro preconditions
- Source finding IDs
- /vg:build instructions for the executor

### W2 — Code-only SAST kit

`commands/vg/_shared/transition-kits/static-sast.md` — third transition kit, for phases without UI runtime. LLM-driven static analysis: triages SAST candidates (semgrep or fallback), traces data flow, emits findings with `data_flow` field replacing `poc_script_code` (no PoC for static).

`scripts/static-sast-runner.py` — SAST candidate generator. Two modes:
- `semgrep` present → `semgrep --config=auto`
- `semgrep` missing → fallback regex patterns for 8 bug classes:
  - `injection` (SQLi/NoSQLi/cmd)
  - `secrets` (hardcoded keys/tokens/JWT secrets)
  - `broken-auth` (route without middleware)
  - `idor` (object query without scope check)
  - `unsafe-deserialize` (pickle/yaml/eval)
  - `mass-assignment` (`...req.body` spread)
  - `path-traversal` (fs ops with user input)
  - `crypto-weak` (MD5/SHA1 for auth, AES-ECB)

Smoke-tested: 7 detections across 5 bug classes from a 14-line vulnerable JS fixture (SQL concat + JWT secret + admin route + IDOR + pickle.loads).

### W3 — Inter-worker findings broker

`scripts/findings-broker.py` — polls `runs/` during dispatch, broadcasts critical findings to in-flight workers via `runs/.broker-context.json`. Workers MAY check this file at step boundaries.

Default broadcast triggers (Strix-inspired):
- `auth_bypass_critical` — severity=critical + security_impact=auth_bypass
- `tenant_leakage_critical` — severity=critical + security_impact=tenant_leakage
- `credential_in_response` — token/secret/api_key in finding's response evidence

Each broadcast includes `actionable_for_other_workers[]` — concrete suggestions like "if you're testing the same role, try other admin routes — the bypass may be middleware-wide" or "inspect your responses for token leakage".

Two modes:
- Snapshot (`--phase-dir <path>`) — one-shot scan + write
- Daemon (`--daemon --interval 5`) — alongside `spawn-crud-roundtrip.py`, polls until INDEX.json shows complete

### Files

- **NEW** `scripts/route-findings-to-build.py`
- **NEW** `commands/vg/_shared/transition-kits/static-sast.md`
- **NEW** `scripts/static-sast-runner.py`
- **NEW** `scripts/findings-broker.py`
- **MODIFY** `commands/vg/review.md` — Phase 2f (route auto-fix)

### Sequence — arc complete

Per discussion 2026-04-30, this completes the 4-release remediation:

- v2.34.0 — review→test back-flow (closes #52)
- v2.35.0 — CRUD round-trip + scanner invariants (closes #50, #51)
- v2.36.0 — TEST-GOALS expansion + 2 kits (closes #49)
- **v2.37.0 (this)** — auto-fix loop + code-only SAST + inter-worker broker

All 4 issues opened on the "review hời hợt" pattern (#49, #50, #51, #52) are now closed. Arc summary:

| Layer | Before arc | After arc |
|---|---|---|
| Goal layer | ~67 manual high-level | 60-100 manual + 200-400 expanded + 50-150 discovered = **3-source coverage** |
| Worker tier | Haiku 4.5 ($1/M) | Gemini Flash ($0.075/M) — **13× cheaper** |
| Discovery | sidebar-bound 1-role | 3-role auth-aware + iterative re-discovery + static route extractor |
| Verdict gate | path-existence check | 3 content invariants — AI cannot bypass with empty artifacts |
| Findings | none | Strix-style with PoC, dedupe, confidence, repro_preconditions |
| Bug → fix | manual triage | opt-in auto-route via AUTO-FIX-TASKS.md |
| Code-only phases | Haiku navigator (broken) | static-sast kit + semgrep wrapper |
| Cross-worker context | none | broker broadcasts critical findings |

---

## v2.36.0 (2026-04-30) — TEST-GOALS expansion + 2 transition kits (closes #49)

Continues v2.35.0's CRUD round-trip foundation. Closes the planner-time gap where blueprint declared 67 high-level goals while CRUD-SURFACES.md specified 200-300 verification points. Adds 2 more transition kits per Codex review feedback ("CRUD round-trip is a good primitive for simple admin surfaces, not a universal review primitive").

### Closes #49 — blueprint expand TEST-GOALS from CRUD-SURFACES

- **NEW** `scripts/expand-test-goals-from-crud-surfaces.py` — reads CRUD-SURFACES.md, enumerates per-resource × per-operation × per-role × per-variant (filter / sort / pagination / state / row_action / bulk_action), dedupes against existing TEST-GOALS.md + TEST-GOALS-DISCOVERED.md, emits `TEST-GOALS-EXPANDED.md` with `G-CRUD-*` IDs.
- **MODIFIED** `commands/vg/blueprint.md` — new sub-step `2b5d_expand_from_crud_surfaces` after TEST-GOALS + CRUD-SURFACES generation.
- **MODIFIED** `commands/vg/test.md` — sub-step `5d-auto` now reads BOTH `TEST-GOALS-DISCOVERED.md` (runtime, v2.34) AND `TEST-GOALS-EXPANDED.md` (planner, this release).
- **MODIFIED** `scripts/codegen-auto-goals.py` — accepts both `G-AUTO-*` and `G-CRUD-*` prefixes.

### 3-source goal layer (complete)

```
TEST-GOALS.md            ← manual high-level (blueprint primary, ~60-100 goals)
TEST-GOALS-EXPANDED.md   ← planner expansion from CRUD-SURFACES (~200-400 goals)  [NEW v2.36]
TEST-GOALS-DISCOVERED.md ← runtime UI scan emit (~50-150 goals)                   [v2.34]
```

Smoke test: 1 resource × 5 ops × 2 roles × 4 filters/sorts × 4 states × 3 row-actions × 1 bulk-action → **36 expansion goals** from a single resource. Realistic phase (10 resources): 200-400 expansion goals matching Codex's predicted verification surface.

### Goal categories emitted

| Variant | Stub format | Priority |
|---|---|---|
| Operation × role | `G-CRUD-{resource}-{op}-{role}` | critical (mutation) / important (read) |
| Filter | `G-CRUD-{resource}-list-{role}-filter-{name}` | important |
| Sort column | `G-CRUD-{resource}-list-{role}-sort-{column}` | important |
| Pagination | `G-CRUD-{resource}-list-{role}-paging` | important |
| State (loading/empty/error/zero_result/unauthorized) | `G-CRUD-{resource}-list-{role}-state-{name}` | nice-to-have / important |
| Row action | `G-CRUD-{resource}-row-{role}-{action}` | important |
| Bulk action | `G-CRUD-{resource}-bulk-{role}-{action}` | important |

Each stub has `expected_status` derived from CRUD-SURFACES `expected_behavior[role][op]` matrix — not a global naive role matrix (Codex critique #4 fix).

### 2 more transition kits (Codex critique #1 fix)

CRUD round-trip alone misses approval workflows, bulk operations, settings toggles, async jobs. v2.36 ships:

- **NEW** `commands/vg/_shared/transition-kits/approval-flow.md` — 8-step lifecycle test for resources with pending → approved/rejected state machine. Tests separation-of-duties (requester cannot approve own request), audit log emit on state transition, idempotency on re-approve, invalid transitions (reject → approve).
- **NEW** `commands/vg/_shared/transition-kits/bulk-action.md` — 8-step multi-select + batch test. Tests partial-failure handling (5 succeed / 2 fail), batch limit enforcement (DoS), unauthorized role bulk-mutate bypass, race-condition probe (rows changing during op).

Resources opt-in via `kit:` field in CRUD-SURFACES.md:

```yaml
resources:
  - name: topup_requests
    kit: approval-flow              # was crud-roundtrip
    requester_role: user
    approver_role: admin
    lifecycle_states: [pending, approved, rejected]
```

### Token cost (estimated per phase)

- Blueprint expansion: ~$0.00 (deterministic Python script, no LLM)
- Worker dispatch (Gemini Flash): same as v2.35 (~$0.045 per 30 round-trip workflows)
- Codegen 5d-auto: same as v2.34 (template-based, no LLM)

Net: same cost as v2.35, **3-5× more goal coverage**.

### Files

- **NEW** `commands/vg/_shared/transition-kits/approval-flow.md`
- **NEW** `commands/vg/_shared/transition-kits/bulk-action.md`
- **NEW** `scripts/expand-test-goals-from-crud-surfaces.py`
- **MODIFIED** `commands/vg/blueprint.md` (+1 sub-step)
- **MODIFIED** `commands/vg/test.md` (5d-auto reads both sources)
- **MODIFIED** `scripts/codegen-auto-goals.py` (accepts G-CRUD-* prefix)

### Sequence note

This is fix 3 of 4 for the systemic *"review hời hợt"* pattern:

- v2.34.0 (shipped) — review→test back-flow (closes #52)
- v2.35.0 (shipped) — CRUD round-trip + scanner invariants (closes #50, #51)
- **v2.36.0 (this)** — TEST-GOALS expansion + approval-flow + bulk-action (closes #49)
- v2.37.0 — auto-fix loop + code-only SAST kit + inter-worker findings broker

---

## v2.35.0 (2026-04-30) — CRUD round-trip review (closes #50, #51)

User feedback: review pipeline is "hời hợt" — prescribed exhaustive scan, target wrong roles, wastes tokens, fails to find real bugs. CRUD operations are not independent lenses; they're a chained workflow with Read interleaved between mutations to verify persistence.

This release reshapes review's bug-finding strategy around two ideas borrowed from `usestrix/strix`:

1. **Skills are prompts, not code** — the kit prompt `crud-roundtrip.md` teaches an LLM how to find bugs in a CRUD resource. No prescribed click-everything workflow.
2. **Run artifacts, not findings-only** — workers emit `coverage{attempted, passed, failed, blocked, skipped}` per workflow run. Findings derived from `steps[].status==fail`. Verdict gate distinguishes "ran clean" from "didn't run".

After Codex GPT-5 cross-AI review, the abstraction was widened from "5 CRUD lenses" to "state transition with invariants" — `(role, resource, precondition, action, expected_state_delta, forbidden_side_effects)`. CRUD round-trip is the first kit; v2.36+ will add approval-flow, bulk-action, settings-toggle.

### Architecture

```
Manager (Claude Sonnet via Task)              ← reads CRUD-SURFACES, dispatches
  ├─ scripts/review-fixture-bootstrap.py       ← issues ephemeral tokens per role
  ├─ scripts/extract-routes-static.py          ← graphify-less route extractor
  ├─ scripts/verify-routes-live.py             ← URL drift gate (closes #50)
  ├─ scripts/merge-nav-by-role.py              ← 3-role navigator merger
  ├─ scripts/discover-iteration.py             ← iterative re-discovery (max 2 iter)
  ├─ scripts/spawn-crud-roundtrip.py           ← worker dispatcher (Gemini Flash)
  └─ scripts/derive-findings.py                ← Strix-style findings + REVIEW-BUGS.md
       │
       └─ Workers (Gemini Flash via gemini CLI)
              ├─ -p "@crud-roundtrip.md + context"
              ├─ -m gemini-2.5-flash             ← $0.075/M = 13× cheaper than Haiku
              ├─ --approval-mode yolo
              ├─ --allowed-mcp-server-names playwright1
              └─ writes runs/{resource}-{role}.json (run artifact)
```

### Worker tier — Gemini Flash via gemini CLI

Cost per phase (30 round-trip workflows × ~20k tokens):
- Haiku 4.5: ~$0.60
- DeepSeek V3 (via opencode): ~$0.16
- **Gemini-2.5-flash: ~$0.045** (13× cheaper than Haiku, 3.7× cheaper than DeepSeek)

Gemini CLI already MCP-configured by `install.sh` (5 Playwright servers in `~/.gemini/settings.json`). Already in cross-CLI plumbing. Zero new dependency.

### Closes #50 — Build URL drift gate

`scripts/verify-routes-live.py` probes every registered route against the running app via `curl --head`. Classifies live/drift/error/auth_only. With `--gate` flag, exits 1 on drift detected. Routes loaded from either `routes-static.json` (extract-routes-static.py output), `CRUD-SURFACES.md`, or both.

### Closes #51 — Verdict gate hardening (3 invariants)

Replaces path-existence checks with content invariants. AI cannot write empty artifacts to bypass review verdict.

1. **`verify-haiku-scan-completeness.py`** — every non-UNREACHABLE view in nav-discovery.json must have `scan-{slug}.json` with `elements_total >= 1`
2. **`verify-runtime-map-coverage.py`** — every UI-surface goal in TEST-GOALS.md must have `views[X].elements > 0` AND `goal_sequences[id].steps > 0` in RUNTIME-MAP.json
3. **`verify-crud-runs-coverage.py`** — every `(resource × role)` declared with `kit: crud-roundtrip` must have `runs/{resource}-{role}.json` with `coverage.attempted >= 1` and `evidence_ref` populated per non-skipped step

Override per-phase via `--skip-content-invariants=<reason>` (logs OVERRIDE-DEBT for post-merge triage).

### New transition kit format

`commands/vg/_shared/transition-kits/crud-roundtrip.md` — first kit. Format mirrors Strix's vulnerability skills (~150 lines markdown teaching LLM how to test, not runnable code). 8-step round-trip per (resource × role):

1. Read list (baseline) — capture row count, columns, sample rows
2. Create — submit valid payload OR verify role denied (matrix-driven)
3. Read list (persistence) — verify row count incremented + new row visible
4. Read detail — verify all fields persisted
5. Update — modify field OR verify role denied
6. Read detail (apply) — verify field changed (compare actual values, not `updated_at` to avoid clock-skew)
7. Delete — confirm dialog handling + DELETE OR verify role denied
8. Read list (deletion) — entity gone (hard) OR archived (soft per `delete_policy`)

Per-step expected behavior matrix from `CRUD-SURFACES.expected_behavior[role]` block. Per-run unique payload values (`name: "vg-review-{run_id}-create"`) avoid collisions across parallel workers.

### Findings schema — Strix-influenced

Enriched per Codex review feedback. Severity separated from security_impact:

```json
{
  "id": "F-001",
  "title": "...",
  "severity": "critical|high|medium|low|info",
  "security_impact": "auth_bypass|scope_violation|data_integrity|tenant_leakage|info_disclosure|none",
  "confidence": "high|medium|low",
  "dedupe_key": "<resource>-<role>-<step>-<normalized_title>",
  "actor": {"role": "...", "user_id": "...", "tenant": "..."},
  "environment": "...",
  "step_ref": "step-2",
  "request": {...},
  "response": {...},
  "trace_id": "...",
  "data_created": [{"resource": "topup_requests", "id": "tr-x"}],
  "cleanup_status": "completed|partial|skipped",
  "remediation_steps": [...],
  "cwe": "CWE-862"
}
```

`REVIEW-BUGS.md` is the human-readable triage doc, sorted by severity. Findings NOT auto-routed to `/vg:build` in v2.35.0 (deferred to v2.37 after schema dogfood validates dedupe + confidence quality).

### Auth fixture — credentials never committed

Codex review flagged credentials-in-config as bad. Fixed:

- `vg.config.md` declares `review.roles: [...]` and `review.auth.base_url`
- `.review-fixtures/seed-users.local.yaml` — gitignored, user-managed credentials
- `.review-fixtures/tokens.local.yaml` — gitignored, ephemeral tokens issued by `review-fixture-bootstrap.py` against the app's login API
- `.gitignore` updated automatically by bootstrap script

### Auth-aware navigator (3-role discovery)

Navigator runs 3× (admin/user/anon), captures union of visible routes per role into a role-visibility matrix:

```json
{
  "views": {
    "/admin/users": {
      "visible_to": ["admin"],
      "denied_for": ["user", "anon"],
      "discovery_role_evidence": {
        "admin": {"http_status": 200, "in_sidebar": true},
        "user": {"http_status": 403, "in_sidebar": false},
        "anon": {"http_status": 401, "in_sidebar": false}
      }
    }
  }
}
```

Workers spawned by `spawn-crud-roundtrip.py` read this matrix to know expected behavior per role per view.

### Iterative re-discovery (max 2 iter, +5 views/iter)

`discover-iteration.py` reads `scan-*.json sub_views_discovered[]` after Phase 2b-3 collect+merge. New views not in initial nav-discovery get queued for additional Haiku scans. Caps prevent runaway discovery.

### Static route extractor (graphify-less fallback)

`extract-routes-static.py` provides regex-based route discovery for projects without graphify configured. Patterns cover Express/Fastify/Hono, FastAPI/Flask/Django, React Router/Vue Router, Next.js Pages+App Router, Go (Echo/Gin/chi). Smoke-tested on multi-framework fixture: 7 routes detected across 4 frameworks with no false positives.

### Files

- **NEW** `commands/vg/_shared/transition-kits/crud-roundtrip.md` — first kit prompt
- **NEW** `commands/vg/_shared/templates/run-artifact-template.json` — JSON Schema
- **NEW** `scripts/review-fixture-bootstrap.py`
- **NEW** `scripts/extract-routes-static.py`
- **NEW** `scripts/verify-routes-live.py`
- **NEW** `scripts/merge-nav-by-role.py`
- **NEW** `scripts/discover-iteration.py`
- **NEW** `scripts/spawn-crud-roundtrip.py`
- **NEW** `scripts/derive-findings.py`
- **NEW** `scripts/validators/verify-haiku-scan-completeness.py` (closes #51 invariant 1)
- **NEW** `scripts/validators/verify-runtime-map-coverage.py` (closes #51 invariant 2)
- **NEW** `scripts/validators/verify-crud-runs-coverage.py` (closes #51 invariant 3)
- **MODIFY** `commands/vg/review.md` — Phase 2d (CRUD dispatch), Phase 2e (findings), verdict gate hardening
- **MODIFY** `vg.config.template.md` — `review.crud_roundtrip`, `review.auth`, `review.roles`, `review.iteration`, `review.url_drift_gate`
- **MODIFY** `scripts/validators/registry.yaml` — register 3 new validators

### Sequence note

Per discussion 2026-04-30, this is fix 2 of 4 for the systemic *"review hời hợt"* pattern:

- v2.34.0 (shipped) — closes #52 (review→test back-flow)
- **v2.35.0 (this)** — closes #50 + #51 (URL drift + scanner content invariants + CRUD round-trip)
- v2.36.0 — closes #49 (blueprint expand TEST-GOALS from CRUD-SURFACES) + 2 more transition kits
- v2.37.0 — auto-route findings to /vg:build (after schema dogfood)

---

## v2.34.0 (2026-04-30) — review→test goal-enrichment back-flow (closes #52)

User feedback: *"chúng ta đã build từ ban đầu là review sẽ spawn haiku, với codex thì sẽ chạy trong session để dò và vẽ ra bản đồ UI, từ đó bấm rất nhiều component và rich thêm goals tổng hợp cho đoạn test sau đó, nhưng có vẻ nó đang bị bỏ quên."*

The original 4-step `/vg:review` design:
1. Spawn Haiku/in-session Codex
2. Discover UI + draw map → `views[X].elements[]`
3. Click many components → `scan-{view}.json`
4. **Enrich TEST-GOALS for test layer** ← MISSING

Steps 1–3 were implemented; step 4 never wired. Result: `views[X].elements[]` accumulated 200+ runtime-discovered components (buttons, mutations, forms, tables, tabs), but no code consumed them. `/vg:test` codegen used only the 67 high-level goals from blueprint. ~70%+ of runtime-observed surface left untested.

Cross-grep confirmed before this release:
```
"enrich", "discovered_goals", "G-AUTO", "G-DISCOVER",
"TEST-GOALS-DISCOVERED" → 0 matches in commands/ or scripts/
```

### What this release adds

- **NEW** `scripts/enrich-test-goals.py` — parses every `scan-*.json` under `${PHASE_DIR}`, classifies elements (modal triggers, mutation buttons, forms, table row actions, paging, tabs), dedupes against existing `TEST-GOALS.md` `interactive_controls`, and emits `${PHASE_DIR}/TEST-GOALS-DISCOVERED.md` with `G-AUTO-*` goal stubs in YAML frontmatter format (mirrors `TEST-GOAL-enriched-template.md` schema). Has a `--validate-only` mode that exits 1 when any view has elements scanned but zero auto-goals derived (catches scanner output drift).

- **NEW** `scripts/codegen-auto-goals.py` — sister script that reads `TEST-GOALS-DISCOVERED.md` and emits skeleton Playwright specs `auto-{goal-id-slug}.spec.ts` to `GENERATED_TESTS_DIR`. No LLM call (auto-goals are review-grade stubs documenting what scanner observed; reviewer iterates on next blueprint pass). Each spec is `test.fail()` until reviewer fleshes out selectors, with comment block listing trigger/main_steps/alternate_flows/postconditions/observed-endpoint from runtime evidence.

- **MODIFIED** `commands/vg/review.md` — new step `phase2c_enrich_test_goals` after `2b-3 collect+merge`. Invokes enrich script + validator. BLOCKS review if enrichment coverage gap detected (override via `--skip-enrich-validate=<reason>` logs OVERRIDE-DEBT).

- **MODIFIED** `commands/vg/test.md` — new substep `5d-auto` after main `5d_codegen`. Invokes codegen-auto-goals script. Skeleton specs land in same dir as main codegen output, prefixed `auto-` for visual distinction.

### Goal stub categories emitted

| Element source | Goal stub | Priority |
|---|---|---|
| `results[].outcome == "modal_opened"` | `G-AUTO-{view}-modal-{name}` | important |
| `results[].network[].method ∈ {POST,PUT,PATCH,DELETE}` | `G-AUTO-{view}-mutation-{name}-{method}` | critical |
| `forms[]` | `G-AUTO-{view}-form-{trigger}` | critical |
| `tables[].actions_per_row[]` | `G-AUTO-{view}-row-{action}` | important |
| `tables[].row_count > 0` (no declared pagination) | `G-AUTO-{view}-table-paging` | important |
| `tabs[]` | `G-AUTO-{view}-tab-{name}` | nice-to-have |

Each stub includes `evidence{}` block with scan_ref + observed endpoint/status for traceability. `interactive_controls` declared in source TEST-GOALS.md (`filters`, `pagination`, `sort`) cause matching auto-goals to be skipped (avoid duplicates).

### Smoke-tested

- Fixture phase with 1 existing goal + 1 view scan (12 elements) → 8 auto-goals emitted (1 modal + 1 mutation + 1 form + 3 row-actions + 2 tabs). Pagination correctly skipped because declared in source. 8 skeleton specs written.
- `--validate-only` mode: passes when all views have ≥1 auto-goal; fails with concrete view-level gap message when scanner output drifted.
- Spec output validates: `import { test, expect } from '@playwright/test'` syntax, `test.describe` block, single-quote escaping in titles + main_steps comments.

### Sequence note

This is the FIRST of 4 fixes for the systemic *"review hời hợt"* pattern. Per discussion 2026-04-30:

- v2.34.0 (this release) — closes #52 (back-flow gap)
- v2.35.0 — closes #51 (Haiku scanner content invariants)
- v2.36.0 — closes #49 (blueprint expand goals from CRUD-SURFACES)
- v2.37.0 — closes #50 (build URL-drift gate)

Reasoning for upstream-first: a hardened scanner output without a consumer is wasted; goal expansion at planner-time is wasted if test layer can't pull from runtime discoveries. Wire the back-flow first, then harden the producers.

---

## v2.33.0 (2026-04-30) — milestone pipeline (full GSD parity)

User feedback: "VG có tính năng milestone như GSD chưa?" Audit found VG had milestone *concept* (STATE.md `current_milestone`, `## Milestone N` headings in PROJECT.md, `.vg/milestones/{M}/` archive dir, `/vg:security-audit-milestone`, `/vg:project --milestone`) but **no closeout pipeline**. `security-audit-milestone.md:205` referenced `/vg:complete-milestone` as if it existed; it didn't. Dead code path waiting for an orchestrator.

v2.33.0 builds the full pipeline.

### New commands

- **`/vg:milestone-summary {M}`** — aggregate report across all phases in milestone M. Phase pipeline status (specs/plan/build/review/test/UAT) per phase, goal coverage rolled up by priority (critical/important/nice-to-have), decisions inventory (D-XX namespace count), security register snapshot (open threats by severity), override-debt entries carried forward, companion artifact links (security-audit-*.md, SECURITY-PENTEST-CHECKLIST.md, STRIX-ADVISORY.md from v2.32.0), timeline (first commit → last commit). Re-runnable — non-mutating view.
- **`/vg:complete-milestone {M}`** — atomic milestone closeout orchestrator. Six-step flow: (1) gate check via `complete-milestone.py --check` (all phases UAT-accepted, no critical OPEN threats, no critical OVERRIDE-DEBT unresolved); (2) security audit hand-off to `/vg:security-audit-milestone --milestone-gate`; (3) regenerate `MILESTONE-SUMMARY.md`; (4) `git mv .vg/phases/{N}/` → `.vg/milestones/{M}/phases/{N}/` (history preserved); (5) advance STATE.md (`current_milestone` → next, append `milestones_completed[]` entry); (6) atomic commit with `milestone(close):` subject prefix. Override flags `--allow-open-critical=<reason>` + `--allow-open-override-debt=<reason>` log to OVERRIDE-DEBT for next-milestone triage.

### Phase membership resolution

Both commands resolve "which phases belong to milestone M" via three patterns against ROADMAP.md:

```
## M1 …
## Milestone M1 …
## Milestone 1 …
```

Falls back to all phases if no milestone section found (single-milestone projects). Override with `--phases <range>` (e.g. `--phases 3-7`).

### State schema additions

`STATE.md` (still pure markdown, parsed via regex):

```yaml
current_milestone: M2          # was M1, advanced by complete-milestone
milestones_completed:
  - id: M1
    completed_at: 2026-04-30T12:34:56Z
    phases: [2, 5, 7]
```

`.vg/milestones/{M}/.completed` JSON marker also written:

```json
{
  "milestone": "M1",
  "completed_at": "2026-04-30T12:34:56Z",
  "phase_count": 3,
  "vgflow_version": "2.33.0"
}
```

### Wired references

- `commands/vg/next.md:279` — Route 9 (all phases done) now points to `/vg:complete-milestone {M}` first, then `/vg:project --milestone` for next-milestone scoping.
- `commands/vg/progress.md:295` — same redirect.
- `README.md` command reference — new "Milestone (v2.33.0+)" section.

### Closes the v2.32.0 dead path

`security-audit-milestone.md:205` `--milestone-gate` flag has been waiting for an orchestrator since the file was written. v2.33.0's `/vg:complete-milestone` is that orchestrator. The flag now fires.

### Smoke-tested

- Fixture milestone with 2 phases (1 accepted, 1 missing UAT) → `--check` exits 1, blocker message lists missing phase. After UAT.md added → `--check` passes.
- `--finalize` writes STATE.md atomically (current_milestone advances, milestones_completed[] appended), writes `.completed` marker JSON.
- Re-run `--finalize` is idempotent (doesn't duplicate `milestones_completed[]` entry for same id).
- `--allow-open-critical="reason"` waives security gate, logs to OVERRIDE-DEBT carry-forward.

---

## v2.32.1 (2026-04-30) — CRUD-depth review/test hardening (#47, #48)

Patch release for the review/test false-pass class where a CRUD-heavy phase
could define many goals but downstream evidence only showed a list page or
group-level static scan.

### Fix

- **Review matrix merger** now downgrades mutation goals from READY to BLOCKED
  when `RUNTIME-MAP.goal_sequences[G-XX]` lacks a successful
  POST/PUT/PATCH/DELETE observation or lacks persistence proof.
- **New validator** `verify-runtime-map-crud-depth.py` is wired into
  `/vg:review` and `/vg:test`, registered as unquarantinable, and catches:
  list-only mutation evidence, mutation without persistence probe, and
  CRUD UI goals backed by `CRUD-SURFACES.md` that only have group-level
  `goal_sequences` instead of per-goal `G-XX` entries.
- **/vg:test structural fallback** now handles legacy READY artifacts that
  lack a per-goal sequence: non-mutation CRUD goals must generate a
  non-skipped `STRUCTURAL_FROM_CRUD_SURFACES` Playwright spec from
  `CRUD-SURFACES.md`; mutation goals still hard-block until review records
  real runtime mutation + persistence evidence.
- **Mutation codegen contract** is tightened from 3 layers to 4 layers:
  toast, API 2xx, persistence after refresh/re-read, and no console errors.
- **Codex + Claude mirrors** regenerated/synced so both runtimes enforce the
  same review/test rules.

### Verification

- `python -m pytest scripts/tests/test_runtime_map_crud_depth.py scripts/tests/test_crud_surface_workflow_wiring.py scripts/tests/test_mutation_layers.py`
  → 20 passed.
- `python scripts/ci/validator_smoke.py` → all validators compile and emit
  schema-compatible JSON for smokeable validators.
- `python scripts/verify-codex-mirror-equivalence.py` → 64 mirror pairs OK.

---

## v2.32.0 (2026-04-29) — Strix scan advisory plugin (end-of-milestone)

User asked: học được gì từ usestrix/strix về autopentest? Decision: Strix's domain (Docker sandbox + LLM-powered ReAct loop + actual exploit execution) is intentionally **outside** VG's dependency surface. VG aggregates threat-model declarations and curates an advisory recommending the user run Strix — same pattern as Step 5 (`SECURITY-PENTEST-CHECKLIST.md` for human pentesters).

### What this is NOT

- VG does not bundle Strix.
- VG does not run Strix.
- VG does not parse Strix output (yet).
- No new gate, no new BLOCK condition, no new dependency.

### What this is

End-of-milestone Step 6 inside `/vg:security-audit-milestone`. Aggregates the milestone's adversarial surface (declarative `adversarial_scope.threats` from each phase's TEST-GOALS.md + HTTP endpoints from API-CONTRACTS.md grouped by auth model) and emits two artifacts:

- `.vg/milestones/{M}/STRIX-ADVISORY.md` — markdown advisory with: why-this-matters summary, ready-to-copy `docker run ghcr.io/usestrix/strix:latest …` invocation tailored to declared threats, threat → goal traceability table, endpoint surface per phase, post-scan triage guidance, resource expectations.
- `.vg/milestones/{M}/strix-scope.json` — machine-readable scope payload for Strix's `--scope-file` flag (schema_version, target_url, threats, threat_goals, endpoints_by_phase).

### Files

- **NEW** `scripts/generate-strix-advisory.py` — phase walker + advisor renderer. Stdlib-only with optional PyYAML; falls back to regex when PyYAML missing. Resolves milestone scope via STATE.md / ROADMAP.md or explicit `--phases <range>`.
- **MODIFY** `commands/vg/security-audit-milestone.md` — Step 6 added. Reads `security.strix_advisor.enabled` (default true). Skips with explicit log line when disabled.
- **MODIFY** `vg.config.template.md` — `security.strix_advisor.{enabled, target_url}` config block under existing `security:` namespace.

### Why plugin, not core integration

Strix needs Docker + a separate LLM API key + a reachable target URL. Forcing those into VG's install path would break library / CLI / mobile-only project profiles. Step 6 generates an actionable recommendation; the user decides whether to spend the Docker setup + LLM tokens. After Strix runs, the user triages findings into `.vg/SECURITY-REGISTER.md` manually — auto-import is intentionally not provided so findings land with proper phase scope, owner, and severity in the project context.

### Smoke verified

- Fixture milestone with 2 phases, 4 distinct threats, 3 endpoints with mixed auth model (public/authenticated/admin) → advisory groups correctly per auth bucket.
- Empty milestone (no `adversarial_scope` declarations, no API-CONTRACTS) → "Nothing to advise" stanza, no spurious docker invocation.
- Disabled via `security.strix_advisor.enabled: false` → Step 6 logs "(strix_advisor disabled in vg.config.md — skipping Step 6)" and exits cleanly.

---

## v2.31.1 (2026-04-29) - no-session active-run fallback fix

v2.31.0 published successfully, but the `main` test workflow exposed an older
v2.28 active-run regression: when `CLAUDE_SESSION_ID` was absent, `run-start`
wrote `.vg/active-runs/unknown.json` while `run-complete` only looked for an
explicit session id. CLI/CI runs without Claude session env therefore reported
`No active run to complete`.

### Fix

- `scripts/vg-orchestrator/state.py` now consistently defaults
  read/write/clear operations to the `unknown` active-run slot when no session
  id is available.
- Restores no-session CLI behavior while keeping v2.28 multi-session isolation
  for real Claude sessions.
- `scripts/tests/test_bypass_negative.py` now passes locally (`10 passed`),
  restoring the CI negative-bypass suite.

---

## v2.31.0 (2026-04-29) - design-grounded blueprint/build hard gate (#45)

User reported a serious design/build pipeline bug: UI phases could reach build
without blueprint first ensuring that real mockups existed, were copied into the
phase design directory, and were normalized into design-ref slugs. Build also
had multiple design lookup paths, so a task could reference a design that one
stage accepted but another stage could not resolve.

### Closes #45

- `/vg:blueprint` now owns UI design setup end-to-end. Before planning, it
  detects UI phases from phase artifacts, imports existing mockups from
  `design_assets.paths` and common mockup directories into phase-local
  `design/`, auto-runs `/vg:design-scaffold --tool=pencil-mcp` when no mockups
  exist, then auto-runs `/vg:design-extract --auto` so PLAN generation can use
  real `<design-ref>` slugs.
- `/vg:build` now blocks before executor spawn when any `<design-ref>` slug is
  missing. The gate uses the same resolver as pre-executor checks and visual
  validators, covering phase `design/`, transitional `designs/`, shared design
  system assets, and legacy fallback roots consistently.
- Added `scripts/blueprint-design-preflight.py`, `scripts/design-ref-check.py`,
  and `scripts/lib/design_ref_resolver.py` as the shared Python design
  resolution layer.
- `/vg:review`, `pre-executor-check.py`, and design/vision validators now share
  that resolver instead of duplicating path assumptions.
- `/vg:design-scaffold` writes to phase-local `design/`; `/vg:design-extract`
  and shared shell helpers retain `designs/` as a transitional read fallback.
- Codex skill mirrors regenerated for blueprint/build/review/design scaffold and
  extract so release tarballs do not ship stale command mirrors.

---

## v2.30.0 (2026-04-29) — design path 2-tier layout + migration script

User reported design assets landing in project-level `.vg/design-normalized/` regardless of which phase generated them. Root cause: `design-extract.md` had a single hardcoded output dir from `vg.config.md:design_assets.output_dir`; no per-phase scoping.

### 2-tier design path layout

v2.30.0 introduces a 2-tier structure:

- **Tier 1 — phase-scoped** `.vg/phases/{N}/design/`: assets that belong to exactly one phase. `/vg:design-extract` writes here by default for all per-phase design work.
- **Tier 2 — project-shared** `.vg/design-system/`: cross-phase brand assets, design tokens, shared component screenshots. `/vg:design-extract --shared` writes here.
- **Tier 3 — legacy** `.vg/design-normalized/` (soft-deprecated): read-fallback for 2 releases; WARN on first use.

### New files

- **`commands/vg/_shared/lib/design-path-resolver.sh`** — resolver helper. Functions: `vg_design_phase_dir`, `vg_design_shared_dir`, `vg_design_legacy_dir`, `vg_resolve_design_ref` (3-tier read with fallback), `vg_resolve_design_dir` (write target with scope). All consumers source this instead of hardcoding paths.
- **`scripts/migrate-design-paths.py`** — one-shot migration script. Walks legacy `.vg/design-normalized/`, scans `PLAN.md <design-ref slug="...">` citations to classify each slug: single-phase cite → `phases/{N}/design/`; multi-phase cite → `.vg/design-system/`; no cite → `.vg/design-system/orphans/`. Pre-migration backup to `.vg/.design-migration-backup/{ts}/`. Dry-run by default; pass `--apply` to move.

### Files modified

- `commands/vg/design-extract.md` — `WRITE_SCOPE` dispatch: `--shared` → Tier 2, default → Tier 1 via `vg_resolve_design_dir`. Step 2 uses resolver.
- `commands/vg/blueprint.md` — design section sources resolver; detects which tier has manifest.json; WARN on legacy path use.
- `commands/vg/accept.md` — design baseline `BASELINE_PNG` resolved via `vg_resolve_design_ref` (3-tier fallback); legacy absolute path kept as human-readable error fallback.
- `install.sh` — new `--migrate-design` flag: runs `migrate-design-paths.py --apply` on target project after all files are installed.

### Migration for existing projects

```bash
# Dry-run first (default):
python3 .claude/scripts/migrate-design-paths.py --repo . --verbose

# Apply when ready:
python3 .claude/scripts/migrate-design-paths.py --repo . --apply --verbose

# Or during fresh install on a project that has legacy design dir:
bash /path/to/vgflow/install.sh --migrate-design /path/to/project
```

---

## v2.29.0 (2026-04-29) — utcnow() deprecation cleanup + #41/#42 update self-deploy fix

User reported v2.28.0 install on PrintwayV3 still emitting `DeprecationWarning: datetime.datetime.utcnow() is deprecated` from `vg-verify-claim.py:74` + `:96`. Triage found two layers:

1. **PrintwayV3 install was actually pre-v2.22** — DeprecationWarning fix landed v2.22.0, but `/vg:update` silent-merge bug (#30) parked the fixed `vg-verify-claim.py` as `.conflict` and never wrote the upstream copy. v2.24.0 fixed `three_way_merge()`, but the fix lives IN `scripts/vg_update.py` itself — chicken-and-egg #42.
2. **18 other call-sites in canonical still used `utcnow()`** in command markdown + shared libs. Even after fixing the install-update path, those sites would emit warnings at every `/vg:scope`, `/vg:review`, `/vg:test`, `/vg:accept` run on Python 3.12+.

### Closes #41, #42

- **#42** `commands/vg/update.md`: self-bootstrap the merge helper. `vg_update.py` is loaded from the **freshly downloaded tarball**, not from `.claude/scripts/vg_update.py`. A stale/broken installed helper can no longer prevent its own replacement from landing. Refuses to bump `.claude/VGFLOW-VERSION` if core update files (`scripts/vg_update.py`, `commands/vg/update.md`, `commands/vg/reapply-patches.md`) did not land — surfaces silent partial upgrades.
- **#42** `install.sh --refresh`: new flag that backs up VG-managed files in target install before refreshing, so users stuck on stale helper can `bash install.sh --refresh /path/to/project` to force-overwrite. Fresh installs now seed `.claude/vgflow-ancestor/v{version}/` so future 3-way updates have a real baseline (eliminates the "ancestor missing → force-upstream → silent overwrite" cliff).
- **#42** `commands/vg/update.md`: pre-flight integrity scan before merge loop. Walks tarball + install + ancestor, classifies each file (`clean` / `new` / `force_upstream_at_risk` / `skipped`), prints count + first 10 at-risk filenames BEFORE files are overwritten. Audit window for users with missing ancestor stash.
- **#41** `commands/vg/_shared/lib/bug-reporter.sh:bug_reporter_github_submit_from_event()`: GitHub issue body construction no longer embeds `$event` JSON directly into a Python triple-quoted heredoc. Switched to env var (`BR_EVENT="$event" python3 -c '...'`) with single-quoted Python source so backslash/quote/triple-quote/`$`/backtick chars in event payload no longer cause SyntaxError → empty issue body. v2.28.0 fixed the `report_event()` upstream pipeline; this fix completes the chain by also escaping the downstream submit path.

### utcnow() cleanup

Replaced `datetime.utcnow()` → `datetime.now(timezone.utc)` (or `datetime.datetime.now(datetime.timezone.utc)` for module-style imports) in 11 canonical files. Imports updated to include `timezone` where needed. Output identical (`%Y-%m-%dT%H:%M:%SZ`).

Files touched:
- `commands/vg/accept.md`, `project.md`, `scope.md`, `scope-review.md`, `review.md` (×6 sites), `test.md` (×3 sites)
- `commands/vg/_shared/artifact-manifest.md`
- `commands/vg/_shared/lib/artifact-manifest.sh`, `bootstrap-inject.sh`, `matrix-merger.sh`, `scaffold-stitch.sh`

Codex skill mirrors regenerated.

### Recovery for users stuck on pre-v2.22

Two paths:

1. **Clean refresh (recommended)**: `bash install.sh --refresh /path/to/project` from this updated vgflow-repo. Backs up VG-managed files, force-overwrites with v2.29.0 baseline.
2. **Manual hook scripts only**: copy `scripts/vg-verify-claim.py`, `scripts/vg-orchestrator/state.py`, `scripts/vg-orchestrator/__main__.py`, `scripts/vg-build-crossai-loop.py` into `<project>/.claude/scripts/` directly.

After v2.29.0, `/vg:update` self-bootstrap closes the trap — future updates use the upstream helper, not the installed one.

---

## v2.28.0 (2026-04-29) — multi-tenant active-run + #37/38/39 + bug-reporter context

User pushback: "tôi bật 2 cửa sổ, 2 session khác phase, cái nào làm sau bị lock". Plus 6 open GitHub issues (#34–39). Triage found two truly independent failure modes the user perceived as a single "lock" symptom, and three low-context auto-reported bugs traced to one root cause.

### Root causes addressed

1. **`current-run.json` was single-tenant.** A second `/vg:*` invocation on the same project blocked at `cmd_run_start` with `⛔ Active run exists` — even when started from a different Claude Code session. v2.24.0 cross-session detection patched the Stop hook side, never the run-start side.
2. **`commit-attribution.py` greps the commit body** (issue #37). On phase 2, `git log --grep="\(2[-.0-9]*-[0-9]+\):"` matched a pre-existing commit whose body contained `(2026-04-22):` (year `2026` parsed as `2`+`-`+`22`). Pre-existing commit hard-flagged as `subject_format_violation`, blocking `/vg:build run-complete` deterministically. THIS was the actual cause of the user's screenshot — not the multi-session race.
3. **`emit_event` raised EmitError when `current-run.json` had empty `run_id`** (issue #39). Mid-CrossAI-loop run-abort or run-repair cleared state; the loop's expensive Codex+Gemini work succeeded but post-completion event emit fell through and the build BLOCKed. Chicken-and-egg.
4. **Parallel executor agents staged files BEFORE acquiring the commit-queue mutex** (issue #38). The mutex only protected `commit`, not the index. First agent to acquire absorbed the second agent's pre-staged files → cross-attribution corruption.
5. **`bug-reporter.sh` substituted `${context}` into a Python triple-quoted string literal** (issues #34/35/36). Any context with a quote, triple-quote, or newline produced a SyntaxError; `2>/dev/null` swallowed the error → empty data → GitHub issues with empty `Context: \`\`\`json\n\n\`\`\`` blocks.
6. **`__main__.py` referenced `timezone.utc` without importing `timezone`** (pre-existing, latent). `_is_run_stale()` always took the exception path → returned True for every run. v2.24.0 fixed the same pattern in `vg-verify-claim.py` but missed `__main__.py`. Cross-session WARN never fired and same-session block path was unreachable in production.

### Multi-tenant active-run state

- **NEW** `.vg/active-runs/{session_id}.json` — per-session state, authoritative for that session.
- `.vg/current-run.json` — kept as latest-write snapshot for `run-status` aggregate view + pre-v2.28.0 install fallback.
- `state.py` rewritten with `read_active_run` / `write_active_run` / `clear_active_run` / `list_active_runs` keyed by session_id. Legacy `read_current_run` / `write_current_run` / `clear_current_run` shims route through the new API via env `CLAUDE_SESSION_ID`.
- `cmd_run_start`: same-session active → existing block-or-stale-clear logic. Other-session active → WARN nhẹ (not blocking) noting shared git index + commit-queue mutex. Two windows on different phases can now coexist.
- `cmd_run_status`: shows current session run + `other_sessions_active` array of sibling sessions for awareness.
- `vg-verify-claim.py`: Stop hook reads per-session file via `hook_input.session_id`; cross-session detection retained as defense-in-depth.
- `vg-entry-hook.py`, `vg-agent-spawn-guard.py`: per-session reads + propagate `CLAUDE_SESSION_ID` env to subprocess invocations of orchestrator (Claude Code provides session_id via stdin only, not env — manual propagation required).

### Issue fixes (closes #37, #38, #39, #34, #35, #36)

- **#37** `commit-attribution.py:git_log_subjects()`: replaced `git log --grep=PATTERN` (which scans body) with raw `git log --pretty=format:%H%x00%s%x00%b%x01 -2000` then Python-side `re.match` against subject only. Body is no longer scanned for phase regex; date strings in commit bodies can no longer trigger phantom violations.
- **#38** `build-commit-queue.sh`: new `vg_commit_with_files <task_id> <max_wait> <msg_file> <file>...` primitive. Atomic stage+commit inside the mutex with explicit file list — impossible to stage before acquire by construction. Plus diagnostic warning when index has pre-staged files at acquire time. `vg-executor-rules.md` § Parallel-wave commit safety: added explicit "⛔ DO NOT run `git add` BEFORE acquire" rule + showcased the new helper as preferred primitive.
- **#39** `vg-build-crossai-loop.py:emit_event()`: added `_resolve_active_run(phase)` with 3-tier fallback — (1) `.vg/active-runs/{session_id}.json`, (2) legacy `.vg/current-run.json`, (3) SQLite `runs` table for the most recent open `vg:build` row at this phase. Recovers the chicken-and-egg trap; only raises EmitError if all three sources fail.
- **#34/35/36** `bug-reporter.sh:report_bug()` + `report_event()`: pass `sig`, `context`, `redacted` data via env vars (`BR_SIG`, `BR_CTX`, `BR_DATA`) instead of substituting into Python source. Python reads from `os.environ` — fully byte-safe regardless of quotes, triple-quotes, newlines, `$`, backticks. Plus sentinel fallback if encode still fails so issue body never goes empty.

### Smoke matrix verified

- 2 sessions, same project, different phases (`/vg:scope 1` + `/vg:build 2`) → both start, WARN visible to second session.
- `run-status` from session A shows `this_session=A` + `other_sessions_active=[B]`.
- `run-abort` from session A clears only sessionA.json; sessionB.json untouched.
- commit-attribution: fixture repo with body containing `(2026-04-22):` + a real `feat(2-01):` commit → PASS (date string no longer flagged).
- emit_event: simulated empty current-run.json + open vg:build row in events.db → resolves run_id from DB, no EmitError.
- vg_commit_with_files: pre-staged file from prior crashed task → diagnostic WARN + acquire's orphan-clean unstages → final commit contains only the requested files.
- bug-reporter: adversarial context (newline + triple-quote + single-quote + `$dollar`) → event JSON properly nests data with chars preserved.

### Compatibility

- Pre-v2.28.0 installs missing `.vg/active-runs/` directory → `read_active_run()` falls back to legacy `current-run.json`. No state migration required.
- Subprocess CLAUDE_SESSION_ID propagation is opt-in (passes if env present); no env present → falls back to legacy single-tenant behavior. Old hooks keep working.

### User action

After `/vg:update` lands v2.28.0:
- 2 windows on same project: just open both — the second `/vg:build` no longer blocks. WARN about shared git index appears once per run-start.
- Old `current-run.json` snapshot preserved as latest-write mirror; can be safely deleted if state seems wedged.

---

## v2.27.0 (2026-04-28) — programmatic gsd-* spawn guard (PreToolUse hook)

User pushback on v2.26.0: "rule chỉ là text, có chắc AI sẽ không gọi GSD nữa không?". Right — informational reinforcement is a soft enforce. Investigation found a real programmatic mechanism + shipped it.

### Investigation

GSD's own `execute-phase.md` workflow uses identical text-only enforcement:

```
<available_agent_types>
- gsd-executor — Executes plan tasks, commits, creates SUMMARY.md
- gsd-verifier — ...
Always use the exact name from this list — do not fall back to
'general-purpose' or other built-in types
</available_agent_types>
```

GSD has no programmatic guard either. Both VG (now) and GSD relied on the AI reading prose. Both had drift exactly because Claude Code's agent picker scores subagent descriptions and can override "soft should-not" rules from the calling skill.

**Real enforcement vector found:** Claude Code's PreToolUse hook with `matcher: "Agent"` receives the full `tool_input` (including `subagent_type`) BEFORE the spawn fires. Returning `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "..."}}` blocks the spawn AND delivers the reason to Claude for the next turn so it re-spawns correctly.

This is a hard enforce — not a rule the AI can rationalize past, an OS-level interception of the tool call.

### Fix

- **NEW** `scripts/vg-agent-spawn-guard.py`: PreToolUse hook script. Logic:
  1. Reads stdin JSON for `tool_name` + `tool_input.subagent_type`
  2. If tool isn't `Agent` → allow (no-op for Bash/Read/Edit/etc.)
  3. If subagent_type doesn't start with `gsd-` → allow (general-purpose, Explore, custom agents pass)
  4. If subagent_type is in allow-list (`gsd-debugger` only — VG legitimately uses it in build.md step 12) → allow
  5. If `.vg/current-run.json` doesn't exist OR active run command doesn't start with `vg:` → allow (don't break GSD users running `/gsd-execute-phase` directly)
  6. Otherwise → DENY with detailed reason listing VG vs GSD rule-set differences and instructing re-spawn with `general-purpose`
- `scripts/vg-hooks-install.py`: new `PreToolUse` matcher entry for `Agent`. Wires the guard into `.claude/settings.local.json` on next install/repair pass. Allow-list extended for the new script.
- `commands/vg/build.md` step 7: appends "Programmatic enforcement (v2.27.0+)" block telling AI the hook exists and what its deny message looks like — so when the AI sees the reason, it knows the hook fired correctly and re-spawns instead of treating the deny as a transient error.

### Smoke-tested 6 scenarios

- gsd-executor in active VG run → DENY with reason ✓
- general-purpose in active VG run → ALLOW (empty stdout) ✓
- gsd-debugger in active VG run → ALLOW (allow-listed) ✓
- gsd-executor outside any VG run (no current-run.json) → ALLOW ✓
- gsd-executor with stale non-VG run (e.g., gsd:execute-phase active) → ALLOW ✓
- Non-Agent tool (Bash) during VG run → ALLOW ✓

### User action

Re-run hooks installer to land the new guard:

```bash
cd /path/to/your/project
python3 .claude/scripts/vg-hooks-install.py
```

Or the full sync:

```bash
bash sync.sh /path/to/your/project
```

After install, hooks active on next Claude Code session start. Test by running `/vg:build <phase>` and observe wave dispatch — should consistently show `general-purpose(Wave N Task M)`. If you intentionally try to spawn `gsd-executor` (e.g., for debugging), the hook will deny with a clear message; you'll see it in next turn.

**Note on GSD compatibility:** Hook is no-op outside VG context. `/gsd-execute-phase`, `/gsd-autonomous`, etc. continue to spawn `gsd-executor` normally because their `current-run.json` either doesn't exist (not VG-managed) or has a non-`vg:` command prefix. No interference with users who use both VG + GSD on different projects.

### Closed
N/A — pushback follow-up to v2.26.0; no separate issue. Reinforces the v2.20-v2.26 chain.

## v2.26.0 (2026-04-28) — hardened gsd-executor rejection in build.md (root cause traced)

User reported `gsd-executor(Wave 6 Task 16 — Replica set verify)` STILL appearing in wave dispatch despite v2.25.0's text-only fix. Investigation traced the actual root cause this time.

### Root cause

`gsd-executor` is a real agent registered globally at `~/.claude/agents/gsd-executor.md`. It ships with the GSD workflow, has `name: gsd-executor` and description "Executes GSD plans with atomic commits, deviation handling, checkpoint protocols, and state management. Spawned by execute-phase orchestrator or execute-plan command."

Claude Code's agent picker scans available agents by description. When VG's `/vg:build` skill body says "Spawn executor agent (one per plan task)" + dispatches with task lists, GSD's executor description pattern-matches strongly: "execute plan", "atomic commits", "checkpoint" — all phrases that appear in VG's build.md prose. The picker has historically preferred `gsd-executor` over `general-purpose` for these prompts.

V2.25.0's text fix said "NEVER spawn gsd-executor" but didn't explain WHY GSD wins by default, didn't mention the rule set differences, and didn't make the runtime check explicit. The AI dispatching waves saw a soft "should not" and continued routing through GSD when the picker scored it higher.

### Fix in this release

`commands/vg/build.md` step 7 (executor spawn) — replaced the soft "MANDATORY" block with a **HARD RULE — ZERO EXCEPTIONS** block that:

1. Lists the **specific** agent names to reject: `gsd-executor`, `gsd-execute-phase`, any `gsd-*` (except `gsd-debugger` used in step 12).
2. Explains **why the picker wants GSD**: agent ships globally at `~/.claude/agents/gsd-executor.md`, description matches plan-execution prompts.
3. Lists the **concrete rule-set differences** so the AI sees the cost:
   - VG forbids `--no-verify`; GSD allows it in parallel mode
   - VG requires `Per CONTEXT.md D-XX` body citation; GSD does not
   - VG L1-L6 design fidelity gates require structured evidence; GSD has none
   - VG enforces task context capsule with vision-decomposition; GSD doesn't load it
4. Names the **failure mode**: spawn GSD → GSD rule set wins → VG gates silently skip → downstream `/vg:review` + `/vg:test` fail with phantom artifacts.
5. Provides a **runtime self-check**: wave status line MUST read `general-purpose(Wave N Task M)`. If `gsd-executor(...)` appears, abort the spawn and re-spawn explicitly.

This is informational reinforcement — Claude Code does not expose a programmatic "force agent type" hook from skill body. The strongest defense is making the rule unambiguous + explaining the picker's failure mode + giving a runtime check the AI must perform.

### User action

After `/vg:update` to v2.26.0, the next `/vg:build` should dispatch `general-purpose(...)` consistently. If `gsd-executor(...)` still appears:

1. Confirm install version: `cat .claude/VGFLOW-VERSION` should be `2.26.0`. If not, `/vg:update` didn't apply (see #30, fixed v2.24.0 — re-update will work).
2. Check project CLAUDE.md for stale "gsd-executor spawned by /vg:build" prose — delete that section. Authority is build.md inline, not CLAUDE.md.
3. Reload Claude Code session — agent picker results cache per session.
4. If still misbehaving on v2.26.0+ with clean CLAUDE.md and fresh session: open a new issue with `claude --version` output + the dispatch line + a snippet of build.md step 7 from your install (to confirm the fix landed).

### Closed
N/A — user-reported follow-up to v2.25.0 doc fix; no separate issue filed.

## v2.25.0 (2026-04-28) — hooks python3 detection + gsd-executor doc fix

Closes #33 (hooks call `python` instead of `python3`) + clarifies executor agent type so AI doesn't pick `gsd-executor` when project's CLAUDE.md inherits a stale doc fragment.

### Issue #33 — hook commands fail on python3-only systems

`scripts/vg-hooks-install.py:HOOK_ENTRY` hard-coded `python` as the interpreter for all 4 hooks (Stop, PostToolUse Edit, PostToolUse Bash, UserPromptSubmit). On macOS Homebrew (default Python 3.x install) and many Linux distros, only `python3` is on PATH — no `python` symlink. All 4 hooks silently failed with `/bin/sh: python: command not found`. Script shebangs were correct (`#!/usr/bin/env python3`); only the bootstrap settings template was wrong.

**Fix:**
- New `_detect_python_cmd()` resolves at install time via `shutil.which`. Prefers `python3` (matches script shebangs), falls back to `python`, then literal `"python3"` if neither resolves.
- All 4 `HOOK_ENTRY` command strings use the detected name via f-string interpolation.
- `merge_hooks()` repair pass now also detects existing hook commands whose interpreter token doesn't resolve on PATH (e.g., a project installed on a Mac without `python` symlink) and repairs them in-place using the freshly-resolved name. Existing v2.5.2.4 unquoted-path repair preserved.

Affects new installs and any user re-running `bash sync.sh` or `python .claude/scripts/vg-hooks-install.py` on an existing project. Re-run after upgrading to land the repair.

### Stale `gsd-executor` reference (user reported)

User saw wave dispatch line `gsd-executor(Wave 3 Task 7 — Ledger posting service)` instead of expected `general-purpose(...)`. Root cause traced to `templates/vg/claude-md-executor-rules.md:13` which still read "gsd-executor spawned by /vg:build" — old prose from before v2.5.1's migration to general-purpose. Users who copy-pasted this template into their project CLAUDE.md gave their AI sessions an instruction that contradicted the actual `Agent(subagent_type="general-purpose", ...)` line in build.md, and the AI sometimes resolved the contradiction toward the doc instead of the dispatcher.

**Fix:**
- `templates/vg/claude-md-executor-rules.md` rewrites line 13 prose to "general-purpose subagent spawned by /vg:build" + adds explicit IMPORTANT block: "VG spawns general-purpose, NOT gsd-executor. Wrong agent type → stale install symptom (#30, fixed v2.24.0). Re-run /vg:update."
- `commands/vg/build.md` step 7 (executor spawn) prepends MANDATORY guard: "subagent_type MUST be general-purpose. NEVER spawn gsd-executor. If project's CLAUDE.md mentions gsd-executor, IGNORE it." Status line will read `general-purpose(Wave N Task M)` not `gsd-executor(...)`.

User action: paste the updated template block into project CLAUDE.md (or remove the old block — VG_EXECUTOR_RULES are also injected inline at every spawn so CLAUDE.md is no longer authoritative for them).

### Closed
- **#33** (this release — python3 detection + repair)

## v2.24.0 (2026-04-28) — silent update fix + cross-session zombie + is_stale tz bug

3 issues, 1 critical hidden bug. Closes #30, #32, partial #31.

### 1. `/vg:update` silent merge failure (#30, CRITICAL)

**User-visible symptom:** `/vg:update v2.12.7 → v2.23.0` reported `updated=526 new=3 conflicts=51` and rotated VGFLOW-VERSION cleanly. But none of the v2.20-v2.23 bug fixes actually landed in install files. User had to manually `cp` 51 files from `vgflow-ancestor/v2.23.0/` → `.claude/` to recover.

**Root cause:** `vg_update.py three_way_merge()` lines 78-85 — when ancestor missing AND current ≠ upstream, returned `MergeResult("conflict", cur_text)` (LOCAL content, not upstream). Caller in `update.md` step 6 wrote LOCAL as `.merged`, parked it as `.conflict`. `/vg:reapply-patches` saw zero markers and treated as resolved (or deleted as identical-to-local). Upstream content **never reached install**. Worst case: success-shaped UI, partial silent failure.

**Fix:**
- `three_way_merge()`: when ancestor missing AND current ≠ upstream, return `MergeResult("force-upstream", up_text)`. Without baseline, 3-way merge is impossible; user's intent in `/vg:update` is "give me new version" → take upstream as authoritative.
- `cmd_merge` exits 0 for both `clean` and `force-upstream` (caller mv `.merged` → target).
- `commands/vg/update.md` step 6: handles `force-upstream` status as a valid clean-apply path with distinct counter `FORCE_UPSTREAM`. Final summary now reads `updated=N new=M conflicts=K force_upstream=L skipped_meta=S` so user sees count of force-upgraded files. Pre-flight warns if `vgflow-ancestor/v${INSTALLED}/` missing.
- Verified: ancestor-missing fixture → returns `force-upstream`, output content == upstream verbatim. Ancestor-missing + current==upstream → `clean`. Ancestor exists with conflict → markers preserved.

### 2. Cross-session zombie blocks unrelated Stop hook (#32)

**User-visible symptom:** Session A `/vg:build 3.1` crashes without run-complete. Session B working on `/vg:blueprint 2` (different phase entirely) hits Stop hook → blocked by Session A's zombie active-run reporting Phase 3.1's missing telemetry/markers. User must manually `vg-orchestrator run-abort` after every turn. 3 zombie runs aborted in 1 day.

**Root cause:** `vg-verify-claim.py` Stop hook read `current-run.json` blindly without checking which session started the run. The orchestrator's "1 active run at a time" model was project-global, not session-scoped.

**Fix:**
- `vg-verify-claim.py`: new `get_run_session_id(run)` reads session_id from `current-run.json` first, falls back to sqlite query against runs table by run_id.
- Stop hook now branches on cross-session detection (when both sessions have IDs and they differ):
  - **Stale + cross-session** → auto-`run-abort` zombie via orchestrator + approve current Stop. Audit event emitted.
  - **Fresh + cross-session** → don't touch (might be parallel work) + approve current Stop without validating the other session's contract.
  - **Same-session OR unidentifiable** → existing logic preserved (OHOK-6 still blocks AI from gaming threshold).
- Verified 4 scenarios: stale+xsession → cleared, fresh+xsession → no-action, same+stale → BLOCK (OHOK-6 preserved), same+fresh → fall-through.

### 3. `is_stale()` always-True tz bug (PRE-EXISTING, surfaced during #32 work)

**Hidden bug found while testing #32:** `vg-verify-claim.py:is_stale()` and `vg-orchestrator __main__.py:_is_run_stale()` parsed `started_at` via `datetime.fromisoformat(started.rstrip("Z"))` → produces NAIVE datetime. Subtracting from `datetime.now(timezone.utc)` (AWARE) raised `TypeError: can't subtract offset-naive and offset-aware datetimes`. Except branch returned `True` → **is_stale() always returned True regardless of actual age**.

**Impact this caused:** Stop hook BLOCKED on every active run with the "stale" message even when 5 seconds old. Orchestrator's `run-start` auto-cleared every active run as "stale". Users lived with constant Stop hook blocks ascribed to "OHOK-6 threshold protection" but actually triggered by tz parse error.

**Fix:** Normalize `Z` → `+00:00` then add UTC tz if parser still returned naive. Aware-aware subtraction works → real age comparison.

### Closed
- **#30** (this release — force-upstream fix)
- **#32** (this release — cross-session detection + tz bug)
- **#31** — duplicate noise (sig 26ebcf1f, install_success info, vg=unknown). Same empty-context class as #24/#25/#29. Already fixed in v2.19.0 redact rewrite. Reporter v=unknown can't be on v2.19.0+; close as stale.

### Pipeline impact
- `/vg:update` users on stale-ancestor projects will now actually receive bug fixes instead of silently keeping old version
- Multi-session workflows on same project no longer interfere across phases
- Active-run age check now functions correctly (was always-stale-block before)

## v2.23.0 (2026-04-28) — CRUD validator BE-only fix (closes #26)

Backend-only phases in `web-fullstack` projects (wallet/ledger/billing/integration types) generated 270+ field-missing errors per resource at `/vg:blueprint` step 2d_validation_gate because `verify-crud-surface-contract.py` forced a `platforms.web` overlay even when the phase had zero FE work.

### Root cause

`_required_platforms("web-fullstack", phase_text)` checked `WEB_SIGNAL_RE` (matches `view|page|table|form|button|...`) against concatenated SPECS+CONTEXT+API-CONTRACTS+TEST-GOALS+PLAN text. Real BE-only phase docs contain those words in DB/API context — `"wallet table schema"`, `"form validation in handler"`, `"view permissions on /api/wallet/{id}"` — triggering false positives. Validator then required platforms.web for every resource and emitted ~270 missing-field violations per resource × 16 resources for fictional UI that won't exist until phase 6/8.

### Fix

Switched to a deterministic **file-path** signal sourced from `PLAN.md` (the post-blueprint task list cites concrete source paths):

- New `_plan_text(phase_dir)` helper reads `PLAN*.md` only (returns `None` if no PLAN exists yet).
- New `FE_SOURCE_PATH_RE` matches `apps/admin/`, `apps/merchant/`, `apps/vendor/`, `apps/web/`, `packages/ui/`, `packages/web-`, `frontend/`, `.tsx`, `.jsx`.
- `_required_platforms()` now branches:
  - **PLAN.md exists** → trust file paths over prose. Require `platforms.web` only when `FE_SOURCE_PATH_RE` matches PLAN. Always require `platforms.backend` when backend signals (API routes, handler, schema, migration) appear.
  - **No PLAN.md** (pre-blueprint phase) → fall back to legacy prose heuristic (preserves existing behavior on early-stage phases and the 5 existing tests).

### Test coverage
- `test_be_only_phase_in_fullstack_skips_web_overlay` — Reproduces #26: SPECS has FE-prose words from API/DB context, PLAN.md cites only `apps/api/` paths. With the fix: validator requires backend only, contract with backend overlay → PASS. Without the fix: would force web overlay → BLOCK with phantom missing fields.
- `test_fullstack_phase_with_fe_source_in_plan_requires_web` — Counter-test: PLAN.md cites `apps/admin/...Campaigns.tsx`, contract supplies only backend → BLOCK with `platforms.web overlay missing`.
- All 5 existing tests preserved (no PLAN.md fixture, falls back to legacy heuristic).

### Pipeline impact
- `/vg:blueprint` step 2d_validation_gate on BE-only phases of fullstack projects no longer emits phantom platforms.web requirements
- Phases affected on PrintwayV3 per reporter: 3.1 Wallet, 3.2 Topup, 3.3 Order Payment, 3.4a Team RBAC, 3.4b Credit, 3.5 Invoice, 4 Order Flow, 4.1 Net Terms, 5 Integrations, 11 Migration, 12 Competitive — all now author backend overlays only without contract thrash.

## v2.22.0 (2026-04-28) — events.db lock fix + datetime deprecation + crossai stderr separation

User reported: 2 concurrent /vg sessions in the **same project** collide on events.db. One session times out, its slash-command body continues running with no events emitted, Stop hook then reports a misleading runtime_contract violation (missing telemetry, missing markers). Plus a `datetime.utcnow()` deprecation warning surfaces at every Stop hook on Python 3.12+.

### Root cause (lock issue)

`db.py` wrapped every event write in an advisory `_flock()` lockfile (`.vg/.events.lock`) on top of SQLite's WAL + busy_timeout. The advisory lock was redundant — WAL natively serializes writers — and worse, it added a second contention layer with its own 10s timeout and stale-detection logic. When session A held the file lock, session B raised `TimeoutError("flock held >10s")`. The orchestrator caller didn't surface this clearly; the slash-command continued, all subsequent emit-event calls also failed the file lock, and the run ended with **zero events written**. Stop hook saw empty events.db evidence → ran the runtime_contract checker → reported the symptom (violations) instead of the root cause (lock).

### Fix
- **`scripts/vg-orchestrator/db.py`** (and `.claude/` mirror):
  - Dropped the `_flock()` advisory lockfile entirely. No more `.vg/.events.lock`.
  - Switched `connect()` to `isolation_level=None` (autocommit mode) and bumped `busy_timeout` from 5000 → 30000ms.
  - Every write (`create_run`, `complete_run`, `append_event`) now wraps work in `BEGIN IMMEDIATE` + `COMMIT` (or `ROLLBACK` on exception), acquiring the SQLite RESERVED lock at txn start instead of upgrading later. Eliminates SQLITE_BUSY upgrade races.
  - Added `_retry_locked(work, max_total_wait=60s)` Python-level safety net for residual lock errors (e.g., WAL checkpoint stalls). Surfaces a clear `TimeoutError` naming the likely cause when contention exceeds 60s — much better signal than the old "flock held >10s".
  - Updated stale comment in `vg-build-crossai-loop.py:345` ("serializes via _flock" → "serializes via SQLite BEGIN IMMEDIATE + busy_timeout").
- Stress-tested 8 concurrent threads × 10 writes each = 80 events total: 0 errors, hash chain valid. Old code would have timed out at least one thread after 10s.

### Other fixes

- **`datetime.utcnow()` deprecation** (Python 3.12+): replaced 46 occurrences across 13 files with timezone-aware `datetime.now(datetime.timezone.utc)`. Format strings preserve `Z` literal so output is byte-identical. Files: `bootstrap-test-runner`, `build-uat-narrative`, `design-reverse`, `distribution-check`, `generate-pentest-checklist`, `tests/test_verify_claim_hybrid`, `vg-build-crossai-loop`, `vg-entry-hook`, `vg-orchestrator/__main__`, `vg-step-tracker`, `vg-typecheck-hook`, `vg-verify-claim`, `vg-wired-check`. The `DeprecationWarning` user saw at every Stop hook now silent.

- **#27 — CrossAI stderr→stdout merge polluting verdict XML**: `commands/vg/_shared/crossai-invoke.md` line 99 redirected `2>&1` into `result-${cli.name}.xml`. When a CLI emitted large stderr (e.g., Codex CLI's TOML parser warnings on `~/.codex/agents/*.toml`), the XML file became 5000 lines of warnings followed by the actual verdict block; downstream parsers either matched the prompt's example XML (false-positive) or timed out. Split: stdout → `.xml`, stderr → `.err` (forensics-only, not parsed). Closes #27.

- **#28 — `vg-orchestrator override` text honesty**: Stop hook's "Fix options" block in `vg-orchestrator/__main__.py:3691` advertised option 2 as "logs to OVERRIDE-DEBT.md" without mentioning it does NOT bypass the validator on the current run. Users hit the gate, ran override, hit the same gate again — rationalization spiral. Hook text now reads: "logs OVERRIDE-DEBT.md entry ONLY. Does NOT bypass this run's runtime_contract violations. Stop hook will re-fire at next /vg command unless underlying evidence is produced. Use --skip-<validator> CLI flag at command invocation for per-run bypass." Real bypass-via-active-run-flag-consultation behavior deferred to v2.23+ (needs threat-modeling on what counts as "active run", what validators the override should disable, etc.). Partial-fix #28 (text-only); deeper fix tracked.

### Closed issues
- **#27** (this release — stderr separation)
- **#28** partial (this release — text honesty; deep fix deferred to v2.23+)
- **#24, #25** — duplicate noise from #29 (empty-context bug-reports). Already fixed in v2.19.0 (commit 46b4df8) which rewrote `bug_reporter_redact` to use a Python subprocess. Reporter on v2.18.0 needs to update.
- **#29** — same as #24/#25; redact bash parse error, fixed in v2.19.0 redact rewrite. User on v2.18.0 needs to update.

### Deferred
- **#26** — CRUD validator forces `platforms.web` overlay for BE-only phases. Real bug, bigger fix (validator must scan PLAN.md for FE patterns or honor `phase-profile.sh detect_phase_profile`). Defer to v2.23+ to avoid release thrash.

## v2.21.0 (2026-04-28) — Adversarial coverage Hook 1+3 (declarative threat model)

User asked: wire a step that writes tests for cheat / edge / error / lách-goals cases? Plan-mode pushback: NOT a separate step — it's a **cross-cutting concern** that belongs declaratively at goal definition (blueprint) and enforcement-wise at /vg:test. Step 2 of `.claude/plans/cheeky-mapping-engelbart.md`.

v2.21.0 ships **Hook 1 (schema)** + **Hook 3 (validator + test wiring)** lean. Hook 2 (codegen) deferred to v2.22+ once dogfood data shows which threat-types matter most per project domain.

### New
- **Hook 1 — `adversarial_scope` schema** in `commands/vg/_shared/templates/TEST-GOAL-enriched-template.md`. Per-goal threat declaration:
  ```yaml
  adversarial_scope:
    threats: [auth_bypass, injection, duplicate_submit]
    per_threat:
      auth_bypass:
        paths: ["other-tenant-id", "different-role", "expired-session"]
        assertions: ["status: 403 OR 404", "no PII leak in error body"]
      injection:
        payloads: ["${SQLI_PAYLOAD}", "${XSS_PAYLOAD}"]
        assertions: ["no payload execution"]
  ```
  Empty `threats: []` is an explicit decision, not a forgotten field — AI should comment why the goal is low-risk. Threat taxonomy v1: `auth_bypass`, `injection`, `race`, `duplicate_submit`, `boundary_overflow`, `role_escalation`, `csrf_replay`. New `adversarial_evidence` field at goal-bottom for /vg:test population.

- **Hook 3 — `verify-adversarial-coverage.py`** (`scripts/validators/`):
  - Rule 1: goal has `security_checks` block but no `adversarial_scope` → WARN (declare or set explicit `threats: []`)
  - Rule 2: `auth_model != public` AND `threats` missing both `auth_bypass`/`role_escalation` → WARN
  - Rule 3: `pii_fields` non-empty AND `threats` missing `injection` → WARN
  - Severity = warn (v1 dogfood-friendly). Promote to block via `vg.config.md → adversarial_coverage.severity = "block"`.
  - Override path: `--skip-adversarial=<reason>` (≥10 chars expected) — caller logs critical OVERRIDE-DEBT entry.
  - Smoke-tested 4 fixture goals: G-01 (security + adversarial both present, valid) → PASS; G-02 (security but no adversarial) → WARN missing-block; G-03 (no security_checks) → exempt; G-04 (PII without injection coverage) → WARN injection required.

- Registry entry `adversarial-coverage` (`scripts/validators/registry.yaml`): severity=warn, phases=[test, accept], domain=security, runtime=1500ms.

### Modified
- **`commands/vg/test.md` step 5d** — appended adversarial gate after the codegen→r7 console block. Reads `vg.config.md → adversarial_coverage.severity` (default warn). On WARN: prints findings, emits `test_adversarial_coverage_gap` telemetry, continues. On BLOCK + gap: exits 1 with override hint. `--skip-adversarial='<reason>'` flag forwarded to validator.

### Deferred to v2.22+ (Hook 2 — codegen)
- `commands/vg/_shared/templates/ADVERSARIAL-PAYLOAD-LIBRARY.md` (SQLI/XSS/SSTI/path-traversal/cmd-injection ready-to-use payloads)
- `commands/vg/_shared/templates/adversarial-spec.tmpl` (Playwright spec template per threat type)
- `scripts/vg_adversarial_codegen.py` engine (reads `adversarial_scope`, emits `<goal-id>.adversarial.<threat>.spec.ts`)
- `commands/vg/blueprint.md` Round 4 prompt extension nudging AI to populate `adversarial_scope`
- `commands/vg/accept.md` aggregator surfacing failed adversarial specs

### Why declarative-first
Adversarial coverage starts with intent ("what threats matter?"), not implementation ("here's a SQL payload"). Shipping the schema + WARN gate first lets phases declare threats during normal blueprint flow. Codegen ships next once we see real declarations to template against. This avoids generating spec scaffolding that doesn't match the 80% threat-shape across active projects.

### Pipeline impact
- `/vg:blueprint` — no behavior change (template available; AI may now emit `adversarial_scope` voluntarily)
- `/vg:test` step 5d — new WARN gate, default non-blocking. Override flag available
- `/vg:accept` — no aggregator yet (deferred); existing override-debt critical surfacing handles `--skip-adversarial` entries

## v2.20.0 (2026-04-28) — `/vg:polish` optional code-cleanup command

User asked: should code-clean / optimize be wired into the pipeline as a step after build / review / test / fix? Plan-mode pushback: NO, not as a gate. Reasons in `.claude/plans/cheeky-mapping-engelbart.md`:

1. Zero evidence vgflow-built code is dirty enough to warrant a hard gate. Building gates for non-existent problems is premature.
2. Each cleanup commit is a regression risk; gating means clean → re-test → re-clean loop in loop, 2-3× phase slowdown for 5% dirty-code reduction.
3. `simplify` skill (gstack) already covers the same need from user discretion.
4. "Polish" is a human judgement, not a gate-able rule (auto-extract a function may strip domain context, auto-rename may erase intent).

Shipped instead as **optional command** users invoke when ready:

### New
- **`/vg:polish`** (`commands/vg/polish.md` + `scripts/vg_polish.py`):
  - Modes: `--scan` (default, dry-run preview) | `--apply` (atomic commit per fix)
  - Levels: `--level=light` (default) — strip leftover `console.log`/`console.debug`/`console.info`, trailing whitespace. Safe: only touches code that cannot affect runtime. `--level=deep` adds warn-only signals (long functions >80 lines, empty if/else/catch blocks). v1 deep mode is warn-only — no auto-refactor.
  - Scope: `--scope=phase-N` | `--since=<sha>` | `--file=<path>`. Default = whole repo.
  - Per fix: read file, apply minimal edit, `git add` + `git commit -m "polish: <type> in <file>"`. Atomic — failure on one fix doesn't block others.
  - Reverse line-order apply per file so deletions don't shift indices for subsequent fixes in same file.
  - Working-tree-clean precondition (override with `--allow-dirty` for users mid-WIP).
  - Telemetry: `polish.started` / `polish.fix_applied` / `polish.completed`. Decide ROI from `/vg:telemetry --command=vg:polish` after a few months of dogfood; if useful, v3 may promote to gate.

### Detector smoke test (sample.ts fixture)
3 fix candidates + 2 warnings detected. Apply produces 2 atomic commits (1 fix per commit, deduplication via reverse-line ordering when overlap with trailing-whitespace on the same line). `console.error` correctly preserved (not in default delete list). Commented-out `console.log` correctly skipped.

### Deferred to v2.21+
- Unused imports / unused vars detector (needs language-aware tooling — eslint/ruff/tsc integration)
- Deep-mode auto-refactor (long-fn extraction, dup-block dedup) — v1 is warn-only
- `polish-helpers.sh` bash module (engine is Python; bash helpers not needed for v1)

### Pipeline impact
Zero. Pipeline (specs → scope → blueprint → build → review → test → accept) does NOT depend on `/vg:polish`. Accept gate unchanged. No new validators registered (opt-in only via `vg.config.md`).

## v2.19.0 (2026-04-28) — Bug squash + run-backfill subcommand (closes 14 issues)

Triage sweep of accumulated `bug-auto` queue surfaced 6 new issues + 1 PR same morning. Single commit-batch closes all of them plus 8 stale issues already fixed in prior versions. One new feature (`run-backfill`) earns the minor bump; everything else is fix.

### New
- **`vg-orchestrator run-backfill`** (`scripts/vg-orchestrator/__main__.py`): documented path for emitting `run.completed` on legacy runs that predate Stop-hook contract enforcement (issue #21). Strict 5-condition guard: (1) `run.started` exists for `--run-id`, (2) no terminal event already, (3) command in supported set, (4) all required artifacts present in phase dir (mirrors `event-reconciliation` REQUIRED_ARTIFACTS), (5) `--reason` ≥ 10 chars. On success: emits `run.completed` with `payload.backfill=true` AND appends critical-severity entry to `OVERRIDE-DEBT.md` so the reviewer must triage at `/vg:accept`. Replaces the `db.append_event` bypass workaround that violated the forgery-detection guard.

### Fix
- **Registry YAML parse** (`scripts/validators/registry.yaml`): two `description:` entries had unquoted `: ` mid-string (line 747 + 889), breaking `yaml.safe_load` at line 747 col 310. Single-quote wrap restored 93/93 entry parse. The pre-existing failure was masking `validator-registry` from loading the catalog (`validate` / `list` returned 0 entries).
- **Commit-attribution regex** (#20, PR #23 by external contributor — merged): `CITATION_PATTERNS` accepted only literal `Per CONTEXT.md D-XX` / `Covers goal: G-XX`. 30+ real commits using natural variants (`implements P1.D-78`, `Goals G-100, G-141`, `G-W10-05`, `G-141.M1`) failed the gate. Relaxed to `\b(?:P[\d.]+\.)?D-(?:\d+|XX)\b` and `\bG-[\w.]+\b`. Phantom-ID detection downstream unchanged (still catches fabricated D/G IDs that don't resolve to real artifacts).
- **`bug-reporter.sh` redact + assignee** (#22, also closes #17 #18 noise + #7 verified): `sed 's|\\|/|g'` was malformed (bash double-quote ate one backslash → sed got `s|\|/|g` matching `|`, not `\`). Bash native `${x//\\//}` also failed under MSYS bash 5.2 glob matcher. Switched whole redact path to a Python subprocess — verified 6 cases (backslash + forward-slash paths, email, phase ID, plain text, empty, embedded quotes). Empty-data side-effect that collapsed sigs to `7467b7f1` resolved. `gh issue create --assignee=vietdev99` permission failures for external submitters now retry without `--assignee` so reports still land. Issue #7's arg-validation guard at lines 358-376 verified in place.
- **`override-resolve` ID format** (#19): orchestrator CLI writes register entries with `OD-NNN` IDs in YAML form; slash command regex only matched legacy table-format `DEBT-YYYYMMDDHHMMSS-PID`. Relaxed to `(DEBT-[0-9]+-[0-9]+|OD-[0-9]+|BF-[0-9]+-[0-9]+)`. Helper `override_resolve_by_id` now branches on ID prefix: YAML IDs → flip `status: active` + insert `resolved_at`/`resolved_event_id`/`resolution_reason` immediately after status (contiguous block); table IDs → unchanged path. The `BF-` flavor was added in the same commit batch for `run-backfill` debt entries.
- **Marker-walk repo root** (`scripts/validator-registry.py`, `scripts/tests/test_validator_registry.py`): both files used a fixed `parents[N]` index that resolved correctly only at install-target depth. Running canonical `scripts/...` directly walked one level outside the repo, so CLI silently reported 0 entries and pytest hit `JSONDecodeError`. Replaced with marker-walk searching upward for `VERSION` + `.git`. Verified canonical CLI now reports 93 entries; canonical pytest 12/12 pass; install-target pytest still 12/12.

### Closed
14 issues closed:
- **Active fixes:** #19, #20, #21, #22 (this release)
- **Verified existing:** #7 (arg-validation guard already present), #14 (wontfix-upstream — Claude Code core injects `<system-reminder>` at harness layer, no skill-side suppression API)
- **Duplicate noise:** #17, #18 (root cause = #22 redact bug, sigs collapsed to `7467b7f1`)
- **Stale fixes shipped in prior versions, verified on v2.18.0:** #3 (v1.11.1), #4 (v1.12.x migration), #6 (v1.12.2+ schema validation), #9 (v1.12.2+ bug-reporter), #10 #11 #12 #13 (all v1.14.1)

## v2.18.0 (2026-04-28) — Phase 20 Wave C: mobile mockup + reverse-engineer + Pencil validator

Wave C closes Phase 20 entirely. 3 decisions covering mobile design tooling, migration use-case (live URL → mockups), and Pencil output sanity.

- **D-13 — Sketch tool** (`scaffold-sketch.sh`): new entry `[i]` in tool selector. macOS-only manual export (`.png` from artboards). Mobile-friendly because Sketch ships built-in iOS/Android/watchOS artboard presets. Reuses `scaffold_wait_for_files` validation pattern from D-04. Decision matrix updated.
- **D-14 — `/vg:design-reverse`**: NEW command for migration projects. Playwright crawls a live URL + route list, captures PNG per route into `design_assets.paths/{slug}.png`. Cookies support for authenticated apps; viewport + `--full-page` flags. Output drops where `/vg:design-extract` consumes via `passthrough` handler — enables Phase 19 L1-L6 gates retroactively on projects with live UI but no design source files (the RTB use case). Companion script `scripts/design-reverse.py` with PASS / PARTIAL / BLOCK verdicts.
- **D-15 — `verify-pencil-output.py`**: defensive validator catching Pencil MCP `batch_design` syntax errors that produce 0-byte or wrong-format output silently. Heuristics: file ≥ 100 bytes; not PNG/JPG/HTML/JSON magic. Registered in `registry.yaml` as severity=block phase=scaffold. Smoke-tested 5 cases: missing / empty / PNG-format / random-200B-pass / no-entries-skip.

**Phase 20 final:** 15 decisions across 3 waves (D-01..D-12 Wave A, D-08..D-11 Wave B, D-13..D-15 Wave C). 10 tools supported (added Sketch in Wave C). 1 reverse-engineer command for migration. Both scaffold (greenfield) and reverse (live UI) directions covered.

**Coverage matrix:** greenfield ✅ (Wave A), tool diversity ✅ (8 Wave A + 1 Wave C), iteration loop with view-decomp ✅ (Wave B), migration ✅ (Wave C), output validation ✅ (Wave C). The only remaining gap is dogfood reliability measurement on real projects — process work, not code.

## v2.17.0 (2026-04-28) — Phase 20 Wave B: PenBoard auto + Claude design + v0 CLI + VIEW-COMPONENTS feedback

Wave B closes Phase 20. Promotes 2 stub tools to full implementation, conditionally automates 1 external tool, and wires the P19→P20 feedback loop.

- **D-08 — PenBoard MCP automated** (`scaffold-penboard.sh` full impl): agent prompt for `mcp__penboard__*` chain. Workspace mode — single `.penboard` file containing multi-page navigation, shared Sidebar/TopBar across pages, entity declarations, primary user flows via `mcp__penboard__write_flow`. ~$0.20/page Opus (heavier than Pencil due to MCP tool overhead).
- **D-09 — Claude design-shotgun integration** (`scaffold-claude-design.sh` full impl): detects `gstack:design-shotgun` skill via `~/.claude/skills/` glob. When present, emits orchestrator prompt for `/design-shotgun` (variants) + user pick + `/design-html` finalization chain. When absent, prints fallback message + ai-html alternative.
- **D-10 — v0 CLI conditional automation** (`scaffold-v0.sh` extension): detects `v0` CLI on PATH + auth via `v0 whoami`. Authenticated → drives `v0 generate --prompt --output --format html` per page, writes evidence with `v0_cli=true`. Else falls back to existing manual-export instructional.
- **D-11 — VIEW-COMPONENTS-aware mockup generation**: D-02 (Pencil MCP) and D-03 (AI HTML) prompts now detect `${PHASE_DIR}/VIEW-COMPONENTS.md` (P19 D-02 vision-decomposition output). When present, per-slug component list becomes AUTHORITATIVE input — every component must appear in mockup output. Closes the P19↔P20 feedback loop: vision decomposition spec → scaffold consumes → tighter mockups → P19 L1-L6 verify against tighter ground truth.

**Backward compatibility:** D-11 gates by file presence — projects without P19 D-02 baseline (first scaffold pass) get original prompts unchanged.

Phase 20 fully shipped. All 12 decisions (D-01..D-12) implemented across Wave A (v2.16.0) + Wave B (v2.17.0). Future tracking: dogfood reliability measurement on greenfield phase, mobile-specific mockup tools (Sketch/Marvel), reverse-engineering live UI to mockups (separate phase).

## v2.16.0 (2026-04-28) — Phase 20 Wave A: greenfield design scaffold

Closes the upstream gap exposed by Phase 19. Greenfield projects (zero design assets) bypassed every L1-L6 gate via Form B `no-asset:` and shipped AI-imagined UI. Wave A delivers an entry command, blueprint pre-flight gate, and 8-tool selector covering Pencil MCP / PenBoard MCP / AI HTML / Claude design / Stitch / v0 / Figma / manual.

- **D-01 — `/vg:design-scaffold` entry command** with `--tool=<id>` selector + decision matrix (`--help-tools`). Default `pencil-mcp` per user choice. Bulk by default + `--interactive` flag for per-page review pause.
- **D-02 — Pencil MCP automated** (`scaffold-pencil.sh`): spawns Opus with `mcp__pencil__batch_design` + DESIGN.md tokens, output `.pen` files for `pencil_mcp` handler.
- **D-03 — AI HTML automated** (`scaffold-ai-html.sh`): Opus emits HTML+Tailwind from DESIGN.md tokens; L-002 anti-pattern explicitly banned in prompt; output `.html` for `playwright_render` handler.
- **D-03b — Auto-regen on DESIGN.md change** (`scaffold-staleness-check.py`): caches by DESIGN.md SHA256 in `.scaffold-evidence/<slug>.json`; mismatch → mark stale → re-run.
- **D-04 — 4 instructional sub-flows**: `scaffold-stitch.sh` (Google Stitch), `scaffold-v0.sh` (Vercel v0), `scaffold-figma.sh` (Figma), `scaffold-manual.sh` (hand-written HTML). Print tool-specific instructions + `scaffold_wait_for_files` validation loop with [c]ontinue/[s]kip/[a]bort prompts.
- **D-05 — `/vg:specs` proactive suggestion**: after SPECS committed, soft-prints `/vg:design-system + /vg:design-scaffold` recommendations when FE work + missing tokens/mockups.
- **D-06 — Greenfield Form B critical block at `/vg:accept`**: extends step 3c with `verify-override-debt-threshold.py --kind 'design-greenfield-*' --threshold 1` — ANY single greenfield Form B BLOCKs accept until resolved via scaffold or rationalization-guard.
- **D-12 — Blueprint pre-flight design discovery (NEW per user request 2026-04-28)**: new step 0_design_discovery in `/vg:blueprint` — detects FE work + zero mockups, AskUserQuestion routes 5 options ([a]existing path, [b]external tool, [c]scaffold, [d]explicit skip with critical debt, [skip]one-time bypass). Re-checks after a/b/c. Config gate `design_discovery.enabled` (default true). Closes the silent-skip risk that D-05 soft suggestion alone can't prevent.

**Wave B deferred (v2.17.0):** D-08 PenBoard MCP automation, D-09 Claude design-shotgun integration, D-10 v0 CLI hook, D-11 VIEW-COMPONENTS-aware scaffold (P19 D-02 feedback loop).

**Tool stubs in Wave A:** `scaffold-penboard.sh` and `scaffold-claude-design.sh` print Wave B deferral message + manual workaround.

**Codex mirror count:** 61 → 62 (added `vg-design-scaffold`).

## v2.15.3 (2026-04-28) — CI hard-gate on codex mirror drift (closes #16 process gap)

Patch release. Closes the process gap that allowed v2.15.0–v2.15.1 to ship stale codex mirrors. No code behaviour change.

- `.github/workflows/release.yml` now runs `verify-codex-mirror-equivalence.py` between Setup Python and Build tarball steps. If any of 61 mirror pairs is functionally non-equivalent to canonical after adapter strip, the release fails with a clear remediation sequence (regen + commit + delete-and-retag).
- Pre-2.13.0 tags get a graceful skip (verifier file absent in early tags).
- Effect: any future canonical change (`commands/vg/*.md`) without matching `generate-codex-skills.sh --force` will block tagging at CI time. No silent shipped drift possible.

This is the third option from the recommendation set in CHANGELOG v2.15.2 — chosen over post-commit hook (#2) and pre-tag git hook (#3) because it cannot be bypassed by skipping local hooks.

## v2.15.2 (2026-04-28) — Codex mirror regen (fixes #16)

Patch release closing #16. v2.15.1 release tarball shipped stale `codex-skills/*/SKILL.md` mirrors because Phase 19 commits (v2.13.0–v2.15.0) modified canonical `commands/vg/{accept,blueprint,build,review}.md` without re-running `scripts/generate-codex-skills.sh`. `/vg:sync --verify` after standard-install upgrade reported 5 functional drifts.

- Re-ran generator with `--force`; verifier reports 61/61 pairs OK (zero functional drift after adapter strip).
- 4 mirrors regenerated: vg-accept (+74 lines for D-06), vg-blueprint (+196 for D-01+D-02+D-03), vg-build (+343 for L1+L2+L3+L5+L6 gates), vg-review (+117 for phase 2.5 sub-step 6e).
- Process gap noted: codex mirror regen should auto-fire on canonical change, or be enforced by pre-release CI. Tracking as follow-up; until then, `generate-codex-skills.sh --force` must run before any release tag.

## v2.15.1 (2026-04-28) — Validator registry catch-up (install/update propagation)

Patch release. No behaviour change — closes the catalog gap so the new gates from v2.13.0–v2.15.0 surface in `/vg:validators`, `/vg:doctor`, `/vg:gate-stats`, and the validator-drift check.

- 9 catalog entries added to `scripts/validators/registry.yaml`: `layout-fingerprint`, `build-visual`, `design-ref-coverage` (v2.13.0); `ui-spec-scan-coverage`, `view-decomposition`, `vision-self-verify`, `override-debt-threshold` (v2.14.0); `read-evidence`, `component-scope` (v2.15.0). Each entry declares severity, phases_active, domain, runtime_target_ms, added_in, and one-line description per registry schema.
- `install.sh` and `/vg:update` mechanisms verified to deploy the new artifacts without changes:
  - Fresh `install.sh` smoke landed all 9 new validators + `verify-build-visual.py` + `commands/vg/_shared/design-fidelity-guard.md` + commit-msg hook with D-08 citation gate.
  - `/vg:update` step 6 maps `scripts/*` → `.claude/scripts/*` and uses straight-copy (NEW_FILES path) for files absent locally; modified files use existing 3-way merge.
- No code change to install.sh / update.md was required — recursive `cp` patterns and path-mapping case statements already handle the new files.

## v2.15.0 (2026-04-28) — Closing Phase 19: cryptographic Read evidence + fine-grained planner

Closes the two items v2.14.0 left open. With this release, every Phase 19 decision (D-01 through D-09) has shipped or is documented research.

- **D-09 — read-evidence sentinel with PNG SHA256 (L6 build gate)**: promoted from RESEARCH.md to a shipped gate. Executor MUST Write `.read-evidence/task-${N}.json` after Read PNG, declaring the SHA256 of every file Read at that moment. New `verify-read-evidence.py` re-hashes every declared PNG; mismatch = BLOCK. Cryptographically infeasible to fabricate (search space 2^256), so this is the strongest "prove you Read it" gate available without runtime hook transcript surface. Wired in `build.md` step 9 after L5; off by default via `visual_checks.read_evidence.enabled` until executor rule rollout.
- **D-04 — fine-grained planner component-scope (FEATURE-FLAGGED)**: planner Rule 9 added. When `planner.fine_grained_components.enabled=true` AND `VIEW-COMPONENTS.md` exists (D-02 output), planner decomposes one-page tasks into N tasks per top-level component (`child_count >= 3` OR `position area >= 20% viewport`). New `<component-scope>{Name}</component-scope>` task field. New `verify-component-scope.py` blocks at /vg:build step 9 when staged files fall outside the declared scope and aren't explicitly listed in `<file-path>`. NO-OPS on tasks without the tag → fully backward compatible with v2.14.0 PLAN files.

**Config additions:**
- `visual_checks.read_evidence.enabled` (D-09)
- `planner.fine_grained_components.enabled` (D-04)

**Phase 19 status — final:**

| Decision | Status |
|---|---|
| D-01 scan.json into UI-SPEC | ✅ shipped v2.14.0 |
| D-02 view-decomposition step 2b6c | ✅ shipped v2.14.0 |
| D-03 cross-AI gap-hunt | ✅ shipped v2.14.0 |
| D-04 fine-grained planner | ✅ shipped v2.15.0 (flagged) |
| D-05 vision-self-verify (L5) | ✅ shipped v2.14.0 |
| D-06 manual UAT 3-file diff | ✅ shipped v2.14.0 |
| D-07 override-debt threshold | ✅ shipped v2.14.0 |
| D-08 commit-msg citation | ✅ shipped v2.14.0 |
| D-09 sentinel-with-hash (L6) | ✅ shipped v2.15.0 |

Combined ladder reaches the practical reliability ceiling: ~95% with all default-on layers, ~97% with D-04+D-09 enabled and dogfood-tuned.

## v2.14.0 (2026-04-28) — Design fidelity 95%: upstream view-decomp + downstream vision guard + forcing functions

Phase 19 minor release. Closes the residual gap after v2.13.0's 4-layer pixel pipeline + L-002 mandate. Eight decisions (D-01 through D-09; D-04 deferred), three implementation waves. AI alone never reaches 100%, but the combined stack now meaningfully approaches 95% reliability on dogfood phases.

**Wave A — cheap, high leverage:**
- **D-01 — `scan.json` consumed in UI-SPEC**: blueprint step 2b6 now reads `${DESIGN_OUT}/scans/{slug}.scan.json` for every `<design-ref>` slug. Modals/forms/tabs discovered by Layer 2 Haiku must surface in UI-SPEC.md `## Modals` / `## Forms` / `## Per-Page Layout`. New `verify-ui-spec-scan-coverage.py` blocks if the agent silently dropped scan findings.
- **D-05 — vision-self-verify (Lớp 5)**: separate-model adjudication at /vg:build step 9. Spawns Haiku zero-context with the design PNG + commit diff + VIEW-COMPONENTS row, gets PASS/FLAG/BLOCK on whether expected components actually appear in the JSX. Closes the gap where pixel-similar UI passes L3/L4 SSIM yet misses components entirely. New `verify-vision-self-verify.py` + `design-fidelity-guard.md` skill. Off by default (config gate); ~$0.001/task Haiku when enabled.
- **D-06 — manual UAT 3-file diff**: /vg:accept Section D now surfaces `baseline.png` + `current.png` + `diff.png` side-by-side when L4 SSIM produced a diff. User picks `[f]` → phase rejected with `kind=human-rejected-design` debt; AI cannot bypass interactive prompt.

**Wave B — vision upstream:**
- **D-02 — view-decomposition step 2b6c**: blueprint inserts a step BEFORE UI-SPEC that spawns vision-capable Opus per `<design-ref>` slug to Read the PNG and emit canonical `VIEW-COMPONENTS.md` (semantic component list with positions). New `verify-view-decomposition.py` blocks generic names (div/Container/Wrapper alone), enforces minimum 3 components per slug. Off by default — opt-in via `design_assets.view_decomposition.enabled`.
- **D-03 — cross-AI gap-hunt**: same step 2b6c gets a second adversarial pass with a DIFFERENT model (per `vg.config.crossai_clis`) asking "what did Layer 1 miss?". Reuse of `vg-design-gap-hunter` pattern. ≥2 missed → re-spawn Layer 1 with reminder, max 1 iteration.

**Wave C — forcing functions, closing back doors:**
- **D-07 — design override-debt threshold gate**: /vg:accept step 3c new sub-gate. Blocks accept when ≥N (default 2) unresolved `kind=design-*` entries exist in OVERRIDE-DEBT.md. Caps the stacking of `--skip-design-pixel-gate` / `--skip-fingerprint-check` / `--skip-build-visual` / `--allow-design-drift`. New `verify-override-debt-threshold.py` (count-based, fnmatch glob filter — distinct from age-based SLA validator).
- **D-08 — commit-msg design citation gate**: extends `templates/vg/commit-msg` hook. FE files staged without `Per design/{slug}.png` OR `Design: no-asset (reason)` OR `Design: refactor-only` get rejected at commit boundary. PR #15 L-002 rule moves from convention to hard gate. Independent of `commit_msg_hook.enabled`; gated by `design_citation.enabled` (default true). Pure-rename commits bypass.

**Research only:**
- **D-09 — transcript verification feasibility**: documented in `dev-phases/19-design-fidelity-95-pct-v1/RESEARCH.md`. Direct subagent transcript inspection is NOT feasible with current Claude Code surface (`SubagentStop` returns final output text only, no `tool_calls` payload). Sentinel-file-with-PNG-SHA256 fallback is implementable now but deferred — L1+L2+L5+L6 already meet the 95% target without it.

**Deferred:**
- **D-04 — fine-grained planner re-emit from VIEW-COMPONENTS** marked HIGH risk in plan; would change planner output shape and break existing PLAN fixtures. Skipped this release; revisit after dogfood validates VIEW-COMPONENTS quality.

**Config additions:**
- `visual_checks.vision_self_verify.{enabled,model,timeout_s}` (D-05)
- `design_assets.view_decomposition.{enabled,model,min_components_per_slug}` (D-02)
- `override_debt.design_threshold` (D-07)
- `design_citation.enabled` (D-08)

**Reliability ladder (anecdotal estimate):**

| Stack | Reliability |
|---|---|
| Pre-v2.13 (prompt + manual UAT only) | ~30% |
| v2.13.0 (4 layers + L-002) | ~70% |
| v2.14.0 Wave A (D-01 + D-05 + D-06) | ~85% |
| v2.14.0 full (Wave A + B + C) | ~95% |
| v2.14.0 + D-09 sentinel-with-hash (future) | ~97% |
| 100% | impossible — AI is stochastic |

## v2.13.0 (2026-04-28) — Design pixel fidelity pipeline (4 layers) + L-002 planner mandate

Minor release closing the silent-skip gap where AI-built UI shipped generic Tailwind despite a phase having a complete design folder. Four stacked gates so a slip in any one layer is caught by the next, plus a planner-side coverage validator.

- **L-002 lesson — `<design-ref>` mandate (PR #15):** `vg-planner-rules.md` Rule 8 makes `<design-ref>` MANDATORY for FE tasks (file-path matches `apps/{admin,merchant,vendor,web}/**`, `packages/ui/src/{components,theme}/**`, or extension `.tsx/.jsx/.vue/.svelte`). Two emit forms — Form A (slug from `manifest.json`), Form B (`no-asset:{reason}` for explicit gaps, never silent). `vg-executor-rules.md` "Design fidelity" rewritten: Read each PNG via Read tool, cite `Per design/{slug}.png` in commit body, anti-pattern `flex items-center justify-center` for authenticated pages explicitly named.
- **L1 — design-pixel hard-gate at executor spawn:** `pre-executor-check.py` now emits absolute `design_image_paths` + `design_image_required`; `/vg:build` step 8c verifies every required PNG exists on disk before spawning the executor. Override `--skip-design-pixel-gate` (logged to override-debt). Architect L2 prompt template gets the same vision injection rule.
- **L2 — LAYOUT-FINGERPRINT forcing function:** new `verify-layout-fingerprint.py` validator at `/vg:build` step 9 requires `.fingerprints/task-N.fingerprint.md` with H2 sections Grid/Spacing/Hierarchy/Breakpoints (>=60 chars each) before code commits for any `<design-ref>` slug task. Override `--skip-fingerprint-check`.
- **L3 — build-time visual gate:** new `verify-build-visual.py` renders each `<design-ref>` task via headless Playwright + pixelmatches against the design baseline at `/vg:build` step 9. Auto-SKIPs cleanly when dev server / Node / pixelmatch is missing - projects without the harness are not blocked. Override `--skip-build-visual` for real diffs.
- **L4 — design-fidelity SSIM at review:** `/vg:review` phase 2.5 sub-step 6e SSIM-checks every `RUNTIME-MAP` view with a `design_ref` slug, BLOCK on threshold breach. Override `--allow-design-drift` consumes a rationalization-guard slot.
- **PR #15 follow-up — coverage validator:** new `verify-design-ref-coverage.py` walks every PLAN.md task; classifies FE vs non-FE; BLOCKs on missing `<design-ref>`, slug not in manifest, or Form B without reason. WARNs (skips slug validation) when manifest absent; `--strict` promotes WARN to BLOCK for CI.
- **Config:** `design_fidelity_threshold_pct` added to `visual_checks`; `dev_server_url` + `visual_threshold_pct` added to `build_gates`. Both `vg.config.template.md` (top-level) and `templates/vg/vg.config.template.md` (token version) updated.

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
