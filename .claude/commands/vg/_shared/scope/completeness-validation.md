# scope completeness-validation (STEP 5)

> Marker: `3_completeness_validation`.
> 4 automated checks on the generated CONTEXT.md. Surfaces warnings + hard-blocks on critical gaps.

<HARD-GATE>
You MUST run all 5 checks (A endpoint coverage, B design ref, C decision
completeness, D orphan detection, **E upstream prereq verification**).
`step-active` fires before checks, `mark-step` after. BLOCK on any Check
A/C/E gap.

**v2.66.0 BREAKING (strict default ON):** Check B + D WARNs now trigger
exit 1 by default. Pass `--lenient-prereqs` (preflight parse loop exports
`LENIENT_PREREQS=true`) to restore v2.65.x lenient behavior where only
BLOCK_COUNT > 0 fails.

**Check E is strict-only (no lenient exemption):** missing upstream
symbols always BLOCK regardless of `--lenient-prereqs`. See Check E
section below for rationale (PrintwayV3 31×404 cascade root cause).
</HARD-GATE>

## Step active (gate enforcement)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 3_completeness_validation
```

## Check A — Endpoint Coverage (⛔ BLOCK)

For every decision D-XX with **Endpoints:** section, verify ≥ 1 test scenario references that endpoint.

Downstream blueprint 2b5 parses these scenarios → TEST-GOALS. Missing coverage = orphan goals failing phase-end binding gate.

Gap → ⛔ BLOCK:

```
⛔ D-{XX} has endpoints but no test scenario covering them.
   Add a TS-NN under D-{XX} that references the endpoint, or remove the endpoint from D-{XX}.
```

## Check B — Design Ref Coverage (⛔ BLOCK by default in v2.66.0; lenient via flag)

If `config.design_assets` configured, for every decision with **UI Components:**, check design-ref exists in `${PHASE_DIR}/` or `config.design_assets.output_dir`.

Phase 15 D-02 escalation (v2.66.0 BREAKING — strict default ON):
- Resolve fidelity via `scripts/lib/threshold-resolver.py --phase ${PHASE_NUMBER}`
- `production` (≥ 0.95) → missing design-ref = ⛔ BLOCK
- **v2.66.0 BREAKING:** default → BLOCK. Use `--lenient-prereqs` flag for v2.65.x WARN behavior.
- `prototype` (~0.70) → SKIP

Strict (default) BLOCK message:
```
⛔ D-{XX} has UI components but no design reference found. Run /vg:design-extract OR pass --lenient-prereqs to downgrade to WARN (v2.65.x legacy behavior).
```

Lenient (--lenient-prereqs) WARN message:
```
⚠ D-{XX} has UI components but no design reference found. Consider running /vg:design-extract.
```

Production BLOCK message:
```
⛔ D-{XX} has UI components but no design reference. Phase fidelity profile=production requires design-ref per D-02.
   Run /vg:design-extract or relax profile via --fidelity-profile default (logs override-debt as kind=fidelity-profile-relaxed).
```

## Check C — Decision Completeness (⛔ BLOCK if gap ratio > 10%)

Compare SPECS.md in-scope items against CONTEXT.md decisions. Every in-scope item should map to ≥ 1 decision.

Calculation:
```bash
SPECS_ITEMS=$(grep -cE '^- ' "${PHASE_DIR}/SPECS.md" || echo 0)  # rough count of in-scope items
DECISIONS=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")
# Map heuristic: AI cross-references decision text to specs items
GAP_COUNT=<count of specs items with no decision mapping>
GAP_RATIO=$(echo "$GAP_COUNT $SPECS_ITEMS" | awk '{ printf "%.2f\n", $1/$2 }')
```

If `GAP_RATIO > 0.10` → ⛔ BLOCK:
```
⛔ SPECS in-scope item '{item}' has no corresponding decision in CONTEXT.md.
   Coverage gap {GAP_COUNT}/{SPECS_ITEMS} = {GAP_RATIO}. Threshold 10%.
   Either: lock missing decisions in re-scope, or move the item to SPECS Out-of-scope.
```

Downstream blueprint generates orphan tasks → citation gate fails.

## Check D — Orphan Detection (WARN)

Decisions that don't trace back to any SPECS.md in-scope item (potential scope creep).

Found → WARN:
```
⚠ D-{XX} doesn't map to any SPECS in-scope item. Intentional addition or scope creep?
```

## Check E — Upstream Prereq Verification (⛔ BLOCK; v2.66.0 #156, no `--lenient-prereqs` exemption)

When CONTEXT.md declares a `## Prerequisites` section (or table) referencing
fields/endpoints owned by upstream phases (cross-phase prereqs), Check E
verifies each entry exists in the owner phase's SPECS.md or PLAN.md before
allowing scope to complete.

