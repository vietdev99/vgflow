#!/bin/bash
# scaffold-stitch.sh — Phase 20 D-04 instructional flow (Tool E)
#
# Google Stitch is web-only with no public API. Print user instructions,
# wait for files to land in design_assets.paths, then return.

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

  cat <<'INSTRUCT'
╭──────────────────────────────────────────────────────────────────╮
│ Google Stitch — manual export flow                               │
│                                                                  │
│ 1. Mở https://stitch.withgoogle.com/                             │
│ 2. Free tier: 350 generations/tháng (Gemini 2.5 Flash) +         │
│    50 generations Gemini 2.5 Pro/tháng.                          │
│ 3. Dùng "5-screen canvas" — describe app flow bằng natural lang. │
│    Stitch generate up to 5 interconnected screens at once.       │
│ 4. Cho mỗi page trong list dưới đây, copy prompt template +      │
│    paste vào Stitch.                                             │
│ 5. Export mỗi page: Stitch → Export → HTML/CSS (preferred)       │
│    HOẶC Figma (sẽ cần thêm bước manual export PNG sau).          │
│ 6. Save files với tên đúng slug:                                 │
INSTRUCT
  echo "      ${output_dir}/{slug}.html"
  echo ""
  echo "Page list cần generate:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
for p in data['pages']:
    print(f\"  - {p['slug']:30s} ({p.get('type','?'):10s}) {p.get('description','')[:60]}\")
"
  echo ""
  echo "Prompt template — paste vào Stitch's input:"
  ${PYTHON_BIN:-python3} -c "
import json
data = json.load(open(r'${pages_json}'))
design_md = r'${design_md}'
tokens = ''
try:
    with open(design_md) as f:
        tokens = f.read()[:500]
except Exception:
    pass
print('  Design system tokens (apply consistently across all pages):')
print('  ' + (tokens.replace(chr(10), chr(10)+'  ')[:400] if tokens else '(no DESIGN.md — use neutral palette)'))
print('')
for p in data['pages']:
    print(f\"  Page {p['slug']} ({p.get('type','?')}):\")
    print(f\"    {p.get('description','')}\")
    print('')
"
  echo "╰──────────────────────────────────────────────────────────────────╯"

  scaffold_wait_for_files "$pages_json" "$output_dir" "$evidence_dir" "stitch"
}

# scaffold_wait_for_files — shared with v0/figma/manual flows
# Polls $output_dir for expected files until all land or user skips.
scaffold_wait_for_files() {
  local pages_json="$1" output_dir="$2" evidence_dir="$3" tool_name="$4"
  local design_md_sha=""
  if [ -n "${SCAFFOLD_DESIGN_MD:-}" ] && [ -f "${SCAFFOLD_DESIGN_MD}" ]; then
    design_md_sha=$(${PYTHON_BIN:-python3} -c "
import hashlib
print(hashlib.sha256(open(r'${SCAFFOLD_DESIGN_MD}','rb').read()).hexdigest())
" 2>/dev/null)
  fi

  echo ""
  echo "Validation loop — checking ${output_dir} every 30s for expected files."
  echo "Expected exts: html, png, fig, pen, penboard"
  echo ""

  local attempts=0
  local max_attempts=120  # 60 minutes ceiling at 30s intervals
  while [ $attempts -lt $max_attempts ]; do
    local missing
    missing=$(${PYTHON_BIN:-python3} - "$pages_json" "$output_dir" <<'PY'
import json, os, sys
pages = json.load(open(sys.argv[1]))['pages']
out = sys.argv[2]
missing = []
for p in pages:
    slug = p['slug']
    found = False
    for ext in ('html','htm','png','jpg','jpeg','fig','pen','penboard','flow'):
        if os.path.exists(os.path.join(out, f"{slug}.{ext}")):
            found = True
            break
    if not found:
        missing.append(slug)
print(','.join(missing))
PY
)
    if [ -z "$missing" ]; then
      echo "✓ All expected files landed."
      break
    fi
    echo "  Missing: $missing  (attempt $((attempts+1))/$max_attempts)"
    echo "  Press [c]ontinue to wait 30s | [s]kip remaining (logs Form B) | [a]bort"
    read -r -t 30 input || input="c"
    case "$input" in
      s|S) echo "⚠ Skipping remaining: $missing"; break ;;
      a|A) echo "⛔ Aborted by user."; return 1 ;;
      *) attempts=$((attempts + 1)) ;;
    esac
  done

  # Write evidence for files that did land
  ${PYTHON_BIN:-python3} - "$pages_json" "$output_dir" "$evidence_dir" "$tool_name" "$design_md_sha" <<'PY'
import json, os, sys, datetime
pages = json.load(open(sys.argv[1]))['pages']
out, evid, tool, sha = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
os.makedirs(evid, exist_ok=True)
now = datetime.datetime.utcnow().isoformat() + "Z"
for p in pages:
    slug = p['slug']
    for ext in ('html','htm','png','jpg','jpeg','fig','pen','penboard','flow'):
        path = os.path.join(out, f"{slug}.{ext}")
        if os.path.exists(path):
            json.dump({
                "slug": slug, "tool": tool, "file": path,
                "design_md_sha256": sha, "generated_at": now,
                "interactive_mode": False,
            }, open(os.path.join(evid, f"{slug}.json"), "w"), indent=2)
            break
PY
}
