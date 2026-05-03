---
name: "vg-design-extract"
description: "Extract design assets (HTML/PNG/Figma/PenBoard/Pencil) into PNG + structural refs for AI vision consumption"
metadata:
  short-description: "Extract design assets (HTML/PNG/Figma/PenBoard/Pencil) into PNG + structural refs for AI vision consumption"
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

Invoke this skill as `$vg-design-extract`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<rules>
1. **Config required** — `design_assets` section in `.claude/vg.config.md`. Missing = BLOCK.
2. **Screenshot-first** — AI vision consumes PNG directly, not markdown prose description.
3. **No translation layer** — normalize → raw source (PNG + cleaned HTML/structural) → executor sees truth.
4. **4-layer Haiku scan** — inventory → per-page normalize + deep scan → adversarial gap hunt → Opus merge.
5. **One-time per project** — re-run with `--refresh` if assets change.
6. **Zero hardcode** — all paths + handlers from config.
</rules>

<objective>
Normalize any design format into AI-consumable visual + structural refs.

**v2.30.0 — 2-tier output:**
- **Phase-scoped** (default when invoked with phase number) → `${PHASE_DIR}/design/`
  Each phase owns its mockups; isolation prevents cross-phase contamination.
- **Project-shared** (with `--shared` flag, or scope=all without phase) →
  `${config.design_assets.shared_dir}` (default `.vg/design-system/`).
  For brand foundations / design system / cross-phase components.

Compatibility: consumers also read legacy raw scaffold PNGs from
`${PHASE_DIR}/designs/` as a fallback, but new scaffold/extract writes use
`${PHASE_DIR}/design/` so build and review resolve the same phase-local root.

Layout under either tier:
  screenshots/{slug}.{state}.png      ← for Claude vision injection
  refs/{slug}.structural.{html|json|xml}  ← DOM/tree truth
  refs/{slug}.interactions.md         ← handler map (HTML only)
  manifest.json                        ← inventory for blueprint + build

Resolution order at consume time (blueprint/build/accept):
  1. `${PHASE_DIR}/design/...`        (Tier 1 — phase-scoped)
  2. `${PHASE_DIR}/designs/...`       (Tier 1b — raw scaffold fallback)
  3. `${config.design_assets.shared_dir}/...`  (Tier 2 — shared)
  4. `${config.design_assets.output_dir}/...`  (Tier 3 — legacy compat,
                                                soft-deprecated for 2 releases)
</objective>

<available_agent_types>
- general-purpose — used for Haiku scanner prompt when Task tool spawns
</available_agent_types>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first. Confirm `design_assets` section exists.

<step name="0_validate_config">
Check `.claude/vg.config.md` has:
  - `design_assets.paths` (non-empty array)
  - `design_assets.shared_dir` (v2.30+; falls back to `output_dir` for compat)
  - `design_assets.handlers`
  - `design_assets.render_states` (bool)

Missing → BLOCK with guidance: "Run /vg:init or add design_assets section manually. See plan file for schema."
</step>

<step name="1_parse_args">
Parse `$ARGUMENTS`:
- Positional 1 → `SCOPE` (either "all" OR phase number to filter assets)
- `--paths=<glob>` → override config paths for this run
- `--no-states` → disable capture_states for HTML (faster, fewer screenshots)
- `--refresh` → delete the resolved write-target dir first, redo from scratch
- `--shared` (v2.30+) → write to project-shared dir (`design_assets.shared_dir`)
                        instead of phase-scoped. Use for design-system / brand
                        foundations / cross-phase components.

Defaults: SCOPE=all, capture_states=config.design_assets.render_states.

**Write-target dispatch (v2.30+):**
- `SCOPE` is a phase number AND `--shared` not set → `${PHASE_DIR}/design/`
- `SCOPE=all` OR `--shared` set → `${config.design_assets.shared_dir}` (default
  `.vg/design-system/`)

This dispatch happens in step 2 below — `OUTPUT_DIR` resolves accordingly.
</step>

