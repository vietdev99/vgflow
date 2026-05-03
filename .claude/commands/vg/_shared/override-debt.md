---
name: vg:_shared:override-debt
description: Override Debt Register (Shared Reference) — track every --allow/--skip/--override-reason usage, event-based resolution via telemetry (NO time-based expiry), block accept on unresolved critical debt
---

# Override Debt Register — Shared Helper

> **⚠ Runtime note (v1.9.0 T3):** Runnable bash code is at [`_shared/lib/override-debt.sh`](lib/override-debt.sh). Commands MUST `source` the `.sh` file — this `.md` file is documentation only (YAML frontmatter + markdown headers + fenced code blocks cannot be sourced by bash). The bash snippets below are kept in sync with `.sh` for readability.

Every VG override flag (`--allow-*`, `--skip-*`, `--override-*`) MUST log to `${PLANNING_DIR}/OVERRIDE-DEBT.md`. Debt register makes invisible technical debt visible, forces review, blocks `accept` when critical debt is unresolved.

## ⛔ Time-based expiry is BANNED (v1.8.0)

Prior versions auto-escalated or auto-forgave overrides after N days. That model silently buried real issues: a 14-day-old `--allow-missing-commits` override does NOT mean the missing commit appeared — it means we stopped watching.

**New model (event-based resolution):**
- An override entry is ONLY resolved when the bypassed gate later re-runs cleanly.
- Resolution is recorded as a telemetry event (`override_resolved`) whose `event_id` is written back into the debt entry's `resolved_by_event_id` field.
- No clock-based escalation. No retention window. Entries stay OPEN forever (until resolved by event or explicitly `--wont-fix`).
- Legacy entries without `resolved_by_event_id` are flagged `legacy:true` and surfaced for triage.

**Narration policy (NARRATION_POLICY compliant):**
- "override (bỏ qua)" — gate bị tạm bỏ qua, nợ kỹ thuật ghi nhận.
- "resolution (giải quyết)" — gate re-run sạch, nợ được xóa qua telemetry event.
- "legacy (cũ)" — entries trước v1.8.0, chưa có event link — cần triage thủ công.

## Config (add to `.claude/vg.config.md`)

```yaml
debt:
  register_path: "${PLANNING_DIR}/OVERRIDE-DEBT.md"
  # NO auto_expire_days — time-based expiry is BANNED in v1.8.0+
  # Overrides expire ONLY when the bypassed gate re-runs cleanly (via telemetry event).
  blocking_severity: ["critical"]   # /vg:accept blocks if unresolved entries at these severities
  severities:
    critical:                       # safety-critical overrides
      - "--allow-missing-commits"
      - "--override-reason"         # build wave accept with issue ID — still tracked
      - "--override-regressions"
      - "--allow-unreachable"
      - "--allow-unresolved-overrides"
    high:
      - "--allow-no-tests"
      - "--skip-design-check"
      - "--allow-intermediate"
      - "--skip-context-rebuild"
      - "--force-accept-with-debt"
    medium:
      - "--skip-crossai"
      - "--skip-research"
      - "--allow-deferred"
```

## v1.15.0 — Scope + Revalidation (Bootstrap Overlay)

**Scenario 1 fix (playwright laziness):** prior to v1.15.0 an override created
in Phase Y (e.g., `--skip-playwright` because Y has no UI) could silently
propagate to Phase Z even if Z has UI. Overrides now MUST declare a `scope`
predicate and get re-evaluated at the start of every `/vg:*` command.

**New optional fields on each entry (non-breaking; legacy entries still load):**

```yaml
scope:                           # structured DSL predicate (see scope-evaluator.py)
  required_all:
    - "phase.surfaces does_not_contain 'web'"
    - "phase.has_mutation == false"    # example — compose as needed
revalidate_on:                   # triggers that FORCE fresh eval
  - new_phase_starts             # default — every time phase number changes
  - phase.surfaces_change        # if surface topology shifts mid-phase
```

**Fail-closed polarity for overrides (opposite of rules):**
- scope evaluates to `true` → override carried forward (gate stays SKIPPED)
- scope evaluates to `false` → override **EXPIRED** (gate goes ACTIVE)
- scope missing or malformed (legacy) → treated as `legacy` + carried but FLAGGED for triage
- unknown variable → predicate false → override expires (safe default)

