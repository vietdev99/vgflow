# shellcheck shell=bash
# VG v1.9.1 R1 — Surface-driven goal classifier
# Lazy migration: on read, backfill `surface:` field on every goal in TEST-GOALS.md
# using multi-source heuristics (goal text + CONTEXT/API-CONTRACTS/SUMMARY/RUNTIME-MAP + grep).
#
# Contract:
#   classify_goals_if_needed TEST_GOALS_PATH PHASE_DIR
#     Returns 0 on success. Writes surface: field + stamps schema_version: "1.9.1".
#     Idempotent (schema_version >= 1.9.1 → skip).
#     Emits telemetry event `goals_classified` with payload
#       {phase, goals_count, auto, haiku_resolved, user_resolved, low_confidence}.
#
# Config surfaces come from vg.config.md.test_strategy.surfaces[*].detect_keywords.
# No project stack assumed.

# ── internal helpers ───────────────────────────────────────────────────────

_gc_python() { ${PYTHON_BIN:-python3} "$@"; }

# Print "surface=<name>\tconfidence=<0..1>\tevidence=<comma-list>" for one goal
# stdin: concatenated evidence text (goal block + decisions + endpoints + summary + runtime-map).
# args: $1 = surfaces JSON, $2 = default surface name
_gc_score_goal() {
  local _surfaces_json="${1:-${GC_SURFACES_JSON:-}}"
  local _default="${2:-${GC_DEFAULT_SURFACE:-ui}}"
  # stdin format: goal block, then `===CTX===` marker, then project-wide context.
  # Use `mktemp -t` so the path is one both bash and python agree on (avoids Windows /tmp drift).
  local tmp
  tmp=$(mktemp -t gc-score.XXXXXX 2>/dev/null) || tmp="${PWD}/.gc-score-$$.txt"
  cat > "$tmp"
  GC_SURFACES_JSON="$_surfaces_json" GC_DEFAULT_SURFACE="$_default" GC_BLOB_PATH="$tmp" \
    ${PYTHON_BIN:-python3} - <<'PY'
import json, os, re, sys
raw = open(os.environ["GC_BLOB_PATH"], encoding='utf-8', errors='replace').read()
if "===CTX===" in raw:
    goal_part, ctx_part = raw.split("===CTX===", 1)
else:
    goal_part, ctx_part = raw, ""
goal_blob = goal_part.lower()
ctx_blob  = ctx_part.lower()
surfaces = json.loads(os.environ.get("GC_SURFACES_JSON", "{}"))
default = os.environ.get("GC_DEFAULT_SURFACE", "ui")
scores = {}
evidence = {}
def count_hits(kw, blob):
    if kw.startswith("/") or "{" in kw or "}" in kw:
        return 1 if kw in blob else 0
    return 1 if re.search(r"(?<![a-z0-9_])" + re.escape(kw) + r"(?![a-z0-9_])", blob) else 0

for name, cfg in surfaces.items():
    kws = [k.lower() for k in cfg.get("keywords", []) if k]
    goal_hits, ctx_hits = [], []
    for kw in kws:
        if count_hits(kw, goal_blob): goal_hits.append(kw)
        elif count_hits(kw, ctx_blob): ctx_hits.append(kw)
    # Weight goal-text hits 3x vs project-context hits (avoid SUMMARY.md noise dominance).
    weight = 3 * len(goal_hits) + 1 * len(ctx_hits)
    if weight > 0:
        denom = max(4.0, len(kws) * 0.6) if kws else 4.0
        scores[name] = min(1.0, weight / denom)
        evidence[name] = goal_hits + ctx_hits
if not scores:
    print(f"surface={default}\tconfidence=0.30\tevidence=none")
    sys.exit(0)
winner = max(scores.items(), key=lambda kv: kv[1])
name, conf = winner
# Ambiguous tie-breaker: top 2 within 0.1 → lower confidence
ranked = sorted(scores.values(), reverse=True)
if len(ranked) > 1 and (ranked[0] - ranked[1]) < 0.10:
    conf = max(0.45, conf - 0.25)
ev = ",".join(evidence.get(name, []))[:120]
print(f"surface={name}\tconfidence={conf:.2f}\tevidence={ev}")
PY
  rm -f "$tmp" 2>/dev/null || true
}

