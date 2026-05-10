<step name="4_mode_first_time">
## Step 4 (mode=first_time): 7-round adaptive discussion

This is the heart. Each round is a model-driven conversational step. Save draft after each round.

**Adversarial challenger (v1.9.1 R3):** Source `.claude/commands/vg/_shared/lib/answer-challenger.sh` at top of command. After EVERY user answer in Rounds 1, 3, 4, 5 (Round 2 = model presents table, no free answer; Round 6/7 = automated), invoke:

```bash
challenge_answer "$user_answer" "round-$ROUND" "project-foundation" "$accumulated_foundation_draft"
```

Orchestrator protocol (identical to scope.md):
1. Read subagent prompt file (path emitted on fd 3 + stderr)
2. Dispatch Task tool → model=`${config.scope.adversarial_model:-haiku}`, zero parent context
3. Parse stdout → one JSON line: `{has_issue, issue_kind, evidence, follow_up_question, proposed_alternative}`
4. Call `challenger_dispatch "$json" "round-$ROUND" "project-foundation" "project"` (phase=literal "project" for FOUNDATION rounds)
5. If `has_issue=true` → AskUserQuestion with 3 options:
   - **Address** → re-ask the round with revised prompt incorporating challenger's follow_up
   - **Acknowledge** → append to `FOUNDATION.md` draft under `## Acknowledged tradeoffs`
   - **Defer** → append under `## Open questions`
6. Call `challenger_record_user_choice "project" "round-$ROUND" "project-foundation" "$choice"`
7. Loop guard: helper auto-caps at `config.scope.adversarial_max_rounds` (default 3) per session

Skip when `config.scope.adversarial_check: false` or answer is trivial (helper auto-detects).

### Round 1: Capture description

If `$INLINE_DESC` non-empty → use as description, skip prompt.
If `$DOC_PATH` set → read file, use as description.
Else → AskUserQuestion:

```
"Mô tả dự án bằng ngôn ngữ tự nhiên. Càng chi tiết càng tốt — AI sẽ tự suy ra
 foundation và config. Có thể dán paragraph tự do hoặc trả lời theo template:

 - Tên / mục tiêu (vấn đề giải quyết):
 - Người dùng (ai sẽ dùng, bao nhiêu người):
 - Tech stack (nếu đã có ý kiến): 
 - Deploy target (VPS/cloud/app-store/...):
 - Constraint quan trọng (latency/scale/compliance/budget):
 - Brownfield? (có codebase sẵn không, đường dẫn ở đâu)"
```

User responds (1 paragraph or template-filled). Save raw to draft.

```bash
${PYTHON_BIN} - <<PY
import json, datetime
from pathlib import Path
draft = {
  "started_at": datetime.datetime.now().isoformat(),
  "current_round": 1,
  "captured": {"description": """<USER_RESPONSE_HERE>"""},
  "derived": {},
  "decisions": [],
  "status": "in_progress"
}
Path("${DRAFT_FILE}").write_text(json.dumps(draft, indent=2), encoding="utf-8")
PY
```

### Round 2: Parse + present overview

Model parses description into 8 dimensions. Present as table with status flags:
- ✓ derived (clearly stated in description)
- ? ambiguous (mentioned but not specific — "React" without Vite/Next)
- ⚠ missing (not mentioned, default applied)
- 🔒 high-cost (always require Round 4 confirm regardless of source)

```
## Foundation derived (Round 2)

| # | Dimension | Value | Status | Notes |
|---|-----------|-------|--------|-------|
| 1 | Platform | web-saas | ✓🔒 | "SaaS quản lý nhân sự" |
| 2 | Frontend runtime | browser | ✓ | implied |
| 3 | Frontend framework | React | ?🔒 | Vite vs Next.js? |
| 4 | Backend topology | monolith | ✓🔒 | Fastify mentioned |
| 5 | Data layer | SQL (Postgres?) | ✓🔒 | Postgres mentioned |
| 6 | Auth model | own | ⚠ | not mentioned, default |
| 7 | Hosting | VPS | ✓🔒 | "deploy lên VPS" |
| 8 | Distribution | URL | ✓ | implied web |
| 9 | Scale | small (50 users) | ✓ | mentioned |
| 10| Compliance | none | ⚠ | not mentioned |

Routing:
- ? items → Round 3 (targeted dialog)
- 🔒 items → Round 4 (high-cost gate, mandatory confirm)
- ⚠ items → Round 5 (constraints fill-in)
- ✓ + non-🔒 → no further dialog
```