**Hook point:** `.claude/commands/vg/_shared/config-loader.md` runs
`override-revalidate.py` after bootstrap load at every command start.
Expired overrides emit telemetry `override.expired` and are excluded from
gate-bypass logic until user re-authorizes with a fresh override+scope.

## Entry schema (v1.8.0)

Each row in `${PLANNING_DIR}/OVERRIDE-DEBT.md` carries:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | `DEBT-YYYYMMDDHHMMSS-PID` |
| `severity` | enum | `critical` \| `high` \| `medium` |
| `phase` | string | phase number (e.g. `7.12`) |
| `step` | string | e.g. `build.wave-3`, `review.4c-pre` |
| `flag` | string | the override flag (e.g. `--allow-missing-commits`) |
| `reason` | string | user justification |
| `logged_ts` | ISO-8601 UTC | when created |
| `status` | enum | `OPEN` \| `RESOLVED` \| `WONT_FIX` — `WONT_FIX` set by `/vg:override-resolve --wont-fix` for permanent declines; treated as resolved by accept gate |
| `gate_id` | string | telemetry gate id of the bypassed gate (for re-run matching) |
| `resolved_by_event_id` | UUID\|null | telemetry `override_resolved` event id (null until resolved) |
| `legacy` | bool | true for pre-v1.8.0 entries without event link |

Serialized to markdown table; JSON-ish fields kept in trailing inline columns for human readability.

## API

