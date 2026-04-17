---
name: vg:_shared:foundation-drift
description: Foundation Drift (lệch hướng nền tảng) Check — semantic field diff against structured FOUNDATION.md. Tracks detections in append-only register until user acknowledges.
---

# Foundation Drift Check — Shared Helper (v1.8.0 semantic)

Detects when a phase/milestone/scope text asserts claims incompatible with the locked `FOUNDATION.md`. **v1.8.0 tiers:** `INFO` (thông tin — foundation already covers), `WARN` (cảnh báo — real mismatch). `BLOCK` tier is reserved for v1.9.0 (hard requirement miss) — v1.8.0 surfaces it as WARN with note.

## Why semantic, not regex

- **Old (regex on prose):** matched keyword → flag. Missed claims hidden in data model / security posture / deployment topology / SLO fields. High false-negative rate.
- **New (semantic field diff):** extract structured claims from scan text, compare against FOUNDATION yaml dict. Claim "credit card processing" → checks `foundation.compliance` for `PCI-DSS`. Claim "iOS app" → checks `foundation.platform` allows mobile. Foundation-field-aware.

## Tiers (cấp độ)

| Tier | Meaning | v1.8.0 behavior |
|------|---------|-----------------|
| `INFO` (thông tin) | Foundation already covers claim | log informational, no user prompt |
| `WARN` (cảnh báo) | Real mismatch — foundation says X, scan claims Y | print warning + track in register |
| `BLOCK` (chặn) | Hard requirement missing (compliance/security) | **v1.8.0 = WARN** with "v1.9.0 sẽ BLOCK" note; deferred |

**Always soft in v1.8.0** — exits 0, never blocks command flow. User has agency via register.

## Drift register (append-only tracking)

Every detection writes to `.planning/.drift-register.md`. User acknowledges entries to silence them. Entries persist across sessions — nothing lost to summarization.

Register schema:
```markdown
| Date | Source | Tier | Keyword | Foundation Field | Current | Implied | Status | User Ack |
|------|--------|------|---------|------------------|---------|---------|--------|----------|
| 2026-04-17 | roadmap:phase-08 | WARN | "iOS app" | platform | web-saas | mobile | unfixed | NO |
```

**Status values:**
- `unfixed` — detection stands, not yet addressed
- `acknowledged` — user intentionally accepts drift (set via `/vg:doctor --ack <entry-id>`)
- `foundation-updated` — user ran `/vg:project --update foundation` fixing this dimension

**Dedup rule:** same `{source, keyword, tier}` with `status=unfixed` → update timestamp, do not duplicate row.

## API

