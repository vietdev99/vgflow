---
name: vg:gate-stats
description: Gate telemetry query surface — counts by gate_id/outcome, filter by --gate-id/--since/--outcome, flags high-override gates
argument-hint: "[--gate-id=X] [--since=Y] [--outcome=Z]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
---

<NARRATION_POLICY>
**⛔ DO NOT USE TodoWrite / TaskCreate / TaskUpdate.**

Markdown headers for progress. Long Bash > 30s → `run_in_background: true`.

**Translate English terms (RULE)** — first-occurrence English term phải có giải thích VN trong ngoặc. Ví dụ: `gate (cổng)`, `override (bỏ qua)`, `outcome (kết quả)`, `telemetry (đo đạc)`, `milestone (mốc)`, `threshold (ngưỡng)`, `event (sự kiện)`. Không áp dụng: file path, code ID, outcome ID (PASS/FAIL/OVERRIDE).
</NARRATION_POLICY>

<rules>
1. **Read-only** — queries telemetry JSONL only. No writes.
2. **Delegate to `telemetry_query` + `telemetry_warn_overrides`** — no reimplementation of event parsing.
3. **Filters** — `--gate-id=X`, `--since=ISO8601`, `--outcome=PASS|FAIL|OVERRIDE|SKIP|BLOCK|WARN`. Unfiltered = all events.
4. **Flag high-override gates** — threshold from `CONFIG_OVERRIDE_WARN_THRESHOLD` (default 2).
5. **Single `gate_stats_run` event** per invocation.
</rules>

<objective>
Answer: "Which gates fire most often? Which are being overridden too much?"

Produces a sorted table by total event volume, with per-outcome breakdown. Surfaces gates exceeding override threshold as remediation targets.
</objective>

<process>

<step name="0_parse_load">
## Step 0: Parse filters + load helpers

```bash
PLANNING_DIR=".planning"
TELEMETRY_PATH="${PLANNING_DIR}/telemetry.jsonl"
PYTHON_BIN="${PYTHON_BIN:-python3}"

source .claude/commands/vg/_shared/lib/telemetry.sh 2>/dev/null || {
  echo "⛔ telemetry.sh missing — cannot query" >&2
  exit 1
}

FILTER_GATE=""
FILTER_SINCE=""
FILTER_OUTCOME=""
for arg in $ARGUMENTS; do
  case "$arg" in
    --gate-id=*) FILTER_GATE="${arg#--gate-id=}" ;;
    --since=*)   FILTER_SINCE="${arg#--since=}" ;;
    --outcome=*) FILTER_OUTCOME="${arg#--outcome=}" ;;
    --*)         echo "⚠ Unknown flag: $arg" ;;
    *)           echo "⚠ Positional arg ignored: $arg (use --gate-id=)" ;;
  esac
done

export VG_CURRENT_COMMAND="vg:gate-stats"
type telemetry_init >/dev/null 2>&1 && telemetry_init

echo ""
echo "📊 ━━━ /vg:gate-stats ━━━"
[ -n "$FILTER_GATE" ]    && echo "  Filter gate-id: ${FILTER_GATE}"
[ -n "$FILTER_SINCE" ]   && echo "  Filter since:   ${FILTER_SINCE}"
[ -n "$FILTER_OUTCOME" ] && echo "  Filter outcome: ${FILTER_OUTCOME}"
echo ""

if [ ! -f "$TELEMETRY_PATH" ]; then
  echo "  (no telemetry yet — run some VG commands first)"
  exit 0
fi
```
</step>

<step name="1_aggregate">
## Step 1: Aggregate events into per-gate × per-outcome counts

```bash
# Use telemetry_query when filters apply (it handles them); else stream raw file.
if type telemetry_query >/dev/null 2>&1 && { [ -n "$FILTER_GATE" ] || [ -n "$FILTER_SINCE" ] || [ -n "$FILTER_OUTCOME" ]; }; then
  QUERY_ARGS=()
  [ -n "$FILTER_GATE" ]    && QUERY_ARGS+=("--gate-id=${FILTER_GATE}")
  [ -n "$FILTER_SINCE" ]   && QUERY_ARGS+=("--since=${FILTER_SINCE}")
  [ -n "$FILTER_OUTCOME" ] && QUERY_ARGS+=("--outcome=${FILTER_OUTCOME}")
  STREAM_CMD=("telemetry_query" "${QUERY_ARGS[@]}")
  "${STREAM_CMD[@]}" > /tmp/vg-gate-stats.jsonl
  INPUT="/tmp/vg-gate-stats.jsonl"
else
  INPUT="$TELEMETRY_PATH"
fi

${PYTHON_BIN} - "$INPUT" <<'PY'
import json, sys
from collections import defaultdict
path = sys.argv[1]
counts = defaultdict(lambda: defaultdict(int))
try:
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
except FileNotFoundError:
  pass

if not counts:
  print("  (no gate events match filter)")
  sys.exit(0)

totals = {g: sum(oc.values()) for g, oc in counts.items()}
sorted_gates = sorted(counts.keys(), key=lambda g: -totals[g])

print("## Gate event counts")
print()
print("  | Gate | PASS | FAIL | BLOCK | OVERRIDE | SKIP | WARN | Total |")
print("  |------|------|------|-------|----------|------|------|-------|")
for g in sorted_gates:
    oc = counts[g]
    print(f"  | {g} | {oc.get('PASS',0)} | {oc.get('FAIL',0)} | {oc.get('BLOCK',0)} | {oc.get('OVERRIDE',0)} | {oc.get('SKIP',0)} | {oc.get('WARN',0)} | {totals[g]} |")
print()
PY
```
</step>

<step name="2_override_warn">
## Step 2: Surface high-override gates

```bash
echo "## High-override gates (bỏ qua nhiều)"
echo ""
THRESHOLD="${CONFIG_OVERRIDE_WARN_THRESHOLD:-2}"
if type telemetry_warn_overrides >/dev/null 2>&1; then
  telemetry_warn_overrides "$THRESHOLD" || echo "   (no gates exceed threshold ${THRESHOLD})"
else
  echo "   (telemetry_warn_overrides unavailable)"
fi
echo ""

echo "## Recommendations"
echo "   • If a gate is being overridden too often → investigate:"
echo "     - Is the gate threshold too strict?"
echo "     - Is the agent rationalizing past valid concerns?"
echo "     - Review .planning/OVERRIDE-DEBT.md entries for that gate."
echo "   • Drill into a specific gate:  /vg:gate-stats --gate-id=X"
echo "   • Scope to recent window:      /vg:gate-stats --since=2026-04-01"
echo ""
```
</step>

<step name="3_telemetry">
## Step 3: Emit single event

```bash
if type emit_telemetry_v2 >/dev/null 2>&1; then
  payload="{\"filter_gate\":\"${FILTER_GATE}\",\"filter_since\":\"${FILTER_SINCE}\",\"filter_outcome\":\"${FILTER_OUTCOME}\"}"
  emit_telemetry_v2 "gate_stats_run" "project" "gate-stats" "" "PASS" "$payload" >/dev/null 2>&1 || true
fi
rm -f /tmp/vg-gate-stats.jsonl 2>/dev/null || true
```
</step>

</process>

<success_criteria>
- Pure read — no writes to telemetry or registers.
- Filters pass through to `telemetry_query` helper.
- Output = sorted table + override-pressure section + actionable drill-down hints.
- Single `gate_stats_run` telemetry event.
</success_criteria>
</content>
</invoke>