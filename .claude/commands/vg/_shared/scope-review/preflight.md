<!-- v2.74.0 T1-T3 extraction — verbatim step blocks from commands/vg/scope-review.md -->
<!-- Group: preflight | Steps: 0_parse_and_collect, incremental_check -->

<process>

<step name="0_parse_and_collect">
## Step 0: Parse arguments + collect phase data

```bash
# Parse arguments
SKIP_CROSSAI=false
PHASE_FILTER=""
FULL_RESCAN=false

for arg in $ARGUMENTS; do
  case "$arg" in
    --skip-crossai) SKIP_CROSSAI=true ;;
    --phases=*) PHASE_FILTER="${arg#--phases=}" ;;
    --full) FULL_RESCAN=true ;;
  esac
done
```

**Scan for scoped phases:**
```bash
SCOPED_PHASES=()
for dir in ${PHASES_DIR}/*/; do
  if [ -f "${dir}CONTEXT.md" ]; then
    PHASE_NAME=$(basename "$dir")
    # If --phases filter provided, only include matching phases
    if [ -n "$PHASE_FILTER" ]; then
      PHASE_NUM=$(echo "$PHASE_NAME" | grep -oE '^[0-9]+(\.[0-9]+)*')
      if echo ",$PHASE_FILTER," | grep -q ",${PHASE_NUM},"; then
        SCOPED_PHASES+=("$dir")
      fi
    else
      SCOPED_PHASES+=("$dir")
    fi
  fi
done
```

**Validate:**
- If 0 phases found -> BLOCK: "No phases with CONTEXT.md found. Run /vg:scope first."
- If 1 phase found -> WARN: "Only 1 phase scoped ({phase}). Cross-phase review works best with 2+ phases. Proceeding with single-phase structural check."

**Extract from each CONTEXT.md:**
For every scoped phase (filtered later by Step 0.5 if incremental), parse and collect:
- **Decisions:** D-XX title, category, full text
- **Endpoints:** method + path + auth role + purpose (from decision Endpoints: sub-sections)
- **Module names:** inferred from endpoint paths (e.g., `/api/v1/sites` -> sites module) and UI component names
- **Test scenarios:** TS-XX descriptions
- **Dependencies:** any "Depends on Phase X" or "Requires output from Phase X" mentions
- **Files/directories likely touched:** inferred from module names + `config.code_patterns` paths

Store all extracted data in a structured format for cross-referencing in Step 1.

**Also check for DONE phases:**
Scan for phases with completed PIPELINE-STATE.json (`steps.accept.status = "done"`) or existing UAT.md. These are "shipped" phases — used for scope creep detection (Check E).
</step>

<step name="incremental_check">
## Step 0.5: INCREMENTAL SCAN (baseline delta)

Purpose: narrow scan scope to phases whose CONTEXT.md / SPECS.md changed since last successful scope-review (baseline — mốc gốc). At 50+ phases full O(n²) rescan is too slow and users skip the gate; incremental (tăng cường theo delta) keeps it cheap so it runs every time.

**Baseline path:** `${PLANNING_DIR}/.scope-review-baseline.json`

**Schema:**
```json
{
  "ts": "2026-04-17T09:12:33Z",
  "phases": {
    "7.6": {"context_sha256": "abc...", "spec_sha256": "def..."},
    "7.8": {"context_sha256": "ghi...", "spec_sha256": "jkl..."}
  }
}
```

**Logic:**