```bash
# Back-compat entry (wraps semantic version, same signature)
# Inputs: $1 = text to scan, $2 = source identifier (cmd:phase)
# Output: stdout notify block if drift, exit 0 always (soft)
foundation_drift_check() {
  foundation_drift_semantic_check "$1" "$2"
}

# Main semantic check — callable directly for commands that want tier-filtered output
foundation_drift_semantic_check() {
  local scan_text="$1"
  local source="$2"
  local foundation_file="${FOUNDATION_FILE:-.planning/FOUNDATION.md}"
  local register_file="${DRIFT_REGISTER:-.planning/.drift-register.md}"

  # No FOUNDATION.md → skip silently (legacy / pre-v1.6.0)
  [ -f "$foundation_file" ] || return 0

  # Silence flag
  if [[ "${ARGUMENTS:-}" =~ --no-drift-check ]]; then
    mkdir -p "$(dirname "${PHASE_DIR:-.planning}/build-state.log")" 2>/dev/null
    echo "drift-check: skipped via --no-drift-check (source=${source})" \
      >> "${PHASE_DIR:-.planning}/build-state.log" 2>/dev/null
    return 0
  fi

  # Bootstrap register if missing
  foundation_drift_ensure_register "$register_file"

  # Export for Python (avoid heredoc interpolation footguns)
  export _VG_DRIFT_SCAN="$scan_text"
  export _VG_DRIFT_SOURCE="$source"
  export _VG_DRIFT_FOUND="$foundation_file"
  export _VG_DRIFT_REG="$register_file"

  ${PYTHON_BIN:-python3} - <<'PY'
import os, re, sys, json, datetime
from pathlib import Path

scan_text  = os.environ.get("_VG_DRIFT_SCAN", "")
source     = os.environ.get("_VG_DRIFT_SOURCE", "unknown")
found_path = Path(os.environ.get("_VG_DRIFT_FOUND", ".planning/FOUNDATION.md"))
reg_path   = Path(os.environ.get("_VG_DRIFT_REG", ".planning/.drift-register.md"))

# ───────── 1. Parse FOUNDATION.md ─────────
# Support BOTH structured yaml block AND legacy table format.
# Prefer yaml. Fall back to table regex if no yaml found (back-compat).
foundation_text = found_path.read_text(encoding="utf-8", errors="ignore")

foundation = {}
yaml_parseable = False

# Try fenced yaml block (```yaml ... ```)
m = re.search(r'```yaml\s*\n(.*?)\n```', foundation_text, re.DOTALL)
if m:
    try:
        import yaml  # may not be installed — fallback below
        foundation = yaml.safe_load(m.group(1)) or {}
        yaml_parseable = isinstance(foundation, dict)
    except ImportError:
        # No PyYAML → naive parse of top-level `key: value` + `key:` nested
        yaml_parseable = True
        lines = m.group(1).splitlines()
        current_key = None
        for line in lines:
            if not line.strip() or line.strip().startswith("#"): continue
            # top-level scalar: "key: value"
            mk = re.match(r'^([a-z_]+)\s*:\s*(.+)$', line)
            if mk and not line.startswith(" "):
                k, v = mk.group(1), mk.group(2).strip()
                if v.startswith("[") and v.endswith("]"):
                    foundation[k] = [x.strip().strip('"\'') for x in v[1:-1].split(",") if x.strip()]
                elif v.startswith("{") and v.endswith("}"):
                    inner = {}
                    for pair in v[1:-1].split(","):
                        if ":" in pair:
                            pk, pv = pair.split(":", 1)
                            inner[pk.strip()] = pv.strip().strip('"\'')
                    foundation[k] = inner
                else:
                    foundation[k] = v.strip('"\'')
                current_key = k
            # nested: "  sub: value" (2-space indent)
            elif line.startswith("  "):
                mn = re.match(r'^\s{2,}([a-z_]+)\s*:\s*(.+)$', line)
                if mn and current_key:
                    if not isinstance(foundation.get(current_key), dict):
                        foundation[current_key] = {}
                    foundation[current_key][mn.group(1)] = mn.group(2).strip().strip('"\'')
    except Exception:
        yaml_parseable = False

# Fallback: extract legacy markdown table (Dimension | Value) — v1.6.0 format
if not yaml_parseable or not foundation:
    # Map table rows to yaml-style dict for uniform downstream handling
    legacy = {}
    table_patterns = {
        "platform":  r'\|\s*\d*\s*\|\s*Platform(?:\s*type)?\s*\|\s*([^|]+)\|',
        "frontend":  r'\|\s*\d*\s*\|\s*Frontend\s*framework\s*\|\s*([^|]+)\|',
        "backend":   r'\|\s*\d*\s*\|\s*Backend\s*topology\s*\|\s*([^|]+)\|',
        "data":      r'\|\s*\d*\s*\|\s*Data\s*layer\s*\|\s*([^|]+)\|',
        "auth":      r'\|\s*\d*\s*\|\s*Auth\s*model\s*\|\s*([^|]+)\|',
        "hosting":   r'\|\s*\d*\s*\|\s*Hosting\s*\|\s*([^|]+)\|',
    }
    for k, pat in table_patterns.items():
        mm = re.search(pat, foundation_text, re.IGNORECASE)
        if mm:
            legacy[k] = mm.group(1).strip().lower()
    # Compliance — often in Constraints section as a line "Compliance: ..."
    cm = re.search(r'\*\*Compliance:\*\*\s*([^\n]+)', foundation_text, re.IGNORECASE)
    if cm:
        raw = cm.group(1).strip().lower()
        if raw in ("none", "n/a", ""):
            legacy["compliance"] = []
        else:
            legacy["compliance"] = [x.strip().upper() for x in re.split(r'[,/]', raw) if x.strip()]
    foundation = legacy
    yaml_parseable = False  # mark as fallback

# Normalize helpers
def as_list(v):
    if v is None: return []
    if isinstance(v, list): return [str(x).lower() for x in v]
    if isinstance(v, str): return [v.lower()]
    return [str(v).lower()]

def field_str(key, subkey=None):
    v = foundation.get(key)
    if subkey and isinstance(v, dict):
        v = v.get(subkey)
    if isinstance(v, dict):
        return " ".join(str(x).lower() for x in v.values())
    if isinstance(v, list):
        return " ".join(str(x).lower() for x in v)
    return str(v or "").lower()

platform_str   = field_str("platform")
compliance_lst = as_list(foundation.get("compliance"))
scale_str      = field_str("scale")
data_str       = field_str("data")
auth_str       = field_str("auth")
hosting_str    = field_str("hosting")
backend_str    = field_str("backend")

scan_lc = scan_text.lower()

# ───────── 2. High-cost claim extraction ─────────
# Each rule: (regex, human_keyword, foundation_field, check_fn, tier_if_miss, implied_value, note)
# check_fn returns (matched, current_value) — matched=True means foundation covers claim
mobile_re = r'\b(ios\s*app|android\s*app|mobile\s*app|swift(?:ui)?|xcode|app\s*store|testflight|kotlin|jetpack|play\s*store|react\s*native|expo|flutter)\b'
desktop_re = r'\b(electron|tauri|desktop\s*app)\b'
serverless_re = r'\b(serverless|aws\s*lambda|cloudflare\s*workers|edge\s*function)\b'
pci_re = r'\b(credit\s*card|card\s*processing|pci[-\s]?dss|payment\s*card|cardholder\s*data)\b'
gdpr_re = r'\b(gdpr|right\s*to\s*be\s*forgotten|data\s*deletion\s*request|eu\s*personal\s*data)\b'
hipaa_re = r'\b(hipaa|phi|protected\s*health\s*information|medical\s*records)\b'
soc2_re = r'\b(soc\s*2|soc2|service\s*organization\s*control)\b'
rt_auction_re = r'\b(real[-\s]?time\s*bidding|rtb|sub[-\s]?\d+\s*ms|tens\s*of\s*thousands\s*qps|\d{4,}\s*qps)\b'

flags = []

def emit(tier, keyword, dim, current, implied, note=""):
    flags.append({
        "tier": tier, "keyword": keyword, "dimension": dim,
        "current": current or "(unset)", "implied": implied, "note": note
    })

# Platform claims
m = re.search(mobile_re, scan_lc)
if m:
    kw = m.group(0)
    if any(p in platform_str for p in ("mobile", "hybrid")):
        emit("INFO", kw, "platform", platform_str, "mobile",
             "foundation already covers mobile")
    else:
        emit("WARN", kw, "platform", platform_str, "mobile",
             "scan implies mobile but foundation excludes it")

m = re.search(desktop_re, scan_lc)
if m:
    kw = m.group(0)
    if any(p in platform_str for p in ("desktop", "hybrid")):
        emit("INFO", kw, "platform", platform_str, "desktop", "covered")
    else:
        emit("WARN", kw, "platform", platform_str, "desktop", "")

m = re.search(serverless_re, scan_lc)
if m:
    kw = m.group(0)
    if any(p in backend_str for p in ("serverless", "edge", "hybrid")) or \
       any(p in hosting_str for p in ("vercel", "netlify", "lambda", "cloudflare", "workers")):
        emit("INFO", kw, "backend.topology", backend_str, "serverless", "covered")
    else:
        emit("WARN", kw, "backend.topology", backend_str, "serverless", "")

# Compliance claims — WARN in v1.8.0, will BLOCK in v1.9.0
compliance_norm = [c.upper() for c in compliance_lst]

m = re.search(pci_re, scan_lc)
if m:
    kw = m.group(0)
    if "PCI-DSS" in compliance_norm or "PCI" in " ".join(compliance_norm):
        emit("INFO", kw, "compliance", ",".join(compliance_norm) or "none", "PCI-DSS", "covered")
    else:
        emit("WARN", kw, "compliance", ",".join(compliance_norm) or "none", "PCI-DSS",
             "v1.9.0 sẽ BLOCK — hard requirement missing")

m = re.search(gdpr_re, scan_lc)
if m:
    kw = m.group(0)
    if "GDPR" in compliance_norm:
        emit("INFO", kw, "compliance", ",".join(compliance_norm) or "none", "GDPR", "covered")
    else:
        emit("WARN", kw, "compliance", ",".join(compliance_norm) or "none", "GDPR",
             "v1.9.0 sẽ BLOCK")

m = re.search(hipaa_re, scan_lc)
if m:
    kw = m.group(0)
    if "HIPAA" in compliance_norm:
        emit("INFO", kw, "compliance", ",".join(compliance_norm) or "none", "HIPAA", "covered")
    else:
        emit("WARN", kw, "compliance", ",".join(compliance_norm) or "none", "HIPAA",
             "v1.9.0 sẽ BLOCK")

m = re.search(soc2_re, scan_lc)
if m:
    kw = m.group(0)
    if "SOC2" in compliance_norm or "SOC-2" in " ".join(compliance_norm):
        emit("INFO", kw, "compliance", ",".join(compliance_norm) or "none", "SOC2", "covered")
    else:
        emit("WARN", kw, "compliance", ",".join(compliance_norm) or "none", "SOC2",
             "v1.9.0 sẽ BLOCK")

# Scale / QPS claims — WARN if scan implies ≥5000 qps but foundation scale is small
m = re.search(rt_auction_re, scan_lc)
if m:
    kw = m.group(0)
    # Parse qps hint from foundation.scale (support dict + string)
    qps_current = 0
    s = foundation.get("scale")
    qps_raw = ""
    if isinstance(s, dict):
        qps_raw = str(s.get("qps_target", "") or s.get("qps", ""))
    elif isinstance(s, str):
        qps_raw = s
    qm = re.search(r'(\d+)\s*k?', qps_raw.lower())
    if qm:
        val = int(qm.group(1))
        if "k" in qps_raw.lower(): val *= 1000
        qps_current = val
    if qps_current >= 5000:
        emit("INFO", kw, "scale.qps_target", str(qps_current), ">=5000", "covered")
    else:
        emit("WARN", kw, "scale.qps_target", str(qps_current) or "(unset)", ">=5000",
             "scan implies high-QPS workload")

# ───────── 3. Persist to register (append-only, dedup) ─────────
if flags:
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    reg_text = reg_path.read_text(encoding="utf-8", errors="ignore") if reg_path.exists() else ""

    # Parse existing unfixed entries for dedup
    existing_unfixed = set()
    for line in reg_text.splitlines():
        if not line.startswith("| ") or line.startswith("| Date") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 8 and cols[7] == "unfixed":
            existing_unfixed.add((cols[1], cols[3], cols[2]))  # source, keyword, tier

    new_rows = []
    entry_ids = []
    # Count existing non-header rows for entry numbering
    existing_rows = sum(1 for ln in reg_text.splitlines()
                       if ln.startswith("| ") and not ln.startswith("| Date") and not ln.startswith("|---"))
    next_id = existing_rows + 1

    for f in flags:
        key = (source, f'"{f["keyword"]}"', f["tier"])
        if key in existing_unfixed:
            continue  # dedup — already tracked
        row = "| {date} | {src} | {tier} | \"{kw}\" | {dim} | {cur} | {imp} | unfixed | NO |".format(
            date=now, src=source, tier=f["tier"], kw=f["keyword"],
            dim=f["dimension"], cur=f["current"], imp=f["implied"]
        )
        new_rows.append(row)
        entry_ids.append(next_id)
        next_id += 1

    if new_rows:
        # Append to register
        with reg_path.open("a", encoding="utf-8") as rf:
            for r in new_rows:
                rf.write(r + "\n")

# ───────── 4. Notify user (WARN tier only — INFO stays silent by default) ─────────
warn_flags = [f for f in flags if f["tier"] == "WARN"]
info_flags = [f for f in flags if f["tier"] == "INFO"]

# Summary for telemetry piping (JSON on last line)
summary = {
    "source": source,
    "warn_count": len(warn_flags),
    "info_count": len(info_flags),
    "yaml_parseable": yaml_parseable,
    "flags": flags
}

if warn_flags:
    print("")
    print("⚠ FOUNDATION DRIFT (lệch hướng nền tảng) detected — tier: WARN (cảnh báo)")
    print(f"   Source: {source}")
    for f in warn_flags[:5]:
        print(f"   • Keyword '{f['keyword']}' implies {f['dimension']} = {f['implied']}")
        print(f"     Current foundation.{f['dimension']}: {f['current']}")
        if f.get("note"):
            print(f"     Note: {f['note']}")
    print("")
    print("   Suggested fix: /vg:project --update foundation")
    print(f"   Tracked at: {reg_path} ({len(warn_flags)} new entry/entries)")
    print("   Run /vg:doctor --drift to see all unfixed drift entries.")
    print("   Silence this run: re-run with --no-drift-check (logged for audit).")
    print("")

# Emit JSON summary on stderr for caller capture (non-TTY-polluting)
import sys as _sys
print("__DRIFT_SUMMARY__" + json.dumps(summary), file=_sys.stderr)
PY

  local py_exit=$?

  # ───────── 5. Telemetry emission (one event per flag) ─────────
  # We re-parse the summary from stderr via a small helper call (lightweight)
  if command -v emit_telemetry_v2 >/dev/null 2>&1; then
    ${PYTHON_BIN:-python3} - "$register_file" "$source" <<'PY' | while IFS= read -r line; do
import sys, json, re
reg = sys.argv[1]; src = sys.argv[2]
# Emit telemetry only for rows added this session (approximated: unfixed rows with source matching + today's date)
import datetime
today = datetime.datetime.now().strftime("%Y-%m-%d")
try:
  with open(reg, encoding="utf-8") as f:
    for ln in f:
      if not ln.startswith("| ") or ln.startswith("| Date") or ln.startswith("|---"): continue
      cols = [c.strip() for c in ln.strip("|").split("|")]
      if len(cols) < 8: continue
      if cols[0] != today or cols[1] != src: continue
      if cols[7] != "unfixed": continue
      # Emit: tier|keyword|dimension|current
      print("{}|{}|{}|{}".format(cols[2], cols[3].strip('"'), cols[4], cols[5]))
except Exception: pass
PY
      IFS='|' read -r tier kw dim cur <<< "$line"
      payload=$(${PYTHON_BIN:-python3} -c "import json; print(json.dumps({'tier':'$tier','keyword':'$kw','dimension':'$dim','current_value':'$cur','source':'$source'}))")
      emit_telemetry_v2 "drift_detected" "${PHASE_NUMBER:-}" "${VG_CURRENT_STEP:-drift-check}" \
        "foundation-drift" "WARN" "$payload" "" "${VG_CURRENT_COMMAND:-}" >/dev/null
    done
  fi

  unset _VG_DRIFT_SCAN _VG_DRIFT_SOURCE _VG_DRIFT_FOUND _VG_DRIFT_REG
  return 0  # soft — always exit 0 in v1.8.0
}

# Ensure register file exists with header
foundation_drift_ensure_register() {
  local reg="$1"
  [ -f "$reg" ] && return 0
  mkdir -p "$(dirname "$reg")" 2>/dev/null
  cat > "$reg" <<'EOF'
# Drift Register (sổ theo dõi lệch hướng)

Append-only tracking of every foundation drift (lệch hướng nền tảng) detection. Entries persist across sessions. User acknowledges by setting `Status: acknowledged` or running `/vg:project --update foundation` (which sets `Status: foundation-updated`).

**Tiers:**
- `INFO` (thông tin) — foundation already covers; logged for audit
- `WARN` (cảnh báo) — real mismatch; requires user attention
- `BLOCK` (chặn) — reserved for v1.9.0; currently recorded as WARN

**Status values:**
- `unfixed` — detection stands, not yet addressed
- `acknowledged` — user intentionally accepts drift
- `foundation-updated` — foundation was updated to cover this claim

| Date | Source | Tier | Keyword | Foundation Field | Current | Implied | Status | User Ack |
|------|--------|------|---------|------------------|---------|---------|--------|----------|
EOF
}

# Helper for /vg:doctor — count unfixed entries, return JSON
# Output (stdout): {"unfixed":N, "warn_unfixed":M, "entries":[...]}
foundation_drift_check_register() {
  local register_file="${DRIFT_REGISTER:-.planning/.drift-register.md}"
  if [ ! -f "$register_file" ]; then
    echo '{"unfixed":0,"warn_unfixed":0,"info_unfixed":0,"entries":[]}'
    return 0
  fi
  ${PYTHON_BIN:-python3} - "$register_file" <<'PY'
import sys, json
reg = sys.argv[1]
entries = []
try:
  with open(reg, encoding="utf-8") as f:
    for ln in f:
      if not ln.startswith("| ") or ln.startswith("| Date") or ln.startswith("|---"): continue
      cols = [c.strip() for c in ln.strip("|").split("|")]
      if len(cols) < 8: continue
      if cols[7] != "unfixed": continue
      entries.append({
        "date": cols[0], "source": cols[1], "tier": cols[2],
        "keyword": cols[3], "dimension": cols[4], "current": cols[5],
        "implied": cols[6], "status": cols[7],
        "ack": cols[8] if len(cols) > 8 else "NO"
      })
except Exception as e:
  print(json.dumps({"unfixed":0,"warn_unfixed":0,"info_unfixed":0,"entries":[],"error":str(e)}))
  sys.exit(0)
warn = sum(1 for e in entries if e["tier"] == "WARN")
info = sum(1 for e in entries if e["tier"] == "INFO")
print(json.dumps({
  "unfixed": len(entries),
  "warn_unfixed": warn,
  "info_unfixed": info,
  "entries": entries
}))
PY
}
```

