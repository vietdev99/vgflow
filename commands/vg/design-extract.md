---
name: vg:design-extract
description: Extract design assets (HTML/PNG/Figma/PenBoard/Pencil) into PNG + structural refs for AI vision consumption
argument-hint: "[phase-or-all] [--paths=<glob>] [--no-states] [--refresh] [--shared]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "design_extract.started"
    - event_type: "design_extract.completed"
---

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

Layout under either tier:
  screenshots/{slug}.{state}.png      ← for Claude vision injection
  refs/{slug}.structural.{html|json|xml}  ← DOM/tree truth
  refs/{slug}.interactions.md         ← handler map (HTML only)
  manifest.json                        ← inventory for blueprint + build

Resolution order at consume time (blueprint/build/accept):
  1. `${PHASE_DIR}/design/...`        (Tier 1 — phase-scoped)
  2. `${config.design_assets.shared_dir}/...`  (Tier 2 — shared)
  3. `${config.design_assets.output_dir}/...`  (Tier 3 — legacy compat,
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
