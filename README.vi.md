# VGFlow

> **Heavy AI Workflow cho các dự án software production-grade.**
>
> **Ngôn ngữ:** [Tiếng Việt](README.vi.md) · [English](README.md)

VGFlow là một **pipeline AI config-driven** mạnh mẽ — thiết kế chuyên cho các dự án software lớn, đa thành phần, chất lượng production. Pipeline hỗ trợ đầy đủ:

- **Web applications** (React / Next / Vue / Svelte frontend + Node / Python / Go / Rust backend)
- **Web servers / Backend APIs** (REST / GraphQL / gRPC, microservices, RTB engines, ad exchanges)
- **CLI tools** (dev tools, DevOps automation, data pipelines)
- **Mobile apps** (React Native, Flutter, native iOS / Android, hybrid)

Zero hardcode stack — mọi giá trị derive từ `vg.config.md`. Portable 100% qua mọi project, mọi ngôn ngữ, mọi deployment (VPS / Docker / Kubernetes / serverless).

**Phiên bản:** 2.12.5 · **License:** MIT

---

## ⚠ Heavy Workflow — Không dành cho dự án nhỏ

VGFlow là pipeline **chuyên sâu**, **nhiều tầng orchestration**, **tốn token**. Không phải "hỏi AI sửa 1 file" — mỗi phase đi qua 7 steps, spawn multiple AI agents, chạy CrossAI consensus, validate qua weighted gates, commit theo atomic group. Chi phí token từng giai đoạn:

- `/vg:scope` ~$0.15-0.30/phase (Opus adversarial + dimension expander)
- `/vg:build` ~$0.50-2.00/phase (Sonnet execution waves, contract-aware)
- `/vg:review` ~$0.30-0.80/phase (Opus navigator + Haiku scanners + CrossAI)
- `/vg:test` ~$0.20-0.50/phase (goal verification + codegen regression)

**VGFlow shine nhất khi:**
- Phase có **10-50+ tasks**, spans **nhiều apps** trong monorepo
- **Critical domain** constraints (billing, auth, auction, compliance, payout)
- Cần **audit trail** cho production deploy hoặc regulatory review
- Team nhiều developer cần **decision traceability** (D-XX namespace)
- Performance SLA nghiêm ngặt (RTB ≤50ms, API p95 ≤200ms...)

**VGFlow KHÔNG phù hợp khi:**
- Chỉ sửa 1-2 files hoặc hotfix cấp tốc → dùng `/vg:amend` hoặc edit trực tiếp
- Prototype cuối tuần, one-off script → overhead không xứng
- Solo dev làm side project nhỏ → simpler workflow đủ

---

## 🚀 Tại sao chọn VGFlow

### Multi-tier AI Orchestration
**Opus / Sonnet / Haiku tier routing theo độ phức tạp task.** Opus cho reasoning-heavy gates (scope adversarial, plan architect, block resolver L2). Sonnet cho execution waves + code review. Haiku cho exhaustive scan, rationalization guard, pattern probing. Right model, right price, right quality.

### CrossAI N-reviewer Consensus
Blueprint + Scope không phê duyệt bằng 1 AI. Pipeline chạy song song **Claude Code + OpenAI Codex CLI + Gemini CLI** → synthesize consensus → PASS / BLOCK / escalate. Independent eyes catch blind spots.

### Contract-Aware Wave Parallel Execution
`/vg:build` parse dependency graph → graph-coloring waves → parallel execute. File conflicts auto-force sequential. **Contract injection** copy Zod / Pydantic / TypeScript schemas verbatim — zero typo drift. Silent agent failures catch qua **commit-count verification**.

### Goal-Backward Verification với Weighted Gates
Không phải "tests green" — mà **goal-coverage-matrix**: critical 100%, important 80%, nice-to-have 50%. Goals map qua **surface taxonomy** (UI / API / Data / Integration / Time-driven), mỗi surface có dedicated runner. Mixed-phase project vẫn cover đầy đủ.

### 8-Lens Adversarial Scope + Dimension Expander (v1.9.3)
Mỗi answer trong `/vg:scope` qua **8-lens Opus challenger**: contradiction · hidden assumption · edge case · foundation conflict · **security threat** · **performance budget** · **failure mode** · **integration chain**. Cuối round, **dimension-expander** hỏi "what haven't we discussed?" — proactive tìm gap.

### Phase Profile System (6 loại)
Auto-detect `feature / feature-legacy / infra / hotfix / bugfix / migration / docs` → gate policy + test mode + artifacts tự động phù hợp. Không one-size-fits-all.

