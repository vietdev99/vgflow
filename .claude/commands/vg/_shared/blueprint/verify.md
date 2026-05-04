# blueprint verify (STEP 5)

7 verify steps + 1 flag-gated CrossAI review. Mostly grep/path checks +
deterministic Python validators + auto-fix loop + CrossAI consensus pass.
AI orchestrates the bash; subagents not required (validators are determ).

<HARD-GATE>
ALL 7 verify steps MUST execute (8 if --skip-crossai not set). Each step
wraps work with `vg-orchestrator step-active <step>` before and `mark-step`
after — required for hook gate enforcement.

Marker name MUST be canonical (per runtime_contract):
- `2c_verify`            (not `2c_verify_grep`)
- `2c_verify_plan_paths`
- `2c_utility_reuse`     (not `2c1c_verify_utility_reuse`)
- `2c_compile_check`     (not `2c2_compile_check`)
- `2d_validation_gate`
- `2d_test_type_coverage` (not `2f_test_type_coverage_gate`)
- `2d_goal_grounding`     (not `2g_goal_grounding_gate`)
- `2d_crossai_review`     (flag-gated)
</HARD-GATE>

NOTE: This file exceeds the 500-line Anthropic recommendation because
2d_validation_gate is the largest single step (655 lines source). Rather
than split the verify group across multiple ref files (which would break
the 8-ref structure baked into the slim entry SKILL.md), the bash inlines
here. If extraction to dedicated `vg-validation-gate.py` helper happens
post-pilot, this file can shrink ≤350 lines.

---

## STEP 5.1 — grep verify (2c_verify)

Automated contract verification. Must complete in <5 seconds.

```bash
vg-orchestrator step-active 2c_verify

CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
CONTEXT="${PHASE_DIR}/CONTEXT.md"
API_ROUTES="${CONFIG_CODE_PATTERNS_API_ROUTES:-apps/api/src}"

if [ ! -f "$CONTRACTS" ]; then
  echo "⛔ API-CONTRACTS.md not found — step 2b must run first"
  exit 1
fi

# Extract endpoints (method, path) from contracts
CONTRACT_EPS=$(grep -oE '^###\s+(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTRACTS" \
  | sed 's/^###[[:space:]]*//' | sort -u)

# Extract endpoints from CONTEXT.md (VG-native bullet + legacy header)
CONTEXT_EPS=""
if [ -f "$CONTEXT" ]; then
  BULLET_EPS=$(grep -oE '^\s*-\s+(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTEXT" \
    | sed -E 's/^\s*-\s+//' | sort -u)
  HEADER_EPS=$(grep -oE '^###\s+([0-9]+\.[0-9]+\s+)?(GET|POST|PUT|DELETE|PATCH)\s+/\S+' "$CONTEXT" \
    | sed -E 's/^###[[:space:]]*([0-9]+\.[0-9]+[[:space:]]+)?//' | sort -u)
  CONTEXT_EPS=$(printf '%s\n%s\n' "$BULLET_EPS" "$HEADER_EPS" | sort -u | sed '/^$/d')
fi

MISMATCHES=0
MISSING_ENDPOINTS=""
MISSING_HANDLERS=""

# 1. Contract endpoints vs CONTEXT decisions
if [ -n "$CONTEXT_EPS" ]; then
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    ep_norm=$(echo "$ep" | awk '{print $1, $2}')
    if ! echo "$CONTRACT_EPS" | grep -qFx "$ep_norm"; then
      MISSING_ENDPOINTS="${MISSING_ENDPOINTS}\n   - ${ep_norm}"
      MISMATCHES=$((MISMATCHES + 1))
    fi
  done <<< "$CONTEXT_EPS"
fi

# 2. Contract endpoints vs backend handlers (code-pattern grep)
if [ -d "$API_ROUTES" ] && [ -n "$CONTRACT_EPS" ]; then
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    method=$(echo "$ep" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    path=$(echo "$ep" | awk '{print $2}')
    path_escaped=$(echo "$path" | sed 's/\//\\\//g; s/\./\\./g')
    if ! grep -rqE "(\.|router\.|app\.|fastify\.|${method}\s*\(\s*['\"])${path_escaped}['\"]|(route|path):\s*['\"]${path_escaped}['\"]" \
         "$API_ROUTES" 2>/dev/null; then
      MISSING_HANDLERS="${MISSING_HANDLERS}\n   - ${ep} (no handler detected)"
      MISMATCHES=$((MISMATCHES + 1))
    fi
  done <<< "$CONTRACT_EPS"
fi

ENDPOINT_COUNT=$(echo "$CONTRACT_EPS" | grep -c . || true)
CONTEXT_COUNT=$(echo "$CONTEXT_EPS" | grep -c . || true)
ENDPOINT_COUNT="${ENDPOINT_COUNT:-0}"
CONTEXT_COUNT="${CONTEXT_COUNT:-0}"
echo "Verify 1 (grep): ${ENDPOINT_COUNT} contract eps, ${CONTEXT_COUNT} context eps, ${MISMATCHES} mismatches"

if [ "$MISMATCHES" -eq 0 ]; then
  echo "✓ PASS"
else
  # R8-E (codex audit 2026-05-05) — zero tolerance for ANY mismatch between
  # CONTEXT.md decisions (source of truth) and API-CONTRACTS.md endpoints.
  # Even 1 mismatch means blueprint is internally inconsistent → downstream
  # build/review consumers may load wrong contract.
  [ -n "$MISSING_ENDPOINTS" ] && printf "Missing in contracts:%b\n" "$MISSING_ENDPOINTS"
  [ -n "$MISSING_HANDLERS" ] && printf "Missing handlers (may land in build):%b\n" "$MISSING_HANDLERS"

  if [[ "$ARGUMENTS" =~ --allow-contract-context-mismatch ]]; then
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      echo "⛔ --allow-contract-context-mismatch requires --override-reason=<text>" >&2
      exit 1
    fi
    # Canonical override.used emit — runtime_contract.forbidden_without_override
    # requires an exact override.used.flag match for --allow-contract-context-mismatch.
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag "--allow-contract-context-mismatch" \
      --reason "Blueprint accept ${MISMATCHES} endpoint mismatches CONTEXT vs API-CONTRACTS (phase ${PHASE_NUMBER})" \
      >/dev/null 2>&1 || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "blueprint-contract-context-mismatch" "${PHASE_NUMBER}" \
        "${MISMATCHES} endpoint mismatches accepted" "$PHASE_DIR"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "blueprint.contract_context_mismatch_accepted" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"mismatch_count\":${MISMATCHES}}" \
      >/dev/null 2>&1 || true
    echo "⚠ ${MISMATCHES} CONTEXT/contracts mismatch accepted via override"
  else
    echo "⛔ ${MISMATCHES} endpoint mismatch(es) between CONTEXT decisions and API-CONTRACTS" >&2
    echo "   CONTEXT.md is source of truth. Update API-CONTRACTS to match OR amend CONTEXT decisions." >&2
    echo "   Override (with reason): --allow-contract-context-mismatch --override-reason=\"<text>\"" >&2
    exit 1
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_verify" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_verify.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify 2>/dev/null || true
```