# Build surfaces JSON from vg.config.md (cached per-run)
_gc_load_surfaces() {
  [ -n "${GC_SURFACES_JSON:-}" ] && return 0
  local cfg="${VG_CONFIG_PATH:-.claude/vg.config.md}"
  [ -f "$cfg" ] || { echo "{}"; return 1; }
  GC_SURFACES_JSON=$(_gc_python - "$cfg" <<'PY'
import re, sys, json
path = sys.argv[1]
try:
    txt = open(path, encoding='utf-8').read()
except Exception:
    print("{}"); sys.exit(0)
# Find test_strategy: block (YAML-ish embedded in markdown front-matter)
m = re.search(r'^test_strategy:\s*\n((?:[ \t]+.*\n?)+)', txt, re.M)
if not m:
    print("{}"); sys.exit(0)
block = m.group(1)
surfaces = {}
default = "ui"
dm = re.search(r'^\s*default_surface:\s*"?([a-zA-Z0-9_\-]+)"?', block, re.M)
if dm: default = dm.group(1)
# Parse surfaces:\n  <name>:\n    runner: "..."\n    detect_keywords: [...]
sm = re.search(r'^\s*surfaces:\s*\n((?:[ \t]+.*\n?)+)', block, re.M)
if sm:
    sblock = sm.group(1)
    # Split by surface names (keys indented same as first key)
    entries = re.findall(
        r'^( {2,6})([a-zA-Z][a-zA-Z0-9_\-]*):\s*\n((?:\1[ \t]+.*\n?)+)',
        sblock, re.M)
    for _indent, name, body in entries:
        runner_m = re.search(r'runner:\s*"?([^"\n]+)"?', body)
        kw_m = re.search(r'detect_keywords:\s*\[([^\]]*)\]', body)
        keywords = []
        if kw_m:
            keywords = [k.strip().strip('"').strip("'")
                        for k in kw_m.group(1).split(",") if k.strip()]
        surfaces[name] = {
            "runner": runner_m.group(1).strip() if runner_m else "",
            "keywords": keywords,
        }
print(json.dumps({"_default": default, "surfaces": surfaces}))
PY
)
  # Split wrapper → expose GC_DEFAULT_SURFACE + GC_SURFACES_JSON
  GC_DEFAULT_SURFACE=$(_gc_python -c "import json,sys;d=json.loads(sys.argv[1]);print(d.get('_default','ui'))" "$GC_SURFACES_JSON")
  GC_SURFACES_JSON=$(_gc_python -c "import json,sys;d=json.loads(sys.argv[1]);print(json.dumps(d.get('surfaces',{})))" "$GC_SURFACES_JSON")
  export GC_SURFACES_JSON GC_DEFAULT_SURFACE
}

# Gather evidence text for one goal (goal block + relevant excerpts).
# Output format: <goal-block>\n===CTX===\n<project-context>
# Scorer weights goal-block 3x vs context (avoids SUMMARY.md keyword pollution).
_gc_gather_evidence() {
  local goal_id="$1" phase_dir="$2" test_goals_path="$3"
  {
    # ─ Goal block only ─
    _gc_python - "$test_goals_path" "$goal_id" <<'PY'
import re, sys
txt = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'^## Goal ' + re.escape(sys.argv[2]) + r'\b.*?(?=^## Goal |^## Decision Coverage|\Z)',
              txt, re.M | re.S)
if m: print(m.group(0))
PY
    echo "===CTX==="
    # ─ Project-wide context (scored at lower weight) ─
    [ -f "$phase_dir/CONTEXT.md" ] && head -c 4000 "$phase_dir/CONTEXT.md"
    if [ -f "$phase_dir/API-CONTRACTS.md" ]; then
      grep -E '^#|^\s*(GET|POST|PUT|PATCH|DELETE)\s|/api/|/postback|/pixel|/health' \
        "$phase_dir/API-CONTRACTS.md" 2>/dev/null | head -n 30
    fi
    if [ -f "$phase_dir/RUNTIME-MAP.json" ]; then
      _gc_python -c "
import json,sys
try:
  d=json.load(open('$phase_dir/RUNTIME-MAP.json',encoding='utf-8'))
  for v in (d.get('views') or {}).keys(): print(v)
except Exception: pass
"
    fi
  } 2>/dev/null
}

