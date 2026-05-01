#!/bin/bash
# scaffold-sketch.sh — Phase 20 Wave C D-13 (Tool I — Sketch)
#
# Sketch is macOS-only design tool. .sketch files require Sketch app for
# canonical rendering; export to PNG/SVG is manual. Same pattern as Figma.

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

  mkdir -p "$output_dir" "$evidence_dir"
  export SCAFFOLD_DESIGN_MD="$design_md"

  cat <<'INSTRUCT'
╭──────────────────────────────────────────────────────────────────╮
│ Sketch — manual export flow (Tool I — D-13 mobile-friendly)      │
│                                                                  │
│ Sketch là design tool macOS-only, mạnh cho mobile UI nhờ artboard│
│ presets sẵn (iPhone 15 Pro, iPad, watchOS...).                   │
│                                                                  │
│ 1. Mở Sketch.app (macOS only — Windows/Linux dùng Figma instead).│
│ 2. New file → Insert artboard preset (Devices → iOS / Android /  │
│    Web hoặc custom).                                             │
│ 3. Cho mỗi page trong list dưới: 1 artboard.                     │
│ 4. Apply DESIGN.md tokens manually (palette, typography).         │
│ 5. Cho mỗi artboard: File → Export → PNG (2x for retina).        │
│ 6. Save với đúng tên slug:                                       │
INSTRUCT
  echo "      ${output_dir}/{slug}.png"
  echo "    Optional: save .sketch file kế bên (chỉ macOS đọc được)."
  echo ""
  echo "Page list:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
for p in data['pages']:
    print(f\"  - {p['slug']:30s} ({p.get('type','?'):10s}) {p.get('description','')[:60]}\")
"
  echo ""
  if [ -f "$design_md" ]; then
    echo "DESIGN.md tokens:"
    head -20 "$design_md" | sed 's/^/  /'
  fi
  echo "╰──────────────────────────────────────────────────────────────────╯"

  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "sketch"
}
