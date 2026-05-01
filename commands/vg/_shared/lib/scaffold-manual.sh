#!/bin/bash
# scaffold-manual.sh — Phase 20 D-04 instructional flow (Tool H — Manual HTML)

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
│ Manual HTML — designer-written mockups (Tool H)                  │
│                                                                  │
│ Phù hợp khi đã có sẵn HTML mockup hoặc bạn muốn viết tay.        │
│                                                                  │
│ Yêu cầu cho mỗi file:                                            │
│   - Self-contained HTML (single file)                            │
│   - Semantic tags: <header>, <main>, <nav>, <aside>, <section>   │
│   - Tailwind CDN OK; tránh JS frameworks (chỉ mockup)            │
│   - Apply DESIGN.md tokens nếu có (CSS variables hoặc Tailwind   │
│     theme extension)                                             │
│                                                                  │
│ Save tới đúng path:                                              │
INSTRUCT
  echo "    ${output_dir}/{slug}.html"
  echo ""
  echo "Page list cần viết:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
for p in data['pages']:
    print(f\"  - {p['slug']:30s} ({p.get('type','?'):10s}) {p.get('description','')[:60]}\")
"
  echo ""
  if [ -f "$design_md" ]; then
    echo "DESIGN.md tokens (reference):"
    head -20 "$design_md" | sed 's/^/  /'
  else
    echo "(no DESIGN.md — dùng palette neutral)"
  fi
  echo "╰──────────────────────────────────────────────────────────────────╯"

  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "manual-html"
}
