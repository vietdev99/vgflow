# blueprint contracts group — STEP 4 (2b/2b5/2b5a/2b5d)

HEAVY step. You MUST delegate the artifact generation to
`vg-blueprint-contracts` subagent (tool name `Agent`, not `Task`).

<HARD-GATE>
You MUST spawn `vg-blueprint-contracts` for steps 2b_contracts +
2b5_test_goals + 2b5d_expand_from_crud_surfaces (if CRUD-SURFACES present).

You MUST NOT generate API-CONTRACTS.md / TEST-GOALS.md / CRUD-SURFACES.md inline.

Step 2b5a_codex_test_goal_lane runs INSIDE main agent (it spawns Codex CLI
externally, no main-agent generation). Skipping requires
`--skip-codex-test-goal-lane` + override-debt log.
</HARD-GATE>

---

## Orchestration order

1. **Pre-spawn**: `vg-orchestrator step-active 2b_contracts`. Read
   `INTERFACE-STANDARDS.md` (locked in STEP 1.5), `vg.config.md` for
   `contract_format.type`.
2. **Spawn**: `Agent(subagent_type="vg-blueprint-contracts", prompt=<from delegation.md>)`
3. **Post-spawn validation**:
   - Validate API-CONTRACTS.md exists + sha256 match.
   - Validate TEST-GOALS.md exists + Rule 3b persistence gate.
   - Validate CRUD-SURFACES.md exists.
   - Run goal classifier (surface assignment).
   - Schema validation gate (verify-artifact-schema.py).
4. **Mark step 2b_contracts** + **2b5_test_goals**.
5. **Run 2b5a Codex lane** (separate spawn, NOT vg-blueprint-contracts).
6. **Run 2b5d expand** (deterministic Python script).
7. **Mark steps 2b5a + 2b5d** + emit `blueprint.contracts_generated`.

---

## STEP 4.1 — pre-spawn checklist

```bash
vg-orchestrator step-active 2b_contracts

# Verify INTERFACE-STANDARDS locked (from STEP 1.5)
[ -f "${PHASE_DIR}/INTERFACE-STANDARDS.md" ] || {
  echo "⛔ INTERFACE-STANDARDS.md missing — re-run STEP 1.5 (verify_prerequisites)"
  exit 1
}
[ -f "${PHASE_DIR}/INTERFACE-STANDARDS.json" ] || {
  echo "⛔ INTERFACE-STANDARDS.json missing — re-run STEP 1.5"
  exit 1
}

# Read config
CONTRACT_TYPE=$(vg_config_get contract_format.type zod_code_block 2>/dev/null || echo zod_code_block)
COMPILE_CMD=$(vg_config_get contract_format.compile_cmd "" 2>/dev/null || echo "")
echo "✓ Contracts will use format: ${CONTRACT_TYPE}"
```

---

## STEP 4.2 — spawn vg-blueprint-contracts

Read `contracts-delegation.md` for the full prompt template. **MANDATORY**:
emit colored-tag narration before + after the spawn (per vg-meta-skill).

```bash
bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts spawning "writing API/TEST-GOALS/CRUD for ${PHASE_NUMBER}"
```

Then call:
```
Agent(subagent_type="vg-blueprint-contracts", prompt=<rendered template>)
```

The subagent writes:
- `${PHASE_DIR}/API-CONTRACTS.md` (4-block per endpoint format)
- `${PHASE_DIR}/TEST-GOALS.md` (per-decision goals + persistence + URL state)
- `${PHASE_DIR}/CRUD-SURFACES.md` (resource × operation × platform contract)

Returns JSON with paths + sha256 + bindings_satisfied + warnings.

```bash
bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts returned "API endpoints+goals+CRUD generated"
```

If subagent error JSON or empty output:
```bash
bash scripts/vg-narrate-spawn.sh vg-blueprint-contracts failed "<one-line cause>"
```

---

## STEP 4.3 — post-spawn validation

### Validate paths + sha256