Save draft with `current_round=2, derived.foundation_v1=<table>`.

Ask AskUserQuestion: "OK với suy luận này? [y] Yes proceed / [a] Adjust dimension / [d] Discuss deeper from start"

### Round 3: Targeted dialog (skip if no `?` items)

For EACH `?` dimension, model presents OPTIONS with TRADE-OFFS, asks user:

```
"Dimension {N}: Frontend framework
 Bạn nhắc 'React' nhưng có nhiều route đi:

 - Vite + React Router    — SPA thuần, simple, không SEO. Phù hợp internal tool.
 - Next.js (app router)   — SSR + SEO + RSC. Phù hợp public-facing có search.
 - Remix                  — SSR + nested routing tốt. Ít user hơn Next.js.

 Mình đề xuất: Vite (vì internal tool 50 users, SEO không cần).
 [v] Vite (recommended) [n] Next.js [r] Remix [s] Skip — quyết sau"
```

User answers → record F-XX trong decisions array.

**Namespace (không gian tên) note — BREAKING CHANGE v1.8.0:**
- FOUNDATION.md decisions use `F-XX` (project-level, stable across milestones). Ví dụ: `F-01` = Platform decision.
- Per-phase CONTEXT.md decisions use `P{phase}.D-XX` (scoped to phase). Ví dụ: `P7.10.1.D-12` = decision 12 of phase 7.10.1.
- Bare `D-XX` is LEGACY (còn chấp nhận bởi commit-msg hook tới v1.10.0, sau đó reject).
- Rationale: ngăn collision (xung đột) khi phase 15+ có `D-12` trùng với FOUNDATION `D-12` → AI agents cite sai source.
- Migration (chuyển đổi) tool: `.claude/scripts/migrate-d-xx-namespace.py` — tự động rename trong mọi artifact.

### Round 4: High-cost confirmation gate (MANDATORY — never skip)

Model presents ALL `🔒` decisions as a single confirm gate (using new F-XX namespace):

```
"⚠ HIGH-COST DECISIONS (irreversible — confirm explicit trước khi lock):

  🔒 F-01 Platform: web-saas
     Đổi sau = rewrite ~80% UI (sang mobile/desktop). 

  🔒 F-03 Frontend framework: Vite
     Đổi sang Next.js sau = re-architect routing + data fetching.

  🔒 F-04 Backend topology: monolith Fastify
     Đổi sang serverless = re-architect deploy + state management.

  🔒 F-05 Database: Postgres
     Đổi sang NoSQL = data layer rewrite + migration script.

  🔒 F-07 Hosting: VPS
     Đổi sang Vercel/cloud = redeploy infra + CI/CD redo.

 Confirm tất cả? [y] Yes / [r] Revisit dimension cụ thể / [a] Abort"
```

NEVER auto-skip Round 4. Even with `--auto` mode, must confirm. All IDs here are `F-XX` (FOUNDATION namespace).

### Round 5: Constraints fill-in (skip if all answered)

For each `⚠` dimension still missing or default-applied, ask (record as F-XX):

```
"Constraint: Compliance (F-10)
 Bạn không nhắc — default 'none'. Có cần GDPR/HIPAA/SOC2 không?
 [n] None [g] GDPR [h] HIPAA [s] SOC2 [m] Multiple (specify)"
```

Cover: scale (precise users), latency budget, compliance, team size, budget tier. All foundation-scope constraints → F-XX.

### Round 6: Auto-derive vg.config.md from foundation

Model derives config tự động dựa trên foundation. Show preview:

```
## vg.config.md preview (auto-derived from FOUNDATION)

```yaml
project:
  name: <from PROJECT description>
  type: web-saas

frontend:
  framework: vite
  port: 5173
  dev_command: pnpm dev --filter web

backend:
  framework: fastify
  port: 3001
  dev_command: pnpm dev --filter api
  health_endpoint: /health

build_gates:
  typecheck_cmd: pnpm turbo typecheck
  test_cmd: pnpm turbo test
  e2e_cmd: pnpm turbo e2e

deploy:
  target: vps
  ssh_alias: <NEED_USER_INPUT>     ← chỉ field này cần hỏi
  health_url: https://<your-domain>/health  ← cần xác nhận

models:
  executor: sonnet
  planner: opus

