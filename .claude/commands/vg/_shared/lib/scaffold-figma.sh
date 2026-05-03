#!/bin/bash
# scaffold-figma.sh — Phase 20 D-04 instructional flow (Tool G — Figma)

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
│ Figma — manual export flow (Tool G)                              │
│                                                                  │
│ Phù hợp khi team có designer riêng dùng Figma. VG không drive    │
│ Figma programmatically (cần OAuth + plan limits) — hướng dẫn     │
│ designer export PNG, drop vào path, VG nhận.                     │
│                                                                  │
│ 1. Mở Figma file/project có sẵn (hoặc tạo mới + apply tokens     │
│    từ DESIGN.md).                                                │
│ 2. Tạo 1 frame per page trong list dưới đây.                     │
│ 3. Cho mỗi frame:                                                │
│    a. Right-click → Export → PNG (2x recommended).               │
│    b. Save với đúng tên slug:                                    │
INSTRUCT
  echo "         ${output_dir}/{slug}.png"
  echo "    c. (Optional) Save .fig file kế bên — VG support nhưng"
  echo "       extract phải làm thủ công."
  echo ""
  echo "Page list cần export:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
for p in data['pages']:
    print(f\"  - {p['slug']:30s} ({p.get('type','?'):10s}) {p.get('description','')[:60]}\")
"
  echo ""
  if [ -f "$design_md" ]; then
    echo "DESIGN.md tokens (apply consistently — designer ref):"
    head -30 "$design_md" | sed 's/^/  /'
  fi
  echo "╰──────────────────────────────────────────────────────────────────╯"

  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "figma"
}