---

## STEP 5.2 — plan path validation (2c_verify_plan_paths)

Catches stale `<file-path>` tags in PLAN — Phase 10 bug class:
PLAN said `apps/api/src/infrastructure/clickhouse/migrations/0017_add_deal_columns.sql`
but real CH schemas live at `apps/workers/src/consumer/clickhouse/schemas.js`.
Caught only when executor opened the file. This step catches them at blueprint
time before /vg:build spawns executors.

```bash
vg-orchestrator step-active 2c_verify_plan_paths

PATH_CHECKER=".claude/scripts/verify-plan-paths.py"
if [ -f "$PATH_CHECKER" ]; then
  echo ""
  echo "━━━ PLAN path validation ━━━"
  ${PYTHON_BIN:-python} "$PATH_CHECKER" \
    --phase-dir "${PHASE_DIR}" \
    --repo-root "${REPO_ROOT:-.}"
  PATH_EXIT=$?

  case "$PATH_EXIT" in
    0) echo "✓ All PLAN paths valid" ;;
    2)
      echo "⚠ PLAN has path warnings — review output above."
      echo "  Intentional new subsystems → proceed (non-blocking)."
      echo "  Stale paths → fix PLAN now before /vg:build."
      ;;
    1)
      echo "⛔ PLAN has malformed paths — fix PLAN.md before proceeding."
      exit 1
      ;;
  esac
else
  echo "⚠ verify-plan-paths.py missing — skipping (older install)"
fi
```

Classifications: VALID (file exists OR parent dir exists OR another task creates
it), WARN (parent missing, no creator), FAIL (malformed: absolute / `..` escape /
empty). WARN → non-blocking. User can `<also-edits>foo/bar/` on upstream task to
declare intentional. FAIL → exit 1.

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_verify_plan_paths" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_verify_plan_paths.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_verify_plan_paths 2>/dev/null || true
```

---

## STEP 5.3 — utility reuse check (2c_utility_reuse)

Catches PLAN tasks redeclaring helpers already in `PROJECT.md` →
`## Shared Utility Contract`. Phase 10 audit found ~1500-2500 LOC duplicate
(16 files declaring own `formatCurrency`, 52 `Intl.NumberFormat currency`
occurrences).

