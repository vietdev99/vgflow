# VGFlow

> **Heavy AI Workflow for production-grade software projects.**
>
> **Languages:** [English](README.md) · [Tiếng Việt](README.vi.md)

VGFlow là một **config-driven AI development pipeline** mạnh mẽ — được thiết kế chuyên cho các dự án software lớn, đa thành phần, chất lượng production. Pipeline hỗ trợ đầy đủ các loại hình:

- **Web applications** (React / Next / Vue / Svelte frontend + Node / Python / Go / Rust backend)
- **Web servers / Backend APIs** (REST / GraphQL / gRPC, microservices, RTB engines, ad exchanges)
- **CLI tools** (CLI utilities, dev tools, DevOps automation)
- **Mobile apps** (React Native, Flutter, native iOS / Android, hybrid)

Zero hardcoded stack — mọi giá trị đều derive từ `vg.config.md`. Portable 100% qua mọi project, mọi ngôn ngữ, mọi deployment model (VPS / Docker / Kubernetes / serverless).

**Version:** 2.43.1 · **License:** MIT

**v2.43.1 (2026-05-01):** Roam hard gates — silent-skip enforcement via `runtime_contract.must_emit_telemetry` + `.tmp` markers, env/model/mode prompt always-fires (resume = pre-fill not lock-in), platform detection (web / mobile-native / desktop / api-only) with tool availability check, new `self` executor mode (current Claude Code session = executor via MCP Playwright). PR #65.

**v2.43.0 (2026-04-30):** `/vg:roam` exploratory CRUD-lifecycle pass + `/vg:deploy` standalone multi-env skill + `/vg:scope` step 1b `preferred_env_for` prompt. Roam is post-confirmation janitor — catches silent state mismatches `/vg:review`/`/vg:test` miss; lens-driven (table-interaction, form-lifecycle, business-coherence, etc.). Deploy: multi-select envs with prod typed-token gate, writes DEPLOY-STATE.json consumed by env recommendation engine.

