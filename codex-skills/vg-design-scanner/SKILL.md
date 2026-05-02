---
name: "vg-design-scanner"
description: "Normalize one design asset + deep-scan for modals/states/forms — workflow followed by Haiku agents spawned from /vg:design-extract Layer 2."
metadata:
  short-description: "Normalize one design asset + deep-scan for modals/states/forms — workflow followed by Haiku agents spawned from /vg:design-extract Layer 2."
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

Invoke this skill as `$vg-design-scanner`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



# Design Scanner — Layer 2 Haiku Workflow

You are a scanner agent spawned by `/vg:design-extract`. Your ONLY job: normalize ONE design asset + extract everything AI needs to know about it.

## Arguments (injected by orchestrator)

```
ASSET_PATH        = "{absolute path to design file}"
SLUG              = "{filesystem-safe slug}"
HANDLER           = "playwright_render | passthrough | penboard_render | pencil_xml | figma_fallback"
OUTPUT_DIR        = "{absolute output directory, e.g. .vg/design-normalized}"
CAPTURE_STATES    = {true|false}
NORMALIZER_SCRIPT = "{absolute path to design-normalize.py}"
```

## WORKFLOW — FOLLOW EXACTLY

### STEP 1: Run normalizer

```bash
python "{NORMALIZER_SCRIPT}" "{ASSET_PATH}" \
  --output "{OUTPUT_DIR}" \
  --slug "{SLUG}" \
  {--states if CAPTURE_STATES}
```

Capture exit code + stdout.

If exit != 0:
  → Record error in scan.json
  → Write `{OUTPUT_DIR}/scans/{SLUG}.scan.json` with `{"error": "...", "handler": "..."}`
  → Exit gracefully (don't retry — higher layers handle)

### STEP 2: Read normalizer manifest for this asset

```bash
cat {OUTPUT_DIR}/manifest.json  # or re-read from normalizer output
```

Extract the entry for this SLUG. Fields:
  - screenshots[]
  - structural (path to HTML/JSON/XML)
  - interactions (path to .md, HTML only)
  - warning (if present)

### STEP 3: Deep read structural + interactions (handler-specific)

**IF HANDLER == "playwright_render" (HTML):**

Read `refs/{SLUG}.structural.html`:
- Grep `<script>` blocks count
- Grep `onclick=`, `onchange=`, `addEventListener` count
- Grep `class="..modal..|..dialog..|..popup..|..drawer.."`
- Grep `style="display:none" | hidden`
- Grep `<form>` count
- Grep `<input>` count (incl. hidden)
- Grep `role="tab" | class="..tab.."`

Read `refs/{SLUG}.interactions.md`:
- Count inline handlers
- Count triggers
- List function names that appear multiple times (likely open/close modal pairs)

Infer discovered entities:
- Modals: function names matching `open.*Modal|open.*Dialog|show.*Dialog`
- Forms: `<form>` groups + submit-bound handlers
- Tabs: `[role="tab"]` OR `.tab-*` classes
- Dynamic sections: onclick-triggered DOM mutations

**IF HANDLER == "penboard_render":**

Read `refs/{SLUG}.structural.json`:
- List pages with name, id
- Count nodes per page
- Identify special node types: frame, text, input, button (based on `type` field)
- Check `connections` for page-to-page transitions
- Check `dataEntities` for data bindings

**IF HANDLER in (passthrough, pencil_xml, figma_fallback):**
- Minimal scan: record screenshot path + any warning from normalizer
- No deep extraction (static image or unparsable proprietary format)

### STEP 4: Write per-asset scan

Write to `{OUTPUT_DIR}/scans/{SLUG}.scan.json`:

```json
{
  "slug": "{SLUG}",
  "handler": "{HANDLER}",
  "asset_path": "{ASSET_PATH}",
  "scanned_at": "{ISO}",
  "normalizer_result": {
    "screenshots": [...],
    "structural": "refs/{SLUG}.structural.html",
    "interactions": "refs/{SLUG}.interactions.md"
  },
  "summary": {
    "script_blocks": 0,
    "inline_handlers": 0,
    "addEventListener_calls": 0,
    "modals_hinted": 0,
    "forms_count": 0,
    "inputs_count": 0,
    "tabs_count": 0,
    "hidden_elements": 0,
    "states_captured": 0
  },
  "modals_discovered": [
    {"name": "openAddSiteModal", "trigger_count": 3, "trigger_text": ["Add New Site", "..."]}
  ],
  "forms_discovered": [
    {"id": "...", "field_count": 5, "submit_handler": "..."}
  ],
  "tabs_discovered": [
    {"label": "Sites", "panel_id": "..."}
  ],
  "pages": [                   // PenBoard only
    {"id": "page-1", "name": "Login", "node_count": 15}
  ],
  "warnings": [],
  "next_steps": [              // what Layer 3 should verify
    "Verify all modal open/close pairs",
    "Check forms submit targets",
    "List hidden elements not in state screenshots"
  ]
}
```

## HARD RULES

- Run normalizer ONCE. Don't retry on error (Layer 3 handles gaps).
- READ output files; don't invent summary numbers.
- If structural file missing → record error, don't fabricate summary.
- Keep scan.json compact (<10KB). Don't inline full HTML or interactions content.
- References ONLY — AI consuming scan.json should `@` path to actually read content.

## OUTPUT CONTRACT

Exit successfully ONLY when:
- `{OUTPUT_DIR}/scans/{SLUG}.scan.json` written
- Normalizer outputs present at expected paths (or warning field explains absence)

Exit with error (for Layer 3 retry decision) when:
- Normalizer fails AND no structural available
- Structural file unreadable
