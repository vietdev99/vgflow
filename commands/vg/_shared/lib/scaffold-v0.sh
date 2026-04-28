#!/bin/bash
# scaffold-v0.sh — Phase 20 D-04 instructional flow (Tool F — Vercel v0)

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
│ Vercel v0 — manual export flow (Tool F)                          │
│                                                                  │
│ NOTE: v0 cần Vercel paid subscription cho full export. Free      │
│       tier có thể đủ cho preview nhưng download bị hạn chế.      │
│                                                                  │
│ 1. Mở https://v0.app/                                            │
│ 2. Login với Vercel account.                                     │
│ 3. Cho mỗi page trong list dưới: tạo new chat, paste prompt.     │
│ 4. v0 generate React component preview. Adjust qua follow-up     │
│    prompts nếu cần.                                              │
│ 5. Export mã: dropdown → "Export Code" → choose React+Tailwind   │
│    HOẶC HTML+Tailwind (preferred cho mockup, dễ playwright       │
│    render).                                                      │
│ 6. Save mỗi page với tên đúng:                                   │
INSTRUCT
  echo "      ${output_dir}/{slug}.html"
  echo ""
  echo "Page list:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
for p in data['pages']:
    print(f\"  - {p['slug']:30s} ({p.get('type','?'):10s}) {p.get('description','')[:60]}\")
"
  echo ""
  echo "Prompt template (cho từng page, replace {slug}/{type}/{desc}):"
  echo "  > Create a {type} page for {slug}: {desc}"
  echo "  > Use Tailwind CSS, semantic HTML5, realistic Vietnamese copy."
  echo "  > Include header (TopBar 52px) + sidebar (240px) + main content."
  echo ""
  echo "  Đính kèm DESIGN.md tokens:"
  if [ -f "$design_md" ]; then
    head -30 "$design_md" | sed 's/^/    /'
  else
    echo "    (no DESIGN.md — v0 dùng default palette)"
  fi
  echo "╰──────────────────────────────────────────────────────────────────╯"

  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "v0"
}