```bash
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
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"

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
# Usage: override_resolve GATE_ID PHASE TELEMETRY_EVENT_ID [STATUS]
#   Called when a previously-bypassed gate re-runs cleanly. Links the clean
#   telemetry event to the original debt entry.
#   STATUS (optional, default RESOLVED): RESOLVED | WONT_FIX
override_resolve() {
  local gate_id="$1"
  local phase="$2"
  local telemetry_event_id="$3"
  local status="${4:-RESOLVED}"
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || return 0
  [ -z "$gate_id" ] && { echo "override_resolve: gate_id required" >&2; return 1; }
  case "$status" in RESOLVED|WONT_FIX) ;; *) echo "override_resolve: invalid status '$status' (want RESOLVED|WONT_FIX)" >&2; return 1 ;; esac

  # Find matching OPEN entry for (gate_id, phase) and update in-place
  ${PYTHON_BIN:-python3} - "$register" "$gate_id" "$phase" "$telemetry_event_id" "$status" <<'PY'
import re, sys
from pathlib import Path
register, gate_id, phase, event_id, new_status = sys.argv[1:6]
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
    new_line = f"| {did} | {sev} | {ph} | {step} | {flag} | {reason} | {ts} | {new_status} | {gid} | {event_id} | {legacy or 'false'} |"
    out.append(new_line)
    matched += 1
    print(f"override_resolve: matched {did} (gate={gid}, phase={ph}) → {new_status} via event {event_id}", file=sys.stderr)
  else:
    out.append(line)
p.write_text('\n'.join(out) + ('\n' if out else ''), encoding='utf-8')
if matched == 0:
  print(f"override_resolve: no OPEN entry found for gate={gate_id} phase={phase}", file=sys.stderr)
PY

  # Emit telemetry resolution event (idempotent — event already exists, this just mirrors into schema)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "override_resolved" "$phase" "" "$gate_id" "PASS" \
      "{\"original_override_event_id\":\"$telemetry_event_id\",\"status\":\"$status\"}"
  fi
}

# Helper — resolve a single debt entry by its DEBT-ID (used by /vg:override-resolve --wont-fix)
# Usage: override_resolve_by_id DEBT_ID STATUS REASON
#   STATUS: RESOLVED | WONT_FIX
#   Emits override_resolved telemetry event with {status, reason, debt_id}.
#   Prints emitted event_id on success, or empty string + nonzero exit on failure.
override_resolve_by_id() {
  local debt_id="$1" new_status="$2" reason="$3"
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
  [ -f "$register" ] || { echo "override_resolve_by_id: register not found" >&2; return 1; }
  [ -z "$debt_id" ] && { echo "override_resolve_by_id: debt_id required" >&2; return 1; }
  [ -z "$reason" ] && { echo "override_resolve_by_id: reason required" >&2; return 1; }
  case "$new_status" in RESOLVED|WONT_FIX) ;; *) echo "override_resolve_by_id: invalid status" >&2; return 1 ;; esac

  # Emit telemetry first so we can write event_id back into the row
  local event_id="manual-${new_status,,}-$(date -u +%Y%m%d%H%M%S)"
  local payload
  payload=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.dumps({'status':sys.argv[1],'reason':sys.argv[2],'debt_id':sys.argv[3],'manual':True}))" \
    "$new_status" "$reason" "$debt_id" 2>/dev/null || echo "{}")
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    local emitted
    emitted=$(emit_telemetry_v2 "override_resolved" "" "" "" "PASS" "$payload" 2>/dev/null | tail -n1)
    [ -n "$emitted" ] && event_id="$emitted"
  fi

  # Patch the single matching row (by DEBT-ID, must be OPEN/active).
  # Issue #19: register has TWO coexisting formats:
  #   - Markdown table:  | DEBT-YYYYMMDDHHMMSS-PID | sev | ph | step | flag | reason | ts | OPEN | gid | rbe | legacy |
  #   - YAML block:      `- id: OD-NNN\n  logged_at: ...\n  ... \n  status: active\n`
  # Orchestrator CLI writes the YAML form; legacy gates use the table.
  # Detect by ID prefix and mutate the right shape.
  ${PYTHON_BIN:-python3} - "$register" "$debt_id" "$new_status" "$event_id" "$reason" <<'PY' || return 1
import re, sys
from datetime import datetime, timezone
from pathlib import Path
register, target_id, new_status, event_id, reason = sys.argv[1:6]
p = Path(register)
text = p.read_text(encoding='utf-8')
lines = text.splitlines()

is_yaml_id = bool(re.match(r'^(OD-\d+|BF-\d+-\d+)$', target_id))

if is_yaml_id:
  # YAML block format. Find `- id: OD-NNN`, update its status sub-key.
  out, matched, found_any = [], 0, False
  i = 0
  while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    if stripped == f'- id: {target_id}':
      found_any = True
      # Block runs from this `- id:` line up to (but not including)
      # the next `- ` at the same indent or EOF.
      block = [line]
      j = i + 1
      while j < len(lines):
        nxt = lines[j]
        if re.match(r'^- ', nxt):
          break
        block.append(nxt)
        j += 1
      # Find status: line inside the block.
      status_idx = None
      for k, bl in enumerate(block):
        if re.match(r'^\s*status:', bl):
          status_idx = k
          break
      if status_idx is None:
        # Malformed block — leave alone, keep going.
        out.extend(block); i = j; continue
      current = block[status_idx].split(':', 1)[1].strip()
      if current.lower() in ('active', 'open'):
        # Preserve indentation of the status line.
        indent = re.match(r'^(\s*)', block[status_idx]).group(1)
        ts_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Replace newlines + double-quotes in reason for safe YAML scalar.
        safe_reason = reason.replace('"', "'").replace('\n', ' ')
        block[status_idx] = f"{indent}status: {new_status}"
        # Insert resolved_* keys immediately after status to keep the YAML
        # block contiguous (avoids blank-line gaps if the original entry
        # ended with whitespace).
        block[status_idx+1:status_idx+1] = [
          f"{indent}resolved_at: {ts_iso}",
          f"{indent}resolved_event_id: {event_id}",
          f'{indent}resolution_reason: "{safe_reason}"',
        ]
        matched += 1
      out.extend(block)
      i = j
    else:
      out.append(line)
      i += 1
else:
  # Markdown table format (legacy DEBT-... IDs).
  row_re = re.compile(
    r'^\|\s*(DEBT-\d+-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|'
  )
  out, matched, found_any = [], 0, False
  for line in lines:
    m = row_re.match(line)
    if not m:
      out.append(line); continue
    did, sev, ph, step, flag, reason_old, ts, status, gid, rbe, legacy = [g.strip() for g in m.groups()]
    if did == target_id:
      found_any = True
      if status == 'OPEN':
        merged_reason = f"{reason_old} || {new_status.lower()}: {reason}"
        out.append(f"| {did} | {sev} | {ph} | {step} | {flag} | {merged_reason} | {ts} | {new_status} | {gid} | {event_id} | {legacy or 'false'} |")
        matched += 1
        continue
    out.append(line)

p.write_text('\n'.join(out) + ('\n' if out else ''), encoding='utf-8')
if not found_any:
  print(f"override_resolve_by_id: DEBT-ID not found: {target_id}", file=sys.stderr); sys.exit(2)
if matched == 0:
  print(f"override_resolve_by_id: {target_id} already resolved (not OPEN/active) — no change", file=sys.stderr); sys.exit(3)
print(f"override_resolve_by_id: {target_id} → {new_status} (event {event_id})", file=sys.stderr)
PY

  echo "$event_id"
}

# Helper — list unresolved overrides (resolved_by_event_id == null, status == OPEN)
# Returns: JSON array to stdout. Each entry: {id, severity, phase, step, flag, reason, logged_ts, gate_id, legacy}
override_list_unresolved() {
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
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
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
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
  local register="${CONFIG_DEBT_REGISTER_PATH:-${PLANNING_DIR}/OVERRIDE-DEBT.md}"
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
```

