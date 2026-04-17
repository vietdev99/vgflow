# Changelog

All notable changes to VG workflow documented here. Format follows [Keep a Changelog](https://keepachangelog.com/), adheres to [SemVer](https://semver.org/).

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
