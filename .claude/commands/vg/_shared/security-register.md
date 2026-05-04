---
name: vg:_shared:security-register
description: Security Register (Shared Reference) — cumulative milestone-level threat tracking with STRIDE+OWASP taxonomy, cross-phase correlation, decay policy
---

# Security Register — Shared Helper

Per-phase security audits miss cross-phase composite threats (e.g., auth hole in P5 + privilege escalation in P7 = together they're CRITICAL even if each alone is MEDIUM). `${PLANNING_DIR}/SECURITY-REGISTER.md` is a cumulative milestone-level ledger of all threats, their mitigations, and cross-phase correlations.

## Config (add to `.claude/vg.config.md`)

```yaml
security:
  register_path: "${PLANNING_DIR}/SECURITY-REGISTER.md"
  taxonomy:                              # supported threat classifications
    - stride                             # Spoofing, Tampering, Repudiation, Information disclosure, DoS, Elevation
    - owasp_top_10                       # injection, broken-auth, sensitive-data, xxe, broken-access, ...
    - custom                             # project-specific tags
  severity_scale: ["info", "low", "medium", "high", "critical"]
  decay_policy:
    mitigated_archive_days: 90           # RESOLVED + mitigation verified → archive after N days
    unresolved_escalate_days: 30         # OPEN + severity≥high → auto-escalate if no progress
  composite_rules:                       # auto-escalate rules when N threats correlate
    - name: "auth-weakness + privilege-escalation"
      patterns: ["broken-auth", "broken-access"]
      resulting_severity: "critical"
      phases_min: 2
  accept_gate:
    block_on_open: ["critical"]          # /vg:accept blocks if OPEN threats at these severities
  milestone_audit:
    required_before_milestone_complete: true
```

## File schema — `${PLANNING_DIR}/SECURITY-REGISTER.md`

```markdown
# Security Register (Milestone: {milestone_id})

Cumulative threat ledger across all phases. Auto-maintained. Cross-phase composite threats computed by `/vg:security-audit-milestone`.

## Threats

| ID | Severity | Phase(s) | Taxonomy | Title | Mitigation Status | Evidence | Created | Last Updated |
|----|----------|----------|----------|-------|-------------------|----------|---------|--------------|
| SEC-001 | high | 7.12 | stride:T, owasp:A03 | Conversion pixel accepts arbitrary advertiser_id without auth | MITIGATED | apps/api/src/modules/conversions/*.ts: HMAC check | 2026-04-10 | 2026-04-17 |
| SEC-002 | medium | 5, 7.8 | stride:I | Video ad VAST response leaks internal URLs | OPEN | — | 2026-04-01 | 2026-04-15 |

## Composite Threats (auto-correlated)

| Composite ID | Component SEC-IDs | Phases | Combined Severity | Rule |
|-------------|-------------------|--------|-------------------|------|
| COMP-001 | SEC-002, SEC-014 | 5, 7.8, 7.12 | critical | info-disclosure-chain |

## Decay Log
- 2026-01-15 SEC-005 archived (mitigated 90d ago)
- 2026-04-17 SEC-012 escalated to high (unresolved 30d)

## Audit Trail
- 2026-04-17T09:30Z `/vg:security-audit-milestone` run: +2 new, +1 composite, 1 escalated
```

## API

```bash
# Add/update threat — called from /vg:secure-phase
register_threat() {
  local threat_id="${1:-auto}"          # "auto" generates SEC-NNN
  local severity="$2"                   # critical|high|medium|low|info
  local phase="$3"                      # "7.12" or "5,7.8" (multi-phase)
  local taxonomy="$4"                   # "stride:T,owasp:A03"
  local title="$5"                      # short description
  local status="${6:-OPEN}"             # OPEN|IN_PROGRESS|MITIGATED|ACCEPTED_RISK
  local evidence="${7:--}"              # file:line references
  local register="${CONFIG_SECURITY_REGISTER_PATH:-${PLANNING_DIR}/SECURITY-REGISTER.md}"

  # Bootstrap if missing
  if [ ! -f "$register" ]; then
    local milestone="${MILESTONE_ID:-unknown}"
    cat > "$register" <<HEADER
# Security Register (Milestone: ${milestone})

Cumulative threat ledger across all phases. Auto-maintained. Cross-phase composite threats computed by \`/vg:security-audit-milestone\`.

## Threats

| ID | Severity | Phase(s) | Taxonomy | Title | Mitigation Status | Evidence | Created | Last Updated |
|----|----------|----------|----------|-------|-------------------|----------|---------|--------------|

## Composite Threats (auto-correlated)

| Composite ID | Component SEC-IDs | Phases | Combined Severity | Rule |
|-------------|-------------------|--------|-------------------|------|

## Decay Log

## Audit Trail
HEADER
  fi

  # Auto-generate ID if requested
  if [ "$threat_id" = "auto" ]; then
    local max_id
    max_id=$(awk -F'|' '/\| SEC-[0-9]+/ {gsub(/^ +SEC-| +$/,"",$2); print $2}' "$register" | sort -n | tail -1)
    threat_id=$(printf "SEC-%03d" $(( ${max_id:-0} + 1 )))
  fi

  local today
  today=$(date -u +%F)

  # Check if threat ID exists → update instead of append
  if grep -q "^| ${threat_id} |" "$register"; then
    ${PYTHON_BIN:-python3} - "$register" "$threat_id" "$severity" "$phase" "$taxonomy" "$title" "$status" "$evidence" "$today" <<'PY'
import sys, re
path, tid, sev, phase, tax, title, status, ev, today = sys.argv[1:]
text = open(path, encoding='utf-8').read()
# Update row — keep Created date, update Last Updated
pattern = re.compile(rf'^\| ({re.escape(tid)}) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|', re.M)
def repl(m):
  created = m.group(8).strip()
  return f"| {tid} | {sev} | {phase} | {tax} | {title} | {status} | {ev} | {created} | {today} |"
new = pattern.sub(repl, text)
open(path, 'w', encoding='utf-8').write(new)
PY
  else
    # Append new row — find end of Threats table
    ${PYTHON_BIN:-python3} - "$register" "$threat_id" "$severity" "$phase" "$taxonomy" "$title" "$status" "$evidence" "$today" <<'PY'
import sys
path, tid, sev, phase, tax, title, status, ev, today = sys.argv[1:]
text = open(path, encoding='utf-8').read()
# Find "## Threats" section, append after its header row
lines = text.splitlines()
out = []; in_threats = False; appended = False
for i, line in enumerate(lines):
  out.append(line)
  if line.strip() == "## Threats": in_threats = True
  elif in_threats and line.startswith("|----") and not appended:
    out.append(f"| {tid} | {sev} | {phase} | {tax} | {title} | {status} | {ev} | {today} | {today} |")
    appended = True; in_threats = False
open(path, 'w', encoding='utf-8').write("\n".join(out) + "\n")
PY
  fi

  # Telemetry
  if type -t emit_telemetry >/dev/null 2>&1; then
    emit_telemetry "security_threat_added" "$phase" "secure-phase" \
      "{\"threat_id\":\"$threat_id\",\"severity\":\"$severity\",\"stride_category\":\"$taxonomy\"}"
  fi

  echo "$threat_id"
}

# Check /vg:accept gate
check_security_accept_gate() {
  local register="${CONFIG_SECURITY_REGISTER_PATH:-${PLANNING_DIR}/SECURITY-REGISTER.md}"
  [ -f "$register" ] || return 0
  local blocking="${CONFIG_SECURITY_ACCEPT_GATE_BLOCK_ON_OPEN:-critical}"

  local open_critical
  open_critical=$(awk -F'|' -v block="$blocking" '
    /^\| SEC-/ {
      gsub(/^ +| +$/, "", $2); gsub(/^ +| +$/, "", $7);
      if (index(block, $2) > 0 && ($7 == "OPEN" || $7 == "IN_PROGRESS")) c++
    } END { print c+0 }' "$register")

  if [ "$open_critical" -gt 0 ]; then
    echo "⛔ ${open_critical} OPEN threats at blocking severity (${blocking}) in ${register}"
    echo "   Resolve: update Mitigation Status to MITIGATED + attach Evidence"
    echo "   Or (AUDIT-LOGGED): mark as ACCEPTED_RISK with Evidence=risk-acceptance-doc-url"
    return 1
  fi
  return 0
}

# Decay policy — called from /vg:security-audit-milestone
apply_decay_policy() {
  local register="${CONFIG_SECURITY_REGISTER_PATH:-${PLANNING_DIR}/SECURITY-REGISTER.md}"
  [ -f "$register" ] || return 0
  local archive_days="${CONFIG_SECURITY_DECAY_POLICY_MITIGATED_ARCHIVE_DAYS:-90}"
  local escalate_days="${CONFIG_SECURITY_DECAY_POLICY_UNRESOLVED_ESCALATE_DAYS:-30}"

  ${PYTHON_BIN:-python3} - "$register" "$archive_days" "$escalate_days" <<'PY'
import sys, re
from datetime import datetime, timedelta, timezone
path, archive_d, escalate_d = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
today = datetime.now(timezone.utc).date()
text = open(path, encoding='utf-8').read()

row_re = re.compile(r'^\| (SEC-\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|', re.M)
changes = []

def maybe_transition(m):
  sec_id, sev, phase, tax, title, status, ev, created, updated = [x.strip() for x in m.groups()]
  try: upd_date = datetime.fromisoformat(updated).date()
  except Exception: return m.group(0)
  age = (today - upd_date).days
  if status == "MITIGATED" and age >= archive_d:
    changes.append(f"- {today.isoformat()} {sec_id} archived (mitigated {age}d ago)")
    return f"| {sec_id} | {sev} | {phase} | {tax} | {title} | ARCHIVED | {ev} | {created} | {today.isoformat()} |"
  if status in ("OPEN", "IN_PROGRESS") and sev in ("high", "critical") and age >= escalate_d:
    new_sev = "critical" if sev == "high" else sev
    changes.append(f"- {today.isoformat()} {sec_id} escalated {sev}→{new_sev} (unresolved {age}d)")
    return f"| {sec_id} | {new_sev} | {phase} | {tax} | {title} | {status} | {ev} | {created} | {today.isoformat()} |"
  return m.group(0)

new_text = row_re.sub(maybe_transition, text)

if changes:
  # Append to Decay Log section
  if "## Decay Log" in new_text:
    new_text = new_text.replace("## Decay Log\n", "## Decay Log\n" + "\n".join(changes) + "\n")
  open(path, 'w', encoding='utf-8').write(new_text)
  print(f"Decay applied: {len(changes)} transitions")
PY
}
```

## Integration points

| Command | Call |
|---------|------|
| `/vg:secure-phase` (existing GSD) | After findings, for each finding: `register_threat "auto" "${sev}" "${phase}" "${tax}" "${title}" "${status}" "${evidence}"` |
| `/vg:accept` step 0 | `check_security_accept_gate "$PHASE"` → exit 1 if blocking |
| `/vg:security-audit-milestone` | `apply_decay_policy` + composite correlation |
| `/vg:progress` | Show open-threat count surface |

## Severity + status state machine

```
OPEN ──────► IN_PROGRESS ──────► MITIGATED ──────► ARCHIVED (after 90d)
  │             │                    │
  │             │                    └─► (stays MITIGATED if re-opened)
  │             │
  └─────────────┴─► ACCEPTED_RISK (explicit risk acceptance with audit doc)

Auto-transitions (decay policy):
  OPEN/IN_PROGRESS + severity≥high + age≥30d → severity bumped one tier (high→critical)
  MITIGATED + age≥90d → ARCHIVED
```

## Success criteria

- Every `/vg:secure-phase` finding written to register (not just SECURITY.md)
- Register is milestone-scoped (resets at milestone archive)
- `/vg:accept` blocks if critical OPEN threats exist
- Cross-phase composite rules correlate threats spanning multiple phases
- Decay policy auto-escalates stale + archives resolved
- Human-editable markdown (no tool lock-in)