```bash
vg-orchestrator step-active 2c_utility_reuse

UTILITY_CHECKER=".claude/scripts/verify-utility-reuse.py"
PROJECT_MD="${PLANNING_DIR}/PROJECT.md"

if [ -f "$UTILITY_CHECKER" ] && [ -f "$PROJECT_MD" ]; then
  echo ""
  echo "━━━ Utility reuse check (prevent duplicate helpers) ━━━"
  ${PYTHON_BIN:-python} "$UTILITY_CHECKER" \
    --project "$PROJECT_MD" \
    --phase-dir "${PHASE_DIR}"
  UTIL_EXIT=$?

  case "$UTIL_EXIT" in
    0) echo "✓ No utility-reuse violations" ;;
    2)
      echo "⚠ Utility-reuse warnings — consider consolidating into shared utils"
      echo "  Non-blocking. New helper genuinely phase-local → add Task 0 (extend utils)."
      ;;
    1)
      echo "⛔ PLAN redeclares helpers already in shared utility contract."
      echo "   Fix: replace re-declaration with import from shared utils, OR"
      echo "        add Task 0 (extend utils) + reuse across tasks."
      echo "   Rationale: every duplicate helper adds AST nodes (tsc slowdown) + graphify noise."
      echo "   Override: --override-reason=<issue-id>"
      if [[ ! "${ARGUMENTS:-}" =~ --override-reason= ]]; then
        exit 1
      fi
      # Canonical override.used emit — runtime_contract.forbidden_without_override
      # requires an exact override.used.flag match for --override-reason.
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag "--override-reason" \
        --reason "blueprint 2c utility-reuse violation: PLAN redeclares shared helpers (phase ${PHASE_NUMBER})" \
        >/dev/null 2>&1 || true
      echo "⚠ --override-reason set — proceeding with duplication debt"
      echo "utility-reuse: $(date -u +%FT%TZ) phase=${PHASE_NUMBER} override=yes" >> "${PHASE_DIR}/build-state.log"
      ;;
  esac
else
  [ ! -f "$UTILITY_CHECKER" ] && echo "⚠ verify-utility-reuse.py missing — skipping (older install)"
  [ ! -f "$PROJECT_MD" ] && echo "⚠ PROJECT.md missing — skipping (run /vg:project first)"
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_utility_reuse" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_utility_reuse.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_utility_reuse 2>/dev/null || true
```

---

## STEP 5.4 — contract compile check (2c_compile_check)

Extract executable code blocks from API-CONTRACTS.md → compile via
`config.contract_format.compile_cmd`. Catches contract syntax errors BEFORE
build consumes them. <10 sec.

```bash
vg-orchestrator step-active 2c_compile_check

CONTRACTS="${PHASE_DIR}/API-CONTRACTS.md"
COMPILE_CMD=$(vg_config_get contract_format.compile_cmd "")
CONTRACT_TYPE=$(vg_config_get contract_format.type "zod_code_block")

case "$CONTRACT_TYPE" in
  zod_code_block|typescript_interface) FENCE_LANG="typescript" ;;
  openapi_yaml)                        FENCE_LANG="yaml" ;;
  pydantic_model)                      FENCE_LANG="python" ;;
  *)                                   FENCE_LANG="typescript" ;;
esac

TMP_DIR=$(mktemp -d)
COMPILE_INPUT=$(${PYTHON_BIN} - "$CONTRACTS" "$TMP_DIR" "$FENCE_LANG" "$CONTRACT_TYPE" <<'PYEOF'
import sys, re
from pathlib import Path
contracts, tmpdir, lang, ctype = sys.argv[1:5]
text = Path(contracts).read_text(encoding='utf-8')
pattern = re.compile(r"```" + re.escape(lang) + r"\s*\n(.*?)\n```", re.DOTALL)
blocks = pattern.findall(text)
if not blocks:
    print(f"NO_CODE_BLOCKS: expected ```{lang} blocks, found 0. Contract format violated.")
    sys.exit(3)

prelude = ""
if ctype == "zod_code_block":
    prelude = "import { z } from 'zod';\n\n"
elif ctype == "pydantic_model":
    prelude = "from pydantic import BaseModel\nfrom typing import Optional, List, Literal\nfrom datetime import datetime\n\n"

ext = {"typescript": "ts", "yaml": "yaml", "python": "py"}.get(lang, "ts")
out = Path(tmpdir) / f"contracts-check.{ext}"
out.write_text(prelude + "\n\n".join(blocks), encoding='utf-8')
print(out)
PYEOF
)

if [ -n "$COMPILE_CMD" ]; then
  ACTUAL_CMD=$(echo "$COMPILE_CMD" | sed "s|{FILE}|$COMPILE_INPUT|g")
  [[ "$COMPILE_CMD" == *"{FILE}"* ]] || ACTUAL_CMD="$COMPILE_CMD $COMPILE_INPUT"

  eval "$ACTUAL_CMD" 2>&1 | tee "${PHASE_DIR}/contract-compile.log"
  EXIT=${PIPESTATUS[0]}
  if [ $EXIT -ne 0 ]; then
    echo "CONTRACT COMPILE FAILED — see ${PHASE_DIR}/contract-compile.log"
    echo "Fix contract syntax in ${PHASE_DIR}/API-CONTRACTS.md and re-run /vg:blueprint --from=2b"
    exit 1
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2c_compile_check" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2c_compile_check.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2c_compile_check 2>/dev/null || true
```

---

## STEP 5.5 — validation gate + auto-fix + CrossAI (2d_validation_gate + 2d_crossai_review)

**Combined step:** deterministic validation (plan↔SPECS↔goals↔contracts) +
auto-fix retry loop + CrossAI consensus review.

### 5.5.1 — load/init blueprint-state.json

```bash
vg-orchestrator step-active 2d_validation_gate