```bash
# Recompute SHA256 of API-CONTRACTS.md, assert match against subagent return
ACTUAL_SHA=$(sha256sum "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null | awk '{print $1}')
[ "$ACTUAL_SHA" = "$RETURNED_SHA" ] || {
  echo "⛔ API-CONTRACTS.md sha256 mismatch — subagent return suspect"
  exit 1
}

# Per blueprint.md frontmatter content_min_bytes:
#   API-CONTRACTS.md no min, codex-proposal ≥ 40, codex-delta ≥ 80,
#   CRUD-SURFACES.md ≥ 120 unless --crossai-only
[ -f "${PHASE_DIR}/CRUD-SURFACES.md" ] || {
  if [[ ! "$ARGUMENTS" =~ --crossai-only ]]; then
    echo "⛔ CRUD-SURFACES.md missing"
    exit 1
  fi
}

CRUD_BYTES=$(wc -c < "${PHASE_DIR}/CRUD-SURFACES.md" 2>/dev/null || echo 0)
if [ "${CRUD_BYTES:-0}" -lt 120 ] && [[ ! "$ARGUMENTS" =~ --crossai-only ]]; then
  echo "⛔ CRUD-SURFACES.md too small (${CRUD_BYTES} bytes < 120)"
  exit 1
fi
```

### Rule 3b: persistence check coverage gate (BLOCK)

Every TEST-GOALS goal with non-empty `**Mutation evidence:**` MUST have a
`**Persistence check:**` block — otherwise the "ghost save" bug class
(toast + 200 + console clean BUT refresh shows old data) escapes review.

```bash
GOALS_FILE="${PHASE_DIR}/TEST-GOALS.md"
if [ -f "$GOALS_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$GOALS_FILE" <<'PY'
import re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')
goal_pattern = re.compile(r'(^#{2,3}\s+(?:Goal\s+)?G-\d+[^\n]*)\n(.*?)(?=^#{2,3}\s+(?:Goal\s+)?G-\d+|\Z)',
                          re.MULTILINE | re.DOTALL)

mutation_goals_missing_persist = []
mutation_count = 0
persist_count = 0

for m in goal_pattern.finditer(text):
    header = m.group(1).strip()
    body = m.group(2)
    gid_match = re.search(r'G-\d+', header)
    gid = gid_match.group(0) if gid_match else '?'

    mut_match = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.DOTALL)
    has_mutation = False
    if mut_match:
        mut_value = mut_match.group(1).strip()
        if mut_value and not re.match(r'^(N/A|none|—|-|_)\s*$', mut_value, re.I):
            has_mutation = True
            mutation_count += 1

    has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
    if has_persist:
        persist_count += 1

    if has_mutation and not has_persist:
        mutation_goals_missing_persist.append(gid)

if mutation_goals_missing_persist:
    print(f"⛔ Rule 3b violation: {len(mutation_goals_missing_persist)} mutation goal(s) thiếu Persistence check:")
    for gid in mutation_goals_missing_persist:
        print(f"   - {gid}")
    print("\nMỗi goal có Mutation evidence PHẢI có Persistence check block.")
    print("Layer 4 review gate sẽ catch ghost save bug — thiếu block = BLOCKED.")
    sys.exit(1)

print(f"✓ Rule 3b: {mutation_count} mutation goals, {persist_count} with Persistence check")
PY
  PERSIST_RC=$?
  if [ "$PERSIST_RC" != "0" ]; then
    echo "blueprint-r3b-violation phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/blueprint-state.log"
    type -t emit_telemetry_v2 >/dev/null 2>&1 && \
      emit_telemetry_v2 "blueprint_r3b_persistence_missing" "${PHASE_NUMBER}" "blueprint.2b5" "blueprint_r3b_persistence_missing" "FAIL" "{}"
    if [[ "$ARGUMENTS" =~ --allow-missing-persistence ]]; then
      type -t log_override_debt >/dev/null 2>&1 && \
        log_override_debt "blueprint-missing-persistence" "${PHASE_NUMBER}" "mutation goals without Persistence check" "$PHASE_DIR"
      echo "⚠ --allow-missing-persistence set — proceeding, debt logged"
    else
      echo "   Fix: edit TEST-GOALS.md, thêm Persistence check block cho goals trên"
      echo "   Override (NOT recommended): --allow-missing-persistence"
      exit 1
    fi
  fi
fi
```

### Bidirectional Goal ↔ Task linkage (auto-injection)

