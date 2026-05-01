#!/bin/bash
# amendment-preflight.sh — detect+apply config amendments locked in scope
# before blueprint runs. Prevents "scope said add `rtb` surface but nobody
# edited vg.config.md → blueprint runs with stale config".
#
# Exposed functions:
#   amendment_scan PHASE_DIR                          → emit JSON array on stdout
#   amendment_block_if_pending PHASE_DIR CONFIG MODE  → preflight gate (block|apply|warn)
#
# Called by: blueprint.md Step 0 (new)

set -u

# ─────────────────────────────────────────────────────────────────────────
# Scanner — PIPELINE-STATE.json `config_amendments_needed` is authoritative.
# Enriches each entry from CONTEXT.md decisions if a YAML snippet exists.
# Never false-positives on generic config mentions.
# ─────────────────────────────────────────────────────────────────────────
amendment_scan() {
  local phase_dir="$1"
  local context="${phase_dir}/CONTEXT.md"
  local state="${phase_dir}/PIPELINE-STATE.json"

  [ -f "$state" ] || { echo '[]'; return 0; }

  "${PYTHON_BIN:-python3}" - "$context" "$state" <<'PY'
import json, re, sys
from pathlib import Path

ctx_path = Path(sys.argv[1])
state_path = Path(sys.argv[2])

try:
    state = json.loads(state_path.read_text(encoding='utf-8'))
except Exception:
    print('[]'); sys.exit(0)

pending = state.get('steps', {}).get('scope', {}).get('config_amendments_needed', [])
if not pending:
    print('[]'); sys.exit(0)

ctx = ctx_path.read_text(encoding='utf-8') if ctx_path.exists() else ''

# Map each pending entry to a structured amendment
results = []
for raw in pending:
    amendment = {
        'raw': raw,
        'summary': raw,
    }
    # Heuristic: parse "add <name> surface to vg.config.md"
    surf_m = re.search(r'add\s+(?:surface\s+)?[\'"`]?(\w[\w-]*)[\'"`]?\s+surface\s+to', raw, re.I)
    if not surf_m:
        surf_m = re.search(r'add\s+surface\s+[\'"`]?(\w[\w-]*)[\'"`]?', raw, re.I)
    if surf_m:
        surface_name = surf_m.group(1)
        amendment['type'] = 'add_surface'
        amendment['surface_name'] = surface_name

        # Look for YAML snippet in CONTEXT decisions mentioning this surface name
        # Parse each decision block, check if it contains `<surface>:` as new key
        paths = []
        for dec in re.finditer(r'^### (P[\w.]+\.D-\d+): ([^\n]+)\n(.+?)(?=^### |\Z)', ctx, re.M | re.S):
            body = dec.group(3)
            # Look for YAML-like block with our surface name
            pattern = rf'^\s+{re.escape(surface_name)}:\s*\n((?:\s+[^\n]+\n)+)'
            block_m = re.search(pattern, body, re.M)
            if block_m:
                path_m = re.search(r'paths:\s*\[([^\]]+)\]', block_m.group(1))
                if path_m:
                    paths = [p.strip().strip('"\' ') for p in path_m.group(1).split(',')]
                stack_m = re.search(r'stack:\s*["\']?([^"\'\n]+)', block_m.group(1))
                if stack_m:
                    amendment['stack'] = stack_m.group(1).strip()
                amendment['decision_id'] = dec.group(1)
                break
        amendment['paths'] = paths
    else:
        amendment['type'] = 'generic'

    results.append(amendment)

print(json.dumps(results, indent=2))
PY
}


# ─────────────────────────────────────────────────────────────────────────
# Verify a single amendment applied
# ─────────────────────────────────────────────────────────────────────────
amendment_verify_applied() {
  local amendment_json="$1"
  local config_file="${2:-.claude/vg.config.md}"

  echo "$amendment_json" | "${PYTHON_BIN:-python3}" - "$config_file" <<'PY'
import json, re, sys
amendment = json.loads(sys.stdin.read())
cfg_path = sys.argv[1]
try:
    cfg = open(cfg_path, encoding='utf-8').read()
except Exception:
    sys.exit(1)
t = amendment.get('type', 'generic')
if t == 'add_surface':
    name = amendment['surface_name']
    if re.search(rf'^surfaces:[\s\S]+?^  {re.escape(name)}:', cfg, re.M):
        sys.exit(0)
    sys.exit(1)
sys.exit(1)  # generic: cannot verify
PY
}