STATE_FILE="${PHASE_DIR}/blueprint-state.json"
if [ -f "$STATE_FILE" ]; then
  LAST_STEP=$(jq -r .current_step "$STATE_FILE")
  LAST_ITER=$(jq -r '.iterations | length' "$STATE_FILE")
  LAST_MODE=$(jq -r '.validation_mode_chosen // "unknown"' "$STATE_FILE")
  echo "Blueprint state found: step=$LAST_STEP iter=$LAST_ITER mode=$LAST_MODE"
  # AskUserQuestion: Resume / Restart from step / Fresh
fi

jq -n --arg phase "$PHASE_NUMBER" --arg ts "$(date -u +%FT%TZ)" '{
  phase: $phase, pipeline_version: "vg-v5.2", started_at: $ts, updated_at: $ts,
  current_step: "2d_validation",
  steps_status: {
    "2a_plan": "completed", "2b_contracts": "completed",
    "2b5_test_goals": "completed", "2c_verify": "completed",
    "2c_compile_check": "completed", "2d_validation": "in_progress",
    "3_complete": "pending"
  },
  validation_mode_chosen: null, thresholds: null, iterations: [], user_overrides: []
}' > "$STATE_FILE"
```

### 5.5.2 — strictness mode prompt

Skip if `--auto` (use `config.plan_validation.default_mode`).

```
AskUserQuestion: "Plan validation strictness — AI auto-fix up to 3 iterations."
  [Recommended: Strict]
  Options:
    - Strict (10% D / 15% G / 5% endpoints miss → BLOCK)
    - Default (20% / 30% / 10%)
    - Loose (40% / 50% / 20%)
    - Custom (enter values)
```

Save mode + thresholds to blueprint-state.json.

### 5.5.3 — deterministic validation checks

```bash
# Parse CONTEXT decisions — accepts bare D-XX AND namespaced P{phase}.D-XX
DECISIONS=$(grep -oE '^### (P[0-9.]+\.)?D-[0-9]+' "${PHASE_DIR}/CONTEXT.md" \
  | sed -E 's/^### //' | sort -u)
TASKS=$(grep -oE '^## Task [0-9]+' "${PHASE_DIR}"/PLAN*.md | sort -u)
GOALS=$(grep -oE '^### (Goal\s+)?G-[0-9]+' "${PHASE_DIR}/TEST-GOALS.md" \
  | sed -E 's/^### (Goal\s+)?//' | sort -u)
ENDPOINTS=$(grep -oE '^### (POST|GET|PUT|DELETE|PATCH) /' "${PHASE_DIR}/API-CONTRACTS.md" | sort -u)

# Cross-check 1 — Decisions covered by tasks
decisions_missing=""
for D in $DECISIONS; do
  if ! grep -rqE "(implements-decision[>:]\s*${D}|<goals-covered>[^<]*${D}\b)" \
       "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    decisions_missing="${decisions_missing} ${D}"
  fi
done

# Cross-check 2 — Goals covered by tasks
goals_missing=""
for G in $GOALS; do
  if ! grep -rqE "<goals-covered>[^<]*${G}\b" "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    goals_missing="${goals_missing} ${G}"
  fi
done

# Orphan goals (flagged by 2b5 bidirectional linkage)
orphan_goals=$(grep -B1 "Implemented by:.*⚠ NONE" "${PHASE_DIR}/TEST-GOALS.md" \
  | grep -oE 'G-[0-9]+' | sort -u)
goals_missing=$(echo "${goals_missing} ${orphan_goals}" | tr ' ' '\n' | sort -u | tr '\n' ' ')

# Cross-check 3 — Endpoints covered by tasks
endpoints_missing=""
for E_HEADER in $ENDPOINTS; do
  E=$(echo "$E_HEADER" | sed -E 's/^### //')
  if ! grep -rqF "${E}" "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
    endpoints_missing="${endpoints_missing} ${E}"
  fi
done

DEC_TOTAL=$(echo "$DECISIONS" | wc -w);  DEC_MISS=$(echo "$decisions_missing" | wc -w)
GOAL_TOTAL=$(echo "$GOALS" | wc -w);     GOAL_MISS=$(echo "$goals_missing" | wc -w)
EP_TOTAL=$(echo "$ENDPOINTS" | wc -w);   EP_MISS=$(echo "$endpoints_missing" | wc -w)