(... các field khác auto-fill từ foundation)
```

Hỏi user chỉ những field có `<NEED_USER_INPUT>` placeholder. Không hỏi gì thêm nếu foundation đủ rõ.
```

### Round 7: Architecture Lock (v2.5 Phase D)

**Purpose:** Lock the 8 architectural subsections that govern every future phase. Without this, executors drift across models — FE naming conventions diverge between phases, security baseline degrades, performance budgets get reinvented each phase. This is the single most important section for cross-model code consistency.

The 8 subsections are appended to `FOUNDATION.md` as `## 9. Architecture Lock` and get injected into every blueprint planner prompt as `<architecture_context>`.

**Flow (each subsection = 1 Q with dimension-appropriate depth):**

```
"9.1 Tech stack matrix — xác nhận stack cụ thể:
 [tự-fill từ F-01..F-08 discovered in rounds 1-5]
 - Lang: {FE: React+TS, BE: Node+TS, RTB: Rust}
 - DB: {primary: MongoDB, analytics: ClickHouse, cache: Redis}
 - Auth: {session-cookie SameSite=Strict + argon2id}
 - Deploy: {rsync+PM2 for Node, systemctl for Rust, ansible provisioning}
 - CI: {GitHub Actions with turbo cache}

 Confirm?  [y] keep  [e] edit specific field  [a] add alternative considered"

"9.2 Module boundary — how do apps/packages/shared depend?
 Example: apps/web → packages/ui-kit (allowed), apps/api → packages/schemas (allowed),
 apps/web → apps/api (BANNED — go through HTTP only), packages/* → apps/* (BANNED).
 Apply same pattern? Or project has specific boundaries?
 [y] standard (apps→packages→shared) [e] custom rules [n] skip"

"9.3 Folder convention — route layout + test colocation + asset org
 Typical: apps/api/src/modules/{feature}/{routes,schemas,services}.ts
          apps/web/src/features/{feature}/{components,hooks,pages}.tsx
          tests colocated (.test.ts next to impl) + e2e in apps/web/e2e/
 [y] adopt standard  [e] describe custom convention  [s] skip if existing codebase"

"9.4 Cross-cutting concerns — logging, error handling, async pattern, i18n
 Logging: {pino structured JSON? or winston? or console wrapper?}
 Error handling: {throw + global error handler? Result<T,E>? both?}
 Async: {async/await consistently | callbacks never | worker queues for long jobs}
 i18n: {project has multi-locale? vi+en? keys format?}
 Answer each or 'skip' for unused"

"9.5 Security baseline (LOCK ONCE, applies to all phases):
 Đây là tầng 2 (identity/session) + tầng 3 (server hardening).
 - Session token: {JWT RS256 | opaque session cookie | both?}
 - Lifetime: access ≤ 15min, refresh ≤ 7 days rotated
 - Cookie flags: Secure + HttpOnly + SameSite=Strict
 - CORS: whitelist origins (không wildcard với credentials)
 - OAuth: PKCE mandatory cho public clients (SPA, mobile)
 - Password: argon2id work factor min, length ≥ 12
 - 2FA: {TOTP | SMS | none based on risk profile}
 - Audit log events: {login/logout/role-change/data-export logged with user_id + IP}
 - TLS: version ≥ 1.2, HSTS max-age ≥ 31536000 + includeSubDomains
 - Security headers: CSP default-src 'self', X-Frame-Options DENY, X-Content-Type-Options nosniff
 - Secret management: {Vault | SOPS | KMS | .env + never commit}
 - Dependency: lockfile + CVE scan (deps-security-scan validator)
 - Backup: encrypted at rest (AES-256), {daily|weekly} offsite copy
 - Compliance flags: {GDPR|HIPAA|SOC2|PCI-DSS|none} applicability

 Quan trọng: những giá trị này sẽ đi vào verify-security-baseline gate.
 Nếu không sure, dùng default sensible — sau vẫn /vg:project --update được.
 [f] fill template [q] quick defaults [s] skip (phase chỉ có demo/prototype)"

"9.6 Performance baseline — p95 per tier + cache + bundle + CDN
 - API tier default: read p95 ≤ 250ms, write p95 ≤ 500ms
 - RTB tier (low-latency): p99 ≤ 50ms (OpenRTB constraint)
 - Cache strategy: {Redis 5min TTL + tag-invalidate | in-memory LRU | none}
 - Bundle budget FE route: 250KB default (adjust per project)
 - n_plus_one_max query count per endpoint: 3 (triggers warning)
 - CDN: {Cloudflare | Fastly | none}
 [y] adopt defaults [e] custom per-tier"

"9.7 Testing baseline — runner, E2E framework, coverage, mock strategy
 - Unit runner: {vitest | jest | pytest | cargo test}
 - E2E framework: {Playwright | Cypress | native selenium}
 - Coverage threshold: {80%/70%/60% per app?}
 - Mock strategy: {MSW for API | never mock DB | fixtures for ClickHouse}
 - Fixture location: apps/*/e2e/fixtures/
 [y] standard [e] custom]"

"9.8 Model-portable code style — rules that transcend Claude/GPT/Gemini
 - Imports: explicit (no wildcard * imports)
 - Exports: named > default (default export only cho React.lazy)
 - Type annotations: mandatory function signatures (params + return)
 - Comment density: 1 per ~10 SLOC khi có WHY (no WHAT comments)
 - Import ordering: external → internal packages → relative
 - File naming: {kebab-case.ts | camelCase.ts | PascalCase.tsx for components}
 - Error handling idiom: {throw + narrow catches | Result<T,E> | neither}
 Cross-model validation: CrossAI 2d-6 will diff code style across AI outputs.
 [y] standard [e] project-specific]"

"9.9 UI state conventions — list view URL synchronization (v2.8.4 Phase J)
 Áp dụng cho mọi list/table/grid view trong dashboard. Mục tiêu: refresh
 giữ filter/sort/page, share link giữ state, browser back/forward navigate
 đúng các state thay đổi. Đây là dashboard UX baseline modern (Linear,
 Stripe, GitHub, ProductHunt — tất cả default thế).
 - list_view_state_in_url: {true (default) | false (local-only state, hiếm)}
 - url_param_naming: {kebab (status, sort-by, page-size) | camel (status, sortBy, pageSize)}
 - array_format: {csv (?tags=a,b,c) | repeat (?tag=a&tag=b)}
 - debounce_search_ms: {300 default | adjust per UX}
 - default_page_size: {20 | adjust}
 Override per-goal: TEST-GOALS interactive_controls.url_sync: false
 với url_sync_waive_reason (logged as soft debt).
 verify-url-state-sync.py validator runs at /vg:review phase 2.7.
 [y] standard (kebab + csv + 300ms + 20) [e] custom [s] skip nếu project no list views]"
```