### Block Resolver 4 Levels
L1 Inline auto-fix → L2 Architect Haiku propose → L3 User Choice → L4 Stuck. AI tự nghĩ options trước khi đòi user quyết định.

### Live Browser Discovery (MCP Playwright)
`/vg:review` organic exploration — click sidebar, mỗi button, quan sát console errors + network 4xx/5xx + i18n resolution. **Mobile-aware (v1.9.4):** single-device project auto-sequential, web parallel 5-slot, cli/library skip UI.

### 3-Way Git Merge Updates
`/vg:update` pull latest từ GitHub, 3-way merge với user edits, park conflicts cho `/vg:reapply-patches`. Không clobber custom changes.

### SHA256 Artifact Manifest + Atomic Commits
Mỗi phase có manifest hash-validates artifacts. Corruption detect early qua `/vg:integrity`. Namespace enforcement `P{phase}.D-XX` → cross-phase traceability.

### Structured Telemetry + Override Debt Register
Append-only JSONL events. Query qua `/vg:telemetry` + `/vg:gate-stats`. Mỗi `--allow-*` / `--skip-*` được log với event-based resolution.

### Rationalization Guard (Chống Cắt Góc)
Gate skip đề xuất → spawn Haiku zero-context adjudicates: real blocker hay rationalization. Anti-corner-cutting ở critical gates.

### Visual Regression + Security Register
UI pixel-diff vs baseline. Threats STRIDE+OWASP cumulated qua milestone, cross-phase correlation.

### Foundation Drift Detection
8-dimension foundation lock tại `/vg:project`. Mỗi phase scope check drift — đảm bảo không silent assumption shift.

### Incremental Graphify (Knowledge Graph)
Auto-rebuild knowledge graph sau mỗi wave — fresh sibling/caller context cho wave tiếp theo. God nodes + communities inject vào scope/plan prompts.

---

## Pipeline (2 tầng)

### Tầng dự án (chạy 1 lần khi khởi tạo project / milestone)

```
/vg:project       →  /vg:roadmap   →  /vg:map          →  /vg:prioritize
(thảo luận           (ROADMAP.md,     (tuỳ chọn —          (phase nào
7 vòng →             danh sách        graphify              làm tiếp theo)
PROJECT.md +         phases, soft     codebase)
FOUNDATION.md +      drift warning)
vg.config.md
ATOMIC)
```

**v1.6.0 thay đổi entry point**: `/vg:project` là entry point duy nhất. Nó capture mô tả tự nhiên của user, derive FOUNDATION (8 chiều: platform/runtime/data/auth/hosting/distribution/scale/compliance), rồi auto-generate `vg.config.md`. Config là downstream của foundation, không phải upstream.

`/vg:init` còn giữ làm soft alias backward-compat → `/vg:project --init-only`.

### Tầng phase (7 bước)

```
/vg:specs  →  /vg:scope  →  /vg:blueprint  →  /vg:build  →  /vg:review  →  /vg:test  →  /vg:accept
(mục tiêu,    (thảo luận     (PLAN.md +         (wave-based     (scan + fix    (verify goal   (UAT
scope,        → CONTEXT.md   API-CONTRACTS +     parallel        loop →         + codegen     bằng người
constraints)  với D-XX)      TEST-GOALS)         execute)        RUNTIME-MAP)   regression)   → UAT.md)
```

Shortcut chạy full pipeline: `/vg:phase {X}` chạy cả 7 bước phase với resume support.
Advance step-by-step: `/vg:next` tự detect vị trí hiện tại + invoke command tiếp theo.

---

## Cài đặt (project mới)

```bash
cd /đường/dẫn/project
curl -fsSL https://raw.githubusercontent.com/vietdev99/vgflow/main/install.sh -o /tmp/vgflow-install.sh
bash /tmp/vgflow-install.sh .
```

Hoặc thủ công:
```bash
git clone https://github.com/vietdev99/vgflow.git /tmp/vgflow
bash /tmp/vgflow/install.sh /đường/dẫn/project
```

Script installer sẽ copy commands, skills, scripts, templates, và sinh `.claude/vg.config.md` từ template. Codex parity được cài như full VG skills cộng agent templates trong `.codex/skills/`, `.codex/agents/`, và tuỳ chọn global `~/.codex/`; Gemini vẫn dùng cho CrossAI review support.

## Cập nhật cho install có sẵn

```
/vg:update --check                   # peek phiên bản mới nhất không apply
/vg:update                           # apply release mới nhất
/vg:update --accept-breaking         # bắt buộc khi major version bump
/vg:reapply-patches                  # resolve conflicts từ /vg:update
```

Luồng update: query GitHub API → tải tarball + verify SHA256 → 3-way merge (giữ local edits của user) → park conflicts vào `.claude/vgflow-patches/`.

