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
