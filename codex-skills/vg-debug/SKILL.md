---
name: "vg-debug"
description: "Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)"
metadata:
  short-description: "Targeted bug-fix loop — analyze description, classify, fix, verify with user (no full review sweep)"
  source_allowed_tools:
    - Read
    - Write
    - Edit
    - Bash
    - Glob
    - Grep
    - AskUserQuestion
    - Task
    - SlashCommand
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

Invoke this skill as `$vg-debug`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>




<LANGUAGE_POLICY>
You MUST follow `_shared/language-policy.md`. **NON-NEGOTIABLE.**

Mặc định trả lời bằng **tiếng Việt** (config: `language.primary` trong
`.claude/vg.config.md`, fallback `vi` nếu chưa set). Dùng ngôn ngữ con
người, không technical jargon. Mỗi thuật ngữ tiếng Anh xuất hiện lần đầu
trong narration: thêm giải thích VN trong dấu ngoặc (per
`_shared/term-glossary.md`).

Ví dụ:
- ❌ "Validator failed with 225 evidence count"
- ✅ "Validator báo 225 trường thiếu — chi tiết ở `[path]`. Mình sẽ sửa rồi chạy lại."

File paths, code identifiers (G-04, Wave 9, getUserById), commit messages,
CLI commands stay English. AskUserQuestion title + options + question prose:
ngôn ngữ config.
</LANGUAGE_POLICY>


<rules>
1. **Standalone session** — debug session lives in `.vg/debug/<id>/`, not phase-scoped (Q1 user choice).
2. **AskUserQuestion-driven loop** — no max iterations. Each loop end asks user: fixed / retry / more-info (Q2).
3. **Auto-classify** — AI picks discovery path (code-only / browser / network / infra / spec gap) without asking unless confidence < 80%.
4. **Spec gap → auto /vg:amend** — if classified as spec gap, auto-trigger `/vg:amend <phase>` (Q5=a).
5. **Browser MCP fallback** — if browser MCP unavailable + UI bug, write findings as amendment to phase (Q3) instead of blocking.
6. **Atomic commits per fix** — each fix attempt = 1 commit. Easy rollback if loop fails.
7. **No destructive actions** — fix code only. Don't drop tables, force-push, or delete branches.
</rules>

<objective>
Lightweight targeted bug-fix workflow. Use case: user gặp 1 bug cụ thể (ví dụ click /campaigns crash), thay vì chạy `/vg:review` (15-30 min full Haiku scan), chạy `/vg:debug "<mô tả>"` (3-5 min targeted) để:

1. Parse + classify bug từ natural language
2. Auto-pick discovery method
3. Generate hypothesis chain
4. Apply fix + commit atomic
5. Verify (reproduce)
6. AskUserQuestion loop until user confirms fixed

Output: `.vg/debug/<id>/DEBUG-LOG.md` + atomic commits. If detected spec gap → auto `/vg:amend`.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

### Preflight section (extracted v2.75.0 T6)

Read `_shared/debug/preflight.md` and follow it exactly.
Includes 1 step: 0_parse_and_classify.

Step coverage: 0_parse_and_classify.


### Discovery + hypothesize + fix (extracted v2.75.0 T7)

Read `_shared/debug/discovery-and-fix.md` and follow it exactly.
Includes 2 steps: 1_discovery, 2_hypothesize_and_fix.

Step coverage: 1_discovery, 2_hypothesize_and_fix.


### Verify + close (extracted v2.75.0 T8 — final)

Read `_shared/debug/verify-and-close.md` and follow it exactly.
Includes 2 steps: 3_verify_and_loop, 4_complete.

Step coverage: 3_verify_and_loop, 4_complete.


</process>

<success_criteria>
- Bug description parsed + classified
- Discovery completed (matching bug type)
- At least 1 fix iteration attempted
- User confirmed status via AskUserQuestion (fixed / retry / more)
- DEBUG-LOG.md written with full trace
- 5 telemetry events emitted (parsed, classified, fix_attempted, user_confirmed, completed)
- Atomic commits per fix (rollback-safe)
- Spec gap → auto-routed to /vg:amend (if detected)
</success_criteria>
