#!/bin/bash
# scaffold-ai-html.sh — Phase 20 D-03
#
# Tool C: Opus generates static HTML+Tailwind mockup per page from
# DESIGN.md tokens + page description. Output drops into design_assets.paths
# as .html files; existing playwright_render handler in design-extract
# converts them to PNG + structural HTML.

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

  [ -f "$pages_json" ] || { echo "⛔ scaffold-ai-html: pages-json missing"; return 1; }
  mkdir -p "$output_dir" "$evidence_dir"

  local design_md_sha="" design_md_content=""
  if [ -f "$design_md" ]; then
    design_md_sha=$(${PYTHON_BIN:-python3} -c "
import hashlib
print(hashlib.sha256(open(r'${design_md}','rb').read()).hexdigest())
")
    design_md_content=$(head -200 "$design_md")
  fi

  local interactive="${INTERACTIVE_MODE:-0}"
  local page_count
  page_count=$(${PYTHON_BIN:-python3} -c "import json; print(len(json.load(open(r'${pages_json}'))['pages']))")

  echo "ℹ Tool C — AI HTML. ${page_count} page(s). Interactive: $interactive"
  echo "  DESIGN.md sha256: ${design_md_sha:0:12}"

  # P20 D-11: VIEW-COMPONENTS.md feedback loop
  local view_components_path="${PHASE_DIR:-.}/VIEW-COMPONENTS.md"
  local view_components_block=""
  if [ -f "$view_components_path" ]; then
    view_components_block="

VIEW-COMPONENTS.md present — for each page, treat the matching '## {slug}'
section in ${view_components_path} as authoritative component list. Every
component in the table MUST appear in the HTML output (matching JSX tag,
className, role, or distinctive copy)."
  fi

  cat <<INSTRUCT
================================================================================
AI HTML scaffold — bulk mode${view_components_block:+ (VIEW-COMPONENTS-aware)}

Spawn ONE agent (Opus) with these tool grants:
  - Read (DESIGN.md, ROADMAP, optional reference fixtures)
  - Write (the HTML + evidence files)

Agent prompt:
  You write a static HTML+Tailwind mockup for every page in pages.json.

  Page list:           $(cat "$pages_json")
  DESIGN.md:           $design_md
  VIEW-COMPONENTS.md:  ${view_components_path:-(none — first scaffold pass)}
  Output dir:          $output_dir
  Evidence dir:        $evidence_dir
${view_components_block}

  Per page, write file ${output_dir}/{page.slug}.html with:

  Constraints:
    1. ONLY Tailwind utility classes via CDN <script src="https://cdn.tailwindcss.com"></script>.
       No custom CSS files. Inline <style> ONLY for CSS variables matching
       DESIGN.md tokens (e.g. --color-primary: #6366f1).
    2. Apply DESIGN.md tokens by mapping hex/spacing to nearest Tailwind value.
       Configure tailwind.config inside <script>tailwind.config = {...}</script>.
    3. Layout per page TYPE:
         - list:      Sidebar + TopBar + MainContent (toolbar with search/filter, table, pagination)
         - form:      Sidebar + TopBar + MainContent (form fields, submit button, validation hints)
         - dashboard: Sidebar + TopBar + MainContent (KPI cards grid + content sections)
         - wizard:    Sidebar + TopBar + MainContent (step indicator + step body + navigation)
         - detail:    Sidebar + TopBar + MainContent (header + tabs + body sections)
         - landing:   no sidebar; hero + content sections + footer
       Project profile (admin SPA) → sidebar 240px + topbar 52px + main fills rest.
    4. Realistic copy:
         - Heading: domain-specific (e.g. "Quản lý Site", "Tổng quan", "Thêm User")
         - Button labels: action verbs ("Thêm mới", "Lưu", "Hủy", "Tìm kiếm")
         - Table headers: 4-6 plausible columns per resource
         - Form fields: 4-8 fields per resource
       LOREM IPSUM IS BANNED. If you don't know the domain, infer from page.description.
    5. Semantic HTML required: <header>, <main>, <nav>, <aside>, <section>.
       playwright_render extracts structural-html from this; semantic tags help
       L5 design-fidelity-guard map components.
    6. Self-contained single file. No external imports beyond Tailwind CDN.
    7. NO scripts beyond basic state toggles (data-* attributes for modals etc.).

  Anti-pattern (NEVER write):
    - <main className="flex min-h-screen items-center justify-center">
      <h1>...</h1></main>
    - This is the L-002 anti-pattern that triggered Phase 19. If you write
      this for an admin/dashboard page, the L5 guard will reject it later.

  After writing each .html file, write evidence to ${evidence_dir}/{slug}.json:
    {"slug": "...", "tool": "ai-html", "file": "${output_dir}/{slug}.html",
     "design_md_sha256": "${design_md_sha}",
     "generated_at": "<ISO 8601 UTC NOW>",
     "interactive_mode": false}

  Output JSON to stdout when complete:
    {"completed": <int>, "failed": <int>, "files": [{"slug": "...", "path": "..."}]}

  Budget: 5 minutes wall-clock + 30K tokens (~\$0.05/page average).

================================================================================
INSTRUCT

  # Same as scaffold-pencil.sh: orchestrator parent spawns the Task.
}
