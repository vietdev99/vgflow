---
name: vg:design-extract
description: Extract design assets (HTML/PNG/Figma/PenBoard/Pencil) into PNG + structural refs for AI vision consumption
argument-hint: "[phase-or-all] [--paths=<glob>] [--no-states] [--refresh]"
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
Normalize any design format into AI-consumable visual + structural refs. Output at `{config.design_assets.output_dir}`:
  screenshots/{slug}.{state}.png      ← for Claude vision injection
  refs/{slug}.structural.{html|json|xml}  ← DOM/tree truth
  refs/{slug}.interactions.md         ← handler map (HTML only)
  manifest.json                        ← inventory for blueprint + build
</objective>

<available_agent_types>
- general-purpose — used for Haiku scanner prompt when Task tool spawns
</available_agent_types>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first. Confirm `design_assets` section exists.

<step name="0_validate_config">
Check `.claude/vg.config.md` has:
  - `design_assets.paths` (non-empty array)
  - `design_assets.output_dir`
  - `design_assets.handlers`
  - `design_assets.render_states` (bool)

Missing → BLOCK with guidance: "Run /vg:init or add design_assets section manually. See plan file for schema."
</step>

<step name="1_parse_args">
Parse `$ARGUMENTS`:
- Positional 1 → `SCOPE` (either "all" OR phase number to filter assets)
- `--paths=<glob>` → override config paths for this run
- `--no-states` → disable capture_states for HTML (faster, fewer screenshots)
- `--refresh` → delete output_dir first, redo from scratch

Defaults: SCOPE=all, capture_states=config.design_assets.render_states.
</step>

<step name="2_inventory">
## Layer 1 — Inventory (Opus orchestrator, cheap)

Collect all assets matching config.design_assets.paths (or --paths override).

```bash
OUTPUT_DIR="${config.design_assets.output_dir}"   # default ${PLANNING_DIR}/design-normalized
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
  HTML prototypes: {N}
  PNG/JPG images: {N}
  PenBoard (.pb):  {N}
  Pencil XML:      {N}
  Figma files:     {N}
  Total: {total}
  → Inventory: {OUTPUT_DIR}/inventory.json
```
</step>

<step name="3_normalize_layer2">
## Layer 2 — Per-asset normalize + deep scan (Haiku parallel)

For EACH asset in inventory, spawn 1 Haiku agent via Task tool.

**Parallelism:** up to `config.design_assets.max_parallel_haiku` (default 5).

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

The skill will:
  1. Call normalizer script → produce PNG + structural
  2. If HTML: read interactions.md + structural.html, enumerate modals/tabs/states
  3. Produce per-asset summary: what pages/states/modals discovered

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
      "screenshots": [
        "screenshots/{slug}.default.png",
        "screenshots/{slug}.trigger-2-add_new_site.png"
      ],
      "structural": "refs/{slug}.structural.html",
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
