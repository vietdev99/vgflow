---
name: vg:doctor
description: Health check + integrity validator + recovery guide — read-only state inspector for VG pipeline
argument-hint: "[phase] [--integrity|--gates|--recover {phase}] [--apply]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Use markdown headers in your text output between tool calls (e.g. `## ━━━ Checking phase 07.12 ━━━`). Long Bash > 30s → `run_in_background: true` + `BashOutput` polls.

**Translate English terms (RULE)** — output có thuật ngữ tiếng Anh PHẢI thêm giải thích VN trong dấu ngoặc tại lần đầu xuất hiện. Tham khảo `_shared/term-glossary.md`. Ví dụ: `manifest (kê khai)`, `integrity (toàn vẹn)`, `recovery (khôi phục)`, `gates (cổng)`, `override (bỏ qua)`, `debt (nợ kỹ thuật)`, `corruption (hư hỏng)`, `stuck (tắc nghẽn)`. Không áp dụng: file path (`PIPELINE-STATE.json`), code identifier (`D-XX`, `PASS/FAIL`).
</NARRATION_POLICY>

<rules>
1. **Read-only by default** — base command, `{phase}`, `--integrity`, `--gates` modes NEVER modify any file. No writes, no deletes, no git operations.
2. **`--recover` is suggest-only** unless `--apply` flag also present. Default: print recovery commands for user to run manually. Với `--apply` + explicit second confirm → may run safe helpers.
3. **Delegate to shared helpers** — don't reinvent validation/query logic. Reuse `artifact_manifest_validate`, `telemetry_query`, `telemetry_warn_overrides`.
4. **Structured output** — tables not raw dumps. Every issue gets 1-line actionable recommendation.
5. **No side effects on telemetry itself** — `/vg:doctor` emits at most one `doctor_run` event per invocation (so inspector calls don't inflate gate override counts).
6. **Fail gracefully** — missing manifests, missing telemetry, missing phases → WARN + continue. Never exit 1 unless user misuse (bad args).
</rules>

<objective>
One-stop state inspector (kiểm tra trạng thái) for the VG pipeline. Answers four questions without making user parse raw logs:

1. **Is the project healthy?** (full mode)
2. **Why is phase X stuck?** (phase mode)
3. **Are any artifacts corrupted?** (`--integrity`)
4. **Which gates fire most often?** (`--gates`)
5. **How do I un-break phase X?** (`--recover {phase}`)

All heavy lifting via `_shared/artifact-manifest.md` + `_shared/telemetry.md` helpers. This command is a thin router + pretty-printer on top.
</objective>

<process>

<step name="0_parse_args">
## Step 0: Parse args + load shared helpers

```bash
PLANNING_DIR=".planning"
PHASES_DIR="${PLANNING_DIR}/phases"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
DEBT_REGISTER="${PLANNING_DIR}/OVERRIDE-DEBT.md"
DRIFT_REGISTER="${PLANNING_DIR}/DRIFT-REGISTER.md"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Load shared helpers (define artifact_manifest_validate, telemetry_query, telemetry_warn_overrides)
source .claude/commands/vg/_shared/artifact-manifest.md 2>/dev/null || true
source .claude/commands/vg/_shared/telemetry.md 2>/dev/null || true

# Parse args
MODE="full"
PHASE_ARG=""
APPLY_FLAG=false

for arg in $ARGUMENTS; do
  case "$arg" in
    --integrity)  MODE="integrity" ;;
    --gates)      MODE="gates" ;;
    --recover)    MODE="recover" ;;
    --apply)      APPLY_FLAG=true ;;
    --*)          echo "⚠ Unknown flag: $arg" ;;
    *)            PHASE_ARG="$arg" ;;
  esac
done

# Phase-arg implies phase mode unless other mode already set
if [ -n "$PHASE_ARG" ] && [ "$MODE" = "full" ]; then
  MODE="phase"
fi

# Validate recover needs phase arg
if [ "$MODE" = "recover" ] && [ -z "$PHASE_ARG" ]; then
  echo "⛔ --recover requires {phase} argument (e.g. /vg:doctor --recover 07.12)"
  exit 1
fi

export VG_CURRENT_COMMAND="vg:doctor"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "🩺 ━━━ /vg:doctor — Mode: ${MODE} ━━━"
echo ""
```
</step>

<step name="1_full_health_check">
## Step 1 (mode=full): Project-level health check

Runs only when `MODE=full` (no args). Sequential pass over all phases + cross-cutting registers.

```bash
if [ "$MODE" = "full" ]; then
  echo "## Project health overview"
  echo ""

  # Discover phases
  PHASE_DIRS=()
  if [ -d "$PHASES_DIR" ]; then
    while IFS= read -r d; do
      [ -d "$d" ] && PHASE_DIRS+=("$d")
    done < <(find "$PHASES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
  fi

  if [ ${#PHASE_DIRS[@]} -eq 0 ]; then
    echo "⚠ No phases found under ${PHASES_DIR}. Run /vg:roadmap hoặc /vg:add-phase."
    echo ""
  else
    echo "| Phase | Manifest | Last command | Unresolved overrides | Recommended action |"
    echo "|-------|----------|--------------|----------------------|--------------------|"

    for phase_dir in "${PHASE_DIRS[@]}"; do
      phase_name=$(basename "$phase_dir")
      phase_num=$(echo "$phase_name" | grep -oE '^[0-9.]+')

      # Manifest status (validate silent — capture exit code only)
      manifest_status="?"
      if type artifact_manifest_validate >/dev/null 2>&1; then
        artifact_manifest_validate "$phase_dir" >/dev/null 2>&1
        case $? in
          0) manifest_status="✓ valid" ;;
          1) manifest_status="⚠ legacy (missing)" ;;
          2) manifest_status="⛔ corruption" ;;
        esac
      else
        manifest_status="? helper unavailable"
      fi

      # Last telemetry command
      last_cmd="—"
      if [ -f "$TELEMETRY_PATH" ]; then
        last_cmd=$(${PYTHON_BIN} - "$TELEMETRY_PATH" "$phase_num" <<'PY' 2>/dev/null
import json, sys
path, phs = sys.argv[1], sys.argv[2]
last = None
try:
  for line in open(path, encoding='utf-8'):
    try:
      ev = json.loads(line)
      if ev.get("phase") == phs:
        last = ev
    except: pass
except: pass
print(last.get("command", "—") if last else "—")
PY
)
      fi

      # Unresolved overrides for this phase
      unresolved=0
      if [ -f "$DEBT_REGISTER" ]; then
        unresolved=$(grep -cE "\| .*\| ${phase_num} \|.*\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
      fi

      # Recommended action
      action="—"
      case "$manifest_status" in
        *corruption*) action="/vg:doctor --recover ${phase_num}" ;;
        *legacy*)     action="next read auto-backfills" ;;
        *valid*)
          if [ "$unresolved" -gt 0 ]; then
            action="review OVERRIDE-DEBT.md entries"
          fi
          ;;
      esac

      printf "| %s | %s | %s | %s | %s |\n" "$phase_num" "$manifest_status" "$last_cmd" "$unresolved" "$action"
    done
    echo ""
  fi

  # Cross-cutting: telemetry override warning
  echo "## Gate override pressure (áp lực bỏ qua cổng)"
  echo ""
  if type telemetry_warn_overrides >/dev/null 2>&1; then
    telemetry_warn_overrides 2 || echo "   (no gates exceed threshold)"
  else
    echo "   (telemetry helper unavailable)"
  fi
  echo ""

  # Override debt register summary
  echo "## Override debt register (sổ nợ bỏ qua)"
  echo ""
  if [ -f "$DEBT_REGISTER" ]; then
    open_count=$(grep -cE "\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    escalated=$(grep -cE "\| ESCALATED \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    echo "   Open: ${open_count}   Escalated: ${escalated}"
    [ "$escalated" -gt 0 ] && echo "   ⚠ Escalated entries block /vg:accept. Resolve hoặc run /vg:doctor --recover."
  else
    echo "   (no debt register — clean state)"
  fi
  echo ""

  # Drift register (T6 produces this)
  echo "## Drift register (sổ lệch hướng)"
  echo ""
  if [ -f "$DRIFT_REGISTER" ]; then
    unfixed=$(grep -cE "^\| .* \| (info|warn) \| .* \| (?!resolved)" "$DRIFT_REGISTER" 2>/dev/null || echo 0)
    echo "   Unfixed drift entries: ${unfixed}"
    [ "$unfixed" -gt 0 ] && echo "   Recommended: /vg:project --update để re-lock foundation."
  else
    echo "   (no drift register — clean state)"
  fi
  echo ""

  echo "## Next actions"
  echo "   • Deep phase inspection:  /vg:doctor {phase}"
  echo "   • Artifact integrity sweep: /vg:doctor --integrity"
  echo "   • Gate statistics:        /vg:doctor --gates"
  echo "   • Guided recovery:        /vg:doctor --recover {phase}"
  echo ""
fi
```
</step>

<step name="2_phase_deep_inspection">
## Step 2 (mode=phase): Deep inspection of one phase

```bash
if [ "$MODE" = "phase" ]; then
  phase_dir=""
  # Locate phase directory by prefix
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      phase_dir="$d"
      break
    fi
  done

  if [ -z "$phase_dir" ]; then
    echo "⛔ Phase ${PHASE_ARG} not found under ${PHASES_DIR}"
    exit 1
  fi

  echo "## Phase ${PHASE_ARG} — deep inspection"
  echo ""
  echo "  Directory: ${phase_dir}"
  echo ""

  # 2a. Artifact manifest detail
  echo "### Artifacts + manifest (kê khai)"
  echo ""
  manifest_path="${phase_dir}/.artifact-manifest.json"
  if [ -f "$manifest_path" ]; then
    ${PYTHON_BIN} - "$phase_dir" "$manifest_path" <<'PY'
import json, sys, hashlib
from pathlib import Path
phase_dir = Path(sys.argv[1])
m = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
print(f"  Manifest version: {m.get('manifest_version', '?')}")
print(f"  Generated by:     {m.get('generated_by', '?')}")
print(f"  Generated at:     {m.get('generated_at', '?')}")
print(f"  Artifact count:   {len(m.get('artifacts', []))}")
print()
print("  | Artifact | Size | Lines | Integrity |")
print("  |----------|------|-------|-----------|")
for art in m.get("artifacts", []):
    abs_path = phase_dir / art["path"]
    if not abs_path.exists():
        status = "⛔ missing"
    else:
        actual = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        status = "✓" if actual == art["sha256"] else "⛔ mismatch"
    print(f"  | {art['path']} | {art.get('bytes', '?')}B | {art.get('lines', '?')} | {status} |")
PY
  else
    echo "  ⚠ No manifest (legacy phase). Next read auto-backfills."
    # List actual files anyway
    echo ""
    echo "  Files present:"
    find "$phase_dir" -maxdepth 1 -type f \( -name '*.md' -o -name '*.json' \) | sort | sed 's|^|    |'
  fi
  echo ""

  # 2b. Last 10 telemetry events
  echo "### Recent telemetry events (last 10)"
  echo ""
  if type telemetry_query >/dev/null 2>&1 && [ -f "$TELEMETRY_PATH" ]; then
    telemetry_query --phase="${PHASE_ARG}" | tail -10 | \
      ${PYTHON_BIN} - <<'PY' 2>/dev/null
import json, sys
print("  | Timestamp | Command | Step | Gate | Outcome |")
print("  |-----------|---------|------|------|---------|")
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      ts = ev.get("ts", "?")[:19]
      cmd = ev.get("command", "?")
      step = ev.get("step", "?")
      gate = ev.get("gate_id") or "—"
      outc = ev.get("outcome") or ev.get("event_type", "?")
      print(f"  | {ts} | {cmd} | {step} | {gate} | {outc} |")
    except: pass
PY
  else
    echo "  (no telemetry — either helper unavailable or no events for this phase)"
  fi
  echo ""

  # 2c. Pipeline state
  echo "### Pipeline state"
  echo ""
  pipeline_state="${phase_dir}/PIPELINE-STATE.json"
  if [ -f "$pipeline_state" ]; then
    ${PYTHON_BIN} - "$pipeline_state" <<'PY'
import json, sys
s = json.loads(open(sys.argv[1], encoding='utf-8').read())
for k, v in s.items():
    if isinstance(v, (dict, list)):
        v = json.dumps(v)[:80]
    print(f"  • {k}: {v}")
PY
  else
    echo "  (no PIPELINE-STATE.json — phase may be new or pre-v1.8.0)"
  fi
  echo ""

  # 2d. Recommended next action
  echo "### Recommended next action"
  echo ""
  # Heuristic: look for common artifacts to guess step
  if [ -f "${phase_dir}/UAT.md" ]; then
    echo "  ✓ Phase complete. Move to next phase: /vg:next"
  elif [ -f "${phase_dir}/SANDBOX-TEST.md" ]; then
    echo "  → Run /vg:accept ${PHASE_ARG}"
  elif [ -f "${phase_dir}/RUNTIME-MAP.json" ]; then
    echo "  → Run /vg:test ${PHASE_ARG}"
  elif ls "${phase_dir}"/SUMMARY*.md >/dev/null 2>&1; then
    echo "  → Run /vg:review ${PHASE_ARG}"
  elif [ -f "${phase_dir}/PLAN.md" ] || ls "${phase_dir}"/PLAN*.md >/dev/null 2>&1; then
    echo "  → Run /vg:build ${PHASE_ARG}"
  elif [ -f "${phase_dir}/CONTEXT.md" ]; then
    echo "  → Run /vg:blueprint ${PHASE_ARG}"
  elif [ -f "${phase_dir}/SPECS.md" ]; then
    echo "  → Run /vg:scope ${PHASE_ARG}"
  else
    echo "  → Run /vg:specs ${PHASE_ARG}"
  fi
  echo ""
fi
```
</step>

<step name="3_integrity_mode">
## Step 3 (mode=integrity): Hash-validate every artifact

```bash
if [ "$MODE" = "integrity" ]; then
  echo "## Integrity sweep (quét toàn vẹn) — all phases"
  echo ""

  total=0; valid=0; legacy=0; corrupt=0
  issues=()

  for phase_dir in "${PHASES_DIR}"/*; do
    [ -d "$phase_dir" ] || continue
    total=$((total + 1))
    phase_name=$(basename "$phase_dir")

    if type artifact_manifest_validate >/dev/null 2>&1; then
      output=$(artifact_manifest_validate "$phase_dir" 2>&1)
      case $? in
        0) valid=$((valid + 1)) ;;
        1) legacy=$((legacy + 1)) ;;
        2)
          corrupt=$((corrupt + 1))
          issues+=("${phase_name}: ${output}")
          ;;
      esac
    fi
  done

  echo "  Total phases: ${total}"
  echo "  ✓ Valid:      ${valid}"
  echo "  ⚠ Legacy:     ${legacy}  (auto-backfills on next read — no action needed)"
  echo "  ⛔ Corruption: ${corrupt}"
  echo ""

  if [ "$corrupt" -gt 0 ]; then
    echo "## Corruption details"
    echo ""
    for issue in "${issues[@]}"; do
      phase=$(echo "$issue" | cut -d: -f1)
      echo "### ${phase}"
      echo "$issue" | sed 's/^[^:]*: //' | sed 's/^/  /'
      echo ""
      echo "  **Recovery:** /vg:doctor --recover ${phase}"
      echo ""
    done
  else
    echo "  🎉 No corruption detected."
  fi
  echo ""
fi
```
</step>

<step name="4_gates_mode">
## Step 4 (mode=gates): Gate statistics

```bash
if [ "$MODE" = "gates" ]; then
  echo "## Gate events (cổng) — current milestone"
  echo ""

  if [ ! -f "$TELEMETRY_PATH" ]; then
    echo "  (no telemetry yet — run some VG commands first)"
    exit 0
  fi

  ${PYTHON_BIN} - "$TELEMETRY_PATH" <<'PY'
import json, sys
from collections import defaultdict
path = sys.argv[1]
counts = defaultdict(lambda: defaultdict(int))  # gate_id → outcome → count
for line in open(path, encoding='utf-8'):
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      gid = ev.get("gate_id")
      outc = ev.get("outcome")
      if gid and outc in ("PASS", "FAIL", "SKIP", "OVERRIDE", "BLOCK", "WARN"):
          counts[gid][outc] += 1
    except: pass

if not counts:
    print("  (no gate events recorded)")
    sys.exit(0)

# Total by gate for sort
totals = {g: sum(oc.values()) for g, oc in counts.items()}
sorted_gates = sorted(counts.keys(), key=lambda g: -totals[g])

print("  | Gate | PASS | FAIL | BLOCK | OVERRIDE | SKIP | WARN | Total |")
print("  |------|------|------|-------|----------|------|------|-------|")
for g in sorted_gates:
    oc = counts[g]
    print(f"  | {g} | {oc.get('PASS',0)} | {oc.get('FAIL',0)} | {oc.get('BLOCK',0)} | {oc.get('OVERRIDE',0)} | {oc.get('SKIP',0)} | {oc.get('WARN',0)} | {totals[g]} |")

print()
# Flag high-override gates
flagged = [(g, counts[g].get("OVERRIDE", 0)) for g in counts if counts[g].get("OVERRIDE", 0) > 2]
if flagged:
    print("  ⚠ Gates with > 2 OVERRIDE (bỏ qua) outcomes:")
    for g, c in sorted(flagged, key=lambda x: -x[1]):
        print(f"     • {g}: {c} overrides")
    print()
    print("  Recommended: investigate root cause. Gate threshold too strict?")
    print("  Or agent rationalizing past valid concerns? Review OVERRIDE-DEBT.md.")
PY
  echo ""
fi
```
</step>

<step name="5_recover_mode">
## Step 5 (mode=recover): Guided recovery suggestions

```bash
if [ "$MODE" = "recover" ]; then
  phase_dir=""
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      phase_dir="$d"
      break
    fi
  done

  if [ -z "$phase_dir" ]; then
    echo "⛔ Phase ${PHASE_ARG} not found. Check /vg:doctor to see available phases."
    exit 1
  fi

  echo "## Recovery (khôi phục) for phase ${PHASE_ARG}"
  echo ""
  echo "  Default mode: **suggest-only** — prints commands for you to run manually."
  [ "$APPLY_FLAG" = "true" ] && echo "  --apply mode: will prompt before running safe helpers."
  echo ""

  # Classify corruption type
  echo "### Detecting corruption type"
  echo ""

  corruption_type="unknown"
  corruption_detail=""

  # Check 1: manifest validation
  if type artifact_manifest_validate >/dev/null 2>&1; then
    val_output=$(artifact_manifest_validate "$phase_dir" 2>&1)
    val_rc=$?
    case $val_rc in
      0)
        corruption_type="clean"
        corruption_detail="Manifest valid. No file-level corruption."
        ;;
      1)
        corruption_type="legacy-no-manifest"
        corruption_detail="Missing .artifact-manifest.json (legacy phase)."
        ;;
      2)
        if echo "$val_output" | grep -q "ARTIFACT MISSING"; then
          corruption_type="missing-artifacts"
        elif echo "$val_output" | grep -q "ARTIFACT CORRUPTION"; then
          corruption_type="hash-mismatch"
        elif echo "$val_output" | grep -q "MANIFEST CORRUPTION"; then
          corruption_type="manifest-self-corruption"
        else
          corruption_type="unknown-corruption"
        fi
        corruption_detail="$val_output"
        ;;
    esac
  fi

  # Check 2: pipeline state staleness
  pipeline_state="${phase_dir}/PIPELINE-STATE.json"
  stuck="no"
  if [ -f "$pipeline_state" ]; then
    stuck=$(${PYTHON_BIN} - "$pipeline_state" <<'PY' 2>/dev/null
import json, sys, os, datetime
try:
  s = json.loads(open(sys.argv[1], encoding='utf-8').read())
  mtime = os.path.getmtime(sys.argv[1])
  age_hours = (datetime.datetime.now().timestamp() - mtime) / 3600
  last_step = s.get("last_step") or s.get("current_step") or "?"
  if age_hours > 24 and last_step not in ("accept", "done"):
    print(f"stuck@{last_step}(age {int(age_hours)}h)")
  else:
    print("no")
except:
  print("no")
PY
)
  fi

  echo "  Type:    **${corruption_type}**"
  [ "$stuck" != "no" ] && echo "  Pipeline: ${stuck}"
  echo ""
  [ -n "$corruption_detail" ] && echo "$corruption_detail" | sed 's/^/  /'
  echo ""

  # Suggest recovery commands per type
  echo "### Suggested recovery commands"
  echo ""
  case "$corruption_type" in
    clean)
      echo "  ✓ No corruption. Nothing to recover."
      if [ "$stuck" != "no" ]; then
        echo "  But pipeline appears ${stuck}:"
        echo "    /vg:next ${PHASE_ARG}       # auto-advance to next step"
        echo "    /vg:progress ${PHASE_ARG}   # inspect current state"
      fi
      ;;
    legacy-no-manifest)
      echo "  Manifest auto-backfills on next read (no action required)."
      echo "  To force explicit backfill now, run any read command:"
      echo "    /vg:progress ${PHASE_ARG}"
      ;;
    manifest-self-corruption)
      echo "  Manifest itself tampered/corrupted. Safest: regenerate via the command that"
      echo "  originally produced the artifacts. Most likely:"
      echo "    /vg:blueprint ${PHASE_ARG}   # if PLAN/CONTRACTS/TEST-GOALS exist"
      echo "    /vg:review ${PHASE_ARG}      # if RUNTIME-MAP exists"
      ;;
    missing-artifacts)
      echo "  Files referenced by manifest are gone. Re-run producer:"
      echo "    /vg:blueprint ${PHASE_ARG}   # regenerates PLAN/CONTRACTS/TEST-GOALS"
      echo "  OR restore from git:"
      echo "    git checkout HEAD -- ${phase_dir}/"
      ;;
    hash-mismatch)
      echo "  Artifact content changed after manifest write (manual edit suspected)."
      echo "  Option 1 — keep edits, refresh manifest:"
      echo "    /vg:blueprint ${PHASE_ARG}   # regenerates manifest with current content"
      echo "  Option 2 — revert edits to manifest version:"
      echo "    git checkout ${phase_dir}/"
      ;;
    unknown-corruption|unknown)
      echo "  Could not classify. Manual inspection required:"
      echo "    cat ${phase_dir}/.artifact-manifest.json"
      echo "    /vg:doctor ${PHASE_ARG}       # deep phase inspection"
      ;;
  esac
  echo ""

  # Apply mode — only for safe ops, with explicit confirm
  if [ "$APPLY_FLAG" = "true" ]; then
    echo "### --apply mode"
    echo ""
    echo "  ⚠ --apply is not yet implemented for destructive ops."
    echo "  Run suggested commands manually. Future: interactive confirm + run."
  fi
  echo ""
fi
```
</step>

<step name="6_emit_telemetry">
## Step 6: Emit single doctor_run event

```bash
# One event per invocation — inspector must not pollute gate statistics
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "doctor_run" "${PHASE_ARG:-project}" "doctor.${MODE}" \
    "" "PASS" "{\"mode\":\"${MODE}\",\"apply\":${APPLY_FLAG}}" >/dev/null 2>&1 || true
fi
```
</step>

</process>

## Example outputs

### `/vg:doctor` (full mode)
```
🩺 ━━━ /vg:doctor — Mode: full ━━━

## Project health overview

| Phase | Manifest | Last command | Unresolved overrides | Recommended action |
|-------|----------|--------------|----------------------|--------------------|
| 07.10 | ✓ valid  | vg:accept    | 0                    | —                  |
| 07.11 | ⚠ legacy | vg:blueprint | 2                    | review OVERRIDE-DEBT.md |
| 07.12 | ⛔ corruption | vg:review | 1                | /vg:doctor --recover 07.12 |

## Gate override pressure
   • not-scanned-defer: 4 overrides  ← investigate
   • visual-regression: 3 overrides

## Override debt register
   Open: 3   Escalated: 1
   ⚠ Escalated entries block /vg:accept.
```

### `/vg:doctor --recover 07.12`
```
## Recovery for phase 07.12

### Detecting corruption type
  Type: **hash-mismatch**
  ⛔ ARTIFACT CORRUPTION: PLAN.md expected abc123... actual def456...

### Suggested recovery commands
  Option 1 — keep edits, refresh manifest:
    /vg:blueprint 07.12   # regenerates manifest with current content
  Option 2 — revert edits to manifest version:
    git checkout .planning/phases/07.12-.../
```

<success_criteria>
- **Read-only safe by default.** Base/phase/integrity/gates modes never modify files. Recover mode default prints commands only.
- **All heavy lifting delegated.** Uses `artifact_manifest_validate`, `telemetry_query`, `telemetry_warn_overrides` — no reimplementation.
- **Actionable output.** Every issue row includes a specific recommended command, not just description.
- **Graceful degradation.** Missing telemetry / manifest / phase → WARN + continue; exit 1 only on arg misuse.
- **Zero telemetry pollution.** At most one `doctor_run` event per invocation.
- **Under 500 lines, compact but complete.** Covers 5 modes (full / phase / integrity / gates / recover) with example outputs.
</success_criteria>
