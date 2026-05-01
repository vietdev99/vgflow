#!/bin/bash
# surface-gap-detector.sh — detect when a phase's tech approach touches paths
# not declared in `surfaces:` block of .claude/vg.config.md.
#
# Problem solved: Phase 10 scope Round 2 proposed work on apps/rtb-engine/ (Rust)
# but config only declares surface `web` (paths=[apps/web, apps/api]). Workflow
# had no automated way to detect this mismatch → user had to notice.
#
# This helper scans a recommendation text for path references and diffs against
# declared surface paths. Emits JSON with missing surfaces + suggested names.
#
# Exposed functions:
#   detect_surface_gaps RECOMMENDATION_TEXT           → prints JSON to stdout
#   format_gap_narrative GAPS_JSON                    → human-readable summary
#   surface_gap_detector_is_enabled                   → true/false (config gate)

set -u

# Defaults — override via config
SURFACE_GAP_MIN_CONFIDENCE=0.6

# ─────────────────────────────────────────────────────────────────────────
# Parse surfaces: block from vg.config.md
# ─────────────────────────────────────────────────────────────────────────
_parse_declared_surfaces() {
  local config_file="${1:-.claude/vg.config.md}"
  [ -f "$config_file" ] || { echo '{"surfaces":[]}'; return; }

  "${PYTHON_BIN:-python3}" - "$config_file" <<'PY'
import json, re, sys
cfg_path = sys.argv[1]
try:
    text = open(cfg_path, encoding='utf-8').read()
except Exception as e:
    print(json.dumps({"surfaces":[], "error":str(e)}))
    sys.exit(0)

# Find surfaces: block (YAML-ish in markdown)
# Pattern: surfaces:\n  <name>:\n    paths: [...]\n    stack: "..."
m = re.search(r'^surfaces:\s*\n((?:[ \t]{2,}[^\n]+\n)+)', text, re.M)
if not m:
    print(json.dumps({"surfaces":[]}))
    sys.exit(0)

block = m.group(1)
surfaces = []
current = None
for line in block.split('\n'):
    # New surface name (2-space indent)
    sm = re.match(r'^  ([\w-]+):\s*$', line)
    if sm:
        if current:
            surfaces.append(current)
        current = {"name": sm.group(1), "paths": [], "stack": ""}
        continue
    if current is None: continue
    # paths: [a, b]
    pm = re.match(r'^    paths:\s*\[(.+?)\]', line)
    if pm:
        current["paths"] = [p.strip().strip('"\'') for p in pm.group(1).split(',')]
        continue
    # stack: "..."
    st = re.match(r'^    stack:\s*["\']?([^"\'\n]+)["\']?', line)
    if st:
        current["stack"] = st.group(1).strip()
if current:
    surfaces.append(current)

print(json.dumps({"surfaces": surfaces}))
PY
}


# ─────────────────────────────────────────────────────────────────────────
# Suggest surface name from observed path
# ─────────────────────────────────────────────────────────────────────────
_suggest_surface_name() {
  local path="$1"
  # Strip leading apps/ or packages/ and take next segment
  echo "$path" | "${PYTHON_BIN:-python3}" -c "
import sys, re
p = sys.stdin.read().strip()
m = re.match(r'^(apps|packages)/([\w-]+)', p)
if m:
    name = m.group(2)
    # Heuristic renames
    name = re.sub(r'-engine$', '', name)
    name = re.sub(r'-service$', '', name)
    print(name)
else:
    print(p.strip('/').split('/')[0])
"
}


# ─────────────────────────────────────────────────────────────────────────
# Main detector
# ─────────────────────────────────────────────────────────────────────────
detect_surface_gaps() {
  local recommendation="$1"
  local config_file="${2:-.claude/vg.config.md}"

  # Extract mentioned paths (apps/X, packages/X, infra/X)
  local mentioned
  mentioned=$(echo "$recommendation" | grep -oE '(apps|packages|infra)/[a-z0-9][a-z0-9_-]*' | sort -u || true)

  if [ -z "$mentioned" ]; then
    echo '{"missing_surfaces": [], "matched_surfaces": [], "mentioned_paths": []}'
    return 0
  fi

  # Parse declared surfaces
  local declared_json
  declared_json=$(_parse_declared_surfaces "$config_file")

  # Diff using Python for correctness
  MENTIONED="$mentioned" DECLARED="$declared_json" "${PYTHON_BIN:-python3}" - <<'PY'
import json, os, re
mentioned = [p for p in os.environ['MENTIONED'].split('\n') if p.strip()]
declared = json.loads(os.environ['DECLARED']).get('surfaces', [])

# Build path -> surface map from declared
declared_paths = {}
for s in declared:
    for p in s.get('paths', []):
        declared_paths[p.strip('/')] = s['name']

matched_surfaces = set()
missing = []

for path in mentioned:
    path = path.strip('/')
    # Exact match to declared path
    if path in declared_paths:
        matched_surfaces.add(declared_paths[path])
        continue
    # Check if path is prefix of any declared path or vice versa
    found = False
    for dp, sname in declared_paths.items():
        if path.startswith(dp + '/') or dp.startswith(path + '/') or path == dp:
            matched_surfaces.add(sname)
            found = True
            break
    if not found:
        missing.append(path)

# Dedupe missing + suggest surface name
suggested = {}
for path in missing:
    m = re.match(r'^(apps|packages|infra)/([\w-]+)', path)
    if m:
        name = m.group(2)
        # Heuristic: strip common suffixes
        name = re.sub(r'-engine$', '', name)
        name = re.sub(r'-service$', '', name)
    else:
        name = path.split('/')[-1]
    if name not in suggested:
        suggested[name] = {"suggested_name": name, "paths": [path]}
    else:
        if path not in suggested[name]['paths']:
            suggested[name]['paths'].append(path)

print(json.dumps({
    "mentioned_paths": mentioned,
    "matched_surfaces": sorted(matched_surfaces),
    "missing_surfaces": list(suggested.values()),
}, indent=2))
PY
}


# ─────────────────────────────────────────────────────────────────────────
# Format narrative for AskUserQuestion display
# ─────────────────────────────────────────────────────────────────────────
format_gap_narrative() {
  local gaps_json="$1"
  echo "$gaps_json" | "${PYTHON_BIN:-python3}" -c "
import json, sys
d = json.loads(sys.stdin.read())
missing = d.get('missing_surfaces', [])
matched = d.get('matched_surfaces', [])
if not missing:
    print(f'✓ All mentioned paths covered by declared surfaces: {matched}')
    sys.exit(0)
print(f'⚠ Surface gap detected:')
print(f'  Matched surfaces: {matched}')
print(f'  Missing — mentioned paths not covered by any declared surface:')
for g in missing:
    print(f'    • {g[\"suggested_name\"]} → {g[\"paths\"]}')
print()
print('  Config fix (vg.config.md):')
for g in missing:
    first_path = g['paths'][0]
    print(f'    surfaces.{g[\"suggested_name\"]}:')
    print(f'      paths: [{first_path}]')
    print(f'      stack: \"<tech>\"')
"
}


# ─────────────────────────────────────────────────────────────────────────
# Config gate
# ─────────────────────────────────────────────────────────────────────────
surface_gap_detector_is_enabled() {
  local config_file="${1:-.claude/vg.config.md}"
  # Enabled unless explicitly disabled via scope.surface_gap_detect: false
  grep -qE 'surface_gap_detect:\s*false' "$config_file" 2>/dev/null && return 1
  return 0
}

# If sourced standalone, no-op. Functions exported on demand.
