# blueprint edge-cases (STEP 4 sub-step — `2b5e_edge_cases`)

Generates `EDGE-CASES.md` (Layer 3) + `EDGE-CASES/index.md` (Layer 2) +
`EDGE-CASES/G-NN.md` (Layer 1) for each goal in `TEST-GOALS.md`.

Runs **after `2b5_test_goals`** (need TEST-GOALS first) and **before
`2b5d_expand_from_crud_surfaces`** (CRUD surfaces use edge-case scenarios
to enrich its overlay coverage).

<HARD-GATE>
You MUST run this step UNLESS:
- Phase has `resources: []` in CRUD-SURFACES.md (no CRUD/resource behavior
  → edge-cases not applicable; emit `blueprint.edge_cases_skipped` instead)
- User passed `--skip-edge-cases` flag (paired with `--override-reason=<text>`,
  logs override-debt entry)

Otherwise: missing EDGE-CASES.md = build/review/test consume incomplete
contract. Downstream code generation skips data-variant coverage entirely.
</HARD-GATE>

---

## STEP 4.5 (2b5e_edge_cases) — orchestration

```bash
vg-orchestrator step-active 2b5e_edge_cases

# Skip-conditions check
SKIP_REASON=""
if [[ "$ARGUMENTS" =~ --skip-edge-cases ]]; then
  if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
    echo "⛔ --skip-edge-cases requires --override-reason=<text>"
    exit 1
  fi
  SKIP_REASON="--skip-edge-cases flag (override-debt logged)"
elif [ -f "${PHASE_DIR}/CRUD-SURFACES.md" ]; then
  # Check if no_crud_reason is set
  if "${PYTHON_BIN:-python3}" -c "
import json, re, sys
src = open('${PHASE_DIR}/CRUD-SURFACES.md').read()
m = re.search(r'\`\`\`json\n(.*?)\n\`\`\`', src, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    if data.get('no_crud_reason') or not data.get('resources'):
        sys.exit(0)
sys.exit(1)
"; then
    SKIP_REASON="phase has no CRUD resources (CRUD-SURFACES.md says no_crud_reason)"
  fi
fi

if [ -n "$SKIP_REASON" ]; then
  vg-orchestrator emit-event "blueprint.edge_cases_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"${SKIP_REASON}\"}"
  echo "▸ Edge cases skipped: $SKIP_REASON"
else
  # Determine profile + load matching template
  PROFILE=$(vg_config_get profile web-fullstack)
  TEMPLATE_PATH=".claude/commands/vg/_shared/templates/edge-cases-${PROFILE}.md"

  # mobile-* profiles share one template
  if [[ "$PROFILE" == mobile-* ]]; then
    TEMPLATE_PATH=".claude/commands/vg/_shared/templates/edge-cases-mobile.md"
  fi

  if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "⚠ No edge-cases template for profile=${PROFILE} — using web-fullstack"
    TEMPLATE_PATH=".claude/commands/vg/_shared/templates/edge-cases-web-fullstack.md"
  fi

  echo "▸ Generating EDGE-CASES with template: $TEMPLATE_PATH"

  # The vg-blueprint-contracts subagent has already generated TEST-GOALS.
  # Re-spawn it (or extend its return) for EDGE-CASES generation. See
  # `contracts-delegation.md` Part 4 for the prompt template.
  bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts spawning \
    "edge cases for ${PHASE_NUMBER} (${PROFILE})"

  # Agent(subagent_type="vg-blueprint-contracts", prompt=<from contracts-delegation.md Part 4>):
  #   reads: TEST-GOALS/G-*.md, $TEMPLATE_PATH, CONTEXT.md
  #   writes: EDGE-CASES/G-NN.md (Layer 1) + EDGE-CASES/index.md (Layer 2)
  #          + EDGE-CASES.md (Layer 3 flat concat)
  #   returns: {edge_cases_path, edge_cases_index_path, edge_cases_sub_files,
  #            variant_count_per_goal: {G-04: 5, ...}, total_variants: N}

  bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts returned \
    "${TOTAL_VARIANTS} variants across ${GOAL_COUNT} goals"

  # Validate output
  [ -f "${PHASE_DIR}/EDGE-CASES.md" ] || {
    echo "⛔ EDGE-CASES.md missing after subagent return"
    exit 1
  }
  [ -f "${PHASE_DIR}/EDGE-CASES/index.md" ] || {
    echo "⛔ EDGE-CASES/index.md missing"
    exit 1
  }
  EDGE_GOALS=$(ls "${PHASE_DIR}/EDGE-CASES/G-"*.md 2>/dev/null | wc -l)
  if [ "$EDGE_GOALS" -lt 1 ]; then
    echo "⛔ EDGE-CASES/G-*.md per-goal split missing (${EDGE_GOALS} files)"
    exit 1
  fi

  # Emit telemetry
  TOTAL_VARIANTS=$(grep -h "variant_id" "${PHASE_DIR}/EDGE-CASES/G-"*.md | wc -l)
  vg-orchestrator emit-event "blueprint.edge_cases_generated" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"total_variants\":${TOTAL_VARIANTS},\"goal_count\":${EDGE_GOALS},\"profile\":\"${PROFILE}\"}"

  echo "▸ Edge cases generated: ${EDGE_GOALS} goals × variants = ${TOTAL_VARIANTS} total"
fi

vg-orchestrator mark-step blueprint 2b5e_edge_cases
```

