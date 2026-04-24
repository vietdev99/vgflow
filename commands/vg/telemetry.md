---
name: vg:telemetry
description: Summarize VG telemetry — gate hit counts, override frequency, phase timing, fix routing distribution
argument-hint: "[--since=<date>] [--phase=<X>] [--event=<type>] [--format=table|json|csv] [--top=<N>]"
allowed-tools:
  - Bash
  - Read
observation_only: true
contract_exempt_reason: "read-only: parses .vg/telemetry.jsonl + events.db to print summaries — no writes"
---

<objective>
Read `${PLANNING_DIR}/telemetry.jsonl` and summarize workflow behavior:
1. Gate hit frequency (which gates fire most → candidates for UX improvement)
2. Override flag usage (which flags get abused → candidates for removal)
3. Fix routing distribution (inline vs spawn vs escalated → model cost analysis)
4. Phase step durations (p50/p95 per step → bottleneck detection)
5. CrossAI verdicts (consensus vs tie-break rate)
6. Cross-phase patterns (which phase has most gate blocks)

Output: human-readable table by default, or JSON/CSV for tooling.
</objective>

<process>

<step name="0_config">
Source config loader. Read:
- `CONFIG_TELEMETRY_PATH` (default `${PLANNING_DIR}/telemetry.jsonl`)
- `CONFIG_TELEMETRY_ENABLED` (block if false)

If telemetry disabled: print "Telemetry disabled in config. Enable via `telemetry.enabled: true` in vg.config.md." and exit 0.

Parse args:
- `--since=<ISO-date>` — filter events from this date (default: 30 days ago)
- `--phase=<X>` — filter to single phase
- `--event=<type>` — filter to event type
- `--format=table|json|csv` (default table)
- `--top=<N>` — limit table rows (default 20)
</step>

<step name="1_load_and_filter">

```bash
TELEMETRY_PATH="${CONFIG_TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"

if [ ! -f "$TELEMETRY_PATH" ]; then
  echo "No telemetry data yet: ${TELEMETRY_PATH}"
  echo "Run VG commands; telemetry auto-populates."
  exit 0
fi

SINCE="${ARG_SINCE:-$(date -u -d '30 days ago' +%FT%TZ 2>/dev/null || date -u -v-30d +%FT%TZ 2>/dev/null)}"
PHASE_FILTER="${ARG_PHASE:-}"
EVENT_FILTER="${ARG_EVENT:-}"
FORMAT="${ARG_FORMAT:-table}"
TOP="${ARG_TOP:-20}"
```
</step>

<step name="2_summarize">