After TEST-GOALS.md written, inject cross-references so build step 8 can
quickly find context:

1. **Goals → Tasks**: per G-XX, detect tasks in PLAN*.md implementing it
   (match by endpoint/file mentions). Append `**Implemented by:**` line.
2. **Tasks → Goals**: per task, inject `<goals-covered>` attribute (auto-detect
   from task description matching goal mutation evidence).

Algorithm (deterministic, no AI):
- For each goal extract endpoints from "mutation evidence".
- For each task: if contains matching endpoint OR feature-name → append.
- Orphan tasks → `<goals-covered>no-goal-impact</goals-covered>` or `UNKNOWN — review`.
- Orphan goals → `**Implemented by:** ⚠ NONE (spec gap — plan regen needed)`.

### Surface classification (v1.9.1 R1 — required)

```bash
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
```

Return codes:
- `0` → all goals classified ≥0.8 confidence (auto-count narration).
- `2` → 0.5..0.8 band needs Haiku tie-break. Read `${PHASE_DIR}/.goal-classifier-pending.tsv`,
  spawn ONE Haiku subagent per goal (returns `{surface, confidence}`),
  call `classify_goals_apply` with resolved TSV.
- `3` → some goals <0.5 confidence. BLOCK until user picks via `AskUserQuestion`.

Narration:
```
🎯 Goal surfaces: 17 ui · 5 api · 3 data · 2 time-driven · 1 integration
```

### Schema validation (BLOCK on TEST-GOALS.md frontmatter drift)

```bash
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact test-goals \
  > "${PHASE_DIR}/.tmp/artifact-schema-test-goals.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ TEST-GOALS.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-test-goals.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-test-goals.json"
  exit 2
fi
```

### Mark steps 2b + 2b5

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b_contracts" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b_contracts.done"
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b5_test_goals" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b5_test_goals.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b_contracts 2>/dev/null || true
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5_test_goals 2>/dev/null || true
```

---

## STEP 4.4 — Codex TEST-GOALS lane (2b5a)

Independent Codex co-author for TEST-GOALS coverage. Codex does NOT edit
TEST-GOALS.md directly — writes proposal artifact, then deterministic delta
script forces planner to reconcile or skip with debt.

```bash
vg-orchestrator step-active 2b5a_codex_test_goal_lane

CODEX_GOAL_MARKER="${PHASE_DIR}/.step-markers/2b5a_codex_test_goal_lane.done"
CODEX_GOAL_SKIP_MARKER="${PHASE_DIR}/.step-markers/2b5a_codex_test_goal_lane.skipped"
CODEX_GOAL_PROPOSAL="${PHASE_DIR}/TEST-GOALS.codex-proposal.md"
CODEX_GOAL_DELTA="${PHASE_DIR}/TEST-GOALS.codex-delta.md"