<step name="2_inventory">
## Layer 1 — Inventory (Opus orchestrator, cheap)

Collect all assets matching config.design_assets.paths (or --paths override).

```bash
# v2.30+ 2-tier resolver — dispatch by --shared flag + SCOPE (phase number)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/design-path-resolver.sh"

if [ "$WRITE_SCOPE" = "shared" ] || [ "$SCOPE" = "all" ]; then
  # Project-shared dir (design system, cross-phase components)
  OUTPUT_DIR="$(vg_resolve_design_dir "" shared)"
elif [ -n "$SCOPE" ] && [ "$SCOPE" != "all" ]; then
  # Phase-scoped dir — locate phase dir from SCOPE (phase number)
  PHASE_DIR_FOR_DESIGN="$(find_phase_dir "$SCOPE" 2>/dev/null || echo ".vg/phases/${SCOPE}")"
  OUTPUT_DIR="$(vg_resolve_design_dir "$PHASE_DIR_FOR_DESIGN" phase)"
else
  # Fallback — shared dir
  OUTPUT_DIR="$(vg_resolve_design_dir "" shared)"
fi

echo "▸ Design extract write-target: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# Resolve normalizer script path — portable across machines/CI
# Orchestrator MUST resolve to absolute BEFORE spawning Haiku agents
# (Haiku agents may run with different cwd; absolute path is required)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
NORMALIZER_SCRIPT="${REPO_ROOT}/.claude/scripts/design-normalize.py"

if [ ! -f "$NORMALIZER_SCRIPT" ]; then
  echo "⛔ Normalizer missing: $NORMALIZER_SCRIPT"
  echo "   Run: ./vgflow/install.sh .  (reinstalls scripts)"
  exit 1
fi

# Glob each pattern, dedupe
# (config patterns may be relative to repo root or absolute)
# Build ASSETS=[ {path, handler, slug} ... ]
```

For each asset: determine `handler` by extension via config.design_assets.handlers mapping.
Generate `slug` from path (filesystem-safe).

Write `{OUTPUT_DIR}/inventory.json`:
```json
{
  "scope": "all|phase-X",
  "generated_at": "ISO",
  "total_assets": N,
  "by_handler": {"playwright_render": N, "passthrough": N, "penboard_render": N, ...},
  "assets": [ { "path": "...", "handler": "...", "slug": "..." } ]
}
```

Display:
```
Design Inventory — Phase {SCOPE}
  HTML prototypes:           {N}
  PNG/JPG images (default):  {N}
  PNG (.structural.png OCR): {N}    ← Phase 15 D-01 — opt-in marker triggers OCR pipeline
  PenBoard legacy (.pb):     {N}
  PenBoard MCP (.penboard/.flow):  {N}   ← Phase 15 D-01 — live workspace via mcp__penboard__*
  Pencil legacy (.xml):      {N}
  Pencil MCP (.pen):         {N}    ← Phase 15 D-01 — encrypted file via mcp__pencil__*
  Figma files:               {N}
  Total: {total}
  → Inventory: {OUTPUT_DIR}/inventory.json
```
</step>

<step name="3_normalize_layer2">
## Layer 2 — Per-asset normalize + deep scan (Haiku parallel)

For EACH asset in inventory, spawn 1 Haiku agent via Task tool.

**Parallelism:** up to `config.design_assets.max_parallel_haiku` (default 5).

### Phase 15 D-01 — MCP delegation pattern (handler ∈ {pencil_mcp, penboard_mcp})

Pencil `.pen` files are ENCRYPTED (only readable via `mcp__pencil__*`); Penboard
`.penboard`/`.flow` workspaces are MCP-managed. Python normalizer subprocess
**cannot call MCP tools directly** (those are AI-context tools).

For these handlers, Haiku scanner MUST run in **2-step extraction**:

