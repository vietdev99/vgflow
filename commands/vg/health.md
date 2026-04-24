---
name: vg:health
description: Project health check — per-phase manifest status, last command, override pressure, drift register. Pass {phase} for deep inspection.
argument-hint: "[phase]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
observation_only: true
contract_exempt_reason: "read-only: inspects phase manifests + OVERRIDE-DEBT.md + drift register to print health report. No writes."
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Use markdown headers in text output (e.g. `## ━━━ Scanning phases ━━━`). Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Tham khảo `_shared/term-glossary.md`. Ví dụ: `manifest (kê khai)`, `override (bỏ qua)`, `debt (nợ kỹ thuật)`, `drift (lệch hướng)`, `pipeline (đường ống)`, `telemetry (đo đạc)`. Không áp dụng: file path, code ID.
</NARRATION_POLICY>

<rules>
1. **Read-only** — never writes, never deletes, no git ops. Pure state inspection.
2. **Summary vs deep** — no arg = project-wide summary table. `{phase}` arg = deep inspection of that phase.
3. **Delegate to shared helpers** — reuse `artifact_manifest_validate`, `telemetry_warn_overrides`, `telemetry_query`.
4. **Graceful degradation** — missing manifest/telemetry/register → WARN line + continue. Exit 1 only on bad args.
5. **No telemetry pollution** — at most one `health_run` event emitted per invocation.
</rules>

<objective>
Answer two questions without raw-log parsing:
1. **Is the project healthy overall?** (summary mode — all phases)
2. **Why is phase X stuck?** (deep mode — one phase)

Pretty-printer on top of shared helpers. No corruption repair — that lives in `/vg:recover`.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse + load helpers

```bash
PLANNING_DIR=".planning"
PHASES_DIR="${PLANNING_DIR}/phases"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
DEBT_REGISTER="${PLANNING_DIR}/OVERRIDE-DEBT.md"
DRIFT_REGISTER="${PLANNING_DIR}/DRIFT-REGISTER.md"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/artifact-manifest.sh 2>/dev/null || \
  echo "⚠ artifact-manifest.sh missing — integrity checks will degrade" >&2
source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || \
  echo "⚠ telemetry.sh missing — event logging disabled" >&2

PHASE_ARG=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --*) echo "⚠ Unknown flag: $arg (use /vg:gate-stats, /vg:integrity, /vg:recover instead)" ;;
    *)   PHASE_ARG="$arg" ;;
  esac
done

MODE="summary"
[ -n "$PHASE_ARG" ] && MODE="deep"

export VG_CURRENT_COMMAND="vg:health"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "🩺 ━━━ /vg:health — ${MODE} ━━━"
echo ""
```
</step>

<step name="1_summary">
## Step 1 (mode=summary): Project overview table

