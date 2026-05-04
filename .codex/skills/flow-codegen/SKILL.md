---
name: "flow-codegen"
description: "Generate Playwright flow test files from FLOW-SPEC.md — condition-based waits, checkpoint saves, role switches, resume logic, two-stage CrossAI review"
metadata:
  short-description: "Generate Playwright flow test files from FLOW-SPEC.md — condition-based waits, checkpoint saves, role switches, resume logic, two-stage CrossAI review"
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

Codex hook processes cannot mutate the environment of later shell tool calls.
If a command-body shell lacks `CLAUDE_SESSION_ID`, `vg-orchestrator` recovers
the session from `.vg/.session-context.json` and the matching
`.vg/active-runs/<session>.json`. Do not create a fresh run when the
UserPromptSubmit hook already registered the same command/phase.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

Run fenced command-body shell snippets with Bash explicitly, for example
`/bin/bash -lc '<snippet>'`, instead of the user's login shell. VGFlow source
commands use Bash semantics such as `[[ ... ]]`, arrays, `BASH_SOURCE`, and
`set -u`; zsh can misinterpret those snippets and create false failures.

Do not manually retype long command-body heredocs into nested shell strings.
Prefer deterministic Codex helpers shipped in `.claude/scripts/`. For
`/vg:blueprint` STEP 3.1, run `codex-vg-env.py` and
`codex-blueprint-plan-prep.py` exactly as documented in
`_shared/blueprint/plan-overview.md`; then spawn the planner from the prepared
prompt. This avoids zsh glob/quote expansion corrupting Python heredocs before
Bash executes them.

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

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

For tasklist projection, Codex must write evidence as soon as
`tasklist-contract.json` exists: after `emit-tasklist.py`, run
`vg-orchestrator tasklist-projected --adapter codex` as its own tool call.
Do not group `tasklist-projected` and `step-active` in one shell command;
PreToolUse evaluates the entire command before the evidence file exists and
will block the grouped command. Some command preflights have bootstrap steps
before `emit-tasklist.py`; only those declared bootstrap steps may run before
the tasklist contract exists.

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

When creating prompt files for `codex-spawn.sh`, use a single-quoted heredoc
delimiter such as `cat > "$PROMPT_FILE" <<'EOF'` or write from an existing
template. Do not use unquoted `<<EOF` for prompts that contain backticks,
`$...`, command substitutions, or markdown code fences: the shell will
expand them before Codex sees the prompt and can corrupt the child contract.
If runtime variables must be injected, prefer a small controlled render step
that substitutes placeholders after the quoted template is written.

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

Invoke this skill as `$flow-codegen`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Flow Codegen — Playwright Test Generation

Generate Playwright test files from FLOW-SPEC.md with condition-based waits, checkpoint persistence, role switch logic, and resume entry points.

**Called by:** `/rtb:sandbox-test` Step 8.5a
**Input:** ONLY `{phase}-FLOW-SPEC.md`
**Reference:** `apps/web/e2e/helpers.ts` (import list only — do NOT read implementation)
**Output:** `apps/web/e2e/flows/{phase}-{flow-name}.flow.spec.ts`

## Context Budget

Read FLOW-SPEC.md only. Do NOT read source code, FLOW-REGISTRY, CONTEXT, PLAN, or any other planning artifacts.

## Process

### Step 1: Read FLOW-SPEC.md

Parse all flows with their step sequences, mutation assertions, role switch points, and checkpoint types.

### Step 2: Generate Test File (per flow)

For each flow, create `apps/web/e2e/flows/{phase}-{flow-name}.flow.spec.ts` with:

**File scaffold:**
```typescript
import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

// Checkpoint directory — set by orchestrator via environment or config
// RTB: .planning/phases/{phase}/checkpoints
// VG: ${PHASES_DIR}/{phase}/checkpoints (from vg.config.md)
const CHECKPOINT_DIR = process.env.FLOW_CHECKPOINT_DIR || '.planning/phases/{phase}/checkpoints';
const CHECKPOINT_FILE = path.join(CHECKPOINT_DIR, '{flow-name}.checkpoint.json');

// Credentials — loaded from config or environment
// Orchestrator should set these from credentials config (rtb: _shared/credentials.md, vg: vg.config.md)
const CREDENTIALS = JSON.parse(process.env.FLOW_CREDENTIALS || '{}');
// Fallback structure: { roleName: { email, password, domain } }

test.describe('{Flow Name} — Multi-Page Flow', () => {
  // ... steps generated below
});
```

**Per step — use these EXACT patterns based on step type:**