**Step A (MCP extraction — AI tool calls):**
- For `pencil_mcp`:
  ```
  mcp__pencil__open_document(asset.path)
  state = mcp__pencil__get_editor_state
  nodes = mcp__pencil__batch_get(<root pattern>)
  boxes = mcp__pencil__export_nodes(state.selectedNodeIds or all)
  png   = mcp__pencil__get_screenshot
  → Save combined as JSON to {OUTPUT_DIR}/.tmp/{slug}.pencil-raw.json
  → Save png to {OUTPUT_DIR}/.tmp/{slug}.pencil-screenshot.png
  ```
- For `penboard_mcp`:
  ```
  flows      = mcp__penboard__list_flows
  flow_data  = [mcp__penboard__read_flow(f.name) for f in flows]
  docs       = [mcp__penboard__read_doc(...) for each doc id]
  entities   = mcp__penboard__manage_entities({operation: 'list'})
  conns      = mcp__penboard__manage_connections({operation: 'list'})
  preview    = mcp__penboard__generate_preview(...)
  → Save combined as JSON to {OUTPUT_DIR}/.tmp/{slug}.penboard-raw.json
  → Save preview png to {OUTPUT_DIR}/.tmp/{slug}.penboard-preview.png
  ```

**Step B (normalizer subprocess):**
Call normalizer with same args as other handlers. Python handler reads pre-saved
raw + screenshot from `.tmp/`, converts to canonical `structural-json.v1.json`,
copies screenshot to `screenshots/{slug}.default.png`. If raw missing → handler
returns error (Step A did not complete).

**Cleanup:** `.tmp/` artifacts may be deleted by Layer 4 merge after manifest
finalization (kept by default for debugging — gitignore the path).

### Standard handlers (HTML, PNG passthrough/OCR, legacy XML/PB, Figma)

Haiku invokes normalizer directly (1-step):

**Haiku prompt (fixed, no discretion):**
```
Read skill: vg-design-scanner (at .claude/skills/vg-design-scanner/SKILL.md)
Follow exactly. Inject these args:

  ASSET_PATH   = "{asset.path}"
  SLUG         = "{asset.slug}"
  HANDLER      = "{asset.handler}"
  OUTPUT_DIR   = "{config.design_assets.output_dir}"
  CAPTURE_STATES = {true|false from --no-states flag}
  NORMALIZER_SCRIPT = "${NORMALIZER_SCRIPT}"  (absolute — orchestrator resolves before Haiku spawn)
  MCP_DELEGATION = {true if handler ∈ {pencil_mcp, penboard_mcp} else false}

The skill will:
  1. If MCP_DELEGATION: run Step A (MCP tool calls + save raw to .tmp/) FIRST
  2. Call normalizer script → produce PNG + structural (or convert MCP raw → structural)
  3. If HTML: read interactions.md + structural.html, enumerate modals/tabs/states
  4. Produce per-asset summary: what pages/states/modals discovered

Output: {OUTPUT_DIR}/scans/{slug}.scan.json
Do NOT invent content. ONLY consume normalizer output.
```

Wait for all Haiku to complete. Collect `{OUTPUT_DIR}/scans/*.scan.json`.
</step>

<step name="4_adversarial_layer3">
## Layer 3 — Adversarial gap hunter (Haiku 2nd pass per asset)

For EACH asset where Layer 2 flagged warnings OR has interactions (likely complex):

Spawn adversarial Haiku:
```
Read skill: vg-design-gap-hunter (at .claude/skills/vg-design-gap-hunter/SKILL.md)
Follow exactly. Inject:

  ASSET_PATH      = "{asset.path}"
  LAYER2_SCAN     = "{OUTPUT_DIR}/scans/{slug}.scan.json"
  LAYER2_STRUCT   = "{OUTPUT_DIR}/refs/{slug}.structural.*"
  LAYER2_INTERACT = "{OUTPUT_DIR}/refs/{slug}.interactions.md"
  OUTPUT_DIR      = "{OUTPUT_DIR}"
  SLUG            = "{slug}"

Job: FIND what Layer 2 missed. Specifically check:
  - Modals/dialogs/drawers not captured in states
  - Tabs not enumerated  
  - Hidden elements in JS not extracted
  - Form fields not listed
  - Conditional renders missed

Output: {OUTPUT_DIR}/scans/{slug}.gaps.json
```

