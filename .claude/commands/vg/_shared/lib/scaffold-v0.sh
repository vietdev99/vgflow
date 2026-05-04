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

  # P20 D-10 (Wave B): detect v0 CLI on PATH for paid-subscription users.
  # If present + authenticated, drive automatically. Else fallback below.
  if command -v v0 >/dev/null 2>&1; then
    echo "ℹ v0 CLI detected on PATH — checking auth..."
    if v0 whoami >/dev/null 2>&1; then
      echo "✓ v0 authenticated. Driving automated chain (Wave B D-10)."
      scaffold_v0_automated "$pages_json" "$output_dir" "$design_md" "$evidence_dir"
      return $?
    else
      echo "⚠ v0 CLI present but not authenticated. Run: v0 login"
      echo "  Falling back to manual export flow."
    fi
  fi

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

# scaffold_v0_automated — P20 D-10: v0 CLI driven generation
# Iterates pages.json, calls `v0 generate` per page, saves HTML to output_dir.
scaffold_v0_automated() {
  local pages_json="$1" output_dir="$2" design_md="$3" evidence_dir="$4"
  local design_md_sha=""
  if [ -f "$design_md" ]; then
    design_md_sha=$(${PYTHON_BIN:-python3} -c "
import hashlib
print(hashlib.sha256(open(r'${design_md}','rb').read()).hexdigest())
" 2>/dev/null)
  fi

  local tokens_summary=""
  if [ -f "$design_md" ]; then
    tokens_summary=$(head -30 "$design_md" | tr '\n' ' ' | head -c 400)
  fi

  local total
  total=$(${PYTHON_BIN:-python3} -c "import json; print(len(json.load(open(r'${pages_json}'))['pages']))")
  local completed=0 failed=0

  ${PYTHON_BIN:-python3} - "$pages_json" <<'PY' | while IFS=$'\t' read -r slug type description; do
import json, sys
data = json.load(open(sys.argv[1]))
for p in data['pages']:
    print(f"{p['slug']}\t{p.get('type','?')}\t{p.get('description','')[:200]}")
PY
    [ -z "$slug" ] && continue
    local target="${output_dir}/${slug}.html"
    if [ -f "$target" ] && [ -z "${SCAFFOLD_REFRESH:-}" ]; then
      echo "  ✓ ${slug} — exists, skip (use --refresh to overwrite)"
      continue
    fi
    local prompt="Create a ${type} page for ${slug}: ${description}. Use Tailwind CSS, semantic HTML5, realistic Vietnamese copy. Include header (TopBar 52px) + sidebar (240px) + main content. Tokens: ${tokens_summary}. Export as static HTML with Tailwind CDN."
    echo "  → v0 generate ${slug}..."
    if v0 generate --prompt "$prompt" --output "$target" --format html 2>/dev/null; then
      cat > "${evidence_dir}/${slug}.json" <<EVID
{"slug":"${slug}","tool":"v0","file":"${target}","design_md_sha256":"${design_md_sha}","generated_at":"$(date -u +%FT%TZ)","interactive_mode":false,"v0_cli":true}
EVID
      completed=$((completed + 1))
      echo "    ✓ ${target}"
    else
      failed=$((failed + 1))
      echo "    ✗ v0 generate failed for ${slug}"
    fi
  done

  echo ""
  echo "v0 automated: ${completed} ok, ${failed} failed (${total} total)"
  [ "$failed" = "0" ]
}