# ─────────────────────────────────────────────────────────────────────────
# Apply add_surface amendment
# ─────────────────────────────────────────────────────────────────────────
amendment_apply() {
  local amendment_json="$1"
  local config_file="${2:-.claude/vg.config.md}"

  echo "$amendment_json" | "${PYTHON_BIN:-python3}" - "$config_file" <<'PY'
import json, re, sys
a = json.loads(sys.stdin.read())
cfg_path = sys.argv[1]

if a.get('type') != 'add_surface':
    print(f"⚠ Amendment type '{a.get('type')}' requires manual edit", file=sys.stderr)
    sys.exit(2)

cfg = open(cfg_path, encoding='utf-8').read()
name = a['surface_name']
paths = a.get('paths', [])
stack = a.get('stack', '<FILL-IN>')

m = re.search(r'^(surfaces:\s*\n)((?:[ \t]{2,}[^\n]+\n)+)', cfg, re.M)
if not m:
    print(f"⚠ No surfaces: block in {cfg_path}", file=sys.stderr)
    sys.exit(1)

if re.search(rf'^  {re.escape(name)}:', m.group(2), re.M):
    print(f"✓ Surface '{name}' already applied")
    sys.exit(0)

paths_str = ', '.join(f'"{p}"' for p in paths) if paths else ''
insertion = f"  {name}:\n    type: \"service\"\n    paths: [{paths_str}]\n    stack: \"{stack}\"\n"

new_cfg = cfg[:m.end()] + insertion + cfg[m.end():]
open(cfg_path, 'w', encoding='utf-8').write(new_cfg)
print(f"✓ Applied: added surface '{name}' with paths {paths}, stack='{stack}'")
sys.exit(0)
PY
}


# ─────────────────────────────────────────────────────────────────────────
# Main preflight gate
# ─────────────────────────────────────────────────────────────────────────
amendment_block_if_pending() {
  local phase_dir="$1"
  local config_file="${2:-.claude/vg.config.md}"
  local mode="${3:-block}"  # block | apply | warn

  local amendments
  amendments=$(amendment_scan "$phase_dir")
  local count
  count=$(echo "$amendments" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)

  if [ "$count" -eq 0 ]; then
    return 0
  fi

  # Compute unapplied via single Python pass (avoid pipe scoping issues)
  local unapplied_json
  unapplied_json=$("${PYTHON_BIN:-python3}" - "$amendments" "$config_file" <<'PY'
import json, re, sys
amendments = json.loads(sys.argv[1])
cfg = open(sys.argv[2], encoding='utf-8').read()
unapplied = []
for a in amendments:
    if a.get('type') == 'add_surface':
        name = a['surface_name']
        if not re.search(rf'^  {re.escape(name)}:', cfg, re.M):
            unapplied.append(a)
    else:
        unapplied.append(a)  # generic cannot auto-verify
print(json.dumps(unapplied))
PY
)

  local unapplied_count
  unapplied_count=$(echo "$unapplied_json" | "${PYTHON_BIN:-python3}" -c "import json,sys;print(len(json.loads(sys.stdin.read())))")

  echo "━━━ Scope-locked config amendments (${count} total, ${unapplied_count} pending) ━━━"
  echo "$amendments" | "${PYTHON_BIN:-python3}" -c "
import json, sys
for a in json.loads(sys.stdin.read()):
    sid = a.get('decision_id', '?')
    t = a.get('type', 'generic')
    print(f'  • [{t}] {sid}: {a.get(\"summary\",\"?\")}')"

  if [ "$unapplied_count" -eq 0 ]; then
    echo "✓ All amendments already applied"
    return 0
  fi

  case "$mode" in
    apply)
      echo ""
      echo "Mode: apply — auto-applying ${unapplied_count} amendment(s)..."
      # Heredoc overrides stdin so pass JSON via argv (fixes Windows git bash pipe/heredoc clash)
      "${PYTHON_BIN:-python3}" - "$unapplied_json" "$config_file" <<'PY'
import json, re, sys
unapplied = json.loads(sys.argv[1])
cfg_path = sys.argv[2]
cfg = open(cfg_path, encoding='utf-8').read()
for a in unapplied:
    if a.get('type') != 'add_surface':
        print(f"⚠ {a.get('decision_id','?')} type={a.get('type')} requires manual edit", file=sys.stderr)
        continue
    name = a['surface_name']
    paths = a.get('paths', [])
    stack = a.get('stack', '<FILL-IN>')
    if re.search(rf'^  {re.escape(name)}:', cfg, re.M):
        print(f"✓ Surface '{name}' already present — skip")
        continue
    m = re.search(r'^(surfaces:\s*\n)((?:[ \t]{2,}[^\n]+\n)+)', cfg, re.M)
    if not m:
        print(f"⚠ No surfaces: block found in config — cannot apply '{name}'", file=sys.stderr)
        continue
    paths_str = ', '.join(f'"{p}"' for p in paths) if paths else ''
    insertion = f"  {name}:\n    type: \"service\"\n    paths: [{paths_str}]\n    stack: \"{stack}\"\n"
    cfg = cfg[:m.end()] + insertion + cfg[m.end():]
    print(f"✓ Applied: surface '{name}' with paths {paths} stack={stack}")
open(cfg_path, 'w', encoding='utf-8').write(cfg)
PY
      return 0
      ;;
    warn)
      echo "⚠ ${unapplied_count} amendment(s) unapplied — proceeding anyway (debt mode)"
      return 0
      ;;
    block|*)
      echo ""
      echo "⛔ ${unapplied_count} unapplied config amendment(s) block blueprint."
      echo ""
      echo "Fix options:"
      echo "  (a) Auto-apply: re-run blueprint with --apply-amendments"
      echo "  (b) Manual: edit ${config_file} per decision bodies, then re-run"
      echo "  (c) Override: --skip-amendment-check (creates debt)"
      return 1
      ;;
  esac
}