If gaps.count > 0 AND iteration < 2: spawn Layer 2 again with gap focus. Max 2 retries.
</step>

<step name="5_merge_layer4">
## Layer 4 — Consolidate (Opus)

For each asset, merge Layer 2 scan + Layer 3 gaps → canonical per-asset ref.

Aggregate to `{OUTPUT_DIR}/manifest.json`:
```json
{
  "version": "1",
  "generated_at": "ISO",
  "scope": "all|phase-X",
  "total_assets": N,
  "by_handler": {...},
  "assets": [
    {
      "path": "...",
      "slug": "...",
      "handler": "...",
      "mcp_handler_used": false,   // Phase 15 D-01 — true for pencil_mcp/penboard_mcp; false for legacy + HTML/PNG
      "screenshots": [
        "screenshots/{slug}.default.png",
        "screenshots/{slug}.trigger-2-add_new_site.png"
      ],
      "structural": "refs/{slug}.structural.html",     // legacy: path to .html/.xml/.pb-derived
      "structural_json": "refs/{slug}.structural.json", // Phase 15 D-01 — AST/box-list per structural-json.v1.json (HTML cheerio + PNG OCR + Pencil/Penboard MCP)
      "interactions": "refs/{slug}.interactions.md",
      "pages": [...],           // PenBoard only
      "modals_discovered": [...],
      "forms_discovered": [...],
      "tabs_discovered": [...],
      "warnings": [...],
      "gaps_found_in_l3": [...]
    }
  ]
}
```

**Cross-check with phase plan (if SCOPE is specific phase):**
- Read `${PHASE_DIR}/PLAN*.md` tasks
- Check: task mentions a page → does that page have asset in manifest?
- Task without asset reference → flag for `/vg:blueprint` step 2b4 to link later
</step>

<step name="6_report">
Display summary:
```
Design extraction complete.
  Assets processed: {total} ({ok} OK, {fail} failed)
  Screenshots:      {N}
  Structural refs:  {N}
  Interactions:     {N} (HTML assets)
  Warnings:         {N}
  Gaps caught L3:   {N}

Output: {OUTPUT_DIR}/
  screenshots/   ({N} PNGs)
  refs/          ({N} structural + {M} interactions)
  scans/         (per-asset scan JSONs)
  manifest.json  (inventory + cross-links)

Next:
  1. Commit {OUTPUT_DIR}/ (gitignore screenshots/ if size > 50MB)
  2. /vg:scope {phase}   (will auto-detect design-refs)
  3. /vg:blueprint {phase}  (step 2b4 links plan tasks to design-refs)
```
</step>

<step name="complete">
Commit artifacts:
```bash
# Gitignore screenshots if too large (keep refs + manifest)
if [ $(du -sm "$OUTPUT_DIR/screenshots" 2>/dev/null | cut -f1) -gt 50 ]; then
  echo "$OUTPUT_DIR/screenshots/" >> .gitignore
fi

git add "$OUTPUT_DIR/inventory.json" "$OUTPUT_DIR/manifest.json" "$OUTPUT_DIR/refs/" "$OUTPUT_DIR/scans/"
[ -d "$OUTPUT_DIR/screenshots" ] && git add "$OUTPUT_DIR/screenshots/"

git commit -m "feat(design-extract): normalize {total} design assets → AI-consumable refs"
```
</step>

</process>

<success_criteria>
- `design_assets` config validated
- All assets in scope inventoried
- Each asset normalized (screenshot + structural, OR warning with clear next step)
- Layer 3 adversarial pass caught > 0 gaps OR confirmed Layer 2 complete
- Manifest.json aggregates all → downstream `/vg:blueprint` can consume
- Git commit clean (optionally gitignore large screenshots/)
</success_criteria>
