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

**Version:** 2.12.7 · **License:** MIT

**Latest (v2.12.7):** review/test/accept now runtime-probe linked CSS assets so stylesheet URLs must serve real `text/css`, not HTML/JS/source code.

---

## ⚠ Heavy Workflow — Không dành cho dự án nhỏ

VGFlow là một pipeline **chuyên sâu**, **nhiều tầng orchestration**, **token-intensive**. Không phải "hỏi AI sửa 1 file" — mỗi phase đi qua 7 steps, spawn multiple AI agents, chạy CrossAI consensus, validate qua weighted gates, commit theo atomic group. Token cost ở từng giai đoạn đáng kể:

- `/vg:scope` ~$0.15-0.30/phase (Opus adversarial challenger + dimension expander)
- `/vg:build` ~$0.50-2.00/phase (Sonnet execution waves, contract-aware)
- `/vg:review` ~$0.30-0.80/phase (Opus navigator + Haiku scanners + CrossAI)
- `/vg:test` ~$0.20-0.50/phase (goal verification + codegen regression)

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

### Per-phase execution (7 steps)

```
/vg:specs  →  /vg:scope  →  /vg:blueprint  →  /vg:build  →  /vg:review  →  /vg:test  →  /vg:accept
(goal,        (discussion    (PLAN.md +        (wave-based     (scan + fix    (goal verify    (human UAT
scope,        → CONTEXT.md   API-CONTRACTS +    parallel        loop →         + codegen       → UAT.md)
constraints)   with D-XX)    TEST-GOALS)        execute)        RUNTIME-MAP)   regression)
```

Full pipeline shortcut: `/vg:phase {X}` runs all 7 per-phase steps with resume support.
Advance step-by-step: `/vg:next` auto-detects current position and invokes the next command.

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

### Phase execution (7-step pipeline)
| Step | Command | Output |
|------|---------|--------|
| 1 | `/vg:specs {X}` | SPECS.md (goal, scope, constraints, success criteria) |
| 2 | `/vg:scope {X}` | CONTEXT.md (enriched with decisions D-XX) + DISCUSSION-LOG.md |
| 3 | `/vg:blueprint {X}` | PLAN.md + API-CONTRACTS.md + TEST-GOALS.md + CrossAI review |
| 4 | `/vg:build {X}` | Code + SUMMARY.md (wave-based parallel execution) |
| 5 | `/vg:review {X}` | RUNTIME-MAP.json (browser discovery + fix loop) |
| 6 | `/vg:test {X}` | SANDBOX-TEST.md (goal verification + codegen regression) |
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

### Distribution + infra
| Command | Purpose |
|---------|---------|
| `/vg:update` | Pull latest release from GitHub |
| `/vg:reapply-patches` | Resolve conflicts from `/vg:update` |
| `/vg:sync` | Dev-side source↔mirror sync (maintainer only) |
| `/vg:telemetry` | Summarize workflow telemetry |
| `/vg:security-audit-milestone` | Cross-phase security correlation |

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