```bash
if [ "$MODE" = "summary" ]; then
  echo "## Project health overview"
  echo ""

  PHASE_DIRS=()
  if [ -d "$PHASES_DIR" ]; then
    while IFS= read -r d; do
      [ -d "$d" ] && PHASE_DIRS+=("$d")
    done < <(find "$PHASES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
  fi

  if [ ${#PHASE_DIRS[@]} -eq 0 ]; then
    echo "⚠ No phases found. Run /vg:roadmap hoặc /vg:add-phase."
  else
    echo "| Phase | Manifest | Last command | Unresolved overrides | Recommended action |"
    echo "|-------|----------|--------------|----------------------|--------------------|"

    for phase_dir in "${PHASE_DIRS[@]}"; do
      phase_name=$(basename "$phase_dir")
      phase_num=$(echo "$phase_name" | grep -oE '^[0-9.]+')

      manifest_status="?"
      if type artifact_manifest_validate >/dev/null 2>&1; then
        artifact_manifest_validate "$phase_dir" >/dev/null 2>&1
        case $? in
          0) manifest_status="✓ valid" ;;
          1) manifest_status="⚠ legacy" ;;
          2) manifest_status="⛔ corruption" ;;
        esac
      fi

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
      if ev.get("phase") == phs: last = ev
    except: pass
except: pass
print(last.get("command", "—") if last else "—")
PY
)
      fi

      unresolved=0
      if [ -f "$DEBT_REGISTER" ]; then
        unresolved=$(grep -cE "\| .*\| ${phase_num} \|.*\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
      fi

      action="—"
      case "$manifest_status" in
        *corruption*) action="/vg:recover ${phase_num}" ;;
        *legacy*)     action="next read auto-backfills" ;;
        *valid*)      [ "$unresolved" -gt 0 ] && action="review OVERRIDE-DEBT.md" ;;
      esac

      printf "| %s | %s | %s | %s | %s |\n" "$phase_num" "$manifest_status" "$last_cmd" "$unresolved" "$action"
    done
  fi
  echo ""

  echo "## Gate override pressure (áp lực bỏ qua cổng)"
  echo ""
  if type telemetry_warn_overrides >/dev/null 2>&1; then
    telemetry_warn_overrides 2 || echo "   (no gates exceed threshold)"
  else
    echo "   (telemetry helper unavailable)"
  fi
  echo ""

  echo "## Override debt register (sổ nợ bỏ qua)"
  if [ -f "$DEBT_REGISTER" ]; then
    open_count=$(grep -cE "\| OPEN \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    escalated=$(grep -cE "\| ESCALATED \|" "$DEBT_REGISTER" 2>/dev/null || echo 0)
    echo "   Open: ${open_count}   Escalated: ${escalated}"
    [ "$escalated" -gt 0 ] && echo "   ⚠ Escalated entries block /vg:accept."
  else
    echo "   (no debt register — clean state)"
  fi
  echo ""

  echo "## Drift register (sổ lệch hướng)"
  if [ -f "$DRIFT_REGISTER" ]; then
    unfixed=$(grep -cE "^\| .* \| (info|warn) \| .* \| (?!resolved)" "$DRIFT_REGISTER" 2>/dev/null || echo 0)
    echo "   Unfixed: ${unfixed}"
    [ "$unfixed" -gt 0 ] && echo "   Run /vg:project --update để re-lock foundation."
  else
    echo "   (no drift register — clean state)"
  fi
  echo ""

  echo "## Semantic enrichment (v1.14.0+ migrate gates)"
  VERIFY_SCRIPT=""
  [ -f "${REPO_ROOT}/.claude/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
  [ -f "${REPO_ROOT}/scripts/verify-migrate-output.py" ] && VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"

  if [ -z "$VERIFY_SCRIPT" ]; then
    echo "   (validator not installed — skip semantic check)"
  else
    needs_enrich=0
    fully_enriched=0
    no_test_goals=0
    for phase_dir in "${PHASE_DIRS[@]}"; do
      [ -f "$phase_dir/TEST-GOALS.md" ] || { no_test_goals=$((no_test_goals + 1)); continue; }
      fail_count=$(${PYTHON_BIN} "$VERIFY_SCRIPT" --json "$phase_dir" 2>/dev/null \
        | ${PYTHON_BIN} -c "import sys,json; print(json.loads(sys.stdin.read()).get('fail',0))" 2>/dev/null)
      if [ "${fail_count:-0}" -gt 0 ]; then
        needs_enrich=$((needs_enrich + 1))
      else
        fully_enriched=$((fully_enriched + 1))
      fi
    done
    echo "   Fully enriched (all gates pass): ${fully_enriched}"
    echo "   Needs enrichment (≥1 gate fails): ${needs_enrich}"
    echo "   No TEST-GOALS yet:                 ${no_test_goals}"
    [ "$needs_enrich" -gt 0 ] && echo "   Detail per phase: /vg:health {phase}"
    [ "$needs_enrich" -gt 0 ] && echo "   Bulk re-enrich:  /vg:migrate {phase} --force (per phase)"
  fi
  echo ""

  echo "## Next actions"
  echo "   • Deep inspect:    /vg:health {phase}"
  echo "   • Integrity sweep: /vg:integrity"
  echo "   • Gate statistics: /vg:gate-stats"
  echo "   • Recover phase:   /vg:recover {phase}"
  echo ""
fi
```
</step>

<step name="2_deep">
## Step 2 (mode=deep): Single-phase deep inspection