```bash
BASELINE_PATH="${PLANNING_DIR}/.scope-review-baseline.json"
INCREMENTAL=true
SCAN_SET=()       # phase IDs to actually scan this run
SKIPPED_SET=()    # phase IDs unchanged since baseline
CHANGED_COUNT=0
NEW_COUNT=0
REMOVED_COUNT=0
BASELINE_TS="(none)"

if [ "$FULL_RESCAN" = "true" ]; then
  INCREMENTAL=false
  echo "ℹ Full rescan (--full) — bypassing baseline (mốc gốc bị bỏ qua)."
elif [ ! -f "$BASELINE_PATH" ]; then
  INCREMENTAL=false
  echo "ℹ No baseline (chưa có mốc gốc) — running full scan to seed baseline."
else
  # Compute current hashes + compare to baseline
  DELTA_JSON=$(${PYTHON_BIN:-python3} - "$BASELINE_PATH" "$PHASES_DIR" <<'PY'
import json, hashlib, sys, os
from pathlib import Path

baseline_path = Path(sys.argv[1])
phases_dir = Path(sys.argv[2])

baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
baseline_phases = baseline.get("phases", {})

def sha256_file(p):
    if not p.exists(): return None
    return hashlib.sha256(p.read_bytes()).hexdigest()

def phase_id(name):
    # e.g. "07.12-conversion-tracking-pixel" -> "7.12" ; "7.6-sites" -> "7.6"
    import re
    m = re.match(r'^0*([0-9]+(?:\.[0-9]+)*)', name)
    return m.group(1) if m else name

current = {}
for d in sorted(phases_dir.iterdir()):
    if not d.is_dir(): continue
    ctx = d / "CONTEXT.md"
    spec = d / "SPECS.md"
    if not ctx.exists(): continue  # only care about scoped phases
    pid = phase_id(d.name)
    current[pid] = {
        "context_sha256": sha256_file(ctx),
        "spec_sha256": sha256_file(spec),
        "dir_name": d.name,
    }

changed, new, removed, unchanged = [], [], [], []
for pid, info in current.items():
    base = baseline_phases.get(pid)
    if not base:
        new.append(pid)
    elif base.get("context_sha256") != info["context_sha256"] or \
         base.get("spec_sha256") != info["spec_sha256"]:
        changed.append(pid)
    else:
        unchanged.append(pid)
for pid in baseline_phases:
    if pid not in current:
        removed.append(pid)

print(json.dumps({
    "baseline_ts": baseline.get("ts", "(unknown)"),
    "changed": sorted(changed),
    "new": sorted(new),
    "removed": sorted(removed),
    "unchanged": sorted(unchanged),
    "current_map": {k: v["dir_name"] for k, v in current.items()},
}, ensure_ascii=False))
PY
)
  BASELINE_TS=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(json.loads(sys.stdin.read())['baseline_ts'])")
  CHANGED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['changed']))")
  NEW_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['new']))")
  REMOVED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['removed']))")
  UNCHANGED_LIST=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['unchanged']))")

  CHANGED_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['changed']))")
  NEW_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['new']))")
  REMOVED_COUNT=$(echo "$DELTA_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(len(json.loads(sys.stdin.read())['removed']))")

  if [ "$CHANGED_COUNT" = "0" ] && [ "$NEW_COUNT" = "0" ] && [ "$REMOVED_COUNT" = "0" ]; then
    echo "✓ No phases changed since ${BASELINE_TS}. Scope-review is already current."
    echo "  Use --full to force rescan."
    # Early-exit optimization: still emit telemetry + skip to baseline rewrite
    type emit_telemetry_v2 >/dev/null 2>&1 && \
      emit_telemetry_v2 "gate_hit" "" "scope-review.incremental" \
        "scope-review-incremental" "PASS" \
        "{\"changed_count\":0,\"new_count\":0,\"removed_count\":0,\"early_exit\":true,\"conflicts_found\":0}"
    # Still refresh baseline timestamp, then exit.
    # (baseline hashes unchanged; just bump ts)
    exit 0
  fi

  # Build SCAN_SET = changed + new + their dependents (ROADMAP.md "Depends on" cascade)
  SCAN_JSON=$(${PYTHON_BIN:-python3} - "$PLANNING_DIR" "$CHANGED_LIST" "$NEW_LIST" <<'PY'
import sys, re, json
from pathlib import Path

planning_dir = Path(sys.argv[1])
changed = [p for p in sys.argv[2].split(',') if p]
new = [p for p in sys.argv[3].split(',') if p]
seed = set(changed + new)

# Parse ROADMAP.md for "Depends on: X.Y, A.B" per phase row
roadmap = planning_dir / "ROADMAP.md"
deps_reverse = {}   # phase -> set of phases that depend ON it
if roadmap.exists():
    content = roadmap.read_text(encoding='utf-8', errors='ignore')
    # Strategy: find "Phase X.Y" heading followed by "Depends on: ..." within block
    # Supports: "Depends on: 7.6, 7.8" OR "- Depends on Phase 7.6"
    phase_blocks = re.split(r'^\s*#{1,4}\s*Phase\s+', content, flags=re.MULTILINE)
    for block in phase_blocks[1:]:
        head = re.match(r'([0-9]+(?:\.[0-9]+)*)', block)
        if not head: continue
        pid = head.group(1)
        # Find dependency mentions
        dep_matches = re.findall(
            r'[Dd]epends\s+on[:\s]+((?:Phase\s+)?[0-9.,\s]+)', block)
        for m in dep_matches:
            for dep in re.findall(r'([0-9]+(?:\.[0-9]+)*)', m):
                deps_reverse.setdefault(dep, set()).add(pid)

# Cascade: for every seed, add all phases that depend on it (transitive)
scan = set(seed)
frontier = set(seed)
while frontier:
    next_frontier = set()
    for pid in frontier:
        for dependent in deps_reverse.get(pid, []):
            if dependent not in scan:
                scan.add(dependent)
                next_frontier.add(dependent)
    frontier = next_frontier

print(json.dumps({"scan": sorted(scan)}, ensure_ascii=False))
PY
)
  SCAN_LIST=$(echo "$SCAN_JSON" | ${PYTHON_BIN:-python3} -c "import json,sys;print(','.join(json.loads(sys.stdin.read())['scan']))")

  # Narrow SCOPED_PHASES down to SCAN_LIST members
  NARROWED_PHASES=()
  IFS=',' read -ra SCAN_ARR <<< "$SCAN_LIST"
  for dir in "${SCOPED_PHASES[@]}"; do
    pname=$(basename "$dir")
    pnum=$(echo "$pname" | grep -oE '^0*[0-9]+(\.[0-9]+)*' | sed 's/^0*//')
    for target in "${SCAN_ARR[@]}"; do
      [ "$pnum" = "$target" ] && NARROWED_PHASES+=("$dir") && break
    done
  done
  # Track which phases were skipped
  IFS=',' read -ra UNCH_ARR <<< "$UNCHANGED_LIST"
  for u in "${UNCH_ARR[@]}"; do
    # Unchanged phases NOT pulled in as dependents of changed phases
    skipped=true
    for target in "${SCAN_ARR[@]}"; do
      [ "$u" = "$target" ] && skipped=false && break
    done
    $skipped && SKIPPED_SET+=("$u")
  done

  SCOPED_PHASES=("${NARROWED_PHASES[@]}")
  SCAN_SET=("${SCAN_ARR[@]}")

  echo ""
  echo "📊 Incremental scan (quét tăng cường theo delta): ${CHANGED_COUNT} phases changed since ${BASELINE_TS}, ${NEW_COUNT} new"
  echo "   Scope this run: [${SCAN_LIST}]"
  echo "   Skipped (unchanged — bỏ qua vì không đổi): ${#SKIPPED_SET[@]} phases"
  [ "$REMOVED_COUNT" != "0" ] && echo "   Removed from disk (xoá khỏi đĩa): ${REMOVED_LIST}"
  echo ""
fi
```

**Notes:**
- If `$PHASE_FILTER` is also set (from `--phases=...`), its filter intersects SCAN_SET (user explicit > baseline).
- Dependents cascade uses ROADMAP.md "Depends on" — if roadmap missing or phase not listed, no cascade (just changed+new).
- Early-exit when nothing changed saves the full Step 1 scan.
</step>

</process>
