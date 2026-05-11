---
name: "vg-project"
description: "Entry point — project identity + foundation + auto-init via 7-round adaptive discussion. Replaces standalone /vg:init."
metadata:
  short-description: "Entry point — project identity + foundation + auto-init via 7-round adaptive discussion. Replaces standalone /vg:init."
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Runtime lock

When this skill is running inside Codex, DO NOT switch to Claude CLI to execute
the workflow entrypoint. Keep the current Codex runtime, export
`VG_RUNTIME=codex`, use Codex `update_plan` for the compact visible task
window, and bind it with `vg-orchestrator tasklist-projected --adapter codex`.

VGFlow source paths are resolved through global `VG_HOME` (default:
`~/.vgflow`). Project-local Claude workflow files may be absent in
global-only installs; Codex must use
`${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}` and
`${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}` for workflow
helpers. References below to "Claude CLI", `TodoWrite`, or Haiku describe
the Claude adapter only. Codex must map them through this adapter contract
instead of aborting the current run and relaunching Claude.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Compact Codex plan window + orchestrator step markers | Use `tasklist-contract.json` as source of truth. Do not paste the full hierarchy into Codex `update_plan`. Show at most 6 rows: active group/step first, next 2-3 pending steps, completed groups collapsed, and `+N pending`. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash "${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg}/_shared/lib/codex-spawn.sh" \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-project`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Use markdown headers in your text output between tool calls (e.g. `## ━━━ Round 3: Tech ambiguities ━━━`). Long Bash > 30s → `run_in_background: true` + `BashOutput` polls.

**Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `Foundation (nền tảng)`, `migrate (chuyển đổi)`, `merge (gộp) NOT overwrite (ghi đè)`, `legacy-v1 (định dạng cũ v1)`, `greenfield (dự án mới)`, `brownfield (dự án có codebase)`. Không áp dụng: file path (`PROJECT.md`), code identifier (`D-XX`, `pnpm`), config tag values (`web-saas`), lần lặp lại trong cùng message.
</NARRATION_POLICY>

<rules>
1. **Single entry point** — replaces `/vg:init`. `/vg:init` is now a soft alias for `/vg:project --init-only`.
2. **7-round adaptive discussion** — heavy by design (high-precision projects). Skip rounds where no ambiguity, but never skip Round 4 (high-cost gate).
3. **Three artifacts written atomically** — `PROJECT.md`, `FOUNDATION.md`, `vg.config.md`. All-or-nothing commit.
4. **Foundation = load-bearing** — drives roadmap/init/scope/add-phase. Drift detection ở downstream commands.
5. **MERGE NOT OVERWRITE** — re-runs preserve existing decisions. Only [w] Rewrite resets (with backup).
6. **Resumable** — `${PLANNING_DIR}/.project-draft.json` checkpoints every round. Interrupt-safe.
7. **Brownfield aware** — `--migrate` extracts foundation from existing PROJECT.md + codebase scan.
</rules>

<objective>
First command in VG pipeline. Captures project identity, derives foundation (8 platform/runtime/data/auth/hosting/distribution/scale/compliance dimensions), and auto-generates `vg.config.md` from foundation. All downstream commands (roadmap, scope, blueprint) consume FOUNDATION.md.

Pipeline: **project** → roadmap → map → prioritize → specs → scope → blueprint → build → review → test → accept
</objective>

<process>

### Preflight section (extracted v2.71.0 T1)

Read `_shared/project/preflight.md` and follow it exactly.
Includes 3 steps: 0_parse_args, 0b_print_state_summary, 0c_scan_existing_docs.

### Routing section (extracted v2.71.0 T2)

Read `_shared/project/routing.md` and follow it exactly.
Includes 4 steps: 1_route_mode, 2a_resume_check, 2b_mode_menu, 3_mode_view.

### First-time mode (Rounds 1-9, extracted v2.71.0 T3 — LARGEST section)

Read `_shared/project/first-time-rounds.md` and follow it exactly.
Includes 1 step + 9 rounds: 4_mode_first_time + Round 1 (Capture description), Round 2 (Parse + overview), Round 3 (Targeted dialog), Round 4 (Confirmation gate — MANDATORY), Round 5 (Constraints fill-in), Round 6 (Auto-derive vg.config.md), Round 7 (Architecture Lock), Round 8 (Security Testing Strategy), Round 9 (Atomic write + commit).

