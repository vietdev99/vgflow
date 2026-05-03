---
name: "write-test-spec"
description: "Write comprehensive E2E test specifications for a phase — reads existing test docs (TEST-STRATEGY, BUSINESS-FLOW-SPECS, WIDE-VIEW-AUDIT), scans HTML prototypes for hidden modals, cross-references React+API, cross-AI verifies specs with Codex+Gemini+Sonnet"
metadata:
  short-description: "Write comprehensive E2E test specifications for a phase — reads existing test docs (TEST-STRATEGY, BUSINESS-FLOW-SPECS, WIDE-VIEW-AUDIT), scans HTML prototypes for hidden modals, cross-references React+API, cross-AI verifies specs with Codex+Gemini+Sonnet"
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

Invoke this skill as `$write-test-spec`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Skill: Write Test Spec

Create comprehensive E2E test specifications for a phase BEFORE coding begins.

**Pipeline position:** This runs BEFORE build, not after.

```
/write-test-spec {X}    <- Specs FIRST (this skill)
        |
/vg:build {X}           <- Code to pass specs
        |
/vg:test {X}            <- Run specs on target env
        |
/vg:accept {X}          <- Human UAT
```

## Arguments
```
/write-test-spec <phase>              -- Full spec for a phase
/write-test-spec <phase> --page <name> -- Spec for one page only
/write-test-spec <phase> --audit-only  -- Gap audit only, no spec output
```

## Process

### Step 0: Read Existing Test Documentation (MUST READ FIRST)

The project has a comprehensive test documentation system. Read ALL of these BEFORE writing anything.

**0a. TEST-STRATEGY.md — the foundation (CRITICAL):**

```bash
cat {config.paths.planning}/TEST-STRATEGY.md
```

This file contains:
- **Per-phase test audit** — what tests are ALREADY recommended for this phase
- **Specific test file names + test case descriptions** — don't reinvent, USE THESE
- **Critical Business Flows** — end-to-end paths that MUST be tested
- **Test conventions** — file structure, naming, patterns
- **Coverage targets** — per-app coverage requirements
- **Gaps sorted by severity** — CRITICAL, HIGH, MEDIUM

Extract the section for THIS phase. The recommended test files ARE the spec.

**0b. BUSINESS-FLOW-SPECS.md — the test methodology:**

```bash
cat {config.paths.phases}/BUSINESS-FLOW-SPECS.md
```

Defines:
- **Wide-View rule** — mandatory checklist per page visit
- **Data Validation Rules** — column headers, forbidden patterns, badges, dates, numbers
- **Business Flows** — step-by-step with field values, expected results
- **Session strategy** — seamless, no re-login
- **Helper functions** — assertTableColumns, assertTableDataValid, etc.

**0c. Phase-specific artifacts:**

```bash
PHASE_DIR=$(ls -d {config.paths.phases}/${PHASE}*)

cat "$PHASE_DIR"/CONTEXT.md         # Decisions (D-XX) -> each = test assertion
cat "$PHASE_DIR"/PLAN.md            # must_haves.truths -> each = test step
cat "$PHASE_DIR"/SPECS.md 2>/dev/null # Phase spec if exists
```

**0d. Existing test results and audits:**

```bash
cat {config.paths.planning}/TEST-REPORT-VI.md 2>/dev/null
cat "$PHASE_DIR"/SANDBOX-TEST.md 2>/dev/null
```

**0e. ROADMAP success criteria:**

```bash
grep -A 20 "Phase ${PHASE}" {config.paths.planning}/ROADMAP.md
```

**0f. Existing E2E infrastructure:**

```bash
ls {config.paths.flow_tests}/                # Which flow test files exist
cat {config.paths.e2e_tests}/helpers.ts      # Available helper functions
```

**0g. Build the Goal Matrix from ALL sources:**

Combine goals from: TEST-STRATEGY recommended tests + CONTEXT decisions + PLAN must_haves + ROADMAP criteria + BUSINESS-FLOW-SPECS overlapping flows.

```markdown
## Phase {X} Test Goals

### From TEST-STRATEGY.md (recommended test files for this phase)
| Test File | Test Cases | Already Implemented? |
|-----------|-----------|---------------------|
| {path from TEST-STRATEGY} | {test descriptions} | yes/no |

### From CONTEXT.md Decisions
| Decision | What to Test | Priority |
|----------|-------------|----------|
| D-XX | {assertion} | CRITICAL/HIGH |

### From PLAN must_haves
| Truth | Test Step | Covered? |
|-------|-----------|----------|

### From ROADMAP Success Criteria
| Criterion | Test Step | Covered? |
|-----------|-----------|----------|

### From BUSINESS-FLOW-SPECS (overlapping flows)
| Flow | Steps | Status |
|------|-------|--------|
| Flow {N} | Step {X.Y}-{X.Z} | extend/rewrite/new |
```