## Integration points

| Command | Step | Flag | Call |
|---------|------|------|------|
| `build` | resume | `--skip-context-rebuild` | `log_override_debt "--skip-context-rebuild" "$PHASE" "build.resume" "artifacts fresh" "context-rebuild"` |
| `build` | design | `--skip-design-check` | `log_override_debt "--skip-design-check" "$PHASE" "build.design-manifest" "user override" "design-check"` |
| `build` | wave | `--allow-missing-commits` | `log_override_debt "--allow-missing-commits" "$PHASE" "build.wave-$N" "missing=$MISSING_TASKS" "wave-commits"` |
| `build` | test-infra | `--allow-no-tests` | `log_override_debt "--allow-no-tests" "$PHASE" "build.wave-$N" "test infra not configured" "test-infra"` |
| `build` | hard-gate | `--override-reason=X` | `log_override_debt "--override-reason" "$PHASE" "build.hard-gate" "$REASON_VALUE" "build-hard-gate"` |
| `review` | 4c-pre | `--allow-intermediate` | `log_override_debt "--allow-intermediate" "$PHASE" "review.4c-pre" "NOT_SCANNED=$N, FAILED=$M" "not-scanned-defer"` |
| `blueprint` | hard-gate | `--override` | `log_override_debt "--override" "$PHASE" "blueprint.gate" "user proceed with gaps" "blueprint-gate"` |
| `accept` | regression | `--override-regressions=X` | `log_override_debt "--override-regressions" "$PHASE" "accept.regression" "$REASON" "regression-surface"` |
| `accept` | unresolved-overrides | `--allow-unresolved-overrides` | `log_override_debt "--allow-unresolved-overrides" "$PHASE" "accept.override-resolution-gate" "$REASON" "override-resolution-gate"` |
| `next` | advance | `--allow-deferred` | `log_override_debt "--allow-deferred" "$PHASE" "next.advance" "DEFERRED pending" "deferred-advance"` |
| `test` | crossai | `--skip-crossai` | `log_override_debt "--skip-crossai" "$PHASE" "test.crossai" "per-run opt-out" "crossai"` |

**Note:** The 5th arg (`gate_id`) is the telemetry gate id of the bypassed gate. When that same gate later runs cleanly (emits `PASS` outcome for the same phase), `override_resolve` automatically links the two events and marks the debt entry RESOLVED.

## Resolution trigger pattern

Every gate that CAN be overridden MUST call `override_resolve` on clean pass:

```bash
# Inside a gate — after it passes cleanly
if [ "$gate_pass" = "true" ]; then
  event_id=$(emit_telemetry_v2 "gate_hit" "$PHASE_NUMBER" "$STEP" "$GATE_ID" "PASS" "{\"reason\":\"clean re-run\"}")
  # Auto-resolve any prior overrides for this gate+phase
  override_resolve "$GATE_ID" "$PHASE_NUMBER" "$event_id"
fi
```

