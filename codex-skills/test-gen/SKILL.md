---
name: "test-gen"
description: "Generate TEST-SPEC.md from structured inputs (COMPONENT-MAP + DEPTH-INPUT) — supports --deepen mode for iterative refinement"
metadata:
  short-description: "Generate TEST-SPEC.md from structured inputs (COMPONENT-MAP + DEPTH-INPUT) — supports --deepen mode for iterative refinement"
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

Invoke this skill as `$test-gen`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Test Gen — Structured Spec Generation

Generate TEST-SPEC.md from COMPONENT-MAP.md + DEPTH-INPUT.md. No guessing — every test step traces back to a source (goal, user input, or CrossAI trace).

**Called by:** `/rtb:test-specs` Step 3
**Input:** `{phase}-COMPONENT-MAP.md` + `{phase}-DEPTH-INPUT.md`
**Output:** `.planning/phases/{phase}/{phase}-TEST-SPEC.md`

## Context Budget

Read ONLY COMPONENT-MAP.md and DEPTH-INPUT.md. Do NOT re-read source code, HTML prototypes, or planning artifacts — test-scan already extracted everything needed.

## Process

### 1. Load Structured Inputs

```bash
cat "${PHASE_DIR}/${PHASE}-COMPONENT-MAP.md"   # pages, components, modals, gaps, goals
cat "${PHASE_DIR}/${PHASE}-DEPTH-INPUT.md"      # business flows from user + CrossAI
```

### 2. Generate Per-Page Specs

For each page in COMPONENT-MAP:

**2a. Wide-View Checklist (mandatory per page):**
```
[ ] h1/title — match expected text
[ ] KPI/stat cards — visible, values not NaN/null/undefined
[ ] Toolbar — search + filters present
[ ] Table columns — match COMPONENT-MAP column list
[ ] Table data — no [object Object] / Invalid Date / undefined
[ ] Pagination — visible if applicable
[ ] Primary CTA — visible + enabled
[ ] Empty state — proper message if no data
[ ] Console errors — none unexpected
[ ] Screenshot — capture full page
```

**2b. Component specs by depth:**

| Depth | What to generate |
|-------|-----------------|
| SHALLOW | 1-2 assertions: exists + content correct |
| INTERACTIVE | 3-5 assertions: action + state change + UI update |
| DEEP | Full business flow from DEPTH-INPUT: every step + side effects + error states |

**2c. Modal specs (from COMPONENT-MAP modal inventory):**

For EVERY modal: list ALL fields with type, name, validation, test value.
Include: form submit assertions, error state assertions, close/cancel behavior.

**2d. DataTable row action specs:**

For EVERY row action from COMPONENT-MAP:
```
ACTION: Click [name] on table row
  OPENS: [component] (Modal/Drawer)
  READS: [fields from COMPONENT-MAP]
  CALLS: [secondary API if any]
  ASSERT: renders, no undefined, dates formatted, amounts formatted
```

### 3. Generate Business Flow Specs (from DEPTH-INPUT)

For each DEEP component with business flow trace:

```
## Business Flow: {component name}

### Happy Path
| Step | Action | Assert UI | Assert API | Assert Data |

### Error Paths (from DEPTH-INPUT error states)
| Error | Trigger | Expected UI | Expected API |

### Side Effects (from DEPTH-INPUT)
| Side Effect | Confidence | How to Verify |
| Send email  | HIGH (user) | Check notification list |
| Audit log   | CONFIRMED  | Check audit page |
| Schedule    | DISPUTED   | ⚠ Verify manually |
```

### 4. Source Tracing

Every test step MUST have a source reference:
```
<!-- Source: D-XX from CONTEXT.md -->
<!-- Source: User input for ApproveButton -->
<!-- Source: CrossAI trace CONFIRMED (2/3) -->
<!-- Source: HTML modal scan — adjustmentModal -->
```

This enables: when a spec seems wrong, trace back to WHY it was generated.

### 5. Write TEST-SPEC.md

```markdown
---
phase: {phase}
type: test-spec
goals_covered: {N}/{total}
pages: {N}
modals_covered: {N}/{found}
deep_components: {N}
user_inputs: {N}
crossai_traces: {N}
disputed_items: {N}
---
# Test Spec: Phase {X} — {Name}

## Session Setup
## Goal Coverage Matrix
## PAGE: {name}
  ### Wide-View Checklist
  ### Components (by depth)
  ### Modals
  ### Business Flows
  ### Error Paths
  ### Screenshot Capture Points
```

## --deepen Mode

When existing TEST-SPEC.md exists:

1. Read existing spec as baseline
2. Read NEW DEPTH-INPUT.md (user provided more context)
3. For each new finding in DEPTH-INPUT:
   - Check if already covered in existing spec → skip
   - New finding → append test steps with `<!-- Added by --deepen round {N} -->` marker
4. For DISPUTED items that user confirmed/denied in this round:
   - Confirmed → upgrade to full test steps
   - Denied → remove or mark as out-of-scope
5. Recalculate coverage metrics in frontmatter

**NEVER delete existing test steps during deepen** — only add or upgrade.

## Anti-Patterns
- DO NOT re-scan code — COMPONENT-MAP has everything. Re-scanning = context waste
- DO NOT guess business logic — if not in DEPTH-INPUT, it's not tested (add via --deepen later)
- DO NOT write test steps without source reference — every step must trace to a goal/input/trace
- DO NOT treat all components equally — SHALLOW gets 1 assertion, DEEP gets full flow
- DO NOT skip DISPUTED items — list them as flagged, user decides in --deepen