decisions_miss_pct=$(( DEC_TOTAL > 0 ? DEC_MISS * 100 / DEC_TOTAL : 0 ))
goals_miss_pct=$(( GOAL_TOTAL > 0 ? GOAL_MISS * 100 / GOAL_TOTAL : 0 ))
endpoints_miss_pct=$(( EP_TOTAL > 0 ? EP_MISS * 100 / EP_TOTAL : 0 ))
```

### 5.5.4 — deep completeness gates (Python validators)

Several Python validators (verify-blueprint-completeness, verify-test-goals-
platform-essentials, verify-codex-test-goal-lane, verify-crud-surface-contract,
verify-interface-standards, verify-task-schema, verify-ui-scope-coherence,
verify-crossai-output) run depth checks: per-endpoint auth_path/happy/4xx/401
coverage, list-view interactive_controls, mutation 4-layer persistence,
state-machine guards, etc.

Each validator emits JSON with verdict ∈ {PASS, WARN, BLOCK, SKIP}. BLOCK
exits 1 unless matching `--skip-<validator>` flag passes (logs override-debt).

```bash
run_validator() {
  local label="$1" path="$2" out_file="$3" skip_flag="$4"
  [ -x "$path" ] || return 0
  ${PYTHON_BIN} "$path" --phase "${PHASE_NUMBER}" \
    --config "${REPO_ROOT}/.claude/vg.config.md" \
    > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/${out_file}" 2>&1 || true
  local v
  v=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/${out_file}" 2>/dev/null)
  case "$v" in
    PASS|WARN) echo "✓ ${label}: $v" ;;
    BLOCK)
      echo "⛔ ${label}: BLOCK — see ${VG_TMP}/${out_file}" >&2
      echo "   Override: ${skip_flag} (logs override-debt)" >&2
      if [[ ! "$ARGUMENTS" =~ ${skip_flag} ]]; then exit 1; fi
      ;;
    *) echo "ℹ ${label}: $v" ;;
  esac
}

mkdir -p "${VG_TMP:-${PHASE_DIR}/.vg-tmp}" 2>/dev/null

run_validator "blueprint-completeness" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-blueprint-completeness.py" \
  "blueprint-completeness.json" "--skip-blueprint-completeness"

run_validator "test-goals-platform-essentials" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-test-goals-platform-essentials.py" \
  "test-goals-platform-essentials.json" "--skip-platform-essentials"

run_validator "codex-test-goal-lane" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-codex-test-goal-lane.py" \
  "codex-test-goal-lane.json" "--skip-codex-test-goal-lane"

run_validator "crud-surface-contract" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-crud-surface-contract.py" \
  "crud-surface-contract.json" "--skip-crud-surface-contract"

# Interface standards always BLOCK (no override flag — phase-wide envelope must lock)
INTERFACE_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-interface-standards.py"
if [ -x "$INTERFACE_VAL" ]; then
  ${PYTHON_BIN} "$INTERFACE_VAL" --phase "${PHASE_NUMBER}" \
      --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/interface-standards.json" 2>&1 || true
  INTERFACE_V=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
        "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/interface-standards.json" 2>/dev/null)
  if [ "$INTERFACE_V" = "BLOCK" ]; then
    echo "⛔ interface-standards: BLOCK — API/FE/CLI must lock envelope before build." >&2
    exit 1
  fi
  echo "✓ interface-standards: $INTERFACE_V"
fi

run_validator "P16 task-schema" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-task-schema.py" \
  "task-schema.json" "--skip-task-schema"

run_validator "ui-scope-coherence" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-ui-scope-coherence.py" \
  "ui-scope-coherence.json" "--skip-ui-scope-coherence"

# R8-C — phase-level G-PHASE-NN goal coverage (closes Codex closed-loop audit
# 2026-05-05 gap: component goals verify per-feature, no whole-phase E2E goal).
run_validator "phase-goal-coverage" \
  "${REPO_ROOT}/.claude/scripts/validators/verify-phase-goal-coverage.py" \
  "phase-goal-coverage.json" "--allow-phase-goal-incomplete"

# crossai-output gated on --crossai flag
if [[ "$ARGUMENTS" =~ --crossai ]]; then
  run_validator "P16 crossai-output" \
    "${REPO_ROOT}/.claude/scripts/validators/verify-crossai-output.py" \
    "crossai-output.json" "--skip-crossai-output"
fi
```

### 5.5.5 — gate decision + auto-fix loop

```
Threshold T = state.thresholds (per chosen mode)

if decisions_miss_pct ≤ T.decisions_miss_pct AND
   goals_miss_pct ≤ T.goals_miss_pct AND
   endpoints_miss_pct ≤ T.endpoints_miss_pct:
  → PASS (proceed to CrossAI 5.5.6)
else if iteration < max_auto_fix (default 3):
  → AUTO-FIX (write GAPS-REPORT.md, re-spawn vg-blueprint-planner in PATCH mode)
else:
  → EXHAUSTED (5.5.7)
```

Auto-fix iteration:
```bash
ITER=$(jq '.iterations | length' "$STATE_FILE")
NEXT_ITER=$((ITER + 1))
cp "${PHASE_DIR}"/PLAN*.md "${PHASE_DIR}/PLAN.md.v${NEXT_ITER}"

