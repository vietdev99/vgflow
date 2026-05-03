#!/bin/bash
# scaffold-claude-design.sh — Phase 20 Tool D — Wave B (v2.17.0)
#
# Integrates with gstack ecosystem skills:
#   /design-shotgun        — generate AI design variants per page (3-4 per page)
#   /design-html           — finalize chosen variant to production HTML
#
# Wave B impl: orchestrator detects gstack availability, drives the chain
# automatically. Falls back to instructional flow if gstack not installed.

source "$(dirname "${BASH_SOURCE[0]}")/scaffold-stitch.sh"  # reuse scaffold_wait_for_files

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

  [ -f "$pages_json" ] || { echo "⛔ scaffold-claude-design: pages-json missing"; return 1; }
  mkdir -p "$output_dir" "$evidence_dir"
  export SCAFFOLD_DESIGN_MD="$design_md"

  # Detect gstack skill availability via ~/.claude/skills/ presence
  local gstack_installed=0
  if [ -d "$HOME/.claude/skills/design-shotgun" ] || \
     [ -d "${REPO_ROOT}/.claude/skills/design-shotgun" ]; then
    gstack_installed=1
  fi

  if [ "$gstack_installed" = "0" ]; then
    cat <<'INSTRUCT'
╭──────────────────────────────────────────────────────────────────╮
│ Claude design (gstack ecosystem) — INSTRUCTIONAL FALLBACK        │
│                                                                  │
│ gstack:design-shotgun skill không cài. Có 2 lựa chọn:            │
│                                                                  │
│ 1. Cài gstack: github.com/g-styled/gstack hoặc tương đương,      │
│    rồi /vg:design-scaffold --tool=claude-design --refresh       │
│                                                                  │
│ 2. Chuyển sang ai-html (gần tương đương về output):              │
│    /vg:design-scaffold --tool=ai-html                           │
╰──────────────────────────────────────────────────────────────────╯
INSTRUCT
    return 1
  fi

  echo "ℹ Tool D — Claude design (gstack:design-shotgun + design-html chain)."
  echo "  Output dir: $output_dir"
  echo ""
  echo "Per-page chain:"
  echo "  1. /design-shotgun '<slug>: <description>' → 3-4 variants"
  echo "  2. AskUserQuestion: pick variant"
  echo "  3. /design-html → finalize chosen → save HTML"
  echo "  4. Move HTML tới ${output_dir}/<slug>.html"
  echo ""

  cat <<INSTRUCT
================================================================================
gstack chain — orchestrator-driven (Wave B Tool D)

For each page in pages.json:

  Step 1 — Generate variants:
    SlashCommand: /design-shotgun "page <slug>: <type> for <description>.
                                   Apply tokens from DESIGN.md (palette,
                                   typography, spacing). 4 variants."

  Step 2 — User picks variant:
    AskUserQuestion: "Variants generated cho <slug>. Pick:
      [1] variant 1
      [2] variant 2
      [3] variant 3
      [4] variant 4
      [redo] regenerate
      [skip] skip page"

  Step 3 — Finalize chosen:
    SlashCommand: /design-html --variant=<picked-id>

  Step 4 — Move output:
    mv \$gstack_html_output ${output_dir}/<slug>.html

  Step 5 — Evidence:
    Write ${evidence_dir}/<slug>.json with tool="claude-design", variant_id=<id>.

Page list: $(cat "$pages_json")
DESIGN.md: $design_md

Bulk vs interactive (INTERACTIVE_MODE=${INTERACTIVE_MODE:-0}):
  - bulk: skip Step 2 user pick — auto-pick first variant, log all 4 paths
  - interactive: pause at Step 2 per page

================================================================================
INSTRUCT

  # Wave B note: full chain orchestration (SlashCommand + parse + mv) is
  # complex shell. For now, emit the plan and rely on parent /vg:design-scaffold
  # orchestrator to interpret. Full parse-and-move automation deferred to
  # v2.18+ when gstack output paths stabilize.
  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "claude-design"
}