## Danh sách commands

### Khởi tạo project
| Command | Mục đích |
|---------|---------|
| `/vg:project` | **ENTRY POINT** — Thảo luận 7 vòng → PROJECT.md + FOUNDATION.md + vg.config.md (atomic) |
| `/vg:project --view` | In hiện trạng artifacts (read-only) |
| `/vg:project --update` | Update artifacts hiện có, MERGE preserve phần không touch |
| `/vg:project --milestone` | Append milestone mới (foundation untouched) |
| `/vg:project --rewrite` | Reset destructive với backup → `.archive/{ts}/` |
| `/vg:project --migrate` | Extract FOUNDATION.md từ legacy v1 PROJECT.md + scan codebase |
| `/vg:project --init-only` | Re-derive vg.config.md từ FOUNDATION.md hiện có |
| `/vg:init` | [DEPRECATED] Soft alias → `/vg:project --init-only` |
| `/vg:roadmap` | Derive phases từ PROJECT + FOUNDATION → ROADMAP.md (soft drift warning) |
| `/vg:map` | Rebuild graphify knowledge graph → `codebase-map.md` |
| `/vg:prioritize` | Rank phases theo impact + readiness |

### Phase execution (7-step pipeline)
| Bước | Command | Output |
|------|---------|--------|
| 1 | `/vg:specs {X}` | SPECS.md (goal, scope, constraints, success criteria) |
| 2 | `/vg:scope {X}` | CONTEXT.md (enriched với decisions D-XX) + DISCUSSION-LOG.md |
| 3 | `/vg:blueprint {X}` | PLAN.md + API-CONTRACTS.md + TEST-GOALS.md + CrossAI review |
| 4 | `/vg:build {X}` | Code + SUMMARY.md (wave-based parallel execution) |
| 5 | `/vg:review {X}` | RUNTIME-MAP.json (browser discovery + fix loop) |
| 6 | `/vg:test {X}` | SANDBOX-TEST.md (goal verification + codegen regression) |
| 7 | `/vg:accept {X}` | UAT.md (human acceptance) |

### Quản lý
| Command | Mục đích |
|---------|---------|
| `/vg:phase {X}` | Chạy full 7-step phase pipeline với resume support |
| `/vg:next` | Tự detect + advance step tiếp theo |
| `/vg:progress` | Status toàn bộ phases + check update |
| `/vg:amend {X}` | Mid-phase change — update CONTEXT.md, cascade impact |
| `/vg:add-phase` | Thêm phase mới vào ROADMAP.md |
| `/vg:remove-phase` | Archive + xoá phase |
| `/vg:regression` | Re-run tất cả tests từ các phases đã accept |
| `/vg:migrate {X}` | Convert legacy GSD artifacts sang VG format (cả backfill infra registers) |

### Distribution + infra
| Command | Mục đích |
|---------|---------|
| `/vg:update` | Kéo release mới nhất từ GitHub |
| `/vg:reapply-patches` | Resolve conflicts từ `/vg:update` |
| `/vg:sync` | Dev-side source↔mirror sync (chỉ dành cho maintainer) |
| `/vg:telemetry` | Summarize workflow telemetry |
| `/vg:security-audit-milestone` | Cross-phase security correlation |

## Cấu trúc repo

```
vgflow/
├── VERSION                   ← SemVer (vd "1.1.0")
├── CHANGELOG.md              ← curated mỗi release
├── commands/vg/              ← Claude Code slash commands
├── skills/                   ← api-contract, vg-* skills
├── codex-skills/             ← Codex CLI parity
├── gemini-skills/            ← Gemini CLI parity
├── scripts/                  ← Python helpers (vg_update, graphify, visual-diff, …)
├── templates/vg/             ← commit-msg hook template
├── vg.config.template.md     ← schema seed cho project mới
├── migrations/               ← vN_to_vN+1.md hướng dẫn breaking-change
├── install.sh                ← entrypoint cài đặt lần đầu
└── sync.sh                   ← dev-side source↔mirror (maintainer)
```

## Kênh phát hành

- **Tags:** SemVer — `v1.2.3`
- **Tarballs:** attach vào mỗi GitHub Release (auto-build qua `.github/workflows/release.yml`)
- **Changelog:** `CHANGELOG.md` + render trong body của mỗi Release
- **Breaking changes:** `migrations/vN_to_vN+1.md` hiển thị trước khi update proceed

## Đóng góp

Được maintain bởi [@vietdev99](https://github.com/vietdev99). Tạm thời không accept external PR — welcome bug report qua issues.

## License

MIT — xem [LICENSE](LICENSE)
