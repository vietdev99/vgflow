# scope completeness-validation (STEP 5)

> Marker: `3_completeness_validation`.
> 4 automated checks on the generated CONTEXT.md. Surfaces warnings + hard-blocks on critical gaps.

<HARD-GATE>
You MUST run all 4 checks (A endpoint coverage, B design ref, C decision
completeness, D orphan detection). `step-active` fires before checks,
`mark-step` after. BLOCK on any Check A/C gap; WARN on B (default fidelity)
and D.
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

## Check B — Design Ref Coverage (WARN default; ⛔ BLOCK in production fidelity per D-02)

If `config.design_assets` configured, for every decision with **UI Components:**, check design-ref exists in `${PHASE_DIR}/` or `config.design_assets.output_dir`.

Phase 15 D-02 escalation:
- Resolve fidelity via `scripts/lib/threshold-resolver.py --phase ${PHASE_NUMBER}`
- `production` (≥ 0.95) → missing design-ref = ⛔ BLOCK
- `default` (~0.85) → WARN
- `prototype` (~0.70) → SKIP

Default WARN message:
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
  --payload "{\"warnings\":${WARN_COUNT},\"blocks\":${BLOCK_COUNT},\"fidelity\":\"${FIDELITY}\"}" \
  >/dev/null 2>&1 || true

if [ "$BLOCK_COUNT" -gt 0 ]; then
  echo "⛔ ${BLOCK_COUNT} blocking gap(s) found — fix before /vg:blueprint" >&2
  exit 1
fi

echo "✓ Completeness validation: ${WARN_COUNT} warning(s), ${BLOCK_COUNT} block(s), fidelity=${FIDELITY}"
```

## Mark step

```bash
vg-orchestrator mark-step scope 3_completeness_validation
```

## Advance

Read `_shared/scope/crossai.md` next.
