---
name: vg:design-scaffold
description: "Scaffold UI mockups for greenfield projects — multi-tool selector (Pencil MCP / PenBoard MCP / AI HTML / Claude design / Stitch / v0 / Figma / manual). Output drops into the phase-local design directory for /vg:design-extract."
argument-hint: "[--tool=<name>] [--pages=<list>] [--interactive] [--refresh] [--dry-run] [--help-tools]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Task
  - SlashCommand
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "design_scaffold.started"
    - event_type: "design_scaffold.completed"
---

<rules>
1. **Greenfield on-ramp** — closes the upstream gap exposed by Phase 19. Without scaffold, projects with zero mockups bypass every L1-L6 gate via Form B.
2. **Tool selector** — user-driven via AskUserQuestion or `--tool=<name>` flag. Default recommendation: `pencil-mcp` (free + automated + binary output ideal for downstream gates).
3. **Files converge** — every tool produces files at `$(vg_resolve_design_dir "$PHASE_DIR" phase)/<slug>.{ext}` so `/vg:design-extract` and `/vg:build` resolve the same phase-local assets.
4. **Bulk by default** — multi-page generation in one call; `--interactive` flag opts into per-page review pause.
5. **Auto-regen on DESIGN.md change** — scaffold caches by DESIGN.md SHA256; mockups regenerated when tokens drift.
6. **Idempotent** — re-running with same args + same DESIGN.md = no-op. `--refresh` forces re-scaffold.
7. **No replacement of /vg:design-system** — orthogonal: design-system manages tokens (DESIGN.md), scaffold consumes them.
</rules>

<objective>
Generate UI mockup files for every page in ROADMAP.md so `/vg:design-extract` has assets to normalize. Output:
  ${PHASE_DIR}/design/<slug>.{pen|html|png|fig}           ← per tool
  ${PHASE_DIR}/.scaffold-evidence/{slug}.json            ← per-page provenance (tool, hash, generated_at)
</objective>

<available_agent_types>
- general-purpose — Opus for Pencil MCP (D-02) + AI HTML (D-03) generation
</available_agent_types>

<process>

**Config:** Source `.claude/commands/vg/_shared/lib/design-system.sh` first to read design_assets paths + DESIGN.md location.

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh" 2>/dev/null || true
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-path-resolver.sh" 2>/dev/null || true
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/scaffold-discovery.sh" 2>/dev/null || true
```

<step name="0_validate_prereqs">
## Step 0: Validate prerequisites

```bash
if type -t vg_resolve_design_dir >/dev/null 2>&1; then
  DESIGN_ASSETS_DIR=$(vg_resolve_design_dir "$PHASE_DIR" phase)
else
  DESIGN_ASSETS_DIR="${PHASE_DIR}/design"
fi
DESIGN_MD_PATH="${PLANNING_DIR}/design/DESIGN.md"

# Need at least one of: ROADMAP page list (preferred) OR current PHASE PLAN
ROADMAP="${PLANNING_DIR}/ROADMAP.md"
PLAN_GLOB="${PHASE_DIR}/PLAN*.md"

# Check DESIGN.md presence (not blocking — scaffold can run without tokens
# but quality drops; prompt user to run /vg:design-system first when missing)
if [ ! -f "$DESIGN_MD_PATH" ] && [ ! -f "${PHASE_DIR}/DESIGN.md" ]; then
  echo "⚠ Không thấy DESIGN.md (tokens). Mockups sẽ generic hơn — cân nhắc:"
  echo "    /vg:design-system --browse   (chọn brand từ 58 variants)"
  echo "    /vg:design-system --create   (tạo custom)"
  AskUserQuestion: "Continue scaffold without DESIGN.md? [y/N]"
fi

