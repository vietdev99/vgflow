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

```bash
WARN_COUNT=0
BLOCK_COUNT=0

# (... run the 4 checks above, increment counters ...)

vg-orchestrator emit-event scope.completeness_validation \
  --payload "{\"warnings\":${WARN_COUNT},\"blocks\":${BLOCK_COUNT}}" >/dev/null 2>&1 || true

if [ "$BLOCK_COUNT" -gt 0 ]; then
  echo "⛔ ${BLOCK_COUNT} blocking gap(s) found — fix before /vg:blueprint" >&2
  exit 1
fi

echo "✓ Completeness validation: ${WARN_COUNT} warning(s)"
```

## Mark step

```bash
vg-orchestrator mark-step scope 3_completeness_validation
```

## Advance

Read `_shared/scope/crossai.md` next.