## Accept gate integration

In `.claude/commands/vg/accept.md` step `3c_override_resolution_gate` (after debt surface, before UAT):

```bash
source .claude/commands/vg/_shared/lib/override-debt.sh  # .sh — .md is docs only
override_migrate_legacy                               # idempotent — migrates pre-v1.8.0 entries
if ! check_blocking_debt "$PHASE_NUMBER"; then
  UNRESOLVED=$(override_list_unresolved)
  echo ""
  echo "Unresolved overrides (chưa giải quyết):"
  echo "$UNRESOLVED" | ${PYTHON_BIN} -m json.tool
  echo ""
  echo "Resolution paths:"
  echo "  1. Re-run the failing gate cleanly — auto-resolves via telemetry event"
  echo "  2. /vg:override-resolve {gate_id} --wont-fix --reason='...'  (explicit decline)"
  echo "  3. --allow-unresolved-overrides --reason='...'  (NEW debt entry, still blocks next accept)"
  if [[ ! "$ARGUMENTS" =~ --allow-unresolved-overrides ]]; then exit 1; fi
  REASON=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
  [ -z "$REASON" ] && { echo "⛔ --allow-unresolved-overrides requires --reason='...'"; exit 1; }
  log_override_debt "--allow-unresolved-overrides" "$PHASE_NUMBER" "accept.override-resolution-gate" "$REASON" "override-resolution-gate"
fi
```

## Progress surfacing

In `.claude/commands/vg/progress.md` (detect + report):
```bash
if [ -f "${CONFIG_DEBT_REGISTER_PATH}" ]; then
  UNRESOLVED=$(override_list_unresolved | ${PYTHON_BIN} -c "import json,sys; print(len(json.load(sys.stdin)))")
  LEGACY=$(override_list_unresolved | ${PYTHON_BIN} -c "import json,sys; print(sum(1 for e in json.load(sys.stdin) if e.get('legacy')))")
  [ "${UNRESOLVED:-0}" -gt 0 ] && echo "⚠ Debt (nợ): ${UNRESOLVED} unresolved (${LEGACY} legacy — cũ, cần triage) — see ${CONFIG_DEBT_REGISTER_PATH}"
fi
```

## Manual resolution: `/vg:override-resolve` (v1.9.0+)

For overrides that will NEVER be clean-resolved (e.g. scaffolding phase that deliberately skipped tests — no natural re-run trigger). Use sparingly; prefer clean re-run path.

**Usage:** `/vg:override-resolve <DEBT-ID> --reason='<justification>' [--wont-fix]`

**Behavior:**
1. Validates DEBT-ID exists in OVERRIDE-DEBT.md.
2. If `--wont-fix`: prompts user via AskUserQuestion to confirm permanent decision.
3. Calls `override_resolve_by_id(debt_id, status, reason)` which:
   - Appends resolution reason to the entry's reason column (audit trail preserves both original + resolution justification).
   - Sets `status=WONT_FIX` (or `RESOLVED` for clean manual resolution).
   - Emits telemetry `override_resolved` event with `{status, reason, debt_id, manual:true}`.
4. Accept gate (`override_list_unresolved`) already skips non-OPEN entries — WONT_FIX rows no longer block.

Use `--allow-unresolved-overrides --reason='...'` at `/vg:accept` ONLY when you want a time-boxed defer (still creates NEW debt entry for next accept).

## Success criteria

- Every override flag logged to register with `gate_id` binding for future resolution
- Overrides resolve ONLY via telemetry events (bypassed gate re-runs cleanly)
- NO time-based escalation or expiry anywhere in the helper
- `/vg:accept` blocks if ANY unresolved critical-severity entries exist (regardless of age)
- Legacy pre-v1.8.0 entries migrated in-place with `legacy:true` flag for triage
- `/vg:progress` surfaces unresolved + legacy counts
- Register is human-editable markdown table (no tool lock-in)
- User-facing narration glosses English terms: "override (bỏ qua)", "resolution (giải quyết)", "legacy (cũ)"
