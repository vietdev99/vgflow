# VG Executor Rules — Append-to-CLAUDE.md snippet
#
# Append this section to the target project's CLAUDE.md (project root).
# These are UNIVERSAL rules for any agent executing VG plan tasks.
# They override GSD generic defaults where conflict (e.g., --no-verify bypass).
#
# Why this is a separate file: vgflow install.sh does NOT auto-modify CLAUDE.md —
# too intrusive. User copy-pastes this block once, then all VG executor runs
# read it from CLAUDE.md on subagent spawn.

## VG Executor Rules (universal, all phases)

Applies to any agent executing VG plan tasks (general-purpose subagent
spawned by /vg:build, or any direct code change under VG workflow).
These rules are VG-native and apply regardless of which subagent type
the orchestrator selects.

**IMPORTANT — VG vs GSD executor:** /vg:build spawns
`subagent_type=general-purpose`, NOT `gsd-executor`. GSD's executor
agent enforces a different (looser) rule set including `--no-verify`
parallel mode that VG explicitly forbids. If a wave dispatch shows
"gsd-executor(...)" in the spawn line, that is a stale-install symptom
— /vg:update silent-merge bug (#30, fixed v2.24.0) kept old build.md.
Re-run /vg:update on v2.24.0+ to land the general-purpose dispatch.

### Commit discipline

1. **Commit message pattern** — MUST match regex:
   `^(feat|fix|refactor|test|chore|docs)\([0-9]+(\.[0-9]+)*-[0-9]+\): `
   Example: `feat(7.6-04): add POST /api/sites handler`

2. **Commit body citation** (MANDATORY if touches apps/**/src/** OR packages/**/src/**):
   - Contract: `Per API-CONTRACTS.md line {start}-{end}` (if task touches API)
   - Decision: `Per CONTEXT.md D-XX` (if no contract, but traces to decision)
   - Goal: `Covers goal: G-XX` OR `no-goal-impact` (explicit)
   Missing → commit-msg hook rejects.

3. **NEVER use `--no-verify`** on any file under apps/**/src/**, packages/**/src/**.
   GSD generic execute-plan.md instructs --no-verify in parallel mode — VG OVERRIDES.
   If pre-commit hook fails: READ error → FIX → retry. Max 2 retries per commit,
   then escalate via deviation Rule 4 (architectural).

4. **Before EVERY commit** — run typecheck for affected scope:
   - Monorepo: `{config.build_gates.typecheck_cmd}` (e.g., `pnpm turbo typecheck`)
   - Single app: `{config.build_gates.typecheck_cmd} --filter {app}`
   Must exit 0. Fail → fix inline → re-typecheck. Do NOT commit failing code.

### Contract adherence

5. **Copy contract verbatim** — when API-CONTRACTS.md has `typescript`/`yaml`/`python`
   code blocks per config.contract_format.type:
   - If target schemas file does NOT YET have this symbol → copy code block VERBATIM
     (or import from `{config.contract_format.generated_types_path}` if codegen applies)
   - If symbol already exists (identical name in target file or re-exported from a
     shared types package) → do NOT copy. Extend instead:
       * Zod: `BaseSchema.extend({...})`, `BaseSchema.merge(...)`, `BaseSchema.pick/omit`
       * Pydantic: subclass `class Extended(Base): ...`
       * TypeScript: `interface Extended extends Base { ... }` or `type X = Base & {...}`
   - NEVER retype schemas by hand (source of typos)
   - NEVER duplicate a symbol across files — causes "duplicate identifier" / collision errors

### Design fidelity

6. **Honor design-ref** — if task has `<design-ref>` attribute:
   - READ referenced screenshot `.planning/design-normalized/screenshots/{slug}.{state}.png`
   - READ structural `.planning/design-normalized/refs/{slug}.structural.html` (or .json/.xml)
   - READ interactions `.planning/design-normalized/refs/{slug}.interactions.md` (if HTML)
   - Layout + components + spacing MUST match screenshot
   - Interactive behaviors MUST follow interactions.md handler map
   - Do NOT reinvent layout to "improve" — design is ground truth

### Phase-specific context

Phase-specific details (which endpoint, which goal, which design-ref) are
INJECTED via prompt per task in `/vg:build` step 8. This CLAUDE.md only
holds universal rules. If you receive a task prompt with `<contract_context>`,
`<goals_context>`, `<design_context>`, `<sibling_context>`, `<wave_context>`
blocks — those are authoritative for this task.

### Mobile-specific notes (profile ∈ mobile-*)

These are clarifications to the universal rules — they do NOT loosen them.

7. **Test file conventions** (recognized by Gate 5 goal-test binding):
   - Dart: `*_test.dart` (Flutter)
   - iOS XCTest: `Tests.swift`, `Test.swift`
   - Android JUnit: `Tests.kt`, `Test.kt`
   - Maestro flows: `*.maestro.yaml` / `*.maestro.yml`
   When committing a test covering `G-XX`, the test file MUST live under a
   conventional location AND contain the goal id token so Gate 5 binds them.

8. **Device/signing values come from env vars, not code:**
   - `APPLE_P12_PATH`, `APPLE_P12_PASSWORD`, `APPLE_TEAM_ID`, `ANDROID_KEYSTORE`
     are user-set env vars whose NAMES live in `config.mobile.signing.*_env`.
   - NEVER hardcode team IDs, bundle IDs, cert paths, or emulator names in
     source files or tests. Read from env / Expo / Gradle config.

9. **Mobile gates (build step 8d Gates 6-10) write to build-state.log:**
   - Format: `mobile-gate-N: <name> status=<passed|failed|skipped> [reason=...] ts=<UTC>`
   - If a gate you introduce tooling for is `skipped` with reason `no-tool`,
     honor `config.mobile.gates.native_module_linking.skip_on_missing_tool` —
     do NOT fail the wave. /vg:accept Section F surfaces this to the user.

10. **iOS build on non-macOS hosts** — workflow auto-switches to
    `config.mobile.deploy.cloud_fallback_provider` (default `eas`). Do NOT
    try to invoke `xcodebuild` directly from task code; use the helper in
    `_shared/mobile-deploy.md` which gates on `uname -s == Darwin`.