if [[ "$ARGUMENTS" =~ --skip-codex-test-goal-lane ]]; then
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "$CODEX_GOAL_SKIP_MARKER"
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "blueprint-codex-test-goal-lane-skipped" "${PHASE_NUMBER}" \
      "Codex TEST-GOALS co-author proposal/delta lane skipped" "$PHASE_DIR"
  echo "⚠ --skip-codex-test-goal-lane set — proposal lane skipped and debt logged"
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b5a_codex_test_goal_lane" "${PHASE_DIR}") || touch "$CODEX_GOAL_MARKER"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5a_codex_test_goal_lane 2>/dev/null || true
else
  CODEX_SPAWN="${REPO_ROOT}/.claude/commands/vg/_shared/lib/codex-spawn.sh"
  if [ ! -x "$CODEX_SPAWN" ] && [ ! -f "$CODEX_SPAWN" ]; then
    echo "⛔ codex-spawn.sh missing — cannot run independent Codex TEST-GOALS lane" >&2
    echo "   Override: --skip-codex-test-goal-lane" >&2
    exit 1
  fi
  if ! command -v codex >/dev/null 2>&1; then
    echo "⛔ codex CLI not found — install/login Codex CLI." >&2
    echo "   Override: --skip-codex-test-goal-lane" >&2
    exit 1
  fi

  CODEX_GOAL_PROMPT="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-test-goals-${PHASE_NUMBER}.md"
  mkdir -p "$(dirname "$CODEX_GOAL_PROMPT")" 2>/dev/null
  {
    echo "# Codex TEST-GOALS Co-Author Proposal"
    echo ""
    echo "You are an independent VGFlow planning reviewer. Do not edit files."
    echo "Read the artifacts below and propose missing TEST-GOALS coverage only."
    echo ""
    echo "Output requirements:"
    echo "- Markdown only."
    echo "- Reference decision ID (P{phase}.D-XX or D-XX) per proposal."
    echo "- Focus: CRUD list/form/delete, business flow, authz/security,"
    echo "  abuse, performance, persistence, URL state, mobile/web differences."
    echo "- Do NOT propose selectors or implementation steps."
    echo ""
    echo "## CONTEXT.md"
    sed -n '1,260p' "${PHASE_DIR}/CONTEXT.md" 2>/dev/null || true
    echo ""
    echo "## PLAN.md"
    sed -n '1,260p' "${PHASE_DIR}/PLAN.md" 2>/dev/null || true
    echo ""
    echo "## API-CONTRACTS.md"
    sed -n '1,260p' "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || true
    echo ""
    echo "## TEST-GOALS.md FINAL DRAFT"
    sed -n '1,320p' "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null || true
    echo ""
    echo "## CRUD-SURFACES.md"
    sed -n '1,260p' "${PHASE_DIR}/CRUD-SURFACES.md" 2>/dev/null || true
  } > "$CODEX_GOAL_PROMPT"

  bash "$CODEX_SPAWN" \
    --tier planner --sandbox read-only \
    --prompt-file "$CODEX_GOAL_PROMPT" \
    --out "$CODEX_GOAL_PROPOSAL" \
    --timeout 900 --cd "$REPO_ROOT"

  if [ ! -s "$CODEX_GOAL_PROPOSAL" ]; then
    echo "⛔ Codex proposal output empty: $CODEX_GOAL_PROPOSAL" >&2
    exit 1
  fi

  if ! "${PYTHON_BIN:-python3}" .claude/scripts/test-goal-delta.py \
      --phase-dir "$PHASE_DIR" \
      --final "$PHASE_DIR/TEST-GOALS.md" \
      --proposal "$CODEX_GOAL_PROPOSAL" \
      --out "$CODEX_GOAL_DELTA"; then
    echo "⛔ Codex TEST-GOALS delta has unresolved coverage." >&2
    echo "   Read: $CODEX_GOAL_DELTA" >&2
    echo "   Fix: update TEST-GOALS.md with missing coverage, rerun /vg:blueprint ${PHASE_NUMBER} --from=2b5." >&2
    echo "   Override: --skip-codex-test-goal-lane (debt logged)." >&2
    exit 1
  fi

  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b5a_codex_test_goal_lane" "${PHASE_DIR}") || touch "$CODEX_GOAL_MARKER"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5a_codex_test_goal_lane 2>/dev/null || true
fi
```

---

## STEP 4.5 — Expand TEST-GOALS from CRUD-SURFACES (2b5d_expand_from_crud_surfaces)

After TEST-GOALS.md (manual) and CRUD-SURFACES.md (resource contract) are
written, expand goal layer with per-resource × per-operation × per-role ×
per-variant stubs. Closes the gap where blueprint declared 67 goals but
CRUD-SURFACES specified 200-300 verification points.

Output: `${PHASE_DIR}/TEST-GOALS-EXPANDED.md` with `G-CRUD-*` IDs. Test
codegen consumes alongside `TEST-GOALS.md` (manual) + `TEST-GOALS-DISCOVERED.md`
(runtime).

```bash
vg-orchestrator step-active 2b5d_expand_from_crud_surfaces

echo ""
echo "━━━ 2b5d — Expand TEST-GOALS from CRUD-SURFACES ━━━"

if [ ! -f "${PHASE_DIR}/CRUD-SURFACES.md" ]; then
  echo "  (no CRUD-SURFACES.md — skipping expansion)"