# Write back TEST-GOALS with new surface: fields + schema_version stamp.
# Args: test_goals_path classifications_tsv
# classifications_tsv rows: goal_id<TAB>surface<TAB>confidence<TAB>source(auto|haiku|user)
_gc_apply_classifications() {
  local path="$1" tsv="$2"
  # Write TSV next to the target file (avoids argv-size limits AND cross-tool /tmp path drift on Windows).
  local tsv_path="${path}.gc-apply.tsv"
  printf '%s' "$tsv" > "$tsv_path"
  [ -n "${GC_DEBUG:-}" ] && { echo "[gc-debug] tsv head:"; head -3 "$tsv_path"; echo "[gc-debug] tsv lines: $(wc -l < "$tsv_path")"; } >&2
  GC_TSV_PATH="$tsv_path" _gc_python - "$path" <<'PY'
import os, re, sys
path = sys.argv[1]
tsv = open(os.environ["GC_TSV_PATH"], encoding='utf-8').read()
txt = open(path, encoding='utf-8').read()
rows = {}
for line in tsv.splitlines():
    if not line.strip(): continue
    parts = line.split("\t")
    if len(parts) < 4: continue
    rows[parts[0]] = (parts[1], parts[2], parts[3])

# Ensure frontmatter with schema_version
fm_match = re.match(r'^---\n(.*?)\n---\n', txt, re.S)
if fm_match:
    fm = fm_match.group(1)
    if re.search(r'^schema_version:', fm, re.M):
        fm2 = re.sub(r'^schema_version:.*$', 'schema_version: "1.9.1"', fm, flags=re.M)
    else:
        fm2 = fm + '\nschema_version: "1.9.1"'
    txt = txt.replace(fm_match.group(0), f'---\n{fm2}\n---\n', 1)
else:
    txt = f'---\nschema_version: "1.9.1"\n---\n' + txt

def inject(block, gid):
    if gid not in rows: return block
    surface, conf, source = rows[gid]
    # If already has surface: line, replace; else insert after **Priority:** line
    if re.search(r'^\*\*Surface:\*\*', block, re.M):
        block = re.sub(r'^\*\*Surface:\*\*.*$',
                       f'**Surface:** {surface} (confidence {conf}, via {source})',
                       block, count=1, flags=re.M)
    else:
        block = re.sub(r'(^\*\*Priority:\*\*[^\n]*\n)',
                       r'\1' + f'**Surface:** {surface} (confidence {conf}, via {source})\n',
                       block, count=1, flags=re.M)
    return block

def goal_sub(m):
    header = m.group(0).splitlines()[0]
    gid_m = re.search(r'G-\d+', header)
    if not gid_m: return m.group(0)
    return inject(m.group(0), gid_m.group(0))

txt = re.sub(r'^## Goal G-\d+\b.*?(?=^## Goal |^## Decision Coverage|\Z)',
             goal_sub, txt, flags=re.M | re.S)
with open(path, 'w', encoding='utf-8') as f:
    f.write(txt)
PY
  # Cleanup staging TSV
#DISABLED rm -f "$tsv_path" 2>/dev/null || true
}

# Read current schema_version (empty if none)
_gc_read_schema_version() {
  _gc_python - "$1" <<'PY'
import re, sys
try:
  txt = open(sys.argv[1], encoding='utf-8').read()
except Exception:
  sys.exit(0)
m = re.search(r'^schema_version:\s*"?([0-9A-Za-z.\-]+)"?', txt, re.M)
if m: print(m.group(1))
PY
}

# List goal IDs currently missing `**Surface:**` field
_gc_list_ungraded_goals() {
  _gc_python - "$1" <<'PY'
import re, sys
try:
  txt = open(sys.argv[1], encoding='utf-8').read()
except Exception:
  sys.exit(0)
for m in re.finditer(r'^## Goal (G-\d+)\b.*?(?=^## Goal |^## Decision Coverage|\Z)',
                      txt, re.M | re.S):
    block = m.group(0)
    if not re.search(r'^\*\*Surface:\*\*', block, re.M):
        print(m.group(1))
PY
}

# ── public API ─────────────────────────────────────────────────────────────