cat > "${PHASE_DIR}/GAPS-REPORT.md" <<EOF
# Gaps Report — Iteration $NEXT_ITER (Phase ${PHASE_NUMBER})

## Missing decisions (plan↔SPECS)
${decisions_missing}

## Missing goals (plan↔TEST-GOALS)
${goals_missing}

## Missing endpoints (plan↔API-CONTRACTS)
${endpoints_missing}

## Instruction for planner
APPEND tasks covering missing items. DO NOT rewrite existing tasks.
Match each new task to 1 missing P{phase}.D-XX / F-XX, G-XX, or endpoint.
EOF

# Refresh bootstrap rules
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "blueprint" "${PHASE_NUMBER}"

# Re-spawn vg-blueprint-planner in PATCH mode (read GAPS-REPORT.md, append tasks)
# Then re-run granularity check (2a post), bidirectional linkage (2b5 post),
# grep verify (5.1), compile check (5.4), back to 5.5.3.
```

### 5.5.6 — CrossAI consensus review (when gate PASSED)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2d_crossai_review 2>/dev/null || true

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-skip-guard.sh" 2>/dev/null || \
  echo "⚠ crossai-skip-guard.sh missing — skip audit not enforced" >&2

SKIP_CAUSE_BP=$(crossai_detect_skip_cause "${ARGUMENTS:-}" ".claude/vg.config.md" 2>/dev/null || echo "")

if [ -n "$SKIP_CAUSE_BP" ]; then
  REASON_BP="blueprint CrossAI skip cho phase ${PHASE_NUMBER} (args=${ARGUMENTS:-none})"
  if ! crossai_skip_enforce "vg:blueprint" "$PHASE_NUMBER" "blueprint.2d_crossai_review" \
       "$SKIP_CAUSE_BP" "$REASON_BP"; then
    echo "⛔ Rubber-stamp guard chặn skip — exit." >&2
    exit 1
  fi
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/2d_crossai_review.done"
else
  echo "▸ CrossAI blueprint review starting — phase ${PHASE_NUMBER}"

  # Prepare context file
  CROSSAI_CTX="${VG_TMP:-${PHASE_DIR}/.vg-tmp}/vg-crossai-${PHASE_NUMBER}-blueprint-review.md"
  mkdir -p "$(dirname "$CROSSAI_CTX")" 2>/dev/null
  {
    echo "# CrossAI Blueprint Review — Phase ${PHASE_NUMBER}"
    echo ""
    echo "Gate passed deterministic validation. Review qualitative:"
    echo "1. Plan covers all CONTEXT decisions"
    echo "2. API contracts consistent with plan tasks"
    echo "3. ORG 6 dimensions addressed (Infra/Env/Deploy/Smoke/Integration/Rollback)"
    echo "4. Contract fields reasonable between request/response pairs"
    echo "5. No duplicate endpoints or conflicting field definitions"
    echo "6. Acceptance criteria testable (not vague)"
    echo "7. Design-refs linked appropriately"
    echo ""
    echo "Verdict: pass (score ≥7) | flag (≥5 minor) | block (missing/wrong)"
    echo ""
    echo "## Artifacts"
    echo "---"; cat "${PHASE_DIR}/CONTEXT.md"
    echo "---"
    bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" --phase "${PHASE_NUMBER}" \
      --artifact plan --full 2>/dev/null \
      || cat "${PHASE_DIR}"/PLAN*.md 2>/dev/null
    echo "---"
    bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" --phase "${PHASE_NUMBER}" \
      --artifact contracts --full 2>/dev/null \
      || cat "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null
    echo "---"
    bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" --phase "${PHASE_NUMBER}" \
      --artifact goals --full 2>/dev/null \
      || cat "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null
  } > "$CROSSAI_CTX"

  # Set up + delegate to crossai-invoke.md
  export CONTEXT_FILE="$CROSSAI_CTX"
  export OUTPUT_DIR="${PHASE_DIR}/crossai"
  export LABEL="blueprint-review"
  source "${REPO_ROOT}/.claude/commands/vg/_shared/crossai-invoke.md" 2>/dev/null || true
  # crossai-invoke populates CROSSAI_VERDICT, OK_COUNT, TOTAL_CLIS, CLI_STATUS[]

  case "${CROSSAI_VERDICT:-unknown}" in
    pass) echo "✓ CrossAI: PASS (${OK_COUNT:-?}/${TOTAL_CLIS:-?} CLIs agreed)" ;;
    flag)
      echo "⚠ CrossAI: FLAG — minor concerns"
      echo "   Review ${PHASE_DIR}/crossai/result-*.xml for findings"
      # Auto-fix path: apply Minor fixes inline, proceed
      ;;
    block)
      # R6 Task 7 — bounded remediation cap (blueprint.crossai_remediation_max)
      # Counter file persists across --resume runs at ${PHASE_DIR}/.crossai-iter.json
      CROSSAI_ITER_FILE="${PHASE_DIR}/.crossai-iter.json"
      CROSSAI_REMEDIATION_MAX=$(vg_config_get blueprint.crossai_remediation_max 3 2>/dev/null || echo 3)

      CROSSAI_ITER=0
      if [ -f "$CROSSAI_ITER_FILE" ]; then
        CROSSAI_ITER=$(${PYTHON_BIN:-python3} -c "
import json
try:
  print(json.load(open('${CROSSAI_ITER_FILE}', encoding='utf-8')).get('iter', 0))
except Exception:
  print(0)
" 2>/dev/null || echo 0)
      fi

      if [ "${CROSSAI_ITER:-0}" -ge "${CROSSAI_REMEDIATION_MAX:-3}" ]; then
        echo "⛔ CrossAI: BLOCK — remediation cap reached (${CROSSAI_ITER}/${CROSSAI_REMEDIATION_MAX})"
        echo "   Config key: blueprint.crossai_remediation_max (default 3)"
        echo "   Loop refused — apply fix manually OR override:"
        echo "     /vg:blueprint ${PHASE_NUMBER} --skip-crossai --override-reason='<≥50ch ticket+context>'"

        "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
          "blueprint.crossai_remediation_max_iter_reached" \
          --payload "{\"phase\":\"${PHASE_NUMBER}\",\"iterations\":${CROSSAI_ITER},\"max\":${CROSSAI_REMEDIATION_MAX}}" \
          >/dev/null 2>&1 || true

        type -t log_override_debt >/dev/null 2>&1 && \
          log_override_debt "blueprint-crossai-remediation-max-iter" "${PHASE_NUMBER}" \
            "blueprint.2d_crossai_review" \
            "CrossAI remediation hit hard cap ${CROSSAI_ITER}/${CROSSAI_REMEDIATION_MAX} — manual fix or --skip-crossai required" \
            "$PHASE_DIR" 2>/dev/null || true

        exit 2
      fi

      # Increment + persist counter for next iter
      CROSSAI_ITER=$((CROSSAI_ITER + 1))
      ${PYTHON_BIN:-python3} - <<PY > "$CROSSAI_ITER_FILE"
import json
print(json.dumps({"iter": ${CROSSAI_ITER}, "max": ${CROSSAI_REMEDIATION_MAX}}))
PY

      echo "⛔ CrossAI: BLOCK — major/critical concerns (remediation ${CROSSAI_ITER}/${CROSSAI_REMEDIATION_MAX})"
      echo "   ${PHASE_DIR}/crossai/result-*.xml chứa findings cần resolve"
      echo ""
      echo "Orchestrator MUST:"
      echo "  1. Parse findings → AskUserQuestion (recommended option FIRST per global guidance)"
      echo "  2. User accept fix → apply, re-invoke crossai (cap ${CROSSAI_REMEDIATION_MAX} remediations)"
      echo "  3. User reject → block_resolve_l4_stuck + exit"
      exit 2
      ;;
    inconclusive)
      echo "⛔ CrossAI: INCONCLUSIVE (${OK_COUNT:-0}/${TOTAL_CLIS:-?} CLIs)"
      if [[ "$ARGUMENTS" =~ --allow-crossai-inconclusive ]]; then
        type -t log_override_debt >/dev/null 2>&1 && \
          log_override_debt "blueprint-crossai-inconclusive" "${PHASE_NUMBER}" "${OK_COUNT:-0}/${TOTAL_CLIS:-?} inconclusive" "$PHASE_DIR"
        echo "⚠ --allow-crossai-inconclusive set — proceeding, debt logged"
      else
        echo "Fix: retry / --skip-crossai / --allow-crossai-inconclusive"
        exit 1
      fi
      ;;
    unknown|"") echo "⚠ CrossAI: verdict not set — empty config or --skip-crossai" ;;
    *) echo "⛔ CrossAI: unexpected verdict '${CROSSAI_VERDICT}'"; exit 1 ;;
  esac
fi

# Mark CrossAI marker (fixes v1.15.2 marker drift bug — body wrote 2d_validation_gate but contract expected 2d_crossai_review)
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_crossai_review" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_crossai_review.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_crossai_review 2>/dev/null || true
```