else
  ${PYTHON_BIN:-python3} .claude/scripts/expand-test-goals-from-crud-surfaces.py \
    --phase-dir "$PHASE_DIR"
  EXPAND_RC=$?

  if [ "$EXPAND_RC" -eq 0 ] && [ -f "${PHASE_DIR}/TEST-GOALS-EXPANDED.md" ]; then
    EXPANDED_COUNT=$(grep -c "^id: G-CRUD-" "${PHASE_DIR}/TEST-GOALS-EXPANDED.md" 2>/dev/null || echo 0)
    echo "  ✓ ${EXPANDED_COUNT} expansion goal(s) → TEST-GOALS-EXPANDED.md"
    type -t emit_telemetry_v2 >/dev/null 2>&1 && \
      emit_telemetry_v2 "blueprint_2b5d_expanded" "${PHASE_NUMBER}" "blueprint.2b5d-expand" \
        "test_goals_expansion" "PASS" "{\"expanded\":${EXPANDED_COUNT}}" 2>/dev/null || true
  else
    echo "  ⚠ Expansion failed (rc=${EXPAND_RC}) — codegen falls back to TEST-GOALS.md only"
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b5d_expand_from_crud_surfaces" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b5d_expand_from_crud_surfaces.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b5d_expand_from_crud_surfaces 2>/dev/null || true
```

---

## STEP 4.6 — flow detect (2b7_flow_detect, profile-gated web only)

**Purpose:** Detect goal dependency chains ≥3 in TEST-GOALS.md. When found,
auto-generate `${PHASE_DIR}/FLOW-SPEC.md` skeleton so `/vg:test` step
5c-flow has flows to verify. Without this, multi-page state-machine bugs
(login → create → edit → delete) slip through because per-goal tests verify
each step independently but miss continuity failures.

**Skip conditions:**
- TEST-GOALS.md does not exist (blueprint hasn't generated goals yet)
- Profile is `web-backend-only` / `cli-tool` / `library` (no UI flows)

```bash
vg-orchestrator step-active 2b7_flow_detect

