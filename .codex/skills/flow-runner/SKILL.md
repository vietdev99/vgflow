---
name: "flow-runner"
description: "Execute flow tests via MCP Playwright with checkpoint-resume, 4-rule deviation classification, 3-strike escalation, evidence-required assertions"
metadata:
  short-description: "Execute flow tests via MCP Playwright with checkpoint-resume, 4-rule deviation classification, 3-strike escalation, evidence-required assertions"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
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

Claude Code and Codex now both have project-local hook substrates. VGFlow
`sync.sh`/`install.sh` installs `.codex/hooks.json` plus
`.codex/config.toml` with `[features].codex_hooks = true`. Codex hooks
wrap the same orchestrator that writes `.vg/events.db`, while command-body
guards remain mandatory because Codex hook coverage is still tool-path scoped:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Codex wrapper accepts both `/vg:cmd` and `$vg-cmd`; command-body `vg-orchestrator run-start` is still mandatory and must BLOCK if missing/failing |
| `PreToolUse` Bash -> `hooks/vg-pre-tool-use-bash.sh` | Blocks `vg-orchestrator step-active` until tasklist projection evidence is signed | Codex wrapper sets `CLAUDE_SESSION_ID`/`CLAUDE_HOOK_SESSION_ID` from Codex `session_id` and forwards to the same gate |
| `PreToolUse` Write/Edit -> `hooks/vg-pre-tool-use-write.sh` | Blocks direct writes to protected evidence, marker, and event paths | Codex `apply_patch` wrapper at `codex-hooks/vg-pre-tool-use-apply-patch.py` blocks the same protected paths before patch application |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Codex wrapper forwards Bash results to the same tracker; explicit `vg-orchestrator mark-step` lines remain required |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Codex wrapper runs the same verifier; command-body terminal `vg-orchestrator run-complete` is still required before claiming completion |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Before running any command-body snippet that calls validators, orchestrator
helpers, or `${PYTHON_BIN:-python3}`, execute the Python detection block from
`.claude/commands/vg/_shared/config-loader.md` in that same Bash shell and
export the selected `PYTHON_BIN`. Do not reset `PYTHON_BIN=python3` after
detection: on macOS, bare `python3` is often an older interpreter without
PyYAML, which makes VG validators fail even though a valid Homebrew/Python.org
interpreter is installed.

Each Codex shell tool call starts with a fresh environment. If a later command
invokes `.claude/scripts/*`, validators, or `vg-orchestrator`, redetect
`PYTHON_BIN` or carry the previously detected absolute interpreter into that
same command. Do not run `python3 .claude/scripts/...` directly for VG
validators/orchestrator calls.

For tasklist projection, Codex must write evidence before any step marker call:
after `emit-tasklist.py`, run `vg-orchestrator tasklist-projected --adapter codex`
as its own tool call. Do not group `tasklist-projected` and `step-active` in
one shell command; PreToolUse evaluates the entire command before the evidence
file exists and will block the grouped command.

For top-level VG commands that include a mandatory `git commit` step, ensure
the parent Codex session can write Git metadata. Some Codex
`workspace-write` sandboxes deny `.git/index.lock`; when that happens,
BLOCK and ask the operator to rerun with a sandbox/profile that permits Git
metadata writes instead of skipping or forging the commit marker.

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
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --spawn-role "<vg-subagent-role>" \
  --spawn-id "<stable-spawn-id>" \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.
When `--spawn-role` is set, it also writes Codex spawn evidence to
`.vg/runs/<run_id>/codex-spawns/` and appends
`.vg/runs/<run_id>/.codex-spawn-manifest.jsonl`. Codex Bash hooks block
heavy-step markers and `wave-complete` when required spawn evidence or
build wave `.spawn-count.json` is missing.

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

Invoke this skill as `$flow-runner`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Flow Runner — Checkpoint-Resume Test Execution

Execute Playwright flow tests with checkpoint persistence, resume from failure, deviation-classified fix loops, and evidence-backed assertions.

**Called by:** `/rtb:sandbox-test` Step 8.5b
**Input:** Test file path + checkpoint.json (if resuming)
**Output:** `.planning/phases/{phase}/{phase}-FLOW-RESULT.md`
**Checkpoint:** `.planning/phases/{phase}/checkpoints/{flow}.checkpoint.json`

## Context Budget

Read ONLY the test file and checkpoint.json. Do NOT read FLOW-SPEC, FLOW-REGISTRY, source code, or any other planning artifacts.

## Execution Flow

### Step 1: Check for Existing Checkpoint

```
checkpoint.json exists?
├── NO  → Fresh run (Step 2a)
└── YES → Resume mode (Step 2b)
```

### Step 2a: Fresh Run

Execute the full flow test via MCP Playwright (visible browser). For each step:

1. Execute action (click, fill, navigate)
2. Wait for condition (response, selector, text — NEVER timeout)
3. Run 3-layer assertion (UI + API + Data) + regression verify
4. Capture evidence (screenshot + console_messages + api_calls)
5. Save checkpoint with evidence
6. Handle CP type:
   - `auto-verify` → continue automatically
   - `human-verify` → pause, show screenshot, wait for user confirm
   - `human-action` → STOP, print instruction for user

### Step 2b: Resume Mode

1. Read `checkpoint.json` → find `resume_from` step
2. Login as `resume_context.logged_in_as` role
3. Navigate to `resume_context.current_page`
4. Verify `prior_data` matches current state:
   - Match → continue from failed step
   - Mismatch → fall back to previous checkpoint
   - No valid fallback → re-run from beginning
5. Continue execution from failed step onwards

### Step 3: On Step Failure — Fix Loop

Classify the failure using 4 rules, then apply fix:

**Rule 1: AUTO-FIX (test code bug)**
- Symptoms: selector not found, text mismatch, element position changed
- Action: Read MCP snapshot → update selector or expected text in test file → re-run step
- Example: Button renamed "Submit" → "Submit for Review"

**Rule 2: AUTO-ENHANCE (missing test logic)**
- Symptoms: timeout waiting for element, assertion incomplete, missing wait
- Action: Add `waitForResponse`, add missing assertion, add retry logic → re-run step
- Example: Missing wait for API response before checking badge text

**Rule 3: AUTO-RETRY (infra/transient)**
- Symptoms: page not loading, login timeout, network error, 502/503
- Action: Wait 10 seconds → retry step (max 2 retries per step)
- Example: VPS PM2 restart mid-test, nginx timeout

**Rule 4: ESCALATE (app bug)**
- Symptoms: API returns 4xx/5xx consistently, data unchanged after mutation, wrong state transition
- Action: STOP fix loop → report to user with full evidence bundle
- Example: POST /campaigns/:id/submit returns 403 due to incorrect RBAC rule

### Step 4: 3-Strike Escalation

```
Same step fails attempt 1 → Classify (Rules 1-4) → apply fix
Same step fails attempt 2 → Re-classify (may upgrade, e.g. Rule 1 → Rule 4) → apply
Same step fails attempt 3 → ESCALATE regardless of classification
  → Present: 3 screenshots, 3 error messages, 3 console logs
  → User decides: fix app code / skip step / abort flow

Different step fails → Reset attempt counter, continue normally
```

### Step 5: Resume Impossibility Rules

| Situation | Action |
|-----------|--------|
| Steps 1-2 fail (setup/login) | Re-run from beginning |
| prior_data verify fails (data corrupt) | Re-run from beginning, log warning |
| Role switch step fails | Re-run from step before the role switch |
| 3 resume attempts on same step | Escalate to human |

### Step 6: On All Steps Pass

1. Write `{phase}-FLOW-RESULT.md`:

```markdown
---
phase: {phase}
type: flow-result
tested: {ISO timestamp}
status: PASSED | GAPS_FOUND | FAILED
flows_tested: {N}
total_steps: {N}
passed: {N}
failed: {N}
skipped: {N}
fix_loop_iterations: {N}
---

# Flow Test Result: Phase {phase}

## Flow: {flow-name}
- Status: PASSED
- Steps: {passed}/{total}
- Duration: {seconds}s
- Fix iterations: {N}

### Step Results
| CP | Action | Status | Evidence |
|----|--------|--------|----------|
| CP-1 | {action} | PASSED | [screenshot](path) |

### Screenshots
| CP | File |
|----|------|
```

2. Clean up checkpoint.json (delete file — flow completed)
3. Report summary to orchestrator

## Evidence Requirement

**Every checkpoint — pass or fail — MUST include evidence. No evidence = no pass.**

| Status | Required | Missing evidence action |
|--------|----------|----------------------|
| passed | screenshot + console_errors (even empty []) + api_calls | Treat as unverified → re-run step |
| failed | screenshot + console_errors + error.message | Treat as unverified → re-run step |
| skipped | reason string | Accepted (unreachable steps only) |

## Auto-Mode

When `--auto` flag is set:
- `auto-verify` checkpoints → auto-pass (default behavior, no change)
- `human-verify` checkpoints → auto-approve (skip human confirmation)
- `human-action` checkpoints → still STOP (cannot be automated)

## Anti-Patterns

- NEVER skip evidence capture — "step passed" without screenshot is unverified
- NEVER fix app code from flow-runner — only fix test code (Rules 1-2). App bugs escalate (Rule 4).
- NEVER retry infinitely — max 2 retries for Rule 3 (transient), max 3 attempts total per step
- NEVER resume without verifying prior_data — stale data causes cascade false-failures
- NEVER delete checkpoint.json on failure — it's the resume mechanism
- NEVER continue after human-action checkpoint — wait for user instruction