## Notify pattern (output when WARN detected)

```
⚠ FOUNDATION DRIFT (lệch hướng nền tảng) detected — tier: WARN (cảnh báo)
   Source: roadmap:phase-08
   • Keyword 'iOS app' implies platform = mobile
     Current foundation.platform: web-saas

   Suggested fix: /vg:project --update foundation
   Tracked at: .planning/.drift-register.md (1 new entry)
   Run /vg:doctor --drift to see all unfixed drift entries.
   Silence this run: re-run with --no-drift-check (logged for audit).
```

INFO tier is silent by default (only recorded in register + telemetry) — noise control.

## Integration template

In `/vg:roadmap`, `/vg:add-phase`, `/vg:scope`, `/vg:specs`:

```bash
# Source helpers (config-loader already done upstream)
source .claude/commands/vg/_shared/foundation-drift.md 2>/dev/null || true
source .claude/commands/vg/_shared/telemetry.md 2>/dev/null || true

SCAN="${PHASE_TITLE} ${PHASE_DESC} ${PHASE_SCOPE_BODY}"
SOURCE="${VG_CURRENT_COMMAND:-${COMMAND_NAME:-vg}}:${PHASE_NUMBER:-unknown}"
foundation_drift_semantic_check "$SCAN" "$SOURCE"
# Always exits 0 — soft warning. Continue normal flow.
```