# Profile gate — skip if backend-only / non-web
case "${PHASE_PROFILE:-feature}" in
  web-fullstack|web-frontend-only|feature) ;;
  *) echo "  Profile=${PHASE_PROFILE} — skip flow detect (no UI flows)"
     mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
     (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b7_flow_detect" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b7_flow_detect.done"
     "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b7_flow_detect 2>/dev/null || true
     return 0 2>/dev/null || true ;;
esac

if [ ! -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  echo "  (no TEST-GOALS.md — skip flow detect)"
else
  echo ""
  echo "━━━ 2b7 — FLOW-SPEC auto-detect ━━━"

  # Step 1: Parse dependency graph from TEST-GOALS.md (deterministic, no AI)
  CHAIN_OUTPUT=$(${PYTHON_BIN:-python3} - "${PHASE_DIR}/TEST-GOALS.md" <<'PYEOF'
import sys, re, json
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse goals: ID, title, priority, dependencies
goals = {}
current = None
for line in text.splitlines():
    m = re.match(r'^## Goal (G-\d+):\s*(.+?)(?:\s*\(D-\d+\))?$', line)
    if m:
        current = m.group(1)
        goals[current] = {'title': m.group(2).strip(), 'deps': [], 'priority': 'important'}
        continue
    if current:
        dm = re.match(r'\*\*Dependencies:\*\*\s*(.+)', line)
        if dm:
            deps_str = dm.group(1).strip()
            if deps_str.lower() not in ('none', 'none (root goal)', ''):
                goals[current]['deps'] = re.findall(r'G-\d+', deps_str)
        pm = re.match(r'\*\*Priority:\*\*\s*(\w+)', line)
        if pm:
            goals[current]['priority'] = pm.group(1).strip()

# Build dependency chains via DFS — find all maximal chains
def find_chains(goal_id, visited=None):
    if visited is None:
        visited = []
    visited = visited + [goal_id]
    dependents = [g for g, info in goals.items() if goal_id in info['deps'] and g not in visited]
    if not dependents:
        return [visited]
    chains = []
    for dep in dependents:
        chains.extend(find_chains(dep, visited))
    return chains

# Root goals (no deps)
roots = [g for g, info in goals.items() if not info['deps']]
all_chains = []
for root in roots:
    all_chains.extend(find_chains(root))

# Filter chains ≥3 goals (multi-step business flows)
long_chains = [c for c in all_chains if len(c) >= 3]
seen = set()
unique_chains = []
for chain in sorted(long_chains, key=len, reverse=True):
    key = tuple(chain[:2])  # dedup by first 2 elements
    if key not in seen:
        seen.add(key)
        unique_chains.append(chain)

output = {
    'total_goals': len(goals),
    'total_chains': len(unique_chains),
    'chains': [{'goals': c, 'length': len(c),
                'titles': [goals[g]['title'] for g in c if g in goals]}
               for c in unique_chains],
    'goals': {g: info for g, info in goals.items()}
}
print(json.dumps(output, indent=2))
PYEOF
  )

  CHAIN_COUNT=$(echo "$CHAIN_OUTPUT" | ${PYTHON_BIN:-python3} -c "import sys,json; print(json.load(sys.stdin)['total_chains'])" 2>/dev/null || echo "0")

  if [ "$CHAIN_COUNT" -eq 0 ]; then
    echo "Flow detect: no dependency chains ≥3 found. Skipping FLOW-SPEC generation."
    # No FLOW-SPEC.md = /vg:test 5c-flow will skip (expected for simple phases)
  else
    echo "Flow detect: $CHAIN_COUNT chains ≥3 goals found. Generating FLOW-SPEC.md skeleton..."

    # Bootstrap rule injection — project rules targeting blueprint fire here
    source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
    BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
    vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"

    # Spawn agent to generate FLOW-SPEC.md skeleton
    # Agent(subagent_type="general-purpose", model="${MODEL_TEST_GOALS}"):
    #   prompt:
    #     <bootstrap_rules>
    #     ${BOOTSTRAP_RULES_BLOCK}
    #     </bootstrap_rules>
    #
    #     Generate FLOW-SPEC.md for phase ${PHASE_NUMBER}. Multi-page test flows
    #     for the flow-runner skill.
    #
    #     Input — detected dependency chains:
    #     ${CHAIN_OUTPUT}
    #
    #     Input — full TEST-GOALS.md:
    #     @${PHASE_DIR}/TEST-GOALS.md
    #
    #     Input — API-CONTRACTS.md (for endpoint details):
    #     @${PHASE_DIR}/API-CONTRACTS.md
    #
    #     RULES:
    #     1. Each chain becomes 1 flow (ordered sequence of steps).
    #     2. Each step maps to 1 goal in the chain.
    #     3. Step has: action (what user does), expected (what system shows),
    #        checkpoint (what to save for next step).
    #     4. Use goal success criteria + mutation evidence as step expected/checkpoint.
    #     5. Do NOT invent steps outside the chain.
    #     6. Do NOT specify selectors/CSS classes/exact clicks — describe WHAT not HOW.
    #     7. Flow names describe business operation: "Site CRUD lifecycle",
    #        "Campaign create-to-launch".
    #
    #     Output format:
    #     # Flow Specs — Phase {PHASE}
    #     Generated from: TEST-GOALS.md dependency chains ≥3
    #     Total: {N} flows
    #
    #     ## Flow F-01: {Business operation name}
    #     **Chain:** {G-00 → G-01 → G-03 → G-05}
    #     **Priority:** critical | important
    #     **Roles:** [{roles involved}]
    #
    #     ### Step 1: {Action name} (G-00)
    #     **Action:** {what user does}
    #     **Expected:** {what system shows — from goal success criteria}
    #     **Checkpoint:** {state to verify/save — from mutation evidence}
    #
    #     ## Flow Coverage
    #     | Flow | Goals covered | Priority |
    #
    #     Write to: ${PHASE_DIR}/FLOW-SPEC.md
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2b7_flow_detect" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2b7_flow_detect.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b7_flow_detect 2>/dev/null || true
```

---

## STEP 4.7 — final telemetry

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event blueprint.contracts_generated --phase "${PHASE_NUMBER}" 2>/dev/null || true
```

After all 6 markers (2b_contracts, 2b5_test_goals, 2b5a_codex,
2b5d_expand_from_crud_surfaces, 2b7_flow_detect) touched, return to entry
SKILL.md → STEP 5 (verify).