**v2.41.0 (2026-04-30):** Backlog Closure — Tier-2 element classifiers wired (5 lenses now reachable), hybrid probe-mode actually implemented per `hybrid_routing` config, `recursion.state_hash_hit` + `recursion.mutation_budget_exhausted` telemetry, `/vg:review-batch` entry-point multi-fallback resolution. See [CHANGELOG](CHANGELOG.md#v2410).

---

## ⚠ Heavy Workflow — Không dành cho dự án nhỏ

VGFlow là một pipeline **chuyên sâu**, **nhiều tầng orchestration**, **token-intensive**. Không phải "hỏi AI sửa 1 file" — mỗi phase đi qua 7 steps, spawn multiple AI agents, chạy CrossAI consensus, validate qua weighted gates, commit theo atomic group. Token cost ở từng giai đoạn đáng kể:

- `/vg:scope` ~$0.15-0.30/phase (Opus adversarial challenger + dimension expander)
- `/vg:build` ~$0.50-2.00/phase (Sonnet execution waves, contract-aware)
- `/vg:deploy` ~$0.05/run (mostly bash + ssh, tiny AI surface) [optional, multi-env]
- `/vg:review` ~$0.30-0.80/phase (Opus navigator + Haiku scanners + CrossAI)
- `/vg:test` ~$0.20-0.50/phase (goal verification + codegen regression)
- `/vg:roam` ~$0.10-0.40/phase (lens-driven exploratory pass — `self` mode cheapest, `spawn` adds CLI cost) [optional, post-test]

**VGFlow shine nhất khi:**
- Phase có **10-50+ tasks**, spans **multiple apps** trong monorepo
- **Critical domain constraints** (billing, auth, auction, compliance, payout)
- Cần **audit trail** cho production deploy hoặc regulatory review
- Team có nhiều developers cần **decision traceability** (D-XX namespace)
- Performance SLA nghiêm ngặt (RTB ≤50ms, API p95 ≤200ms...)

**VGFlow KHÔNG phù hợp khi:**
- Chỉ cần sửa 1-2 files hoặc hotfix cấp tốc → dùng `/vg:amend` hoặc direct edit
- Prototype cuối tuần, one-off script → overhead không xứng
- Solo developer làm side project nhỏ → simpler workflow đủ

---

## 🚀 Tại sao chọn VGFlow

### Multi-tier AI Orchestration
**Opus / Sonnet / Haiku tier routing theo task complexity.** Opus cho reasoning-heavy gates (scope adversarial, plan architect, block resolver L2). Sonnet cho execution waves + code review. Haiku cho exhaustive scan, rationalization guard, pattern probing. Right model, right price, right quality.

### Lens-driven Exploratory Pass — `/vg:roam` (v2.43.0)
Post-test janitor catches silent state mismatches `/vg:review` + `/vg:test` miss. **20+ adversarial lenses**: table-interaction (filter/sort/paginate URL state sync), form-lifecycle (Create→Read→Update→Delete round-trip với UI/network/DB coherence), business-coherence (UI claim ↔ network truth ↔ DB read-after-write), modal-state (focus trap, ESC, multi-modal stacking), IDOR/BOLA, mass-assignment, BFLA, race conditions, SSRF, JWT alg confusion, file-upload polyglot, path traversal — full STRIDE+OWASP coverage as separate lens prompts. Commander analyzes raw observe-*.jsonl logs (R1-R8 deterministic rules), generates ROAM-BUGS.md + proposed `.spec.ts` files for the test suite. Per-brief skip on resume — partial runs don't waste prior work.

### Multi-Mode Executor — `self` / `spawn` / `manual` (v2.43.1)
Roam runs the same brief 3 different ways depending on environment:
- **`self`** — current Claude Code session IS the executor, drives Playwright MCP directly. No subprocess, no CLI auth, no Chromium permission issues. Login works because the model is authed to MCP servers. Cheapest + most reliable for web platforms.
- **`spawn`** — VG subprocess `codex exec --full-auto` or `gemini --yolo` per brief, parallel-bounded 5-slot. For when you want a different model voicing the run, or need parallelism across model dirs (Council mode).
- **`manual`** — VG generates `PASTE-PROMPT.md` + INSTRUCTION-*.md per surface; user pastes into any CLI of choice (Claude Code window, Codex desktop, Cursor, web ChatGPT). Drop JSONL back, VG aggregates.

Platform detection (web / mobile-native / desktop / api-only) reads CONTEXT.md keywords + checks tool availability (Playwright MCP, Maestro, adb, codex, gemini binaries) — only offers modes the platform supports. Mobile-native phase without Maestro+adb? Skill hard-blocks and suggests `/vg:setup-mobile`.

### Multi-Env Deploy Bridge — `/vg:deploy` (v2.43.0)
Optional standalone step between build and review/test/roam. Multi-select envs (sandbox/staging/prod), sequential per-env loop, per-env log files. **Prod gate**: separate AskUserQuestion 3-option danger gate (PROCEED / NON-PROD-ONLY / ABORT) interactively, OR `--prod-confirm-token=DEPLOY-PROD-{phase}` for non-interactive runs (token must match exactly — typo aborts). Captures `previous_sha` before overwrite for future `/vg:rollback`. Health check retries 6× 5s before marking failed. DEPLOY-STATE.json drives downstream env recommendation: review/test/roam env gate auto-suggests "sandbox (Recommended — deployed 2min ago, sha abc1234)" via `enrich-env-question.py` (suggestion-only — user always confirms).

### CrossAI N-reviewer Consensus
Blueprint + Scope reviews không phê duyệt bằng 1 AI. Pipeline spawn song song **Claude Code + OpenAI Codex CLI + Gemini CLI** → synthesize consensus → PASS / BLOCK / escalate disagreement. Independent eyes catch blind spots mà single-AI thường miss.

### Contract-Aware Wave Parallel Execution
`/vg:build` parse task dependency graph → graph-coloring waves → parallel execute. File conflicts auto-force sequential. **Contract injection** copies Zod / Pydantic / TypeScript schemas verbatim vào task prompts — zero typo drift từ API contract. Silent agent failures caught via **commit-count verification**.

### Goal-Backward Verification với Weighted Gates
Not "tests green" — mà **goal-coverage-matrix**: critical goals 100%, important 80%, nice-to-have 50%. Goals mapped to code via **surface taxonomy** (UI / API / Data / Integration / Time-driven), mỗi surface có dedicated runner. Mixed-phase project (some UI + some backend) vẫn cover hết.

### 8-Lens Adversarial Scope + Dimension Expander (v1.9.3)
Mỗi answer trong `/vg:scope` đi qua **8-lens Opus challenger**: contradiction · hidden assumption · edge case · foundation conflict · **security threat** · **performance budget** · **failure mode** · **integration chain**. Cuối mỗi round, **dimension-expander** (Opus) đặt câu hỏi "what haven't we discussed yet?" — proactive gap finding, không chờ bug xuất hiện.

### Phase Profile System (6 types)
Auto-detect `feature / feature-legacy / infra / hotfix / bugfix / migration / docs` từ SPECS.md → **gate policy + test mode + required artifacts** tự động phù hợp. Infra phase không cần TEST-GOALS. Migration phase phải có ROLLBACK.md. Feature-legacy (no SPECS) vẫn review được. Không một-size-fits-all.

### Block Resolver 4 Levels (L1 → L4)
Bị block giữa phase? Không phải hard stop. Pipeline escalates:
- **L1 Inline** — auto-fix candidate retries (cheap, local)
- **L2 Architect** — Haiku subagent propose solution (zero-context adjudication)
- **L3 User Choice** — AskUserQuestion với concrete options
- **L4 Stuck** — genuine blocker, escalate with full context

AI tự nghĩ option trước khi đòi user quyết định.

### Live Browser Discovery (MCP Playwright)
`/vg:review` không script tĩnh — organic exploration: click sidebar, click mỗi button, quan sát kết quả, catch console errors + network 4xx/5xx + i18n key resolution. **Mobile-aware (v1.9.4):** single-device projects (iOS sim / Android emu) auto-sequential spawn, web projects parallel 5-slot. CLI/library projects skip UI scan entirely.

### 3-Way Git Merge Updates
`/vg:update` pulls latest release from GitHub, **3-way merge** against user customizations, parks conflicts cho `/vg:reapply-patches`. Không clobber custom edits. Breaking changes (major version) yêu cầu `--accept-breaking` explicit.

### SHA256 Artifact Manifest + Atomic Commits
Mỗi phase có manifest hash-validates all artifacts (SPECS / PLAN / CONTEXT / TEST-GOALS / SUMMARY / RUNTIME-MAP...). Corruption detected early via `/vg:integrity`. Commits atomic per task với **namespace enforcement** `P{phase}.D-XX`.

### Structured Telemetry + Override Debt Register
Append-only JSONL events (gate hits, overrides, fix routing, phase timing). Query qua `/vg:telemetry` + `/vg:gate-stats`. Mỗi `--allow-*` / `--skip-*` được log với **event-based resolution** — không accumulate hidden technical debt.

### Rationalization Guard (Anti-Corner-Cutting)
Khi gate skip được đề xuất, spawn **Haiku subagent zero-context** adjudicates: real blocker vs rationalization? Anti-corner-cutting ở critical gates (compliance, security, performance).

### Visual Regression + Security Register
UI changes pixel-diff vs baseline screenshot. Threats từ **STRIDE + OWASP taxonomy** cumulated qua milestone, cross-phase correlation. Security audit chạy end-of-milestone — không bỏ sót.

### Foundation Drift Detection
8-dimension foundation (platform / runtime / data / auth / hosting / distribution / scale / compliance) lock tại `/vg:project`. Mỗi phase scope check drift — nếu phase đột ngột assume cross-tenancy mà foundation nói single-tenant → flag immediately.

### Incremental Graphify (Knowledge Graph)
Codebase auto-rebuild knowledge graph sau mỗi build wave — fresh sibling/caller context cho next wave. God nodes + communities injected vào scope/plan prompts. Code understanding scale với codebase size.

---

## Reliability Engineering — Những gì xảy ra khi mọi thứ sai

VGFlow không chỉ là happy-path workflow. Từ v2.19.0–v2.32.1, mỗi bug từ production dogfood được trace đến root cause và fix ngay trong cùng pipeline. Dưới đây là những cơ chế bảo vệ được xây từ thực tế:

### Multi-Session Parallel Execution (v2.28.0)
**Problem:** Mở 2 Claude Code windows — `/vg:scope phase 1` + `/vg:build phase 2` — cái nào chạy sau nhận `⛔ Active run exists`. Single-tenant `current-run.json` block toàn project.

**Fix:** Per-session state files `.vg/active-runs/{session_id}.json`. Same session → block-or-stale-clear như trước. Khác session → **WARN nhẹ** về shared git index, không block. `run-status` aggregate shows `this_session` + `other_sessions_active[]`. Hai developer có thể làm song song 2 phase khác nhau cùng project, không cần phối hợp manual.

### Programmatic Agent-Spawn Guard (v2.27.0)
**Problem:** VGFlow dùng `general-purpose` agents; AI thỉnh thoảng spawn `gsd-executor` (wrong rule-set, wrong commit conventions). Prose rule "don't spawn gsd-executor" — AI đọc nhưng Claude Code's agent picker có thể override.

**Fix:** **PreToolUse hook** với `matcher: "Agent"` intercept spawn BEFORE nó fire. Trả về `permissionDecision: "deny"` với reason → Claude nhận reason ở next turn và re-spawn correctly. **Hard enforcement tại OS level** — không phải rule AI có thể rationalize qua. Allow-list cho `gsd-debugger` (VGFlow legitimate dùng ở build step 12). Smoke-tested 6 scenarios kể cả GSD coexistence.

### Self-Healing Update Bootstrap (v2.29.0)
**Problem:** Chicken-and-egg — `vg_update.py` bị stale/broken (silent merge bug #30 parked fix dưới dạng `.conflict`). Update fail. Bản thân updater cần được update nhưng updater không chạy được.

**Fix:** `/vg:update` load merge helper từ **freshly downloaded tarball**, không phải installed copy. Stale installed helper không thể block replacement của chính nó nữa. `install.sh --refresh` force-overwrite mọi VG-managed file với backup trước. Fresh installs seed `.claude/vgflow-ancestor/v{version}/` baseline để future 3-way merges có real ancestor (loại bỏ "ancestor missing → force-upstream → silent overwrite" cliff). Pre-flight integrity scan classify `clean/new/force_upstream_at_risk` trước khi ghi đè.

### Atomic Commit Primitives — Stage-Before-Mutex Bug (v2.28.0)
**Problem:** Parallel executor agents (Wave N) `git add` files TRƯỚC khi acquire commit-queue mutex. Agent đầu tiên acquire mutex absorb file của agent khác → cross-attribution corruption — task A's code committed dưới tên task B.

**Fix:** `vg_commit_with_files <task_id> <max_wait> <msg_file> <file>...` — stage + commit nằm TRONG mutex, không thể tách ra. Index luôn sạch khi acquire. Diagnostic WARN nếu index có pre-staged file tại acquire time (dấu hiệu crashed task trước để lại). Executor rules cập nhật explicit rule: `⛔ DO NOT run git add BEFORE acquire`.

### Adversarial Coverage — Declarative Threat Model (v2.21.0)
**Problem:** Test suites cover happy path + alternate flows. Không có adversarial spec format → AI phải "đoán" threat ở step cuối pipeline khi code đã viết xong.

**Fix:** `adversarial_scope` field trong TEST-GOAL-enriched-template — declared tại `/vg:blueprint` Round 4, không thêm sau:

```yaml
adversarial_scope:
  threats: [auth_bypass, injection, race, duplicate_submit]
  per_threat:
    auth_bypass:
      paths: ["other-tenant-id", "expired-session"]
      assertions: ["status: 403", "no PII leak in error body"]
```

Codegen tự sinh `<goal>.adversarial.<threat>.spec.ts` per threat. Validator `verify-adversarial-coverage.py` enforce: mutation goals không được có empty `threats`. Override `--skip-adversarial=<reason>` log vào OVERRIDE-DEBT.md severity=critical. **Threat model → code → test là một luồng liên tục, không phải afterthought.**

### Commit Attribution — Body-Scan False Positive (v2.28.0)
**Problem:** `git log --grep=PATTERN` scans cả commit body. Phase 2 regex `\(2[-.0-9]*-[0-9]+\):` match date string `(2026-04-22):` trong body của commit cũ → `subject_format_violation` false positive, block `/vg:build run-complete` deterministically.

**Fix:** Drop `--grep` filter, raw `git log --pretty=format:%H%x00%s%x00%b%x01` + Python-side `re.match` anchored tại start của subject chỉ. Body không bao giờ scan nữa. Date strings trong commit bodies không thể trigger phantom violations.

### Design Asset Traceability (v2.30.0)
**Problem:** Tất cả design assets land vào project-level `.vg/design-normalized/` bất kể phase nào generate. Sau 10+ phases, directory là mớ hỗn độn — không biết asset nào thuộc phase nào, không thể prune safely.

**Fix:** 2-tier layout:
- **Tier 1 — phase-scoped:** `.vg/phases/{N}/design/` — default write target per phase
- **Tier 2 — project-shared:** `.vg/design-system/` — brand assets, design tokens dùng cross-phase

`design-path-resolver.sh` abstraction layer — consumers source helper thay vì hardcode path. `/vg:accept` visual baseline resolve qua 3-tier fallback (phase → shared → legacy). Migration script phân tích PLAN.md citations để auto-classify và move existing assets với backup.

### Hard-Gate Enforcement vs Silent-Skip (v2.43.1)
**Problem:** Skill bodies say "MANDATORY FIRST ACTION — invoke AskUserQuestion" but text-only "must ask" instructions are not enforced. Dogfood incident on `/vg:roam` invocation: AI silently skipped both 0aa resume prompt and 0a env+model+mode batch, then proceeded to backfill ROAM-CONFIG.json + relocate observe-* files + spawn S01 — all without user input. Prose rules don't bind AI execution under auto mode.

**Fix:** Three-layer enforcement that binds at runtime, not at "AI cẩn thận":
1. **`runtime_contract.must_emit_telemetry`** with `required_unless_flag: --non-interactive` for `roam.resume_mode_chosen` + `roam.config_confirmed` events. Harness-level gate — Stop hook blocks run if events missing.
2. **`.tmp/{step}-confirmed.marker`** files written ONLY by code paths that follow AskUserQuestion answer. Step 1 entry asserts markers exist + are < 30 min old + env/model/mode env vars non-empty. Bash-level gate — fails fast with explicit "HARD GATE BREACH" message and emits `roam.gate_breach` telemetry.
3. **Legacy state detection** expanded from "ROAM-CONFIG.json exists" to also include RAW-LOG.jsonl / SURFACES.md / ROAM-BUGS.md / INSTRUCTION-*.md / observe-*.jsonl. Pre-v2.42.6 partial runs no longer silently bypass the resume prompt.

**Lesson:** Soft instructions describing "must ask the user" are routinely ignored when AI sees a quicker path. The fix is enforcement at telemetry + filesystem layer — same pattern as `pre-stage commit-queue mutex` (v2.28.0) and `runtime_contract.must_touch_markers` (v2.2). If the harness can't verify it happened, assume it didn't.

### Resume-Mode Footgun — Lock-In vs Pre-Fill (v2.43.1)
**Problem:** When `/vg:roam` detects prior state, v2.42.6-9 silently loaded saved `env`/`model`/`mode` from ROAM-CONFIG.json and skipped the 0a 3-question batch. User wanted to switch env mid-stream (local → sandbox) but resume locked them in to the prior choice. Workaround was `--force` wipe — destructive and discards prior briefs.

**Fix:** Step 0a now ALWAYS fires its 3-question batch regardless of resume mode. Prior config loads as `ROAM_PRIOR_ENV/MODEL/MODE` env vars used as "Recommended — prior run" pre-fill in each option. User must confirm even if they keep the same value. Mid-stream env switches become a 3-click operation, not a wipe.

**Lesson:** "Resume" should mean "skip work that was done", not "lock you out of decisions you made before". Conflating the two creates a footgun. The right primitive is *pre-fill, not silent-load*.

### Bug Reporter — Byte-Safe Context (v2.28.0/v2.29.0)
**Problem:** `bug-reporter.sh` embed `${context}` vào Python triple-quoted heredoc. Context chứa quote / newline / `$` → SyntaxError; `2>/dev/null` swallow error → GitHub issues với empty body.

**Fix:** Pass tất cả data qua env vars (`BR_SIG`, `BR_CTX`, `BR_DATA`) + single-quoted Python source. `os.environ.get()` — fully byte-safe, không quan tâm chars. Sentinel fallback nếu JSON encode fail. GitHub issue body không bao giờ rỗng nữa.

---

## Tại sao đây không chỉ là "AI viết code"

Hầu hết AI coding tools dừng lại ở generation. VGFlow là **enforcement substrate**:

| Layer | Cơ chế |
|---|---|
| **Gate enforcement** | Claude Code hooks (Stop / PreToolUse / UserPromptSubmit) — không phải prose rules |
| **Conflict detection** | Commit-queue mutex với pre-stage guard — không phải "AI cẩn thận" |
| **Session isolation** | Per-session state files — không phải single global lock |
| **Update integrity** | Tarball self-bootstrap + ancestor baseline — không phải hope updater works |
| **Threat coverage** | Declarative adversarial spec + codegen + validator — không phải test-after-code |
| **Telemetry** | Append-only JSONL + SQLite events — không phải logs bị lost |
| **Decision traceability** | D-XX namespace per decision, CONTEXT.md linked to PLAN.md tasks |
| **Bug feedback loop** | Auto-report → dogfood → root cause → same-pipeline fix |

Mỗi cơ chế này không phải viết ra trên giấy — là kết quả của một bug được trace từ production dogfood đến root cause, và fix deployed trong vài giờ.

---

## The Pipeline (Two Tiers)

### Project-level setup (once per project / milestone)

```
/vg:project       →  /vg:roadmap   →  /vg:map          →  /vg:prioritize
(7-round            (ROADMAP.md,     (optional —          (which phase
discussion →        phase list,      graphify              to work next)
PROJECT.md +        soft drift       codebase)
FOUNDATION.md +     warning)
vg.config.md
ATOMIC)
```

**v1.6.0 entry point change**: `/vg:project` is the single entry point. It captures your free-form description, derives FOUNDATION (8 dimensions: platform/runtime/data/auth/hosting/distribution/scale/compliance), then auto-generates `vg.config.md`. Config is downstream of foundation, not upstream.

`/vg:init` is preserved as a backward-compat soft alias → `/vg:project --init-only`.

### Per-phase execution (7 steps + 2 optional bridges, v2.43+)

```
/vg:specs  →  /vg:scope  →  /vg:blueprint  →  /vg:build  →  [/vg:deploy]  →  /vg:review  →  /vg:test  →  [/vg:roam]  →  /vg:accept
(goal,        (discussion    (PLAN.md +        (wave-based     (optional —       (scan + fix    (goal verify    (optional —      (human UAT
scope,        → CONTEXT.md   API-CONTRACTS +    parallel        multi-env         loop →         + codegen       lens-driven       → UAT.md)
constraints)   with D-XX)    TEST-GOALS)        execute)        deploy)           RUNTIME-MAP)   regression)     CRUD pass)
```

**Required core (7 steps):** specs → scope → blueprint → build → review → test → accept
**Optional bridges (v2.43+):** `/vg:deploy` between build and review when phase ships to a remote env; `/vg:roam` between test and accept for ship-critical phases that warrant adversarial coverage.

Full pipeline shortcut: `/vg:phase {X}` runs all 7 required steps with resume support; deploy + roam invoked separately as needed.
Advance step-by-step: `/vg:next` auto-detects current position and invokes the next command (skips deploy/roam unless flagged).

---

## Install (fresh project)

### Requirements

- **Python 3.10+** (v2.5.2.x uses `tuple[bool, str]` type hints and other 3.10 syntax)
- **Git + GitHub CLI (`gh`)** for `/vg:update`
- **Claude Code and/or OpenAI Codex CLI** installed and authenticated
- **Optional**: `pnpm` + `graphify` for full feature set

### One-liner

```bash
cd /path/to/your-project
curl -fsSL https://raw.githubusercontent.com/vietdev99/vgflow/main/install.sh -o /tmp/vgflow-install.sh
bash /tmp/vgflow-install.sh .
```

### Manual

```bash
git clone https://github.com/vietdev99/vgflow.git /tmp/vgflow
bash /tmp/vgflow/install.sh /path/to/your-project
```

The installer copies commands, skills, scripts (including `validators/` + `vg-orchestrator/` + `tests/` subdirectories), templates, and generates `.claude/vg.config.md` from the template. Codex parity is installed as full VG skills plus agent templates in `.codex/skills/`, `.codex/agents/`, and optionally global `~/.codex/`; Gemini remains available for CrossAI review support.

### Post-install: Python dependencies

```bash
cd /path/to/your-project
pip install -r .claude/scripts/requirements.txt   # pyyaml + pytest (only 2 third-party deps)
```

Most of VG is stdlib-only (`hashlib`, `secrets`, `sqlite3`, `json`, `pathlib`). Only the registry loader (`pyyaml`) and regression suite (`pytest`) need installation.

### Post-install: authentication bootstrap

**Required before first `/vg:build` with any `--allow-*` flag.** The allow-flag gate uses HMAC-signed tokens; you need a signing key and a CI nonce directory:

```bash
# One-time: create signing key at ~/.vg/.approver-key (mode 0600 on POSIX)
python .claude/scripts/vg-auth.py init

# Verify
python .claude/scripts/vg-auth.py verify --token dummy --flag X    # expected INVALID (key exists)
```

**Environment variables (optional — override defaults):**

| Variable | Purpose | Default |
|---|---|---|
| `VG_APPROVER_KEY_DIR` | Signing key location (override for CI / testing) | `~/.vg/` |
| `VG_APPROVER_NONCE_DIR` | Nonce challenge storage (v2.5.2.3+) | `~/.vg/.approver-nonces/` |
| `VG_AUTH_CI_MODE` | Set to `1` in CI to enable nonce-bound fallback | unset |
| `VG_AUTH_OPERATOR_ACK` | Nonce value pasted from `vg-auth issue-nonce` | unset |
| `VG_ALLOW_FLAGS_STRICT_MODE` | Force strict env-approver mode (default true v2.5.2.2+) | default strict |
| `VG_ALLOW_FLAGS_LEGACY_RAW` | Opt-in to legacy raw-string env (v2.5.1 compat) | unset |

**CI flow (never let CI self-mint tokens):**

```bash
# On TTY operator machine:
python .claude/scripts/vg-auth.py issue-nonce --ttl-minutes 60    # prints plaintext nonce
# → deliver nonce OOB (Vault/SOPS secret, email, 2FA paste) to CI

# On CI runner:
export VG_AUTH_CI_MODE=1
export VG_AUTH_OPERATOR_ACK="<nonce-pasted-from-OOB>"
python .claude/scripts/vg-auth.py approve --flag allow-security-baseline --ttl-days 1
# → prints signed token; use as VG_HUMAN_OPERATOR in /vg:* calls
```

### Post-install: verify hooks

```bash
python .claude/scripts/vg-hooks-selftest.py    # verifies Stop + PostToolUse + UserPromptSubmit hooks fire
```

If hooks fail with `can't open file 'D:\\AI'` or similar truncated-path errors, the path contains spaces and the hook command wasn't quoted. Fix:

```bash
python .claude/scripts/vg-hooks-install.py    # auto-repairs unquoted ${CLAUDE_PROJECT_DIR}
```

Then **restart Claude Code** — hooks are cached at session start; repaired settings take effect next session only.

## Update existing install

```
/vg:update --check                   # peek at latest version without applying
/vg:update                           # apply latest release
/vg:update --accept-breaking         # required for major version bumps
/vg:reapply-patches                  # resolve conflicts from /vg:update
```

Update flow: query GitHub API → download tarball + SHA256 verify → 3-way merge (preserves your local edits) → park conflicts in `.claude/vgflow-patches/`.

If an older install reports the latest version but core files are still stale, force-refresh VG managed files from the current release:

```bash
cd /path/to/your-project
curl -fsSL https://raw.githubusercontent.com/vietdev99/vgflow/main/install.sh -o /tmp/vgflow-install.sh
bash /tmp/vgflow-install.sh --refresh .
```

`--refresh` backs up existing VG managed files under `.vgflow-refresh-backup/` before overwriting commands, skills, scripts, schemas, templates, and Codex mirrors.

### Migrate design assets to 2-tier layout (v2.30.0+)

Existing projects with `.vg/design-normalized/` can migrate assets to phase-scoped + shared layout:

```bash
# Dry-run (default) — shows classification without moving anything:
python3 .claude/scripts/migrate-design-paths.py --repo . --verbose

# Apply — moves files with backup to .vg/.design-migration-backup/{ts}/:
python3 .claude/scripts/migrate-design-paths.py --repo . --apply --verbose

# Or combine with install --refresh:
bash /tmp/vgflow-install.sh --refresh --migrate-design .
```

The script scans `PLAN.md <design-ref slug="...">` citations to classify each slug: single-phase → `phases/{N}/design/`, multi-phase → `.vg/design-system/`, uncited → `.vg/design-system/orphans/` for triage.

## Command reference

### Project setup
| Command | Purpose |
|---------|---------|
| `/vg:project` | **ENTRY POINT** — 7-round discussion → PROJECT.md + FOUNDATION.md + vg.config.md (atomic) |
| `/vg:project --view` | Pretty-print current artifacts (read-only) |
| `/vg:project --update` | MERGE-preserving update of existing artifacts |
| `/vg:project --milestone` | Append new milestone (foundation untouched) |
| `/vg:project --rewrite` | Destructive reset with backup → `.archive/{ts}/` |
| `/vg:project --migrate` | Extract FOUNDATION.md from legacy v1 PROJECT.md + codebase scan |
| `/vg:project --init-only` | Re-derive vg.config.md from existing FOUNDATION.md |
| `/vg:init` | [DEPRECATED] Soft alias → `/vg:project --init-only` |
| `/vg:roadmap` | Derive phases from PROJECT + FOUNDATION → ROADMAP.md (soft drift warning) |
| `/vg:map` | Rebuild graphify knowledge graph → `codebase-map.md` |
| `/vg:prioritize` | Rank phases by impact + readiness |

### Phase execution (7 required steps + 2 optional bridges)
| Step | Command | Output |
|------|---------|--------|
| 1 | `/vg:specs {X}` | SPECS.md (goal, scope, constraints, success criteria) |
| 2 | `/vg:scope {X}` | CONTEXT.md (enriched with decisions D-XX) + DISCUSSION-LOG.md (step 1b: per-phase `preferred_env_for` env preset) |
| 3 | `/vg:blueprint {X}` | PLAN.md + API-CONTRACTS.md + TEST-GOALS.md + CrossAI review |
| 4 | `/vg:build {X}` | Code + SUMMARY.md (wave-based parallel execution) |
| 4.5 | `/vg:deploy {X}` *(optional, v2.43+)* | DEPLOY-STATE.json with `deployed.{env}` block per env (sha + timestamp + health + previous_sha for rollback). Multi-select envs, prod typed-token gate. |
| 5 | `/vg:review {X}` | RUNTIME-MAP.json (browser discovery + fix loop). Env gate reads DEPLOY-STATE → "Recommended sandbox 2min ago, sha abc1234". |
| 6 | `/vg:test {X}` | SANDBOX-TEST.md (goal verification + codegen regression) |
| 6.5 | `/vg:roam {X}` *(optional, v2.43+)* | ROAM-BUGS.md + RUN-SUMMARY.json + proposed-specs/ (lens-driven CRUD-lifecycle pass). Always asks env/model/mode (v2.43.1 hard gate). |
| 7 | `/vg:accept {X}` | UAT.md (human acceptance) |

### Management
| Command | Purpose |
|---------|---------|
| `/vg:phase {X}` | Run full 7-step phase pipeline with resume support |
| `/vg:next` | Auto-detect + advance to next step |
| `/vg:progress` | Status across all phases + update check |
| `/vg:amend {X}` | Mid-phase change — update CONTEXT.md, cascade impact |
| `/vg:add-phase` | Insert a new phase into ROADMAP.md |
| `/vg:remove-phase` | Archive + delete a phase |
| `/vg:regression` | Re-run all tests from accepted phases |
| `/vg:migrate {X}` | Convert legacy GSD artifacts to VG format (also backfills infra registers) |

### Milestone (v2.33.0+)
| Command | Purpose |
|---------|---------|
| `/vg:milestone-summary {M}` | Aggregate report — phase status, goal coverage, security posture, override debt, companion artifact links |
| `/vg:complete-milestone {M}` | Close milestone — verify all phases accepted → security audit → summary → archive phase dirs → advance STATE.md → atomic commit |
| `/vg:complete-milestone {M} --check` | Dry-run gate check (no mutations) |
| `/vg:security-audit-milestone` | Cross-phase security correlation + Strix scan advisory (v2.32.0) |
| `/vg:project --milestone` | Append next milestone scope to PROJECT.md (after `/vg:complete-milestone`) |

### Distribution + infra
| Command | Purpose |
|---------|---------|
| `/vg:update` | Pull latest release from GitHub |
| `/vg:reapply-patches` | Resolve conflicts from `/vg:update` |
| `/vg:sync` | Dev-side source↔mirror sync (maintainer only) |
| `/vg:telemetry` | Summarize workflow telemetry |

## Meta-memory dogfood (opt-in)

Enable AI's auto-learning loop:

```bash
/vg:meta-memory enable        # full loop: reflect + inject as advice
/vg:meta-memory reflect-only  # reflector only (drafts, no inject)
/vg:meta-memory status
```

This sets `meta_memory_mode: inject-as-advice` in `.claude/vg.config.md`. The harness then:
- Reflects after `/vg:deploy /vg:test /vg:accept /vg:roam /vg:amend`
- Persists promoted rules into `.vg/bootstrap/rules/`
- Injects them as advisory rules into build / accept / deploy preflight

Stop hook reminds you to run `/vg:learn --consolidate --apply` when 24h + 5 sessions accumulate. Does NOT auto-mutate — you stay in control.

Default remains `disabled` — no behavior change unless you explicitly opt in.

## Tasklist + Intent (v2.60.0)

### Auto-restore tasklist on session resume

When a wave is mid-execution and the session crashes / hits limit / compacts, VGFlow restores the full tasklist projection on resume. The Stop hook captures latest TodoWrite state to `.vg/runs/{run_id}/.todowrite-snapshot.json` after every update; SessionStart hook re-projects on resume so `in_progress` items + completed status are preserved. No more "1 next task only" after resume.

### TodoWrite re-order by status

`in_progress` items surface to the top of each group, completed sink to the bottom. Group headers auto-reflect active state — groups with any `in_progress` step show as `in_progress`, fully-completed groups show `completed`.

### Natural language → VG command (intent primer)

The SessionStart-injected primer now includes an Intent → Command map. When you type "build phase 7.14 bằng VG đi" or "lập plan cho phase 8", the AI recognizes the intent and invokes the matching `/vg:*` slash command. Supports both English and Vietnamese trigger phrases.

## Repository layout

```
vgflow/
├── VERSION                   ← SemVer (e.g. "1.1.0")
├── CHANGELOG.md              ← curated per release
├── commands/vg/              ← Claude Code slash commands
├── skills/                   ← api-contract, vg-* skills
├── codex-skills/             ← Codex CLI parity
├── gemini-skills/            ← Gemini CLI parity
├── scripts/                  ← Python helpers (vg_update, graphify, visual-diff, …)
├── templates/vg/             ← commit-msg hook template
├── vg.config.template.md     ← schema seed for new projects
├── migrations/               ← vN_to_vN+1.md breaking-change guides
├── install.sh                ← fresh install entrypoint
└── sync.sh                   ← dev-side source↔mirror (maintainer)
```

## Release channel

- **Tags:** SemVer — `v1.2.3`
- **Tarballs:** attached to each GitHub Release (auto-built via `.github/workflows/release.yml`)
- **Changelog:** `CHANGELOG.md` + rendered in each Release body
- **Breaking changes:** `migrations/vN_to_vN+1.md` shown before update proceeds

## Contributing

Maintained by [@vietdev99](https://github.com/vietdev99). Not accepting external PRs at this stage — bug reports welcome as issues.

## License

MIT — see [LICENSE](LICENSE)