**MANDATORY when escalating CrossAI to user (AskUserQuestion):**
- Pick recommended option BEFORE showing question (CrossAI consensus / CONTEXT
  > PLAN drift / codebase reality / security > convenience).
- Order options with recommended FIRST + " (Recommended)" suffix.
- Explain WHY recommended in option `description` field.
- Do NOT ask without recommendation — silent multi-option puts rationalization
  burden on user.

### 5.5.7 — exhausted

```bash
echo "Plan validation exhausted after max iterations."
echo "Options:"
echo "  (a) /vg:blueprint ${PHASE_NUMBER} --override-reason='<text>' (accept gaps)"
echo "  (b) Edit PLAN.md manually → /vg:blueprint ${PHASE_NUMBER} --from=2d"
echo "  (c) /vg:scope ${PHASE_NUMBER} (refine SPECS — root cause may be spec gap)"
jq '.steps_status["2d_validation"] = "exhausted"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
exit 1
```

### 5.5.8 — passed: finalize

```bash
jq '.steps_status["2d_validation"] = "completed" |
    .current_step = "3_complete" |
    .updated_at = now|strftime("%FT%TZ")' \
   "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_validation_gate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_validation_gate.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_validation_gate 2>/dev/null || true
```

---

## STEP 5.6 — D18 test_type coverage gate (2d_test_type_coverage)

