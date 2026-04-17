# shellcheck shell=bash
# Override Debt Register — bash function library
# Companion runtime for: .claude/commands/vg/_shared/override-debt.md
# Docs (resolution model, entry schema, integration points) live in the .md file.
#
# Exposed functions:
#   - log_override_debt FLAG PHASE STEP REASON [GATE_ID]
#   - override_resolve GATE_ID PHASE TELEMETRY_EVENT_ID
#   - override_list_unresolved               (stdout: JSON array)
#   - override_migrate_legacy
#   - check_blocking_debt PHASE              (exit 1 if blocking debt exists)

# Helper — call AFTER an override is accepted
# Usage: log_override_debt FLAG PHASE STEP REASON GATE_ID
#   GATE_ID (optional): telemetry gate id of the bypassed gate. Needed to match
#   future clean re-runs for event-based resolution. Pass "" if not applicable.
log_override_debt() {
  local flag="$1"        # e.g. "--allow-missing-commits"
  local phase="$2"       # e.g. "7.12"
  local step="$3"        # e.g. "build.wave-3"
  local reason="$4"      # user-provided justification or auto-derived context
  local gate_id="${5:-}" # telemetry gate_id of the bypassed gate (for event-based resolution)
  local register="${CONFIG_DEBT_REGISTER_PATH:-.planning/OVERRIDE-DEBT.md}"

  # Bootstrap file if missing
  if [ ! -f "$register" ]; then
    cat > "$register" <<'HEADER'
# Override Debt Register

Auto-maintained by VG workflow. Every override flag logged here.

**Resolution model (v1.8.0+):** entries resolve ONLY when the bypassed gate re-runs cleanly
(telemetry `override_resolved` event). Time-based expiry is BANNED — entries stay OPEN
forever until resolved by event OR explicitly marked `--wont-fix`. Legacy entries
(without `resolved_by_event_id`) are flagged for manual triage.

`/vg:accept` blocks while critical OPEN entries remain.

## Entries

| ID | Severity | Phase | Step | Flag | Reason | Logged (UTC) | Status | Gate ID | Resolved-By-Event | Legacy |
|----|----------|-------|------|------|--------|--------------|--------|---------|-------------------|--------|
HEADER
  fi

  # Derive severity from config
  local severity="medium"
  for sev in critical high medium; do
    local flags_var="CONFIG_DEBT_SEVERITIES_${sev^^}"
    if grep -qF "$flag" <<<"${!flags_var:-}"; then severity="$sev"; break; fi
  done

  local id="DEBT-$(date -u +%Y%m%d%H%M%S)-$$"
  local ts="$(date -u +%FT%TZ)"
  printf '| %s | %s | %s | %s | `%s` | %s | %s | OPEN | %s |  | false |\n' \
    "$id" "$severity" "$phase" "$step" "$flag" "${reason//|/\\|}" "$ts" "${gate_id:-}" >> "$register"

  # Emit telemetry event (v2 API)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "override_used" "$phase" "$step" "$gate_id" "OVERRIDE" \
      "{\"flag\":\"$flag\",\"severity\":\"$severity\",\"debt_id\":\"$id\"}"
  elif type -t emit_telemetry >/dev/null 2>&1; then
    emit_telemetry "override_used" "$phase" "$step" \
      "{\"flag\":\"$flag\",\"severity\":\"$severity\",\"debt_id\":\"$id\",\"gate_id\":\"$gate_id\"}"
  fi

  echo "⚠ Override (bỏ qua) debt logged: ${id} (${severity}). Gate: ${gate_id:-none}. Review: ${register}"
  echo "   Resolution (giải quyết): re-run gate cleanly → auto-resolved via telemetry event."
}

# Helper — mark an override entry as resolved via telemetry event correlation
# Usage: override_resolve GATE_ID PHASE TELEMETRY_EVENT_ID
#   Called when a previously-bypassed gate re-runs cleanly. Links the clean
#   telemetry event to the original debt entry.
override_resolve() {
  local gate_id="$1"
  local phase="$2"
  local telemetry_event_id="$3"
  local register="${CONFIG_DEBT_REGISTER_PATH:-.planning/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || return 0
  [ -z "$gate_id" ] && { echo "override_resolve: gate_id required" >&2; return 1; }

  # Find matching OPEN entry for (gate_id, phase) and update in-place
  ${PYTHON_BIN:-python3} - "$register" "$gate_id" "$phase" "$telemetry_event_id" <<'PY'
import re, sys
from pathlib import Path
register, gate_id, phase, event_id = sys.argv[1:5]
p = Path(register)
if not p.exists(): sys.exit(0)
text = p.read_text(encoding='utf-8')
lines = text.splitlines()
# Row regex: | ID | Sev | Phase | Step | `flag` | reason | ts | STATUS | gate_id | resolved_by | legacy |
row_re = re.compile(
  r'^\|\s*(DEBT-\d+-\d+)\s*\|([^|]*)\|\s*([^|]*?)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|'
)
out = []
matched = 0
for line in lines:
  m = row_re.match(line)
  if not m:
    out.append(line); continue
  did, sev, ph, step, flag, reason, ts, status, gid, rbe, legacy = [g.strip() for g in m.groups()]
  if status == 'OPEN' and ph == phase and gid == gate_id:
    # Update this row
    new_line = f"| {did} | {sev} | {ph} | {step} | {flag} | {reason} | {ts} | RESOLVED | {gid} | {event_id} | {legacy or 'false'} |"
    out.append(new_line)
    matched += 1
    print(f"override_resolve: matched {did} (gate={gid}, phase={ph}) → RESOLVED via event {event_id}", file=sys.stderr)
  else:
    out.append(line)
p.write_text('\n'.join(out) + ('\n' if out else ''), encoding='utf-8')
if matched == 0:
  print(f"override_resolve: no OPEN entry found for gate={gate_id} phase={phase}", file=sys.stderr)
PY

  # Emit telemetry resolution event (idempotent — event already exists, this just mirrors into schema)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "override_resolved" "$phase" "" "$gate_id" "PASS" \
      "{\"original_override_event_id\":\"$telemetry_event_id\"}"
  fi
}