mkdir -p "$DESIGN_ASSETS_DIR" "${PHASE_DIR}/.scaffold-evidence"
```

If neither ROADMAP nor PLAN exists → BLOCK: "Run /vg:roadmap or /vg:specs first to define page list."
</step>

<step name="1_extract_page_list">
## Step 1: Extract page list

Build the list of pages to scaffold:

1. **Priority order:**
   - `--pages=slug1,slug2,...` flag → use as-is
   - PHASE_DIR PLAN tasks with `<design-ref>SLUG</design-ref>` (Form A only)
   - ROADMAP.md `<page>` declarations
   - Fallback: prompt user to type page list

2. **For each page**, derive metadata from PLAN/ROADMAP:
   - `slug` (kebab-case)
   - `description` (1-line, from task body or page section)
   - `type` (list / form / dashboard / wizard / detail / landing — auto-classify by description regex; user override via interactive prompt)

Write to `${PHASE_DIR}/.tmp/scaffold-pages.json`:

```json
{"pages": [{"slug": "home-dashboard", "description": "...", "type": "dashboard"}, ...]}
```
</step>

<step name="2_check_existing_assets">
## Step 2: Check existing assets

```bash
EXISTING=$(find "$DESIGN_ASSETS_DIR" -maxdepth 2 -type f \
  \( -name "*.pen" -o -name "*.html" -o -name "*.png" -o -name "*.fig" -o -name "*.penboard" \) 2>/dev/null | wc -l)
```

If $EXISTING > 0:
- Match each existing file basename against page list slugs.
- Pages with matching file → SKIP (already have mockup).
- Pages without → continue to scaffold.
- If `--refresh` flag → ignore existing, scaffold all.

**Auto-regen check (Q3 = A):** for each existing mockup file, compare its scaffold-evidence entry's `design_md_sha256` field against current DESIGN.md SHA256.
- Mismatch → mark page as "stale", scaffold again.
- Match → skip.
- No evidence file (manually-added mockup) → leave alone (not scaffold-managed).

Display:
```
Pages to scaffold: <N>
Pages skipped (exists, fresh): <M>
Pages stale (DESIGN.md changed): <K>
Pages new: <P>
```
</step>

<step name="3_tool_selector">
## Step 3: Tool selector

If `--tool=<name>` flag → validate name in {pencil-mcp, penboard-mcp, ai-html, claude-design, stitch, v0, figma, manual-html, sketch} and skip prompt.

Else AskUserQuestion with decision matrix:

```
Pages to scaffold: <N>. DESIGN.md: <yes|no>. Recommended: pencil-mcp (auto, free).

Pick a tool:
  [a] pencil-mcp     — Pencil MCP automated (DEFAULT). Output .pen via mcp__pencil__batch_design.
  [b] penboard-mcp   — PenBoard MCP automated (Wave B). Multi-page workspace.
  [c] ai-html        — Claude writes HTML+Tailwind from DESIGN.md tokens. Cheap, inspectable.
  [d] claude-design  — gstack:design-shotgun variants → comparison board → user picks (Wave B).
  [e] stitch         — Google Stitch (manual export). Best aesthetic, no API.
  [f] v0             — Vercel v0 (manual export, paid). React-first.
  [g] figma          — Figma (manual export). Industry standard for designer teams.
  [h] manual-html    — You write HTML mockups by hand. Trivial integration.
  [i] sketch         — Sketch.app (macOS only). Mobile-friendly artboard presets (Wave C D-13).
  [help]             — print full decision matrix + trade-offs.
```

Save choice as `$TOOL` env var.

`--interactive` flag (Q2 = C) is forwarded to tool sub-flow as `INTERACTIVE_MODE=1` env var.
</step>

<step name="4_per_tool_dispatch">
## Step 4: Per-tool dispatch

```bash
case "$TOOL" in
  pencil-mcp)    SCAFFOLD_LIB="scaffold-pencil.sh" ;;
  penboard-mcp)  SCAFFOLD_LIB="scaffold-penboard.sh" ;;     # Wave B stub
  ai-html)       SCAFFOLD_LIB="scaffold-ai-html.sh" ;;
  claude-design) SCAFFOLD_LIB="scaffold-claude-design.sh" ;;# Wave B stub
  stitch)        SCAFFOLD_LIB="scaffold-stitch.sh" ;;
  v0)            SCAFFOLD_LIB="scaffold-v0.sh" ;;
  figma)         SCAFFOLD_LIB="scaffold-figma.sh" ;;
  manual-html)   SCAFFOLD_LIB="scaffold-manual.sh" ;;
  sketch)        SCAFFOLD_LIB="scaffold-sketch.sh" ;;        # Wave C D-13
  *) echo "⛔ Unknown tool: $TOOL"; exit 1 ;;
