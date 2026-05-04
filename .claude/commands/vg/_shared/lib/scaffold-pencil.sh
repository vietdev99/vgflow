#!/bin/bash
# scaffold-pencil.sh — Phase 20 D-02
#
# Tool A: Pencil MCP automated mockup generation (DEFAULT per user choice 1A).
# Spawns Opus subagent with mcp__pencil__* tool grants + DESIGN.md tokens
# + page list. Output: .pen files in design_assets.paths/<slug>.pen

scaffold_run() {
  local pages_json="" output_dir="" design_md="" evidence_dir=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --pages-json) pages_json="$2"; shift 2 ;;
      --output-dir) output_dir="$2"; shift 2 ;;
      --design-md)  design_md="$2"; shift 2 ;;
      --evidence-dir) evidence_dir="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  [ -f "$pages_json" ] || { echo "⛔ scaffold-pencil: pages-json missing"; return 1; }
  [ -d "$output_dir" ] || mkdir -p "$output_dir"
  [ -d "$evidence_dir" ] || mkdir -p "$evidence_dir"

  local design_md_sha=""
  if [ -f "$design_md" ]; then
    design_md_sha=$(${PYTHON_BIN:-python3} -c "
import hashlib
print(hashlib.sha256(open(r'${design_md}','rb').read()).hexdigest())
" 2>/dev/null)
  fi

  local interactive="${INTERACTIVE_MODE:-0}"
  local page_count
  page_count=$(${PYTHON_BIN:-python3} -c "import json; print(len(json.load(open(r'${pages_json}'))['pages']))" 2>/dev/null || echo 0)

  if [ "$page_count" = "0" ]; then
    echo "⛔ scaffold-pencil: page list empty"
    return 1
  fi

  echo "ℹ Tool A — Pencil MCP. ${page_count} page(s) to generate. Interactive: $interactive"
  echo "  Output dir:  $output_dir"
  echo "  DESIGN.md:   ${design_md:-<none>} (sha256: ${design_md_sha:0:12})"

  # Prompt agent. Bulk mode = single agent processes all pages; interactive
  # mode = one agent per page with pause between.
  if [ "$interactive" = "1" ]; then
    scaffold_pencil_interactive "$pages_json" "$output_dir" "$design_md" "$evidence_dir" "$design_md_sha"
  else
    scaffold_pencil_bulk "$pages_json" "$output_dir" "$design_md" "$evidence_dir" "$design_md_sha"
  fi
}

scaffold_pencil_bulk() {
  local pages_json="$1" output_dir="$2" design_md="$3" evidence_dir="$4" design_md_sha="$5"

  # P20 D-11 (Wave B): if VIEW-COMPONENTS.md exists from P19 D-02 vision
  # decomposition, surface per-slug component lists into the prompt for
  # tighter mockup generation. Tools D-02 and D-03 share this loader.
  local view_components_path="${PHASE_DIR:-.}/VIEW-COMPONENTS.md"
  local view_components_block=""
  if [ -f "$view_components_path" ]; then
    view_components_block="
VIEW-COMPONENTS.md is present (P19 D-02 vision decomposition output).
For each page in pages.json, look up the matching '## {slug}' section in
${view_components_path} and treat its component list as AUTHORITATIVE
input. The mockup MUST include every component listed (semantic names,
correct parent/position/child_count). Generic names rejected upstream.
"
  fi

  cat <<INSTRUCT
================================================================================
Pencil MCP scaffold — bulk mode${view_components_block:+ (VIEW-COMPONENTS-aware)}

Spawn ONE agent (Opus, vision-capable) with these MCP tools granted:
  - mcp__pencil__open_document
  - mcp__pencil__batch_design
  - mcp__pencil__set_themes
  - mcp__pencil__set_variables
  - mcp__pencil__save_document
  - mcp__pencil__get_screenshot
  - Read (for DESIGN.md), Write (for evidence files)

Agent prompt:
  You are a Pencil MCP design scaffolder. You will create .pen mockup files
  for every page in pages.json, applying DESIGN.md tokens.

  Page list:           $(cat "$pages_json")
  DESIGN.md:           $design_md
  VIEW-COMPONENTS.md:  ${view_components_path:-(none — first scaffold pass)}
  Output dir:          $output_dir
  Evidence dir:        $evidence_dir
${view_components_block}

  For each page in pages.json (process all sequentially in this single session):

    1. Call mcp__pencil__open_document('new') — empty .pen.
    2. Call mcp__pencil__set_themes with palette/typography/spacing translated
       from DESIGN.md. Read DESIGN.md first via Read tool.
    3. Call mcp__pencil__batch_design with operations to compose the page
       layout from page.description + page.type. Use semantic component
       names (Sidebar, TopBar, MainContent, KPICard, FormField, NavigationItem,
       FooterDivider, etc.). NEVER use generic names (div, container, wrapper).
       Position per project profile: admin SPA = sidebar 240px + topbar 52px +
       main fills rest. Public site = no sidebar, hero + content sections.
    4. Save .pen file to ${output_dir}/{page.slug}.pen via mcp__pencil__save_document.
    5. Write evidence to ${evidence_dir}/{page.slug}.json:
         {"slug": "...", "tool": "pencil-mcp", "file": "${output_dir}/{slug}.pen",
          "design_md_sha256": "${design_md_sha}",
          "generated_at": "<ISO 8601 UTC NOW>",
          "interactive_mode": false}

  Rules:
    - DO NOT invent components beyond page description.
    - Match page TYPE exactly (list / form / dashboard / wizard / detail / landing).
    - If a page description is ambiguous, pick the closest interpretation but log
      a warning into evidence.warnings[].
    - Total budget: 10 minutes wall-clock + 50K tokens.

  Output JSON to stdout when complete:
    {"completed": <int>, "failed": <int>, "files": [{"slug": "...", "path": "..."}]}

================================================================================
INSTRUCT

  # The orchestrator (parent /vg:design-scaffold) is responsible for spawning
  # the Task agent. This helper just prints the prompt and the parent shell
  # is expected to run:
  #   Task(subagent_type="general-purpose", model="claude-opus-4-7", prompt="<above>")
  #
  # In Wave A, we ship this as instruction-style with a helper-emitted prompt
  # that the orchestrator invokes. Future: encapsulate as direct Task call.
}

scaffold_pencil_interactive() {
  local pages_json="$1" output_dir="$2" design_md="$3" evidence_dir="$4" design_md_sha="$5"
  echo "ℹ Interactive mode — one Opus call per page, pausing between for user review."
  echo ""
  echo "  Per page: Pencil MCP agent generates .pen → screenshot → user [c]ontinue / [r]edo / [s]kip."
  echo ""
  echo "  Same agent prompt as bulk mode, but page list reduced to one per call."
  echo "  After each page: AskUserQuestion before next."
  echo ""
  echo "  Implementation: parent shell loops over pages, spawns Task per page,"
  echo "  waits for AskUserQuestion between iterations."
}