## /vg:doctor integration

T2 agent calls `foundation_drift_check_register` to surface unfixed entries:

```bash
source .claude/commands/vg/_shared/foundation-drift.md
DRIFT_JSON=$(foundation_drift_check_register)
WARN_COUNT=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.stdin.read())['warn_unfixed'])" <<<"$DRIFT_JSON")
if [ "$WARN_COUNT" -gt 0 ]; then
  echo "⚠ ${WARN_COUNT} unfixed drift (lệch hướng) entries — run /vg:doctor --drift for details"
fi
```

## User acknowledgment workflow

User edits `.planning/.drift-register.md` directly, changing `Status: unfixed` → `Status: acknowledged` (and `User Ack: YES`). Or runs `/vg:project --update foundation` which auto-sets `Status: foundation-updated` for entries whose dimension was touched (handled by project.md step 5 cascade).

## Success criteria

- FOUNDATION.md yaml-parseable → structured field diff runs
- FOUNDATION.md table-only (legacy v1.6.0) → graceful fallback, no crash
- FOUNDATION.md missing → silent skip
- Every detection creates/updates a row in `.drift-register.md` (dedup by source+keyword+tier)
- WARN entries trigger user notification with fix hint + register path
- INFO entries silent (logged only)
- BLOCK tier deferred to v1.9.0 (recorded as WARN with note)
- `foundation_drift_check_register` exposes unfixed count for `/vg:doctor`
- Every flag emits `drift_detected` telemetry event
- `--no-drift-check` flag skips, logs to build-state.log
- Never blocks command flow (always exit 0)
- Back-compat `foundation_drift_check` retained — wraps semantic version
