# shellcheck shell=bash
# Telemetry Pipeline — bash function library
# Companion runtime for: .claude/commands/vg/_shared/telemetry.md
# Docs (event schema, standard event types, integration pattern) live in the .md file.
#
# Exposed functions:
#   - telemetry_init
#   - emit_telemetry_v2 EVENT_TYPE PHASE STEP [GATE_ID] [OUTCOME] [PAYLOAD_JSON] [CORRELATION_ID] [COMMAND]
#   - emit_telemetry EVENT_TYPE PHASE STEP [PAYLOAD_JSON]   (back-compat)
#   - telemetry_query [--gate-id=X] [--outcome=X] [--phase=X] [--event-type=X] [--since=X]
#   - telemetry_warn_overrides [THRESHOLD] [MILESTONE_SINCE]
#   - telemetry_prune
#   - telemetry_step_start PHASE STEP
#   - telemetry_step_end PHASE STEP [EXIT_CODE]

# Init once per VG command invocation (top of command)
telemetry_init() {
  [ "${CONFIG_TELEMETRY_ENABLED:-true}" = "true" ] || return 0
  export TELEMETRY_SESSION_ID="${TELEMETRY_SESSION_ID:-$(openssl rand -hex 8 2>/dev/null || printf '%08x%08x' $RANDOM $RANDOM)}"
  export TELEMETRY_PATH="${CONFIG_TELEMETRY_PATH:-.planning/telemetry.jsonl}"
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
  local path="${TELEMETRY_PATH:-.planning/telemetry.jsonl}"

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
# WRITE-STRICT (v1.9.0 T5): legacy 4-arg callers emit a stderr deprecation WARN so debt surfaces.
# The event is still written, but payload gets `legacy_call:true` marker so downstream query
# can filter them out. Config `telemetry.strict_write` (default true v1.9.0) controls WARN.
# v2.0 plan: shim will hard-fail unless CONFIG_TELEMETRY_ALLOW_LEGACY=true.
emit_telemetry() {
  local event_type="$1" phase="$2" step="$3" payload_json="${4-}"
  [ -z "$payload_json" ] && payload_json='{}'

  # Deprecation WARN (Vietnamese user-facing + English caller hint)
  if [ "${CONFIG_TELEMETRY_STRICT_WRITE:-true}" = "true" ]; then
    local caller_hint="${BASH_SOURCE[1]:-unknown}:${BASH_LINENO[0]:-?}"
    echo "⚠ emit_telemetry: DEPRECATED 4-arg call (gọi cũ) from ${caller_hint}; please migrate to emit_telemetry_v2 (event_type phase step gate_id outcome payload). Telemetry query --gate-id sẽ thiếu dữ liệu." >&2
  fi

  # Extract gate_id + outcome from payload if present (best-effort migration)
  local gate_id outcome
  gate_id=$(${PYTHON_BIN:-python3} -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('gate_id',''))" "$payload_json" 2>/dev/null || echo "")
  outcome=$(${PYTHON_BIN:-python3} -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('outcome',''))" "$payload_json" 2>/dev/null || echo "")

  # Inject legacy_call marker into payload so query/summarize can surface debt.
  # Use stdin instead of argv to avoid double-escape when payload contains quotes.
  local marked_payload
  marked_payload=$(${PYTHON_BIN:-python3} -c '
import json, sys
raw = sys.stdin.read()
try:
  d = json.loads(raw) if raw.strip() else {}
except Exception:
  d = {"_raw": raw}
d["legacy_call"] = True
sys.stdout.write(json.dumps(d, ensure_ascii=False))
' <<<"$payload_json" 2>/dev/null)
  [ -z "$marked_payload" ] && marked_payload="$payload_json"

  emit_telemetry_v2 "$event_type" "$phase" "$step" "$gate_id" "$outcome" "$marked_payload"
}

# Query API — filter events by gate_id / outcome / phase / event_type / since
# Usage: telemetry_query --gate-id=X --outcome=OVERRIDE --since=2026-04-10
telemetry_query() {
  local path="${TELEMETRY_PATH:-.planning/telemetry.jsonl}"
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
  local path="${TELEMETRY_PATH:-.planning/telemetry.jsonl}"
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
  local path="${TELEMETRY_PATH:-.planning/telemetry.jsonl}"
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

# Phase timing helpers
# WRITE-STRICT: call emit_telemetry_v2 directly (not shim) so no deprecation WARN.
# Step boundary events are NOT gate events → gate_id="" intentional; outcome="" for start,
# outcome reflects exit code for end. Reserving gate_id for actual gate-hit events keeps
# `telemetry_query --gate-id=X` signal clean.
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
  local outcome="PASS"
  [ "$exit_code" != "0" ] && outcome="FAIL"
  emit_telemetry_v2 "phase_step_end" "$phase" "$step" "" "$outcome" \
    "{\"duration_s\":${duration},\"exit_code\":${exit_code}}"
}
