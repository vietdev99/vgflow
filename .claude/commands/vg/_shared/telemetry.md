---
name: vg:_shared:telemetry
description: Telemetry Pipeline (Shared Reference) — append-only jsonl event log for gate hits, overrides, fix routing, timing. Consumed by /vg:telemetry summarize.
---

# Telemetry — Shared Helper

> **⚠ Runtime note (v1.9.0 T3):** Runnable bash code is at [`_shared/lib/telemetry.sh`](lib/telemetry.sh). Commands MUST `source` the `.sh` file — this `.md` file is documentation only (YAML frontmatter + markdown headers + fenced code blocks cannot be sourced by bash). The bash snippets below are kept in sync with `.sh` for readability.

Every workflow decision point emits a structured JSON event to `${PLANNING_DIR}/telemetry.jsonl`. Data-driven workflow improvement: which gates fire most, which override flags get abused, which fix-routing tier wins, average phase duration.

## Config (add to `.claude/vg.config.md`)

```yaml
telemetry:
  enabled: true
  path: "${PLANNING_DIR}/telemetry.jsonl"
  retention_days: 90                # events older than N days deleted on next emit (cheap)
  sample_rate: 1.0                  # 0.0–1.0 fraction of events to record (1.0 = all)
  event_types_skip: []              # optional blocklist: ["narration", "debug"]
  strict_write: true                # v1.9.0 T5: WARN on legacy 4-arg emit_telemetry() calls.
                                    # v2.0 plan: hard-fail shim unless allow_legacy=true.
  allow_legacy: false               # reserved for v2.0 — do not use in new code.
```

> **⚠ WRITE STRICT (v1.9.0 T5):** New emissions MUST call `emit_telemetry_v2` (6 args).
> The 4-arg `emit_telemetry` shim is kept only for legacy files; it logs a stderr
> deprecation WARN with caller stack hint and tags the payload `legacy_call:true`
> so `telemetry_query --gate-id=X` results remain filterable. Data emitted via the
> shim is permanently missing `gate_id`/`correlation_id` structure — migrate callers
> to v2 before v2.0 where the shim hard-fails.

## Event schema (v1.8.0+ structured)

```json
{
  "event_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",  // uuid v4 — every event uniquely addressable
  "ts": "2026-04-17T09:12:33Z",
  "event_type": "gate_blocked",                         // renamed from "event" (alias kept for back-compat)
  "phase": "7.12",                                      // null if project-level
  "command": "vg:review",                               // which command emitted
  "step": "review.4c-pre",
  "session_id": "abc123",                               // hash of {user, repo, start_ts}
  "git_sha": "d484589f",
  "gate_id": "not-scanned-defer",                       // promoted to top-level (was in meta)
  "outcome": "BLOCK",                                   // PASS | FAIL | SKIP | OVERRIDE | BLOCK | WARN
  "correlation_id": "f47ac10b-...",                     // parent event_id for causal chain (null if root)
  "payload": {                                          // event-specific (renamed from "meta")
    "reason": "NOT_SCANNED=5, FAILED=2",
    "count": 7
  }
}
```

**Back-compat:** Old fields `event` + `meta` still accepted by readers (alias for `event_type` + `payload`). Migration auto-rewrites on first /vg:telemetry --migrate.

## Standard event types

| Event | When | Meta fields |
|-------|------|-------------|
| `gate_hit` | any hard gate fires | `gate_id`, `passed` (bool), `reason` |
| `gate_blocked` | gate blocks execution | `gate_id`, `count`, `reason` |
| `override_used` | --allow/--skip/--override flag accepted | `flag`, `severity`, `debt_id` |
| `fix_routed` | Review 3-tier decision | `tier` (inline/spawn/escalated), `severity`, `model` |
| `crossai_result` | CrossAI consensus reached | `vendors`, `verdict`, `tie_break` (bool) |
| `phase_step_start` | step begins | `step_name` |
| `phase_step_end` | step completes | `step_name`, `duration_s`, `exit_code` |
| `debt_escalated` | debt entry auto-escalates (age) | `debt_id`, `severity`, `age_days` |
| `security_threat_added` | new threat in SECURITY-REGISTER | `threat_id`, `severity`, `stride_category` |
| `visual_regression_fail` | baseline diff > threshold | `view`, `diff_pct`, `threshold_pct` |
| `graphify_skip` | /vg:map skipped (fresh) | `commits_since`, `reason` |
| `graphify_incremental` | incremental rebuild | `files_changed`, `nodes_affected` |
| `override_resolved` | T5: bypassed gate re-runs cleanly OR T2 v1.9.0: manual /vg:override-resolve | `gate_id`, `original_override_event_id`, `status` (RESOLVED\|WONT_FIX), `reason` (manual), `debt_id` (manual), `manual` (bool) |
| `artifact_written` | T3: artifact + manifest written | `artifact`, `sha256`, `bytes` |
| `artifact_read_validated` | T3: manifest validated on read | `artifact`, `expected_sha256`, `actual_sha256`, `match` (bool) |
| `drift_detected` | T6: foundation drift entry | `tier` (info/warn), `keyword`, `dimension`, `current_value` |
| `rationalization_guard_check` | T1 v1.9.0: separate-model guard adjudicates gate-skip | `gate_id`, `verdict` (PASS/FLAG/ESCALATE), `confidence`, `subagent_model`, `subagent_reason`, `flag` |
| `scope_answer_challenged` | R3 v1.9.1: adversarial answer challenger in /vg:scope + /vg:project rounds | `round_id`, `issue_kind` (contradiction/hidden_assumption/edge_case/foundation_conflict), `evidence`, `user_chose` (address/acknowledge/defer/pending), `_skipped` (disabled/trivial/max_rounds_reached) |

