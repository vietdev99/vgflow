# Changelog

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