```bash
if [ "$MODE" = "deep" ]; then
  phase_dir=""
  for d in "${PHASES_DIR}"/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    if [[ "$base" == "${PHASE_ARG}"* ]] || [[ "$base" == "${PHASE_ARG}-"* ]]; then
      phase_dir="$d"; break
    fi
  done

  if [ -z "$phase_dir" ]; then
    echo "⛔ Phase ${PHASE_ARG} not found under ${PHASES_DIR}"
    exit 1
  fi

  echo "## Phase ${PHASE_ARG} — deep inspection"
  echo "  Directory: ${phase_dir}"
  echo ""

  echo "### Artifacts + manifest (kê khai)"
  manifest_path="${phase_dir}/.artifact-manifest.json"
  if [ -f "$manifest_path" ]; then
    ${PYTHON_BIN} - "$phase_dir" "$manifest_path" <<'PY'
import json, sys, hashlib
from pathlib import Path
phase_dir = Path(sys.argv[1])
m = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
print(f"  Manifest version: {m.get('manifest_version', '?')}")
print(f"  Generated by:     {m.get('generated_by', '?')}")
print(f"  Artifact count:   {len(m.get('artifacts', []))}")
print()
print("  | Artifact | Size | Integrity |")
print("  |----------|------|-----------|")
for art in m.get("artifacts", []):
    abs_path = phase_dir / art["path"]
    if not abs_path.exists():
        status = "⛔ missing"
    else:
        actual = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        status = "✓" if actual == art["sha256"] else "⛔ mismatch"
    print(f"  | {art['path']} | {art.get('bytes', '?')}B | {status} |")
PY
  else
    echo "  ⚠ No manifest (legacy). Next read auto-backfills."
    find "$phase_dir" -maxdepth 1 -type f \( -name '*.md' -o -name '*.json' \) | sort | sed 's|^|    |'
  fi
  echo ""

  echo "### Recent telemetry events (last 10)"
  if type telemetry_query >/dev/null 2>&1 && [ -f "$TELEMETRY_PATH" ]; then
    telemetry_query --phase="${PHASE_ARG}" | tail -10 | ${PYTHON_BIN} - <<'PY' 2>/dev/null
import json, sys
print("  | Timestamp | Command | Step | Gate | Outcome |")
print("  |-----------|---------|------|------|---------|")
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      ts = ev.get("ts", "?")[:19]; cmd = ev.get("command", "?"); step = ev.get("step", "?")
      gate = ev.get("gate_id") or "—"; outc = ev.get("outcome") or ev.get("event_type", "?")
      print(f"  | {ts} | {cmd} | {step} | {gate} | {outc} |")
    except: pass
PY
  else
    echo "  (no telemetry for this phase)"
  fi
  echo ""

  echo "### Pipeline state"
  pipeline_state="${phase_dir}/PIPELINE-STATE.json"
  if [ -f "$pipeline_state" ]; then
    ${PYTHON_BIN} - "$pipeline_state" <<'PY'
import json, sys
s = json.loads(open(sys.argv[1], encoding='utf-8').read())
for k, v in s.items():
    if isinstance(v, (dict, list)): v = json.dumps(v)[:80]
    print(f"  • {k}: {v}")
PY
  else
    echo "  (no PIPELINE-STATE.json — phase may be new or pre-v1.8.0)"
  fi
  echo ""

  echo "### Recommended next action"
  if [ -f "${phase_dir}/UAT.md" ]; then
    echo "  ✓ Phase complete. /vg:next"
  elif [ -f "${phase_dir}/SANDBOX-TEST.md" ]; then
    echo "  → /vg:accept ${PHASE_ARG}"
  elif [ -f "${phase_dir}/RUNTIME-MAP.json" ]; then
    echo "  → /vg:test ${PHASE_ARG}"
  elif ls "${phase_dir}"/SUMMARY*.md >/dev/null 2>&1; then
    echo "  → /vg:review ${PHASE_ARG}"
  elif ls "${phase_dir}"/PLAN*.md >/dev/null 2>&1; then
    echo "  → /vg:build ${PHASE_ARG}"
  elif [ -f "${phase_dir}/CONTEXT.md" ]; then
    echo "  → /vg:blueprint ${PHASE_ARG}"
  elif [ -f "${phase_dir}/SPECS.md" ]; then
    echo "  → /vg:scope ${PHASE_ARG}"
  else
    echo "  → /vg:specs ${PHASE_ARG}"
  fi
  echo ""
fi
```
</step>

<step name="3_telemetry">
## Step 3: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "health_run" "${PHASE_ARG:-project}" "health.${MODE}" \
    "" "PASS" "{\"mode\":\"${MODE}\"}" >/dev/null 2>&1 || true
fi
```
</step>

</process>

<success_criteria>
- Read-only; never writes/deletes.
- Summary mode = full-project table. Deep mode = one phase detailed view.
- All corruption/validation delegated to `artifact_manifest_validate`.
- Graceful degradation on missing files/helpers.
- Single `health_run` telemetry event per invocation.
</success_criteria>
</content>
</invoke>