esac

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/${SCAFFOLD_LIB}"
scaffold_run \
  --pages-json "${PHASE_DIR}/.tmp/scaffold-pages.json" \
  --output-dir "${DESIGN_ASSETS_DIR}" \
  --design-md "${DESIGN_MD_PATH}" \
  --evidence-dir "${PHASE_DIR}/.scaffold-evidence"
```

Each `scaffold-*.sh` lib exposes `scaffold_run` with the same args. See per-tool sub-flow specs in the Phase 20 SPECS.md (D-02 through D-04).
</step>

<step name="5_validate_output">
## Step 5: Validate output

```bash
MISSING=()
for slug in "${PAGE_SLUGS[@]}"; do
  found=0
  for ext in pen html png fig penboard; do
    if [ -f "${DESIGN_ASSETS_DIR}/${slug}.${ext}" ]; then
      found=1
      break
    fi
  done
  [ $found -eq 0 ] && MISSING+=("$slug")
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "⛔ Scaffold incomplete — missing files for: ${MISSING[*]}"
  echo "   Tool: $TOOL. Re-run /vg:design-scaffold --tool=$TOOL --pages=${MISSING[*]}"
  exit 1
fi
```

Write per-page evidence:

```json
{
  "slug": "home-dashboard",
  "tool": "pencil-mcp",
  "file": "${PHASE_DIR}/design/home-dashboard.pen",
  "design_md_sha256": "<sha256 of DESIGN.md at scaffold time>",
  "generated_at": "2026-04-28T12:34:56Z",
  "interactive_mode": false
}
```
</step>

<step name="6_auto_extract">
## Step 6: Auto-fire /vg:design-extract

```
SlashCommand: /vg:design-extract --auto
```

Verify `manifest.json` updated with all expected slugs. If any missing → fail loud with diagnostic.
</step>

<step name="7_resume_pipeline">
## Step 7: Resume pipeline

```
Scaffold complete.
  Tool used:        $TOOL
  Pages generated:  <N>
  Pages skipped:    <M>
  Output dir:       $DESIGN_ASSETS_DIR
  Evidence:         ${PHASE_DIR}/.scaffold-evidence/

Next: /vg:blueprint ${PHASE_NUMBER}  (or /vg:phase to continue full pipeline)
```

Mark step + emit telemetry `design_scaffold.completed`.
</step>

</process>

<help_tools_matrix>
# Decision matrix (--help-tools)

| Tool | Auto | Cost/page | Output | Best for |
|---|---|---|---|---|
| **pencil-mcp** (DEFAULT) | ✅ | ~$0.15 Opus | `.pen` binary | Solo dev, in-pipeline, token-faithful |
| penboard-mcp | ✅ Wave B | ~$0.20 Opus | `.penboard` workspace | Multi-page nav-aware (Wave B) |
| **ai-html** | ✅ | ~$0.05 Opus | `.html` Tailwind | DESIGN.md + cheap; hand-editable |
| claude-design | 🟡 Wave B | ~$0.30 (variants) | `.html` | Visual exploration, design-shotgun pattern |
| stitch | 🔴 manual | free 350/mo | `.html` (export) | Best aesthetic; willing to manual export |
| v0 | 🔴 manual | paid Vercel | `.html` React | React shop, has v0 sub |
| figma | 🔴 manual | varies | `.png` (export) | Designer-team, Figma-native |
| manual-html | trivial | $0 | `.html` | Existing hand-written mockups |
| **sketch** | 🔴 manual | $9/mo Sketch sub | `.png` (export 2x) | Mobile-friendly (iOS/Android artboards), macOS only |

</help_tools_matrix>

<success_criteria>
- Page list resolved from PLAN/ROADMAP/--pages
- Tool picked (interactive or flag)
- Per-tool sub-flow produced files at $DESIGN_ASSETS_DIR
- Validation passes (every requested page has a file)
- Evidence written per page
- /vg:design-extract auto-fired and manifest.json populated
- Telemetry events emitted (started + completed)
</success_criteria>
</process>