**Mutation step (POST/PUT/DELETE):**
```typescript
await test.step('CP-{N}: {Action}', async () => {
  const [response] = await Promise.all([
    page.waitForResponse(resp =>
      resp.url().includes('{api-endpoint}') &&
      resp.request().method() === '{METHOD}' &&
      resp.status() < 400
    ),
    page.getByRole('button', { name: '{button-text}' }).click()
  ]);

  // UI Assert
  await expect(page.getByTestId('{indicator}')).toHaveText('{expected}');
  // Regression — old state GONE
  await expect(page.getByText('{old-state}')).not.toBeVisible();
  // API Assert
  const console = await page.evaluate(() => /* console error check */);
  expect(console.filter(m => /[45]\d{2}/.test(m))).toHaveLength(0);
  // Data Assert
  const data = await page.request.get('{verify-endpoint}');
  expect((await data.json()).{field}).toBe('{expected-value}');

  saveCheckpoint('CP-{N}', 'passed', '{cp-type}', { /* snapshot */ });
  await page.screenshot({ path: 'apps/web/e2e/screenshots/{phase}-{flow}-CP{N}.png' });
});
```

**Navigation step:**
```typescript
await test.step('CP-{N}: Navigate to {page}', async () => {
  await page.goto('{url}');
  await page.waitForSelector('{main-content-selector}');
  // Wide-view assertions as needed
  saveCheckpoint('CP-{N}', 'passed', 'auto-verify', {});
});
```

**Role switch step:**
```typescript
await test.step('CP-{N}: Switch to {role}', async () => {
  const {role}Context = await browser.newContext();
  const {role}Page = await {role}Context.newPage();
  await {role}Page.goto('/login');
  await {role}Page.fill('[name="email"]', CREDENTIALS.{role}.email);
  await {role}Page.fill('[name="password"]', CREDENTIALS.{role}.password);
  await {role}Page.getByRole('button', { name: 'Sign In' }).click();
  await {role}Page.waitForSelector('[data-page="dashboard"]');

  saveCheckpoint('CP-{N}', 'passed', 'human-verify', {});
  await {role}Page.screenshot({ path: '.../{phase}-{flow}-CP{N}-role-switch.png' });
});
```

### Step 3: Generate Checkpoint Helper

```typescript
function saveCheckpoint(stepId: string, status: string, cpType: string, snapshot: object) {
  if (!fs.existsSync(CHECKPOINT_DIR)) fs.mkdirSync(CHECKPOINT_DIR, { recursive: true });
  const cp = fs.existsSync(CHECKPOINT_FILE)
    ? JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf-8'))
    : { flow: '{flow}', phase: '{phase}', steps: {} };

  cp.steps[stepId] = {
    status, cp_type: cpType,
    timestamp: new Date().toISOString(),
    evidence: { screenshot: `{phase}-{flow}-${stepId}.png`, console_errors: [], api_calls: [] },
    snapshot
  };
  cp.updated_at = new Date().toISOString();
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify(cp, null, 2));
}
```

### Step 4: Generate Resume Entry Point

```typescript
test.beforeAll(async ({ browser }) => {
  if (!fs.existsSync(CHECKPOINT_FILE)) return; // fresh run

  const cp = JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf-8'));
  if (!cp.resume_from) return;

  // Login as the role at resume point
  const role = cp.resume_context.logged_in_as;
  // Navigate to saved page
  // Verify prior_data matches current state
  // If mismatch → clear checkpoint, force fresh run
});
```

### Step 5: CrossAI Two-Stage Review

**Stage 1 — Spec Compliance** (runs first):
Prompt the 3 CLIs: "Given FLOW-SPEC.md, verify generated test covers: every step in Step Sequence, every mutation assertion (3-layer), every role switch, every checkpoint save, every wait condition matches spec."
- Verdict: COMPLIANT / GAPS

**Stage 2 — Code Quality** (only if Stage 1 passes):
Prompt the 3 CLIs: "Review Playwright test for: no waitForTimeout, selectors use role/testid not CSS class, descriptive error messages, checkpoint evidence objects complete, role switch uses newContext."
- Verdict: QUALITY_PASS / ISSUES

## Anti-Patterns

- NEVER use `waitForTimeout` or `page.waitForTimeout(ms)` — always condition-based waits
- NEVER use CSS class selectors (`.btn-primary`) — use `getByRole`, `getByTestId`, `getByText`
- NEVER skip checkpoint save — every step must persist state for resume
- NEVER skip evidence capture — screenshot + console required even for passing steps
- NEVER hardcode credentials inline — use CREDENTIALS constant object
- NEVER re-login between steps unless role switch — session persists across steps