---

## Output schema (subagent writes)

### Layer 1 — `${PHASE_DIR}/EDGE-CASES/G-NN.md` (per-goal, primary)

```markdown
# Edge Cases — G-04: User creates site with custom domain

**Goal source**: `${PHASE_DIR}/TEST-GOALS/G-04.md`
**Profile**: web-fullstack
**Skipped categories**: [] (none — full coverage)

## Boundary inputs
| variant_id | input | expected_outcome | priority |
|---|---|---|---|
| G-04-b1 | domain="" (empty) | 400 with field-level error "domain required" | critical |
| G-04-b2 | domain="a"*256 | 400 "domain ≤ 253 chars" | critical |
| G-04-b3 | domain="invalid space" | 400 "invalid hostname format" | high |

## Auth boundaries
| variant_id | actor | expected_outcome | priority |
|---|---|---|---|
| G-04-a1 | anonymous | 401 redirect to /login | critical |
| G-04-a2 | peer-tenant publisher | 403 (BOLA — cross-tenant blocked) | critical |

## Concurrency / race
| variant_id | scenario | expected_outcome | priority |
|---|---|---|---|
| G-04-c1 | 2 simultaneous POST same domain | first → 201, second → 409 (atomic uniqueness) | high |
```

### Layer 2 — `${PHASE_DIR}/EDGE-CASES/index.md` (TOC)

```markdown
# Edge Cases — Phase ${PHASE_NUMBER} (Index)

**Profile**: ${PROFILE}
**Template**: edge-cases-${PROFILE}.md
**Total variants**: 47 across 12 goals

| Goal | Title | Variant count | Critical | High | Med | Low |
|---|---|---|---|---|---|---|
| [G-04](./G-04.md) | User creates site with custom domain | 6 | 3 | 2 | 1 | 0 |
| [G-12](./G-12.md) | Campaign list view | 4 | 1 | 2 | 1 | 0 |
| ... | | | | | | |

## Skipped goals (not CRUD-mutating)
- G-99: Health check endpoint — read-only, no edge cases generated
```

### Layer 3 — `${PHASE_DIR}/EDGE-CASES.md` (flat concat — legacy compat)

```markdown
<!-- vg-binding: TEST-GOALS:goals -->
<!-- vg-binding: CRUD-SURFACES:resources -->
<!-- vg-binding: profile:${PROFILE} -->

# Edge Cases — Phase ${PHASE_NUMBER}

(index content + all per-goal content concatenated for legacy grep validators)
```

---

## Variant count guidance

Per goal:
- **Mutation-heavy** (POST/PATCH/DELETE): 5-10 variants (boundary + auth + concurrency)
- **Read-only** (GET): 3-5 variants (auth + pagination + empty)
- **Compute** (no persistence): 2-4 variants (input boundaries only)
- **Trivial** (health, ping): 0 variants — log skip in goal section header

If subagent generates < 3 for non-trivial goals → re-prompt with explicit
"add 2-3 more variants from category X".

---

## Downstream consumers (build, review, test)

After this step, EDGE-CASES becomes input to:

1. **`/vg:build`** wave executor capsule:
   ```
   edge_cases_for_goal: vg-load --phase N --artifact edge-cases --goal G-NN
   ```
   Executor implements code that handles each variant_id correctly.

2. **`/vg:review`** Phase 4 goal_comparison:
   For each goal, also test variants. Status:
   ```
   G-04: PASS (5/6 variants — G-04-c1 NOT_TESTED [needs concurrency harness])
   ```

3. **`/vg:test`** codegen subagent:
   Generates `.spec.ts` with `test.each()` per variant.

4. **`/vg:roam`** lens probes:
   Cross-reference variant_ids with lens findings (e.g., lens-mass-assignment
   should cover G-NN-d* variants).

Legacy phases (pre-2026-05-03 v2.49+): EDGE-CASES.md missing → all 4
consumers skip with `severity=warn` per their respective `required_unless_flag`
declarations. Migration via `vg-migrate-edge-cases.py --phase N` (Phase 2 work).