```bash
${PYTHON_BIN:-python3} - "$TELEMETRY_PATH" "$SINCE" "$PHASE_FILTER" "$EVENT_FILTER" "$FORMAT" "$TOP" <<'PY'
import sys, json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median, quantiles

path, since, phase_f, event_f, fmt, top = sys.argv[1:]
top = int(top)
since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

events = []
for line in open(path, encoding='utf-8'):
  line = line.strip()
  if not line: continue
  try:
    ev = json.loads(line)
    ts = datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))
    if ts < since_dt: continue
    if phase_f and ev.get("phase") != phase_f: continue
    if event_f and ev.get("event") != event_f: continue
    events.append(ev)
  except Exception:
    continue

if not events:
  print("No events matched filters."); sys.exit(0)

# Aggregate
gate_hits = Counter()
gate_blocks = Counter()
overrides = Counter()
fix_tiers = Counter()
fix_models = Counter()
crossai_verdicts = Counter()
crossai_ties = 0
durations = defaultdict(list)
phase_blocks = Counter()
security_threats = Counter()
visual_fails = []

for ev in events:
  e, phase, step, meta = ev["event"], ev.get("phase", "?"), ev.get("step", "?"), ev.get("meta", {})
  if e == "gate_hit":
    gate_hits[meta.get("gate_id", step)] += 1
  elif e == "gate_blocked":
    gate_blocks[meta.get("gate_id", step)] += 1
    phase_blocks[phase] += 1
  elif e == "override_used":
    overrides[meta.get("flag", "?")] += 1
  elif e == "fix_routed":
    fix_tiers[meta.get("tier", "?")] += 1
    fix_models[meta.get("model", "inline")] += 1
  elif e == "crossai_result":
    crossai_verdicts[meta.get("verdict", "?")] += 1
    if meta.get("tie_break"): crossai_ties += 1
  elif e == "phase_step_end":
    d = meta.get("duration_s")
    if isinstance(d, (int, float)) and d >= 0:
      durations[step].append(d)
  elif e == "security_threat_added":
    security_threats[meta.get("severity", "?")] += 1
  elif e == "visual_regression_fail":
    visual_fails.append((phase, meta.get("view"), meta.get("diff_pct")))

# Format
if fmt == "json":
  print(json.dumps({
    "total_events": len(events),
    "window_start": since,
    "gate_blocks": dict(gate_blocks),
    "overrides": dict(overrides),
    "fix_tiers": dict(fix_tiers),
    "fix_models": dict(fix_models),
    "crossai_verdicts": dict(crossai_verdicts),
    "crossai_tie_break_count": crossai_ties,
    "phase_blocks": dict(phase_blocks),
    "security_threats": dict(security_threats),
    "visual_fails": visual_fails,
    "step_durations": {s: {"n": len(d), "p50": median(d), "max": max(d)} for s, d in durations.items() if d},
  }, indent=2))
  sys.exit(0)

# Table format
def tbl(title, counter, n=top):
  if not counter: return
  print(f"\n━━━ {title} ━━━")
  for k, v in counter.most_common(n):
    print(f"  {v:>6}  {k}")

print(f"━━━ VG Telemetry Summary ━━━")
print(f"Events in window: {len(events)} (since {since})")
print(f"Phases touched:   {len(set(e.get('phase','') for e in events if e.get('phase')))}")

tbl("Gates blocked (most frequent)", gate_blocks)
tbl("Gates passed (hits)", gate_hits)
tbl("Override flags used", overrides)
tbl("Fix routing tier", fix_tiers)
tbl("Fix routing models", fix_models)
tbl("CrossAI verdicts", crossai_verdicts)
if crossai_ties:
  print(f"  CrossAI tie-breaks: {crossai_ties}")
tbl("Phases with most blocks", phase_blocks)
tbl("Security threats by severity", security_threats)

if durations:
  print(f"\n━━━ Step durations (seconds) ━━━")
  print(f"  {'step':<40} {'n':>5} {'p50':>8} {'p95':>8} {'max':>8}")
  rows = []
  for step, d in durations.items():
    if not d: continue
    p50 = median(d)
    p95 = quantiles(d, n=20)[-1] if len(d) >= 2 else d[0]
    rows.append((step, len(d), p50, p95, max(d)))
  rows.sort(key=lambda r: r[3], reverse=True)  # sort by p95 desc
  for step, n, p50, p95, mx in rows[:top]:
    print(f"  {step:<40} {n:>5} {p50:>8.1f} {p95:>8.1f} {mx:>8.1f}")

if visual_fails:
  print(f"\n━━━ Visual regressions ({len(visual_fails)}) ━━━")
  for phase, view, pct in visual_fails[:top]:
    print(f"  {phase}  {view}  {pct}%")
PY
```

</step>

<step name="3_csv_export">

If `--format=csv`, emit one CSV file per aggregate:
- `${PLANNING_DIR}/telemetry-summary-gates.csv`
- `${PLANNING_DIR}/telemetry-summary-overrides.csv`
- `${PLANNING_DIR}/telemetry-summary-durations.csv`

Use pandas if available, else manual CSV write.
</step>

</process>

<success_criteria>
- Reads jsonl, respects date/phase/event filters
- Output shows actionable data: which gate fires most, which override abused, slowest steps
- CSV export for external tooling (spreadsheets, Grafana via cron)
- Zero modification of source data (read-only)
</success_criteria>