**Append to draft.foundation_md_content:**
```python
foundation_section_9 = f'''

---

## 9. Architecture Lock

> Locked {iso_timestamp} via `/vg:project` round 7.
> Section 9 is authoritative — every blueprint planner prompt injects this as <architecture_context>.
> Changes here require `/vg:project --update` + re-running affected phases' scope (CONTEXT drift detection).

### 9.1 Tech stack matrix
{tech_stack_block}

### 9.2 Module boundary
{module_boundary_block}

### 9.3 Folder convention
{folder_convention_block}

### 9.4 Cross-cutting concerns
{cross_cutting_block}

### 9.5 Security baseline
{security_baseline_block}

### 9.6 Performance baseline
{perf_baseline_block}

### 9.7 Testing baseline
{testing_baseline_block}

### 9.8 Model-portable code style
{code_style_block}

### 9.9 UI state conventions (v2.8.4 Phase J)
{ui_state_conventions_block}
'''
draft["foundation_md_content"] += foundation_section_9
```

The `ui_state_conventions_block` MUST contain the locked values:
```yaml
list_view_state_in_url: true              # MANDATORY default — override per-goal only
url_param_naming: kebab                   # status, sort-by, page-size
array_format: csv                         # ?tags=a,b,c
debounce_search_ms: 300
default_page_size: 20
```
These flow into vg.config.md `ui_state_conventions` block + executor R7
+ verify-url-state-sync.py severity matrix.

**Migration:** For projects running `/vg:project --migrate` (extracting FOUNDATION from legacy PROJECT.md), auto-scan codebase to pre-fill §9 where possible (tech_stack from package.json, folder convention from existing dirs, testing baseline from existing test scripts). Mark any unresolved fields with `<NEED_USER_INPUT>` — user must fill before section 9 locks.

### Round 8: Security Testing Strategy (v2.5 Phase D)