Validate every mutation goal in TEST-GOALS.md declares `**Test type:**` field
AND aggregate coverage meets thresholds from TEST-STRATEGY.md (D17). Closes
"AI bịa goal" gap — without test_type per goal, /vg:test cannot dispatch
correct verification strategy (api_contract → recipe_executor; ui_ux →
browser scan; security → lens prompt).

```bash
vg-orchestrator step-active 2d_test_type_coverage

TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ]; then
  echo "━━━ D18 test_type coverage gate ━━━"

  # Pre-2026-05-01 phases get WARN grandfather; new phases default BLOCK.
  GOALS_FIRST_COMMIT_TS=$(git log --reverse --format=%ct -- "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null | head -1)
  GRANDFATHER_CUTOFF=$(date -u -j -f "%Y-%m-%d" "2026-05-01" +%s 2>/dev/null \
    || date -u -d "2026-05-01" +%s 2>/dev/null || echo "0")
  if [ -n "$GOALS_FIRST_COMMIT_TS" ] && [ "$GOALS_FIRST_COMMIT_TS" -lt "$GRANDFATHER_CUTOFF" ]; then
    D18_SEVERITY="warn"
    echo "  Pre-2026-05-01 phase — D18 in WARN mode (grandfathered)"
  else
    D18_SEVERITY="block"
  fi

  D18_OUT=$("${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" \
    validate-test-types --phase "${PHASE_NUMBER}" --severity "$D18_SEVERITY" 2>&1)
  D18_RC=$?
  echo "$D18_OUT" | sed 's/^/  D18: /'
  if [ "$D18_RC" -eq 1 ]; then
    echo "⛔ D18 BLOCK: TEST-GOALS missing test_type or coverage gaps."
    echo "   Fix: add **Test type:** {smoke|happy|edge|negative|security|perf|integration} to each mutation goal."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.d18_test_type_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_test_type_coverage" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_test_type_coverage.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_test_type_coverage 2>/dev/null || true
```

---

## STEP 5.7 — PR-F goal_grounding gate (2d_goal_grounding)

Validate every goal declares `goal_grounding ∈ {api, flow, presentation}`.
Drives /vg:test verification dispatch — without grounding, test cannot pick
correct proof shape:

- **api**          → recipe_executor + openapi.json + lifecycle.post_state
- **flow**         → flow-runner walks FLOW-SPEC checkpoints
- **presentation** → screenshot diff + display-computation check

Closes "API = nghiệp vụ, UI = thin client" simplification — true for B2B
billing but NOT for onboarding wizards (flow IS business) or dashboards (UI
computes display from API raw data).

```bash
vg-orchestrator step-active 2d_goal_grounding

GROUNDING_VAL=".claude/scripts/validators/verify-goal-grounding.py"
if [ -f "$GROUNDING_VAL" ] && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  echo "━━━ PR-F goal_grounding gate ━━━"

  GOALS_FIRST_COMMIT_TS=$(git log --reverse --format=%ct -- "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null | head -1)
  GRANDFATHER_CUTOFF=$(date -u -j -f "%Y-%m-%d" "2026-05-01" +%s 2>/dev/null \
    || date -u -d "2026-05-01" +%s 2>/dev/null || echo "0")
  if [ -n "$GOALS_FIRST_COMMIT_TS" ] && [ "$GOALS_FIRST_COMMIT_TS" -lt "$GRANDFATHER_CUTOFF" ]; then
    GROUNDING_SEVERITY="warn"
  else
    GROUNDING_SEVERITY="block"
  fi
  ${PYTHON_BIN:-python3} "$GROUNDING_VAL" \
    --phase "${PHASE_NUMBER}" --severity "$GROUNDING_SEVERITY" 2>&1 | sed 's/^/  PR-F: /'
  GROUND_RC=$?
  if [ "$GROUND_RC" -eq 1 ] && [ "$GROUNDING_SEVERITY" = "block" ]; then
    echo "⛔ PR-F BLOCK: goals missing goal_grounding declaration."
    echo "   Fix: add **Goal grounding:** api|flow|presentation to each goal."
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "blueprint.goal_grounding_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "2d_goal_grounding" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2d_goal_grounding.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2d_goal_grounding 2>/dev/null || true
```

---

After all 7 (or 8 with --skip-crossai not set) markers touched, return to
entry SKILL.md → STEP 6 (close).