## API

```bash
# Init once per VG command invocation (top of command)
telemetry_init() {
  [ "${CONFIG_TELEMETRY_ENABLED:-true}" = "true" ] || return 0
  export TELEMETRY_SESSION_ID="${TELEMETRY_SESSION_ID:-$(openssl rand -hex 8 2>/dev/null || printf '%08x%08x' $RANDOM $RANDOM)}"
  export TELEMETRY_PATH="${CONFIG_TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"
  mkdir -p "$(dirname "$TELEMETRY_PATH")" 2>/dev/null || true

  # Cheap retention: truncate events older than retention_days (only rewrite if cutoff reached)
  local retain="${CONFIG_TELEMETRY_RETENTION_DAYS:-90}"
  if [ -f "$TELEMETRY_PATH" ]; then
    local size_kb
    size_kb=$(wc -c < "$TELEMETRY_PATH" 2>/dev/null || echo 0)
    # Only prune if file > 1MB (avoid rewrite cost on small files)
    [ "$((size_kb / 1024))" -gt 1024 ] && telemetry_prune
  fi
}

# Emit one event (v1.8.0 structured: event_id, event_type, command, gate_id, outcome, correlation_id, payload)
# New API: emit_telemetry_v2 EVENT_TYPE PHASE STEP GATE_ID OUTCOME PAYLOAD_JSON [CORRELATION_ID] [COMMAND]
# Returns: prints emitted event_id to stdout (for downstream correlation)
emit_telemetry_v2() {
  [ "${CONFIG_TELEMETRY_ENABLED:-true}" = "true" ] || return 0
  local event_type="$1" phase="$2" step="$3" gate_id="${4:-}" outcome="${5:-}" payload_json="${6-}"
  [ -z "$payload_json" ] && payload_json='{}'
  local correlation_id="${7:-}" command="${8:-${VG_CURRENT_COMMAND:-unknown}}"
  local path="${TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"

  # Sampling
  local rate="${CONFIG_TELEMETRY_SAMPLE_RATE:-1.0}"
  if [ "$rate" != "1.0" ]; then
    local r
    r=$(${PYTHON_BIN:-python3} -c "import random; print(random.random())" 2>/dev/null || echo 0)
    awk -v r="$r" -v rate="$rate" 'BEGIN{exit (r<rate)?0:1}' || return 0
  fi

  # Skip list
  local skip="${CONFIG_TELEMETRY_EVENT_TYPES_SKIP:-}"
  case " $skip " in *" $event_type "*) return 0 ;; esac

  local ts git_sha event_id
  ts=$(date -u +%FT%TZ)
  git_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  event_id=$(${PYTHON_BIN:-python3} -c "import uuid; print(uuid.uuid4())" 2>/dev/null || \
             printf '%08x-%04x-4%03x-%04x-%012x' $RANDOM $RANDOM $RANDOM $RANDOM $RANDOM$RANDOM)

  ${PYTHON_BIN:-python3} - \
    "$event_id" "$event_type" "$phase" "$command" "$step" "$TELEMETRY_SESSION_ID" \
    "$git_sha" "$ts" "$gate_id" "$outcome" "$correlation_id" "$payload_json" "$path" <<'PY'
import json, sys
(eid, etype, phase, cmd, step, sid, sha, ts, gate_id, outcome, corr_id, payload_raw, path) = sys.argv[1:14]
try:
  payload = json.loads(payload_raw) if payload_raw else {}
except json.JSONDecodeError:
  payload = {"_raw": payload_raw}
event = {
  "event_id": eid,
  "ts": ts,
  "event_type": etype,
  "phase": phase if phase else None,
  "command": cmd,
  "step": step,
  "session_id": sid,
  "git_sha": sha,
  "gate_id": gate_id if gate_id else None,
  "outcome": outcome if outcome else None,
  "correlation_id": corr_id if corr_id else None,
  "payload": payload
}
with open(path, 'a', encoding='utf-8') as f:
  f.write(json.dumps(event, ensure_ascii=False) + "\n")
print(eid)
PY
}

# Back-compat shim (old 4-arg signature → maps to v2 with gate_id/outcome extracted from payload if present)
# WRITE-STRICT (v1.9.0 T5): emits stderr deprecation WARN + tags payload legacy_call:true.
emit_telemetry() {
  local event_type="$1" phase="$2" step="$3" payload_json="${4-}"
  [ -z "$payload_json" ] && payload_json='{}'
  if [ "${CONFIG_TELEMETRY_STRICT_WRITE:-true}" = "true" ]; then
    local caller_hint="${BASH_SOURCE[1]:-unknown}:${BASH_LINENO[0]:-?}"
    echo "⚠ emit_telemetry: DEPRECATED 4-arg call (gọi cũ) from ${caller_hint}; please migrate to emit_telemetry_v2 (event_type phase step gate_id outcome payload). Telemetry query --gate-id sẽ thiếu dữ liệu." >&2
  fi
  local gate_id outcome
  gate_id=$(${PYTHON_BIN:-python3} -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('gate_id',''))" "$payload_json" 2>/dev/null || echo "")
  outcome=$(${PYTHON_BIN:-python3} -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('outcome',''))" "$payload_json" 2>/dev/null || echo "")
  local marked_payload
  marked_payload=$(${PYTHON_BIN:-python3} -c '
import json, sys
raw = sys.stdin.read()
try: d = json.loads(raw) if raw.strip() else {}
except Exception: d = {"_raw": raw}
d["legacy_call"] = True
sys.stdout.write(json.dumps(d, ensure_ascii=False))
' <<<"$payload_json" 2>/dev/null)
  [ -z "$marked_payload" ] && marked_payload="$payload_json"
  emit_telemetry_v2 "$event_type" "$phase" "$step" "$gate_id" "$outcome" "$marked_payload"
}

# Query API — filter events by gate_id / outcome / phase / event_type / since
# Usage: telemetry_query --gate-id=X --outcome=OVERRIDE --since=2026-04-10
telemetry_query() {
  local path="${TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"
  [ -f "$path" ] || return 0
  local gate_id="" outcome="" phase="" event_type="" since=""
  for arg in "$@"; do
    case "$arg" in
      --gate-id=*)    gate_id="${arg#--gate-id=}" ;;
      --outcome=*)    outcome="${arg#--outcome=}" ;;
      --phase=*)      phase="${arg#--phase=}" ;;
      --event-type=*) event_type="${arg#--event-type=}" ;;
      --since=*)      since="${arg#--since=}" ;;
    esac
  done
  ${PYTHON_BIN:-python3} - "$path" "$gate_id" "$outcome" "$phase" "$event_type" "$since" <<'PY'
import json, sys
path, gid, outc, phs, etyp, since = sys.argv[1:7]
def match(ev):
  if gid and ev.get("gate_id") != gid: return False
  if outc and ev.get("outcome") != outc: return False
  if phs and ev.get("phase") != phs: return False
  if etyp and ev.get("event_type", ev.get("event")) != etyp: return False
  if since and ev.get("ts", "") < since: return False
  return True
with open(path, encoding='utf-8') as f:
  for line in f:
    line = line.strip()
    if not line: continue
    try:
      ev = json.loads(line)
      if match(ev):
        print(line)
    except Exception: pass
PY
}

# Auto-WARNING when gate has > N OVERRIDE outcomes in current milestone
# Called by /vg:doctor and at the end of major commands
telemetry_warn_overrides() {
  local threshold="${1:-2}"
  local milestone_since="${2:-$(date -u -d '30 days ago' +%FT%TZ 2>/dev/null || date -u +%FT%TZ)}"
  local path="${TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"
  [ -f "$path" ] || return 0
  ${PYTHON_BIN:-python3} - "$path" "$threshold" "$milestone_since" <<'PY'
import json, sys
from collections import Counter
path, thr, since = sys.argv[1], int(sys.argv[2]), sys.argv[3]
counts = Counter()
for line in open(path, encoding='utf-8'):
  line = line.strip()
  if not line: continue
  try:
    ev = json.loads(line)
    if ev.get("ts", "") < since: continue
    if ev.get("outcome") == "OVERRIDE":
      gid = ev.get("gate_id") or "(no-gate-id)"
      counts[gid] += 1
  except Exception: pass
flagged = [(g, c) for g, c in counts.items() if c > thr]
if flagged:
  print("⚠ TELEMETRY WARNING (cảnh báo): gates with > {} OVERRIDE (bỏ qua) outcomes since {}:".format(thr, since[:10]))
  for g, c in sorted(flagged, key=lambda x: -x[1]):
    print(f"   • {g}: {c} overrides")
  print("   Recommended: investigate cause, consider if gate threshold is too strict OR if AI agent is rationalizing past valid concerns.")
PY
}

# Retention pruner
telemetry_prune() {
  local path="${TELEMETRY_PATH:-${PLANNING_DIR}/telemetry.jsonl}"
  local days="${CONFIG_TELEMETRY_RETENTION_DAYS:-90}"
  [ -f "$path" ] || return 0
  ${PYTHON_BIN:-python3} - "$path" "$days" <<'PY'
import sys, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
path = Path(sys.argv[1]); days = int(sys.argv[2])
cutoff = datetime.now(timezone.utc) - timedelta(days=days)
kept = []
for line in path.read_text(encoding='utf-8').splitlines():
  if not line.strip(): continue
  try:
    ev = json.loads(line)
    ts = datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))
    if ts >= cutoff: kept.append(line)
  except Exception:
    kept.append(line)  # keep malformed lines (avoid silent data loss)
path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding='utf-8')
PY
}

# Phase timing helpers — call emit_telemetry_v2 directly (no shim WARN, keep gate_id empty).
# Step boundaries are NOT gate events. `gate_id` reserved for actual gate hits so that
# `telemetry_query --gate-id=X` returns a clean signal.
telemetry_step_start() {
  local phase="$1" step="$2"
  export "STEP_START_${step//[^a-zA-Z0-9]/_}=$(date +%s)"
  emit_telemetry_v2 "phase_step_start" "$phase" "$step" "" "" "{}"
}

telemetry_step_end() {
  local phase="$1" step="$2" exit_code="${3:-0}"
  local var_name="STEP_START_${step//[^a-zA-Z0-9]/_}"
  local start="${!var_name:-}"
  local duration=0
  [ -n "$start" ] && duration=$(( $(date +%s) - start ))
  local outcome="PASS"; [ "$exit_code" != "0" ] && outcome="FAIL"
  emit_telemetry_v2 "phase_step_end" "$phase" "$step" "" "$outcome" \
    "{\"duration_s\":${duration},\"exit_code\":${exit_code}}"
}
```