**Purpose:** After FOUNDATION §9.5 locks security baseline (implementation rules), Round 8 locks security testing strategy — who tests, how often, what framework. This is a separate artifact `.vg/SECURITY-TEST-PLAN.md` that drives DAST severity gate (Phase B.5/B.6) and pentest checklist gen (Phase I).

4 questions, each with config consequences:

```
"10.1 Risk profile classification
 Determines DAST severity gate + pen-test frequency:

 [c] critical — payment/PII/healthcare/auth-SaaS-multi-tenant
     → High DAST finding = BLOCK, pen-test annual external, SOC2-equivalent
 [m] moderate — internal tool with external users
     → High = WARN, pen-test quarterly internal, compliance as needed
 [l] low — read-only dashboard, marketing site, blog
     → all DAST advisory, no pen-test required

 Select:"

"10.2 DAST tool choice (dynamic scan at /vg:test step 5h)
 [z] OWASP ZAP — docker-based, full HTTP active scan (recommended web)
 [n] Nuclei — binary-based, CVE templates (lightweight, fast)
 [c] Custom — describe tool
 [x] None — read-only project, no HTTP endpoints

 Select:"

"10.3 Pen-test strategy (manual tier, cannot automate)
 [e] external-vendor-annual — budget-heavy, highest quality
 [i] internal-team-quarterly — in-house pen-test rotation
 [b] bug-bounty-continuous — HackerOne/Bugcrowd public/private
 [n] none — low-risk project OR pre-launch

 Select:"

"10.4 Compliance framework mapping
 Drives audit artifact requirements + control coverage check:

 [s] SOC2 Type II
 [i] ISO 27001
 [p1] PCI-DSS Level 1 (millions of tx/year)
 [p4] PCI-DSS Level 4 (small merchant)
 [h] HIPAA (healthcare/PHI)
 [g] GDPR only (EU user data)
 [n] none

 Select (can pick multiple, comma-separated):"
```

**Write SECURITY-TEST-PLAN.md.staged:**
```bash
# Fill template from template file
cp .claude/commands/vg/_shared/templates/SECURITY-TEST-PLAN-template.md "${STP_FILE}.staged"

# Substitute answers (sed or Python script reading DRAFT_FILE)
${PYTHON_BIN} - <<'PY'
import json, os, re
from pathlib import Path
from datetime import datetime, timezone

draft = json.loads(Path(os.environ["DRAFT_FILE"]).read_text(encoding="utf-8"))
stp = Path(os.environ["STP_FILE"] + ".staged")
text = stp.read_text(encoding="utf-8")

# Placeholders: {PROJECT_NAME}, {ISO_TIMESTAMP}, {FOUNDATION_PATH},
# {CRITICAL|MODERATE|LOW}, {ZAP|Nuclei|Custom|None}, etc.
text = text.replace("{PROJECT_NAME}", draft["project_name"])
text = text.replace("{ISO_TIMESTAMP}", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
text = text.replace("{FOUNDATION_PATH}", os.environ["FOUNDATION_FILE"])
# ... answers from round 8
text = text.replace("{CRITICAL|MODERATE|LOW}", draft["security"]["risk_profile"])
# ...
stp.write_text(text, encoding="utf-8")
print(f"✓ SECURITY-TEST-PLAN.md.staged written")
PY
```

**Side-effect on `.claude/vg.config.md`:** Round 8 answers also update config:
- `project.risk_profile: {critical|moderate|low}` (drives DAST severity)
- `security_testing.dast_tool: {ZAP|Nuclei|Custom|None}`
- `security_testing.payload_profile: owasp-top10-2021` (default)
- `security_testing.dast_cascade: [zap,nuclei,grep-only]` (if dast_tool empty → cascade auto-detect)

These get written via `vg_generate_config.py` in Round 9 (was Round 7) atomic step.

### Round 9: Atomic write + commit

Write all 4 files trong 1 transaction.

**v1.13.0 (2026-04-18) — template-based config generation.**
The old inline placeholder heredoc is gone. Config rendering is delegated to
`.claude/scripts/vg_generate_config.py`, which reads the full-schema template
at `.claude/templates/vg/vg.config.template.md` (~700 lines, 100% coverage of
every field workflow commands read) and substitutes only foundation-derived
fields. Previously the heredoc covered ~25% of schema so 75% of config was
best-guess by AI — caused missing fields like `db_name`, `i18n`,
`ports.database`, `rationalization_guard.model`, `surfaces.web` etc. Audit
history lives in `.vg/CONFIG-AUDIT.md`.