# Helper — list unresolved overrides (resolved_by_event_id == null, status == OPEN)
# Returns: JSON array to stdout. Each entry: {id, severity, phase, step, flag, reason, logged_ts, gate_id, legacy}
override_list_unresolved() {
  local register="${CONFIG_DEBT_REGISTER_PATH:-.planning/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || { echo "[]"; return 0; }

  ${PYTHON_BIN:-python3} - "$register" <<'PY'
import re, json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
  print("[]"); sys.exit(0)
row_re = re.compile(
  r'^\|\s*(DEBT-\d+-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|'
)
unresolved = []
for line in p.read_text(encoding='utf-8').splitlines():
  m = row_re.match(line)
  if not m: continue
  did, sev, ph, step, flag, reason, ts, status, gid, rbe, legacy = [g.strip() for g in m.groups()]
  if status != 'OPEN': continue
  if rbe and rbe.lower() not in ('', 'null', 'none'): continue
  unresolved.append({
    "id": did,
    "severity": sev,
    "phase": ph,
    "step": step,
    "flag": flag.strip('`'),
    "reason": reason,
    "logged_ts": ts,
    "gate_id": gid if gid else None,
    "legacy": (legacy.lower() == 'true')
  })
print(json.dumps(unresolved, ensure_ascii=False))
PY
}

# Helper — migrate legacy entries (pre-v1.8.0, no resolved_by_event_id column)
# Adds gate_id="" + resolved_by_event_id="" + legacy=true columns in-place. Idempotent.
override_migrate_legacy() {
  local register="${CONFIG_DEBT_REGISTER_PATH:-.planning/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || return 0

  ${PYTHON_BIN:-python3} - "$register" <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text(encoding='utf-8')
lines = text.splitlines()
# Old schema: | ID | Sev | Phase | Step | `flag` | reason | ts | STATUS | Resolved? |
# New schema: | ID | Sev | Phase | Step | `flag` | reason | ts | STATUS | gate_id | resolved_by | legacy |
old_re = re.compile(
  r'^\|\s*(DEBT-\d+-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(OPEN|RESOLVED|ESCALATED|WONT_FIX)\s*\|([^|]*)\|$'
)
new_re = re.compile(
  r'^\|\s*DEBT-\d+-\d+\s*\|.*\|.*\|.*\|.*\|.*\|.*\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|.*\|.*\|.*\|'
)
out = []
migrated = 0
for line in lines:
  # Already new schema — pass through
  if new_re.match(line):
    out.append(line); continue
  m = old_re.match(line)
  if not m:
    out.append(line); continue
  did, sev, ph, step, flag, reason, ts, status, resolved_old = [g.strip() for g in m.groups()]
  # ESCALATED legacy status → OPEN with legacy flag (time-based was never valid)
  if status == 'ESCALATED':
    status = 'OPEN'
  new_line = f"| {did} | {sev} | {ph} | {step} | {flag} | {reason} | {ts} | {status} |  |  | true |"
  out.append(new_line)
  migrated += 1

if migrated:
  p.write_text('\n'.join(out) + '\n', encoding='utf-8')
  print(f"override_migrate_legacy: migrated {migrated} legacy entries — review 'legacy:true' rows for manual triage", file=sys.stderr)
PY
}

# Helper — /vg:accept calls this before UAT
# Checks OPEN entries at blocking severity that are NOT resolved by event
check_blocking_debt() {
  local phase="$1"
  local register="${CONFIG_DEBT_REGISTER_PATH:-.planning/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || return 0

  local blocking_sev="${CONFIG_DEBT_BLOCKING_SEVERITY:-critical}"
  # Count OPEN + unresolved entries at blocking severity
  local open_count
  open_count=$(${PYTHON_BIN:-python3} - "$register" "$blocking_sev" <<'PY'
import re, sys
from pathlib import Path
register, blocking_sev = sys.argv[1], sys.argv[2]
row_re = re.compile(
  r'^\|\s*(DEBT-\d+-\d+)\s*\|\s*([^|]*?)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|([^|]*)\|\s*([^|]*?)\s*\|([^|]*)\|'
)
blocking = {s.strip() for s in blocking_sev.split()}
count = 0
for line in Path(register).read_text(encoding='utf-8').splitlines():
  m = row_re.match(line)
  if not m: continue
  did, sev, ph, step, flag, reason, ts, status, gid, rbe, legacy = [g.strip() for g in m.groups()]
  if status == 'OPEN' and sev in blocking:
    if not rbe or rbe.lower() in ('', 'null', 'none'):
      count += 1
print(count)
PY
)

  if [ "${open_count:-0}" -gt 0 ]; then
    echo "⛔ ${open_count} unresolved debt entries at blocking severity (${blocking_sev})."
    echo "   Review: ${register}"
    echo "   Resolve (giải quyết): re-run the bypassed gate cleanly → auto-links via telemetry event."
    echo "   Alternatively: /vg:override-resolve {gate_id} --wont-fix --reason='...'"
    echo "   Accept cannot proceed with critical debt unresolved."
    return 1
  fi
  return 0
}