**Why strict (no `--lenient-prereqs` exemption for Check E):** Lenient mode
is intended to downgrade fidelity-style WARNs (design refs, orphan decisions).
Cross-phase prereqs declaring missing upstream symbols ARE the cascade root
cause behind the v2.66.0 PrintwayV3 31×404 incident — there is no legitimate
reason to lenient-skip a missing upstream patch. Check E always BLOCKs on a
missing owner symbol.

**Logic** (executed inside the python pass below; canonical bash sketch for
reviewer reference):

```bash
# Reviewer reference only — actual logic lives in the python block below.
# Parses any ## Prerequisites table with columns: phase | artifact | symbol
# For each row: greps owner phase SPECS.md/PLAN.md for the symbol token.
# If owner files exist but the symbol is missing → BLOCK.
PREREQS_TABLE=$(awk '/^## Prerequisites/,/^## /' "${PHASE_DIR}/CONTEXT.md" 2>/dev/null)
while IFS='|' read -r _ owner_phase artifact symbol _; do
    owner_phase=$(echo "$owner_phase" | xargs)
    symbol=$(echo "$symbol" | xargs)
    [ -z "$owner_phase" ] && continue
    [ -z "$symbol" ] && continue
    owner_specs=".vg/phases/${owner_phase}/SPECS.md"
    owner_plan=".vg/phases/${owner_phase}/PLAN.md"
    found=false
    [ -f "$owner_specs" ] && grep -q "$symbol" "$owner_specs" && found=true
    [ -f "$owner_plan" ] && grep -q "$symbol" "$owner_plan" && found=true
    [ "$found" = "false" ] && {
        # → BLOCK with /vg:amend remedy
        :
    }
done <<< "$PREREQS_TABLE"
```

**Failure remedy text** (operator must do exactly one of these before continuing):

```
⛔ Prereq '{symbol}' not found in owner phase {owner_phase}.
   Choose one remedy:
   1. Run `/vg:amend {owner_phase}` to add the missing field/endpoint to its SPECS/PLAN.
   2. Insert a patch phase (e.g. {owner_phase}.5) before this scope completes.
   3. Remove the prereq from CONTEXT.md if the symbol is actually local.
   Cannot be exempted via --lenient-prereqs (upstream prereqs are strict-only).
```

## Surface warnings + emit events

> Critical-5 r2 fix: previous block was pseudocode (`# (... run the 4 checks
> above ...)` with counters always 0 → mark-step always succeeded silently).
> The block below implements the 4 checks inline using portable shell + a
> single python pass over CONTEXT.md + SPECS.md.

