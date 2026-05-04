---
name: "vg-crossai"
description: "Shared CrossAI engine for VG pipeline — spawns configured CLI agents (0-N from vg.config.md) for parallel review, verification, and test execution"
metadata:
  short-description: "Shared CrossAI engine for VG pipeline — spawns configured CLI agents (0-N from vg.config.md) for parallel review, verification, and test execution"
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

`vg-orchestrator` command shapes are positional. Use
`vg-orchestrator step-active <step_name>`,
`vg-orchestrator mark-step <namespace> <step_name>`, and
`vg-orchestrator emit-event <event_type> --payload '{...}'`. Do not use
`step-active <namespace> <step>`, `event --type`, or grouped helper calls
that mix tasklist projection with the first step marker.

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

Invoke this skill as `$vg-crossai`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# VG CrossAI Engine

Shared engine called internally by `/vg:*` commands. This skill is NOT invoked directly by the user — it provides the cross-AI orchestration layer that other VG commands delegate to when they need multi-CLI verification, review, or test execution.

The engine spawns 3 external CLI agents in parallel, collects their outputs, builds consensus, and returns structured XML results to the calling skill.

<modes>

## Modes

### `review-light`
- **Called by:** /rtb:discuss, /rtb:plan, /rtb:test-specs
- **Statefulness:** Stateless
- **Purpose:** Quick review of artifacts (plans, specs, discussion summaries). Each CLI gets the artifact text and a focused prompt. Results are collected and merged into a single consensus. No files are persisted beyond /tmp.

### `total-check`
- **Called by:** /rtb:crossai-check
- **Statefulness:** Stateless
- **Purpose:** Full quality gate. Reads the entire `.vg/phases/{X}/` directory — all plans, specs, context, and code references. Each CLI performs a comprehensive audit covering correctness, completeness, consistency, and architectural alignment. This is the heaviest mode and should only be triggered explicitly.

### `execute-verify`
- **Called by:** /rtb:execute after each wave
- **Statefulness:** Session-based — writes to `crossai/execute-verify-{wave}.xml`
- **Purpose:** Verifies code produced by each execution wave. Each CLI reviews the diff, checks against the plan, and flags deviations. Results accumulate across waves so the final report shows the full execution trajectory.

### `test-generate`
- **Called by:** /rtb:sandbox-test step 6
- **Statefulness:** Session-based — generates Playwright E2E test code from specs
- **Purpose:** Each CLI independently generates Playwright test code from TEST-SPEC.md. The engine then cross-references the 3 outputs, picks the best implementation per test case, and merges into a final test suite. Disputed approaches are flagged for human review.

### `test-run`
- **Called by:** /rtb:sandbox-test step 7
- **Statefulness:** Session-based — accumulates results across fix loops
- **Purpose:** Runs generated E2E tests on VPS, collects pass/fail results. On failure, each CLI proposes a fix. The engine picks the consensus fix and applies it. Results accumulate across fix loop iterations (max 3) so the final report shows the full fix history.

</modes>

<xml_output_format>

## XML Output Format

All modes produce output conforming to this schema:

```xml
<crossai_review>
  <meta>
    <mode>{mode}</mode>
    <phase>{phase_number}</phase>
    <timestamp>{ISO-8601}</timestamp>
    <session_dir>{path to crossai/ folder if session-based, "none" if stateless}</session_dir>
  </meta>
  <results>
    <cli source="codex" model="configured">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
    <cli source="gemini" model="pro-high-3.1">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
    <cli source="claude" model="sonnet-4.6">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
  </results>
  <consensus>
    <overall_verdict>pass|flag|block</overall_verdict>
    <average_score>{float}</average_score>
    <agreed_findings><!-- findings where 2+ CLIs agree --></agreed_findings>
    <disputed_findings><!-- findings where CLIs disagree — escalate to major --></disputed_findings>
    <auto_fixed><fix description="{what}" file="{path}" /></auto_fixed>
    <needs_human><issue description="{what}" severity="{level}" cli_sources="{who flagged}" /></needs_human>
  </consensus>
</crossai_review>
```

