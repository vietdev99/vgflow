---
name: "test-depth"
description: "Interactive depth discovery — present DEEP components to user for business context, CrossAI trace unknowns, output DEPTH-INPUT.md"
metadata:
  short-description: "Interactive depth discovery — present DEEP components to user for business context, CrossAI trace unknowns, output DEPTH-INPUT.md"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Markdown progress + step markers | Do not rely on Claude's persistent task tail UI. |
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
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
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

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Do NOT blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
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
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
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

Invoke this skill as `$test-depth`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Test Depth — User-Guided Business Flow Discovery

Present DEEP components to user, collect business context they know, CrossAI trace what they don't. Output structured DEPTH-INPUT.md.

**Called by:** `/rtb:test-specs` Step 2
**Input:** `{phase}-COMPONENT-MAP.md` (from test-scan)
**Output:** `.planning/phases/{phase}/{phase}-DEPTH-INPUT.md`

## Philosophy

AI is good at: scanning code, generating technical test steps, cross-referencing.
AI is bad at: guessing hidden business logic, side effects, domain rules.
User is good at: knowing what can go wrong, business rules, edge cases.
User is bad at: writing 100 test steps, remembering all modal fields.

→ **Each side does what they're good at.**

## Process

### 1. Load COMPONENT-MAP.md

Read the map. Extract all DEEP components with their signals and key actions.

### 2. Present DEEP Components to User

Show a numbered list:
```
Phase {X} has {N} DEEP components that trigger business flows.
I need your input on what each one does beyond the obvious.

1. ApproveButton (campaigns) — onClick calls POST /campaigns/:id/approve
   → Beyond status change, what else happens? (notifications? audit? auto-activate?)

2. AddFundsForm (finance) — onSubmit calls POST /funding/deposit
   → Beyond balance increase, what else triggers? (invoice? email? limits?)

3. DeleteSiteButton (sites) — onClick calls DELETE /sites/:id
   → Is this hard delete or soft? Pending period? Cascade to ad units?

For each, tell me:
  (a) What business flow does it trigger?
  (b) Any security risks? (see examples below)

Type "skip" for ones you're unsure about — I'll use CrossAI to trace those.
```

**Security question examples (show 1 per component based on type):**

| Component Type | Security Question |
|---------------|-------------------|
| Mutation with role check | "Can user A trigger this on user B's data? (IDOR)" |
| Financial operation | "Can balance go negative? Double-submit? Race condition?" |
| Role-gated action | "Can a publisher call this admin endpoint? (Privilege escalation)" |
| Data export/view | "Does this leak data from other orgs? (Tenant isolation)" |
| File upload | "Can malicious file be uploaded? Size limit? Type validation?" |
| Auth-related | "Brute force? Session fixation? Token reuse after logout?" |

### 3. Collect User Responses

For each component, user provides one of:
- **Business context:** "Approve also sends email to advertiser, creates audit log, and if campaign has auto_start=true it schedules activation"
- **Security context:** "Yes, IDOR risk — need to verify campaign belongs to caller's org"
- **"skip":** User doesn't know → queue for CrossAI trace
- **Additional edge cases:** "Also check: what if balance insufficient during approval?"

### 4. CrossAI Trace (skipped components only)

For components user skipped, spawn CrossAI depth trace:

Bundle per component: component source + API route + service file.

Prompt each CLI:
```
Trace the COMPLETE business flow triggered by this component.
For EVERY action: API endpoint, middleware, service side effects,
data changes, notifications, audit logs, cross-page impact, error states.
Output as: | # | Layer | Action | Side Effects |
```

Use fast-fail consensus (crossai-invoke.md with `$LABEL="depth-trace"`).

Merge with confidence: AGREED (3/3), CONFIRMED (2/3), DISPUTED (1/3).

### 5. Write DEPTH-INPUT.md

```markdown
---
phase: {phase}
deep_components: {N}
user_provided: {N}
crossai_traced: {N}
disputed_paths: {N}
---

## Component: {name}
- **Source:** user | crossai | both
- **File:** {path}

### Business Flow
| # | Action | Side Effects | Source | Confidence |
|---|--------|-------------|--------|------------|
| 1 | POST /campaigns/:id/approve | Status → approved | user | HIGH |
| 2 | Send email to advertiser | notification.send() | user | HIGH |
| 3 | Create audit log | auditLog.create() | user | HIGH |
| 4 | Schedule activation if auto_start | cron.schedule() | crossai (1/3) | DISPUTED |

### Error States (from user)
- Insufficient balance → 400 + toast
- Already approved → 409 + toast

### Test Implications
- Steps 1-3: MUST test (user confirmed)
- Step 4: VERIFY manually (DISPUTED — only 1 CLI found)
- Error states: MUST test both paths
```

## --deepen Mode

When called with `--deepen`:
1. Read existing DEPTH-INPUT.md
2. Show user which DISPUTED paths are still unverified
3. Ask: "These paths were uncertain last time. Can you confirm or deny?"
4. For NEW components (added since last scan): run full flow (steps 2-4)
5. Append new findings to DEPTH-INPUT.md

## Anti-Patterns
- DO NOT guess business logic — if user doesn't know and CrossAI is uncertain, mark DISPUTED
- DO NOT ask user about SHALLOW/INTERACTIVE components — waste of their time
- DO NOT skip CrossAI for "skip" components — that's the whole point of this step
- DO NOT ask more than 1 question per component — keep it focused
- DO NOT present technical details (hook names, file paths) — ask in business terms