```bash
# 1. Write PROJECT.md.staged + FOUNDATION.md.staged from discussion (small, direct)
${PYTHON_BIN} - <<'PY'
import json, os
from pathlib import Path

draft = json.loads(Path(os.environ["DRAFT_FILE"]).read_text(encoding="utf-8"))

# PROJECT.md ← identity + milestones
project_md = Path(os.environ["PROJECT_FILE"] + ".staged")
project_md.write_text(draft["project_md_content"], encoding="utf-8")

# FOUNDATION.md ← 8 dimensions + F-XX decisions
foundation_md = Path(os.environ["FOUNDATION_FILE"] + ".staged")
foundation_md.write_text(draft["foundation_md_content"], encoding="utf-8")

# Export foundation subset as JSON for config generator (next step)
foundation_json = Path(os.environ["PLANNING_DIR"]) / ".foundation-for-config.json"
foundation_json.write_text(json.dumps(draft["foundation_for_config"], indent=2), encoding="utf-8")
print(f"✓ PROJECT.md.staged + FOUNDATION.md.staged + foundation-for-config.json written")
PY

# 2. Render vg.config.md.staged via generator (the v1.13.0 swap-in)
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg_generate_config.py" \
  --foundation "${PLANNING_DIR}/.foundation-for-config.json" \
  --template   "${REPO_ROOT}/.claude/templates/vg/vg.config.template.md" \
  --output     "${CONFIG_FILE}.staged"

if [ $? -ne 0 ] || [ ! -s "${CONFIG_FILE}.staged" ]; then
  echo "⛔ vg_generate_config.py failed — cannot promote staged artifacts."
  echo "   Run manually to debug:"
  echo "     ${PYTHON_BIN} .claude/scripts/vg_generate_config.py \\"
  echo "       --foundation ${PLANNING_DIR}/.foundation-for-config.json \\"
  echo "       --template   .claude/templates/vg/vg.config.template.md \\"
  echo "       --output     /tmp/config.test.md --strict"
  exit 1
fi

# 3. Cleanup temp JSON (keeps repo tidy — foundation lives in FOUNDATION.md now)
rm -f "${PLANNING_DIR}/.foundation-for-config.json"

# Write-strict gate (v1.9.0 T5): FOUNDATION.md MUST use F-XX, never bare D-XX
# (D-XX is reserved for phase CONTEXT.md as P{phase}.D-XX).
# shellcheck disable=SC1091
source .claude/commands/vg/_shared/lib/namespace-validator.sh
if ! validate_d_xx_namespace "${FOUNDATION_FILE}.staged" "foundation"; then
  echo ""
  echo "⛔ Foundation gate chặn: FOUNDATION.md.staged chứa bare D-XX — phải dùng F-XX."
  echo "   Sửa staging file xong chạy lại /vg:project (resume from draft)."
  exit 1
fi

# v2.5 Phase D: also promote SECURITY-TEST-PLAN.md if Round 8 wrote it
STP_FILE="${PLANNING_DIR:-.vg}/SECURITY-TEST-PLAN.md"

# Atomic promote (mv all-or-nothing — now 4 files)
mv "${PROJECT_FILE}.staged"     "$PROJECT_FILE"
mv "${FOUNDATION_FILE}.staged" "$FOUNDATION_FILE"
mv "${CONFIG_FILE}.staged"     "$CONFIG_FILE"
[ -f "${STP_FILE}.staged" ] && mv "${STP_FILE}.staged" "$STP_FILE"

# Remove draft
rm -f "$DRAFT_FILE"

# Commit
git add "$PROJECT_FILE" "$FOUNDATION_FILE" "$CONFIG_FILE"
[ -f "$STP_FILE" ] && git add "$STP_FILE"
git commit -m "project: foundation locked

Per discussion rounds 1-7. See FOUNDATION.md for F-XX decisions (F = Foundation namespace, stable across milestones; per-phase decisions use P{phase}.D-XX).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Print summary + next steps:
```
✅ Foundation locked. Artifacts:
  - PROJECT.md (project identity + milestones)
  - FOUNDATION.md (8 dimensions + N decisions)
  - vg.config.md (auto-derived from foundation)

Next: /vg:roadmap  (derive phases from project + foundation)
```
</step>