```bash
WARN_COUNT=0
BLOCK_COUNT=0
VALIDATION_LOG=""

# Resolve fidelity (used by Check B production-block branch)
FIDELITY="default"
if [ -x "scripts/lib/threshold-resolver.py" ] || [ -f "scripts/lib/threshold-resolver.py" ]; then
  FIDELITY=$(${PYTHON_BIN:-python3} scripts/lib/threshold-resolver.py \
    --phase "${PHASE_NUMBER}" 2>/dev/null | grep -oE 'production|default|prototype' | head -1 || echo "default")
fi

# Run all 4 checks in a single python pass — emits JSON summary to stdout
VALIDATION_JSON=$(${PYTHON_BIN:-python3} - "${PHASE_DIR}" "${PHASE_NUMBER}" "${FIDELITY}" <<'PY'
import json, os, re, sys
from pathlib import Path

phase_dir, phase_num, fidelity = sys.argv[1], sys.argv[2], sys.argv[3]
phase_dir = Path(phase_dir)
context_path = phase_dir / "CONTEXT.md"
specs_path = phase_dir / "SPECS.md"

warnings, blocks = [], []
if not context_path.exists():
    blocks.append({"check": "preflight", "msg": f"CONTEXT.md missing at {context_path}"})
    print(json.dumps({"warnings": warnings, "blocks": blocks}))
    sys.exit(0)

context = context_path.read_text(encoding="utf-8")
specs = specs_path.read_text(encoding="utf-8") if specs_path.exists() else ""

# Split into per-decision blocks (### P{N}.D-XX or ### D-XX heading)
decision_re = re.compile(r"^###\s+(P[0-9.]+\.)?D-([A-Za-z0-9_-]+)\s*:?\s*(.*)$", re.MULTILINE)
matches = list(decision_re.finditer(context))
decisions = []
for i, m in enumerate(matches):
    start = m.end()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(context)
    body = context[start:end]
    decisions.append({
        "id": (m.group(1) or "") + "D-" + m.group(2),
        "title": m.group(3).strip(),
        "body": body,
    })

# Check A — Endpoint Coverage (BLOCK): every D-XX with **Endpoints:** has >=1 TS reference
endpoint_section_re = re.compile(r"\*\*Endpoints?:\*\*", re.IGNORECASE)
ts_ref_re = re.compile(r"TS-[A-Za-z0-9_-]+", re.IGNORECASE)
endpoint_line_re = re.compile(r"-\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)", re.IGNORECASE)
for d in decisions:
    if endpoint_section_re.search(d["body"]):
        endpoints = endpoint_line_re.findall(d["body"])
        ts_refs = ts_ref_re.findall(d["body"])
        if endpoints and not ts_refs:
            blocks.append({
                "check": "A_endpoint_coverage",
                "decision": d["id"],
                "msg": f"{d['id']} has endpoints but no test scenario (TS-NN) covering them",
            })

# Check B — Design Ref Coverage (WARN default; BLOCK if production fidelity)
ui_section_re = re.compile(r"\*\*UI Components?:\*\*", re.IGNORECASE)
design_assets_dir = os.environ.get("DESIGN_ASSETS_DIR", "")
def has_design_ref(decision_body, phase_dir, design_assets_dir):
    refs = re.findall(r"design[-_][\w.-]+\.(?:png|svg|jpg|jpeg|webp)", decision_body, re.IGNORECASE)
    if refs:
        return True
    # Glob check
    for p in phase_dir.glob("design-*"):
        if p.is_file():
            return True
    if design_assets_dir:
        adir = Path(design_assets_dir)
        if adir.exists() and any(adir.iterdir()):
            return True
    return False
for d in decisions:
    if ui_section_re.search(d["body"]) and not has_design_ref(d["body"], phase_dir, design_assets_dir):
        entry = {"check": "B_design_ref", "decision": d["id"]}
        if fidelity == "production":
            entry["msg"] = f"{d['id']} has UI components but no design reference. Phase fidelity=production requires design-ref per D-02."
            blocks.append(entry)
        elif fidelity == "prototype":
            pass  # SKIP per spec
        else:
            entry["msg"] = f"{d['id']} has UI components but no design reference. Consider /vg:design-extract."
            warnings.append(entry)

# Check C — Decision Completeness (BLOCK if gap_ratio > 0.10)
specs_items = re.findall(r"^[-*]\s+\S+", specs, re.MULTILINE) if specs else []
specs_count = len(specs_items)
decision_count = len(decisions)
if specs_count > 0:
    # Heuristic: count specs items whose first ~6 keyword tokens appear in any decision body+title
    decisions_blob = "\n".join((d["title"] + " " + d["body"]).lower() for d in decisions)
    unmapped = []
    for item in specs_items:
        tokens = re.findall(r"[a-zA-Z0-9_]{4,}", item.lower())[:6]
        if not tokens:
            continue
        # require at least 1 token to appear in decisions_blob to call it "mapped"
        if not any(tok in decisions_blob for tok in tokens):
            unmapped.append(item.strip())
    gap_count = len(unmapped)
    gap_ratio = gap_count / specs_count
    if gap_ratio > 0.10:
        for item in unmapped[:5]:  # cap surfaced examples
            blocks.append({
                "check": "C_decision_completeness",
                "msg": f"SPECS in-scope item '{item}' has no corresponding decision in CONTEXT.md (gap_ratio={gap_ratio:.2f} > 0.10)",
            })

# Check D — Orphan Detection (WARN): decisions not traceable to specs items
if specs:
    specs_blob = specs.lower()
    for d in decisions:
        title_tokens = re.findall(r"[a-zA-Z0-9_]{4,}", d["title"].lower())[:4]
        if title_tokens and not any(tok in specs_blob for tok in title_tokens):
            warnings.append({
                "check": "D_orphan_decision",
                "decision": d["id"],
                "msg": f"{d['id']} doesn't map to any SPECS in-scope item — intentional or scope creep?",
            })

# Check E — Upstream Prereq Verification (v2.66.0 #156, BLOCK; strict-only,
# no --lenient-prereqs exemption). Parse the "## Prerequisites" section in
# CONTEXT.md (markdown table with columns: phase | artifact | symbol | ...)
# For each (owner_phase, symbol) row, grep owner phase SPECS.md/PLAN.md for
# the symbol token. Missing → BLOCK with /vg:amend remedy.
prereq_section_re = re.compile(
    r"^##\s+Prerequisites\s*$(.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
prereq_match = prereq_section_re.search(context)
if prereq_match:
    prereq_block = prereq_match.group(1)
    # Extract markdown table rows: lines starting with `|` and containing 3+ pipes
    repo_root = Path(".")
    phases_root = repo_root / ".vg" / "phases"
    for line in prereq_block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        # Skip header + separator rows
        joined = " ".join(cells).lower()
        if "phase" in joined and "artifact" in joined:
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        owner_phase, _artifact, symbol = cells[0], cells[1], cells[2]
        if not owner_phase or not symbol:
            continue
        # Resolve owner phase dir (slugged or bare)
        owner_dir = None
        if phases_root.exists():
            for p in phases_root.iterdir():
                if p.is_dir() and (p.name == owner_phase or p.name.startswith(f"{owner_phase}-")):
                    owner_dir = p
                    break
        owner_specs = (owner_dir / "SPECS.md") if owner_dir else None
        owner_plan = (owner_dir / "PLAN.md") if owner_dir else None
        found = False
        symbol_token = re.escape(symbol)
        for fp in (owner_specs, owner_plan):
            if fp and fp.exists():
                try:
                    if re.search(symbol_token, fp.read_text(encoding="utf-8")):
                        found = True
                        break
                except Exception:
                    pass
        if not found:
            blocks.append({
                "check": "E_upstream_prereq",
                "owner_phase": owner_phase,
                "symbol": symbol,
                "msg": (
                    f"Prereq '{symbol}' not found in owner phase {owner_phase} "
                    f"(SPECS.md/PLAN.md). Run `/vg:amend {owner_phase}` to add it, "
                    f"insert a patch phase before this scope completes, or remove "
                    f"the prereq if it is actually local. Cannot --lenient-prereqs "
                    f"exempt (upstream prereqs are strict-only)."
                ),
            })

print(json.dumps({"warnings": warnings, "blocks": blocks}))
PY
)

WARN_COUNT=$(echo "$VALIDATION_JSON" | ${PYTHON_BIN:-python3} -c 'import json,sys; print(len(json.load(sys.stdin).get("warnings",[])))')
BLOCK_COUNT=$(echo "$VALIDATION_JSON" | ${PYTHON_BIN:-python3} -c 'import json,sys; print(len(json.load(sys.stdin).get("blocks",[])))')

# Surface human-readable lines
echo "$VALIDATION_JSON" | ${PYTHON_BIN:-python3} -c '
import json, sys
data = json.load(sys.stdin)
for b in data.get("blocks", []):
    print(f"⛔ [{b.get(\"check\")}] {b.get(\"msg\")}", file=sys.stderr)
for w in data.get("warnings", []):
    print(f"⚠ [{w.get(\"check\")}] {w.get(\"msg\")}", file=sys.stderr)
'

vg-orchestrator emit-event scope.completeness_validation \
  --payload "{\"warnings\":${WARN_COUNT},\"blocks\":${BLOCK_COUNT},\"fidelity\":\"${FIDELITY}\",\"lenient_prereqs\":\"${LENIENT_PREREQS:-false}\"}" \
  >/dev/null 2>&1 || true

# v2.66.0 BREAKING: strict default — both BLOCK and WARN trigger exit 1.
# Legacy lenient mode (v2.65.x behavior) opt-in via --lenient-prereqs flag
# (LENIENT_PREREQS=true exported by scope.md preflight parse loop).
if [ "${LENIENT_PREREQS:-false}" = "true" ]; then
  # Lenient mode (legacy v2.65.x behavior, opt-out via --lenient-prereqs flag)
  if [ "$BLOCK_COUNT" -gt 0 ]; then
    echo "⛔ ${BLOCK_COUNT} blocking gap(s) found — fix before /vg:blueprint (lenient mode: ${WARN_COUNT} warnings allowed)" >&2
    exit 1
  fi
else
  # Strict mode (v2.66.0 default — both BLOCK and WARN trigger exit 1)
  if [ "$BLOCK_COUNT" -gt 0 ] || [ "$WARN_COUNT" -gt 0 ]; then
    echo "⛔ ${BLOCK_COUNT} BLOCK + ${WARN_COUNT} WARN violations (strict mode v2.66.0; pass --lenient-prereqs to downgrade WARNs)" >&2
    exit 1
  fi
fi

echo "✓ Completeness validation: ${WARN_COUNT} warning(s), ${BLOCK_COUNT} block(s), fidelity=${FIDELITY}, mode=${LENIENT_PREREQS:+lenient}${LENIENT_PREREQS:-strict}"
```

## Mark step

```bash
vg-orchestrator mark-step scope 3_completeness_validation
```

## Advance

Read `_shared/scope/crossai.md` next.