<!-- BEGIN_LEGACY_FIRST_TIME_PLACEHOLDER (extracted to _shared/project/first-time-rounds.md) -->
<!-- END_LEGACY_FIRST_TIME_PLACEHOLDER -->

### Update modes (extracted v2.71.0 T4)

Read `_shared/project/update-modes.md` and follow it exactly.
Includes 3 steps: 5_mode_update, 6_mode_milestone, 7_mode_rewrite.


### Migrate + init-only + complete (extracted v2.71.0 T5 — final extraction)

Read `_shared/project/migrate-and-init.md` and follow it exactly.
Includes 3 steps: 8_mode_migrate, 9_mode_init_only, 10_complete.


</process>

## FOUNDATION.md template

```markdown
# Foundation — {Project Name}

**Locked:** {ISO timestamp}
**Source:** {first-time | --update | --migrate | --rewrite}
**Source description:** {first 200 chars of user description}

## 1. Platform & Topology (8 dimensions)

**Namespace:** All FOUNDATION decisions use `F-XX` (project-level, stable across milestones). Per-phase decisions live in `${PLANNING_DIR}/phases/*/CONTEXT.md` as `P{phase}.D-XX`.

| # | Dimension | Value | Decision | Confidence |
|---|-----------|-------|----------|------------|
| 1 | Platform type | web-saas / mobile-native / mobile-cross / desktop / cli / hybrid | F-01 | derived/confirmed |
| 2 | Frontend runtime | browser / iOS / Android / Electron / none | F-02 | ... |
| 3 | Frontend framework | React+Vite / Next.js / Vue+Vite / Svelte / Flutter / RN / native-iOS / native-Android | F-03 | ... |
| 4 | Backend topology | none / monolith / microservices / serverless / edge / BaaS | F-04 | ... |
| 5 | Data layer | none / Postgres / MySQL / SQLite / MongoDB / Redis / blob / hybrid | F-05 | ... |
| 6 | Auth model | none / own / OAuth / SSO / passwordless / 3rd-party (Auth0/Clerk) | F-06 | ... |
| 7 | Hosting | VPS / AWS / GCP / Vercel / Netlify / on-prem / app-store / hybrid | F-07 | ... |
| 8 | Distribution | URL / app-store / npm / docker-hub / physical-device | F-08 | ... |

## 2. Tech Stack (concrete choices, derived from above)

- Frontend: {framework + key libs} (F-XX)
- Backend: {framework + key libs} (F-XX)
- Database: {engine + version} (F-XX)
- Build/monorepo: {pnpm+turborepo / npm / cargo / go-mod / ...} (F-XX)
- Test: {vitest / jest / pytest / playwright / maestro / ...} (F-XX)
- Deploy: {SSH+PM2 / git-push / docker / Ansible / ...} (F-XX)

## 3. Constraints

- **Scale:** ~{N users, X QPS}
- **Latency budget:** {p50/p99 targets}
- **Compliance:** {none / GDPR / HIPAA / SOC2 / multiple}
- **Team size:** {solo / 2-5 / 6-20 / 20+}
- **Budget tier:** {hobbyist / bootstrapped / funded / enterprise}

## 4. Decisions

### F-01: Platform = {value}
**Reasoning:** {derivation/discussion summary}
**Reverse cost:** HIGH/MEDIUM/LOW — {what breaks if reversed}
**Confirmed:** {date} by user
**Source:** {description / Round 4 confirm / scan / migration}

(F-02 ... F-N — same structure)

**Namespace rule:** These IDs are `F-XX` (Foundation-scope). Do NOT reuse `D-XX` — that's reserved for per-phase CONTEXT.md as `P{phase}.D-XX`.

## 5. Open Questions

{none if all locked, else list of Q-XX with proposed defaults}

## 6. Drift Check

**Last check:** {date}  
**Status:** ✅ no drift / ⚠ drift detected (see below)  
**Drift entries:** {none, or phase {X} introduced keyword 'mobile' — review platform decision}
```

## vg.config.md derivation rules (Round 6 logic)

**v1.13.0+ (2026-04-18):** Logic lives in `.claude/scripts/vg_generate_config.py`.
This markdown table is reference-only — the authoritative derivation tables
(`FRAMEWORK_PORT`, `BACKEND_PORT`, `BACKEND_HEALTH`, `DATA_PORT`,
`HOSTING_DEPLOY_PROFILE`, `TEST_RUNNER_BY_STACK`) are constants at the top
of `vg_generate_config.py`. Update there, not here.

The generator also emits dynamic blocks: `crossai_clis` / `models` scale with
`team_size`; `services` + `credentials` + `apps` + `infra_deps.services`
derive from `data` / `auth.roles` / `monorepo.apps` / etc. Template:
`.claude/templates/vg/vg.config.template.md` (~700 lines, full schema).

Reference table (indicative — check script for current values):

| Foundation field | → vg.config.md fields |
|------------------|----------------------|
| `frontend.framework: vite` | `worktree_ports.base.web: 5173`, `dev_command: {pm} dev` |
| `frontend.framework: next` | `worktree_ports.base.web: 3000` |
| `backend.framework: fastify` | `worktree_ports.base.api: 3001`, `health: /health` |
| `backend.framework: express` | `worktree_ports.base.api: 3000` |
| `hosting: vps` | `deploy_profile: pm2`, `run_prefix: ssh {{ssh_alias}}` |
| `hosting: vercel` | `deploy_profile: git_push` |
| `data.primary: postgres` | `ports.database: 5432`, `services.local.postgres check` |
| `data.primary: mongodb` | `ports.database: 27017`, `services.local.mongodb check` |
| `monorepo: turborepo` | `build_gates.typecheck_cmd: pnpm turbo typecheck` |
| `team_size: solo` | `models.executor: sonnet`, `models.planner: opus` (cost-aware) |
| `team_size: 6-20+` | `models.executor: opus`, `crossai_clis: [codex, gemini]` (quality-priority) |

User only asked về fields marked `<ASK>` (typically: ssh_alias, deploy.path, domain, secrets). Other fields auto-fill silent.

## Resumable draft format

`${PLANNING_DIR}/.project-draft.json`:
```json
{
  "started_at": "2026-04-17T...",
  "current_round": 4,
  "captured": {
    "description": "<user free-form>",
    "template_responses": {...}
  },
  "derived": {
    "foundation_v1": {
      "platform": "web-saas",
      "frontend_framework": "vite",
      ...
    },
    "ambiguities": [
      {"dim": "auth", "options": ["own", "oauth"], "default": "own"}
    ]
  },
  "decisions": [
    {"id": "F-01", "dim": "platform", "value": "web-saas", "confirmed": true, "round": 4}
  ],
  "status": "in_progress"
}
```

Atomic write after every round (write to `.project-draft.json.tmp` → rename).

## Telemetry

Each `/vg:project` invocation logs to telemetry:
```jsonl
{"ts": "...", "cmd": "vg:project", "mode": "first_time|update|...", "rounds_completed": N, "foundation_changed": true|false, "config_changed": true|false}
```

## Success criteria

- First-time run produces 3 atomic artifacts: PROJECT.md + FOUNDATION.md + vg.config.md
- Re-run with no flag → mode menu (View default)
- `--update`, `--milestone`, `--rewrite`, `--migrate`, `--init-only`, `--view` all routable
- Draft checkpointed every round, resumable on interrupt
- High-cost confirm gate (Round 4) NEVER skipped
- Existing decisions F-XX preserved across `--update` (MERGE NOT OVERWRITE)
- **Namespace enforcement:** FOUNDATION.md uses `F-XX`; phase CONTEXT.md uses `P{phase}.D-XX`. Legacy bare `D-XX` accepted until v1.10.0, then rejected. Migration tool: `.claude/scripts/migrate-d-xx-namespace.py`
- `--rewrite` always backs up to `.archive/{ts}/`
- vg.config.md auto-derived 80-90%, only `<ASK>` fields prompt user
- Foundation drift detection in roadmap/add-phase/scope (separate commands)