This goal matrix is the SPEC'S ACCEPTANCE CRITERIA. Every row must have a test by the end.

### Step 1: Identify Pages in Scope

From the goal matrix, determine which pages/features need testing.

Map each to its 3 sources:

| Feature | HTML Prototype | React Component | API Module |
|---------|---------------|-----------------|------------|
| (from plans) | html/.../*.html | {config.code_patterns.web_pages}/*.tsx | {config.code_patterns.api_routes}/* |

### Step 2: Deep HTML Scan (CRITICAL — hidden modals)

For each HTML page in scope, extract EVERYTHING including hidden elements.

**2a. Surface elements (visible):**
```bash
# Extract: tables, KPI cards, toolbar, buttons, tabs, nav
grep -n "class=\".*table\|<th\|<td\|card\|stat\|kpi\|btn\|button\|tab\|filter\|search\|dropdown" "$HTML_FILE"
```

**2b. Hidden modals (MUST NOT SKIP):**
```bash
# Find ALL modal-overlay or modal containers
grep -n "modal-overlay\|id=\".*[Mm]odal\|class=\".*modal" "$HTML_FILE"
```

For EACH modal found:
1. Read the full modal HTML (from modal-overlay to its closing div)
2. Extract modal title (`modal-title` or `h3`)
3. Extract ALL form fields inside:
   - `<input>` — name, type, placeholder, value
   - `<select>` — name, options (read ALL `<option>` tags)
   - `<textarea>` — name, placeholder
   - `<button>` — text, onclick action
4. Extract tables inside modals (columns, data patterns)
5. Extract tabs inside modals (tab names, tab panels)
6. Extract conditional sections (sections that show/hide based on state)

**2c. Hidden elements outside modals:**
```bash
# Elements with display:none, hidden attribute, or JS-controlled visibility
grep -n "display:none\|display: none\|hidden\|style=\".*visibility" "$HTML_FILE"
```

Check for:
- Dropdown menus with options list
- Tooltip content
- Inactive tab panels
- Conditional form sections (show/hide based on select value)
- Confirmation dialogs
- Context menus (right-click)

**2d. Inline JS event handlers:**
```bash
# Extract onclick, onchange, onsubmit handlers — they reveal hidden workflows
grep -n "onclick=\"\|onchange=\"\|onsubmit=\"" "$HTML_FILE" | head -30
```

Map each handler to the function it calls — that function often shows/hides modals or updates state.

### Step 3: React Component Audit

For each React component (.tsx) that implements the HTML page:

**3a. Columns config:** Look for `columns` array, `ColumnDef`, `createColumnHelper`. Extract exact header text.

**3b. Modal/Drawer components:** Look for `<Dialog>`, `<Modal>`, `<Sheet>`, `<Drawer>`, `useState(open/show/visible)`. Extract trigger, title, fields, submit.

**3c. KPI/Stat cards:** Look for `StatsCard`, `KpiCard`, grid patterns. Extract labels, value sources.

**3d. Form fields:** Look for `<Input>`, `<Select>`, `<Textarea>`, react-hook-form `register()`. Extract names, validation rules.

**3e. Query hooks:** Look for `useQuery`, `useMutation`. Extract endpoint URLs, methods, shapes.

### Step 4: Cross-Reference Gap Analysis (CRITICAL)

Build a comparison matrix for each page:

```markdown
## Gap Analysis: [PageName]

### Surface Widgets
| Widget | HTML Prototype | React Component | Status |
|--------|---------------|-----------------|--------|
| {widget} | {HTML detail} | {React detail} | OK / GAP: {what's missing} |

### Modals (field-level -- NOT modal-level)
| Modal | HTML fields | React fields | Missing |
|-------|------------|-------------|---------|
| {modal} | {count} | {count} | {list missing fields} |

### API Endpoints
| Action | HTML onclick | API Route | React Hook | Status |
|--------|-------------|-----------|------------|--------|
| {action} | {handler} | {route} | {hook} | OK / GAP |
```

### Step 5: Write Test Spec Document

Output: `{config.paths.phases}/{phase}/{phase}-TEST-SPEC.md`

**Structure per page:**

```markdown
---
phase: {phase}
type: test-spec
goals_from_context: {count D-XX decisions}
goals_from_roadmap: {count success criteria}
goals_from_business_flow: {count flow steps}
modals_found: {count}
modals_covered: {count}
gaps_found: {count}
---

# Test Spec: Phase {X} -- {Name}

## Goal Coverage Matrix
(copy from Step 0g -- every row must now have a test step filled in)

## Gap Summary
(from Step 4 -- sorted by severity)

## SESSION SETUP
| Session | Domain | Credentials | Start Page |
|---------|--------|-------------|------------|

## PAGE: {PageName}

### Wide-View Checklist
(h1, screenshot, KPI, toolbar, table columns, Rules 1-5, pagination, CTA, empty state)

### Modals -- ALL fields listed
(for EACH modal: trigger, title, every field with type/name/validation/test-value, tabs, submit, post-submit checks)

### Business Flow Steps
(session, page, wide-view check, action table, API verify, expected result, screenshot, save entityId)

### Data Validation Rules
(per column: which of Rules 1-5 apply, expected format, example)

### Screenshot Capture Points
(page load, modal open, after submit, before leave)

### Parallel Group Assignment
(A/B/C/D, session, mutation risk, run timing)
```

### Step 6: Verify Completeness

**6a. Goal matrix check:** Every row from Step 0g has a test step? Any uncovered goal = FAIL.

**6b. Modal coverage:** Every HTML modal has fields listed in spec? Missing modal = FAIL.

**6c. Field coverage:** Every `<input>`, `<select>`, `<textarea>` in HTML has a test value? Missing field = flag.

**6d. Action coverage:** Every `onclick` handler in HTML has a test step? Missing action = flag.

**6e. Table column coverage:** Every `<th>` in HTML has a column in assertTableColumns()? Missing column = flag.

### Step 7: Output Summary

```markdown
## Spec Complete

Phase: {X}
Goals covered: {G} (from CONTEXT + ROADMAP + BUSINESS-FLOW-SPECS)
Pages covered: {N}
Modals scanned: {M} (HTML) -> {M'} (React) -> {M''} gaps
Fields scanned: {F} (HTML) -> {F'} (React) -> {F''} gaps
Test steps: {S}
Assertions: {A}

### Implementation Gaps (code changes needed before tests pass)
{gaps that need new React components or API endpoints}

### Test Gaps (Playwright code needed)
{spec items that need test implementation}

### Deferred (out of phase scope per CONTEXT.md)
{explicitly excluded items}
```

### Step 8: Cross-AI Spec Verification (MANDATORY)

Specs MUST be verified by external AI CLIs (config.crossai_clis) before they're considered final.

**8a. Prepare review bundle:**

```bash
cat \
  {config.paths.phases}/${PHASE}/TEST-SPEC.md \
  {config.paths.phases}/${PHASE}/CONTEXT.md \
  {config.paths.phases}/${PHASE}/PLAN.md \
  > /tmp/spec-review-bundle.txt
```

**8b. Review prompt — goals + fields + modals:**

```
# Test Spec Review -- Adversarial Audit

Review this TEST SPEC for the project.
Cross-reference against CONTEXT.md decisions, PLAN must_haves, and BUSINESS-FLOW-SPECS goals.

## Check (in order of priority):
1. GOAL COVERAGE: Every D-XX decision -> has a test step?
2. MUST_HAVES: Every must_have truth -> has a test assertion?
3. SUCCESS CRITERIA: Every ROADMAP criterion -> has a verification point?
4. MODAL COMPLETENESS: Every modal field from HTML -> listed in spec?
5. WIDE-VIEW: Every page visit -> full checklist (KPI, toolbar, table, pagination)?
6. API CONTRACT: Every mutation -> watchApi + assertApiResponse?
7. DATA RULES: Every table -> Rules 1-5 applied?
8. CROSS-ROLE: Sessions seamless, no unnecessary re-login?

## Output: Verdict (PASS/GAPS_FOUND), gaps by severity, score X/10
```

**8c. Run CLIs in parallel (from config.crossai_clis):**

Each configured CLI reviews the bundle with the prompt. Commands use `{context}` and `{prompt}` placeholders.

**8d. Consensus matrix -> fix gaps -> re-verify (max 3 cycles).**

**8e. APPROVED when: average score >= 8/10 AND zero CRITICAL gaps.**

## Key Principles

1. **Goals first, HTML second** — read CONTEXT decisions + ROADMAP criteria BEFORE scanning HTML
2. **HTML is source of truth for UI** — if HTML has it and React doesn't, it's a gap
3. **Every modal MUST be tested** — hidden modals are the #1 source of missed coverage
4. **Every field inside every modal MUST be listed** — field-level, not modal-level
5. **Wide-view is mandatory** — no "click and check" without page-level validation first
6. **API contract must match** — form field name <> Zod schema key <> API response field
7. **Screenshots are evidence** — every state change gets captured
8. **Sessions are seamless** — no re-login between steps

## Anti-Patterns

- DO NOT skip Step 0 — jumping to HTML scan without reading CONTEXT/PLAN/ROADMAP = blind spec
- DO NOT write specs based on React only — you will miss hidden HTML modals
- DO NOT list modals at modal-level — list EVERY FIELD inside
- DO NOT skip inactive tabs inside modals — each tab panel has its own fields
- DO NOT assume select options — read ALL `<option>` tags from HTML
- DO NOT skip conditional form sections — Banner shows size dropdown, Native shows asset fields