</xml_output_format>

<spawn_commands>

## Spawn Commands

Verified CLI commands for spawning each agent. Tested 2026-04-10 (codex 0.118.0, gemini 0.36.0, claude 2.1.98).

### Individual CLI Commands

**Codex (configured model):**
```bash
codex exec "$(cat {context_file})" > {output_path} 2>&1 &
```

**Gemini (Pro High 3.1):**
```bash
cat {context_file} | gemini -m gemini-2.5-pro -p "{prompt}" --yolo > {output_path} 2>&1 &
```

**Claude (Sonnet 4.6):**
```bash
cat {context_file} | claude --model sonnet -p "{prompt}" > {output_path} 2>&1 &
```

### Parallel Spawn Pattern

```bash
# Prepare context file
CONTEXT_FILE="/tmp/vg-crossai-${PHASE}-${MODE}-context.md"
OUTPUT_DIR="/tmp/vg-crossai-${PHASE}-${MODE}"
mkdir -p "$OUTPUT_DIR"

# Spawn all 3 CLIs in parallel
codex exec "$(cat $CONTEXT_FILE)" > "$OUTPUT_DIR/codex.out" 2>&1 &
PID_CODEX=$!

cat "$CONTEXT_FILE" | gemini -m gemini-2.5-pro -p "$PROMPT" --yolo > "$OUTPUT_DIR/gemini.out" 2>&1 &
PID_GEMINI=$!

cat "$CONTEXT_FILE" | claude --model sonnet -p "$PROMPT" > "$OUTPUT_DIR/claude.out" 2>&1 &
PID_CLAUDE=$!

# Wait for all to complete
wait $PID_CODEX $PID_GEMINI $PID_CLAUDE

# Collect results
echo "Codex exit: $?"
cat "$OUTPUT_DIR/codex.out"
cat "$OUTPUT_DIR/gemini.out"
cat "$OUTPUT_DIR/claude.out"
```

</spawn_commands>

<severity_routing>

## Severity Routing

### Severity Levels

| Severity | Action | Where Logged |
|----------|--------|-------------|
| **minor** | Auto-fix immediately, no user intervention | `<auto_fixed>` in consensus |
| **major** | Block progress, show to user, ask: fix / defer / re-discuss | `<needs_human>` in consensus |
| **critical** | Hard block, user MUST resolve before proceeding | `<needs_human>` with severity="critical" |

### Consensus Rules

- **2/3 CLIs agree** → use that severity level
- **3-way split** (all different) → escalate to **major**
- **Any single CLI says critical** → treat as **critical** regardless of other CLIs
- **All 3 say pass** → pass with no findings
- **Disputed findings** (CLIs disagree on existence or severity) → escalate to **major**, log in `<disputed_findings>`

</severity_routing>

<context_management>

## Context Management

### Stateless Modes (review-light, total-check)

- Write context to `/tmp/vg-crossai-{phase}-{mode}.md`
- Write CLI outputs to `/tmp/vg-crossai-{phase}-{mode}/`
- Parse outputs, build consensus XML, return to calling skill
- Clean up all `/tmp/vg-crossai-*` files after consensus is built
- No persistent artifacts — the calling skill decides what to save

### Session-Based Modes (execute-verify, test-generate, test-run)

- Write context and outputs to `.vg/phases/{X}/crossai/`
- File naming:
  - `execute-verify-{wave}.xml` — one file per execution wave
  - `test-generate.xml` — merged test suite with per-CLI attribution
  - `test-run-{iteration}.xml` — one file per fix loop iteration
- Keep all files for the next iteration (accumulated state)
- At session end, generate `CROSSAI-REPORT.md` summarizing:
  - Total findings across all iterations
  - Auto-fixed vs human-resolved breakdown
  - Final consensus verdict and score
  - Timeline of iterations with key events

</context_management>