## Integration pattern

**Top of every VG command** (after config load):
```bash
telemetry_init
```

**At every gate hit (WRITE STRICT — use v2):**
```bash
if [ "$NOT_SCANNED" -gt 0 ]; then
  emit_telemetry_v2 "gate_blocked" "$PHASE_NUMBER" "review.4c-pre" \
    "not-scanned-defer" "BLOCK" \
    "{\"count\":${NOT_SCANNED},\"reason\":\"intermediate-status\"}"
  exit 1
fi
```

**At every override accept:**
```bash
if [[ "$ARGUMENTS" =~ --allow-intermediate ]]; then
  log_override_debt "--allow-intermediate" "$PHASE_NUMBER" "review.4c-pre" "..."
  # override-debt.md already emits override_used event via v2, no double-log needed
fi
```

**At fix routing (WRITE STRICT — use v2):**
```bash
emit_telemetry_v2 "fix_routed" "$PHASE_NUMBER" "review.3c" \
  "" "${OUTCOME:-PASS}" \
  "{\"tier\":\"${TIER}\",\"severity\":\"${SEVERITY}\",\"model\":\"${MODEL:-inline}\"}"
```

**At step boundaries:**
```bash
telemetry_step_start "$PHASE_NUMBER" "build.wave-3"
# ... work ...
telemetry_step_end "$PHASE_NUMBER" "build.wave-3" $?
```

## Instrumentation checklist

| Command | Events to emit |
|---------|---------------|
| `build` | gate_hit (wave-commits, test-infra, design-manifest), override_used, phase_step_start/end (per wave), crossai_result (if planner CrossAI runs) |
| `review` | gate_hit (4c-pre intermediate), fix_routed (3c), phase_step_start/end (phase 2/3/4), crossai_result |
| `test` | gate_hit (NOT_SCANNED, verdict compute), phase_step_start/end (5a-5g), visual_regression_fail (if F11 enabled) |
| `accept` | gate_hit (debt, regression), override_used |
| `blueprint` | gate_hit (stale-refs, planner-validation), crossai_result |
| `map` | graphify_skip, graphify_incremental |
| `secure-phase` | security_threat_added, security_threat_resolved |

## Success criteria

- Every gate hit logged (pass AND fail events — not just blocks)
- Phase timing measurable (step_start/end pairs)
- Zero cost if disabled (`config.telemetry.enabled: false` → all emit calls return early)
- File stays bounded via retention_days auto-prune
- Schema forward-compatible (meta is arbitrary JSON — new fields don't break readers)