# classify_goals_if_needed TEST_GOALS_PATH PHASE_DIR
# Behaviour:
#   - schema_version >= 1.9.1 → return 0 (skip)
#   - otherwise: heuristic classify; confidence >= 0.8 auto-assign;
#     0.5..0.8 → orchestrator MUST invoke Haiku subagent (returns code 2 with a
#     pending-list emitted on fd 3 so caller dispatches Task tool);
#     < 0.5 → orchestrator MUST AskUserQuestion inline (code 3).
classify_goals_if_needed() {
  local test_goals_path="$1" phase_dir="$2"
  [ -f "$test_goals_path" ] || { echo "goal-classifier: TEST-GOALS.md missing at $test_goals_path" >&2; return 0; }

  local ver
  ver=$(_gc_read_schema_version "$test_goals_path" 2>/dev/null)
  # Compare semver-ish (string >= "1.9.1" works lexicographically for 1.x)
  if [ -n "$ver" ]; then
    case "$ver" in
      1.9.1|1.9.[2-9]|1.[9][0-9]*|[2-9].*) return 0 ;;
    esac
  fi

  _gc_load_surfaces

  local goals_raw auto=0 haiku=0 low=0
  goals_raw=$(_gc_list_ungraded_goals "$test_goals_path")
  [ -z "$goals_raw" ] && return 0

  local tsv="" pending=""
  while IFS= read -r gid; do
    gid="${gid%$'\r'}"   # strip CR if input arrived as CRLF (Windows)
    [ -z "$gid" ] && continue
    local evidence
    evidence=$(_gc_gather_evidence "$gid" "$phase_dir" "$test_goals_path")
    local result
    result=$(printf '%s' "$evidence" | _gc_score_goal "$GC_SURFACES_JSON" "$GC_DEFAULT_SURFACE")
    local surface conf evline
    surface=$(echo "$result" | sed -n 's/^surface=\([^\t]*\).*/\1/p')
    conf=$(echo "$result" | sed -n 's/.*confidence=\([0-9.]*\).*/\1/p')
    evline=$(echo "$result" | sed -n 's/.*evidence=\(.*\)/\1/p')
    # Classify by confidence buckets
    if awk "BEGIN{exit !($conf >= 0.8)}"; then
      tsv="${tsv}${gid}\t${surface}\t${conf}\tauto\n"
      auto=$((auto+1))
    elif awk "BEGIN{exit !($conf >= 0.5)}"; then
      pending="${pending}${gid}\t${surface}\t${conf}\t${evline}\n"
      haiku=$((haiku+1))
    else
      pending="${pending}${gid}\tLOW\t${conf}\t${evline}\n"
      low=$((low+1))
    fi
  done <<EOF
$goals_raw
EOF

  # Write auto classifications immediately
  if [ -n "$tsv" ]; then
    local tsv_flat
    tsv_flat=$(printf '%b' "$tsv")
    [ -n "${GC_DEBUG:-}" ] && echo "[gc-debug] applying tsv rows=$(echo -n "$tsv_flat" | grep -c .)" >&2
    _gc_apply_classifications "$test_goals_path" "$tsv_flat"
  fi

  # Emit telemetry
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    local phase_id
    phase_id=$(basename "$phase_dir" | sed -E 's/^([0-9.]+).*/\1/')
    local total=$((auto + haiku + low))
    emit_telemetry_v2 "goals_classified" "$phase_id" "classify" "goal-surface" "AUTO" \
      "{\"goals_count\":${total},\"auto\":${auto},\"haiku_pending\":${haiku},\"low_confidence\":${low}}"
  fi

  # Report pending (Haiku / user) via fd 3 if caller listens; always on stderr.
  if [ -n "$pending" ]; then
    local pending_flat
    pending_flat=$(printf '%b' "$pending")
    # fd 3 handoff (orchestrator reads; silent if not redirected).
    # Use a subshell so the fd-3 probe doesn't break `set -e` callers.
    ( printf '%s' "$pending_flat" >&3 ) 2>/dev/null || true
    # Also persist to a discoverable file so orchestrator commands can pick it up deterministically.
    local pending_path="${phase_dir}/.goal-classifier-pending.tsv"
    mkdir -p "$phase_dir" 2>/dev/null || true
    printf '%s' "$pending_flat" > "$pending_path"
    # Narrated summary
    echo "🎯 Goal classifier: ${auto} auto, ${haiku} cần Haiku (tie-break), ${low} cần user (low confidence)." >&2
    # Return 2 if only Haiku-range, 3 if any low-confidence requires user
    [ "$low" -gt 0 ] && return 3
    [ "$haiku" -gt 0 ] && return 2
  else
    echo "🎯 Goal classifier: ${auto}/${auto} goals auto-classified (confidence ≥ 0.8)." >&2
  fi
  return 0
}

# Helper: caller merges Haiku/user verdicts back by calling
#   classify_goals_apply TEST_GOALS_PATH  "G-12\tapi\t0.90\thaiku\nG-13\tdata\t1.00\tuser\n"
classify_goals_apply() {
  local path="$1" tsv="$2"
  _gc_apply_classifications "$path" "$(printf '%b' "$tsv")"
  # Re-stamp schema_version when all goals covered.
  local remaining
  remaining=$(_gc_list_ungraded_goals "$path")
  [ -z "$remaining" ] || echo "goal-classifier: ${remaining} goals still missing surface:" >&2
}

export -f classify_goals_if_needed classify_goals_apply 2>/dev/null || true
