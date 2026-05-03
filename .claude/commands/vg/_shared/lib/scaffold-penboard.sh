#!/bin/bash
# scaffold-penboard.sh — Phase 20 Tool B (PenBoard MCP) — Wave B (v2.17.0)
#
# PenBoard is workspace-managed via mcp__penboard__* tools. Unlike Pencil's
# single-file .pen model, PenBoard organizes mockups as multi-page workspace
# with entities + connections + flows. Best for projects with strong nav
# context (admin SPAs with consistent shell across pages).

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

  [ -f "$pages_json" ] || { echo "⛔ scaffold-penboard: pages-json missing"; return 1; }
  mkdir -p "$output_dir" "$evidence_dir"

  local design_md_sha=""
  if [ -f "$design_md" ]; then
    design_md_sha=$(${PYTHON_BIN:-python3} -c "
import hashlib
print(hashlib.sha256(open(r'${design_md}','rb').read()).hexdigest())
" 2>/dev/null)
  fi

  local interactive="${INTERACTIVE_MODE:-0}"
  local page_count
  page_count=$(${PYTHON_BIN:-python3} -c "import json; print(len(json.load(open(r'${pages_json}'))['pages']))")

  echo "ℹ Tool B — PenBoard MCP. ${page_count} page(s). Interactive: $interactive"
  echo "  Output dir:    $output_dir"
  echo "  DESIGN.md sha: ${design_md_sha:0:12}"
  echo ""

  cat <<INSTRUCT
================================================================================
PenBoard MCP scaffold — workspace mode

Spawn ONE agent (Opus, vision-capable) with these MCP tools granted:
  - mcp__penboard__open_document
  - mcp__penboard__add_page
  - mcp__penboard__rename_page
  - mcp__penboard__reorder_page
  - mcp__penboard__batch_design
  - mcp__penboard__set_themes
  - mcp__penboard__set_variables
  - mcp__penboard__manage_entities    (declare data shapes)
  - mcp__penboard__manage_connections (declare nav links between pages)
  - mcp__penboard__list_flows
  - mcp__penboard__write_flow         (define user flows across pages)
  - mcp__penboard__export_workflow
  - mcp__penboard__save_document
  - Read (DESIGN.md), Write (evidence)

Agent prompt:
  You are a PenBoard MCP design scaffolder. Build ONE PenBoard workspace
  containing all pages from pages.json, with proper navigation links and
  shared entities reused across pages.

  Page list:    $(cat "$pages_json")
  DESIGN.md:    $design_md
  Output file:  ${output_dir}/scaffold-${PHASE_NUMBER:-default}.penboard
  Evidence dir: $evidence_dir

  Workspace build sequence (single MCP session):

    1. mcp__penboard__open_document('new')
    2. mcp__penboard__set_themes — translate DESIGN.md tokens (palette/
       typography/spacing). Read DESIGN.md first via Read tool.
    3. mcp__penboard__manage_entities — declare data shapes inferred from
       page list (e.g. User, Site, Campaign — based on resource names in
       page.description / page.slug).
    4. For each page in pages.json (sequential):
         a. mcp__penboard__add_page — page name = slug, title = description
         b. mcp__penboard__batch_design — compose page layout with semantic
            components (Sidebar, TopBar, MainContent, KPICard, etc.) per
            page.type. SHARE Sidebar + TopBar across pages (use page.children
            references to maintain consistency).
         c. Position per project profile (admin SPA: sidebar 240px + topbar 52px).
    5. mcp__penboard__manage_connections — declare nav links between pages
       based on action verbs in descriptions (e.g. "Manage" → list page,
       "Add" → form page, etc.).
    6. mcp__penboard__write_flow — define 1-2 primary user flows ("Onboarding",
       "Daily admin task") that traverse 3-5 pages.
    7. mcp__penboard__save_document — output as ${output_dir}/scaffold-${PHASE_NUMBER:-default}.penboard
    8. For each page, write evidence to ${evidence_dir}/{slug}.json:
         {"slug": "...", "tool": "penboard-mcp",
          "file": "${output_dir}/scaffold-${PHASE_NUMBER:-default}.penboard",
          "page_id": "<penboard-page-id>",
          "design_md_sha256": "${design_md_sha}",
          "generated_at": "<ISO 8601 UTC NOW>",
          "interactive_mode": false}

  Rules:
    - SHARE shell components (Sidebar, TopBar) across pages — DO NOT
      re-create per page. PenBoard's strength is consistent navigation.
    - Match page TYPE: list / form / dashboard / wizard / detail / landing.
    - DO NOT use generic component names (div, container, wrapper).
    - Total budget: 15 minutes wall-clock + 75K tokens.

  Output JSON to stdout when complete:
    {"completed": <int>, "failed": <int>,
     "workspace": "${output_dir}/scaffold-${PHASE_NUMBER:-default}.penboard",
     "pages": [{"slug": "...", "page_id": "..."}, ...]}

================================================================================
INSTRUCT

  if [ "$interactive" = "1" ]; then
    echo ""
    echo "Interactive mode: agent will pause after each mcp__penboard__add_page"
    echo "for user [c]ontinue / [r]edo / [s]kip via AskUserQuestion."
  fi
}
