# build validate-blueprint (STEP 3)

4 sub-steps: `3_validate_blueprint` (artifacts + CONTEXT format + amendment/CONTEXT freshness), `5_handle_branching` (per-config branch checkout), `6_validate_phase` (PIPELINE-STATE update + plan-count report), `7_discover_plans` (enumerate task files for the build queue).

<HARD-GATE>
You MUST run STEPS 3.1 through 3.4 in exact order. Each step is gated by
markers (Stop hook checks). Skipping any step BLOCKS run completion.

STEP 3.1 (`3_validate_blueprint`) is the contract-and-decision freshness
gate — if it does not run, executors may be spawned against a stale plan
or a CONTEXT.md that drifted post-blueprint. The PreToolUse Bash hook
gates `vg-orchestrator step-active`; each sub-step's bash MUST be wrapped
with `step-active` before its real work and `mark-step` after.

STEP 3.4 (`7_discover_plans`) defines the build queue. If it lists zero
tasks, downstream waves CANNOT spawn — step 8 has nothing to dispatch.
You MUST NOT skip this step before wave execution.
</HARD-GATE>

---

## STEP 3.1 — validate blueprint (3_validate_blueprint)

**MANDATORY GATE — blueprint artifacts + CONTEXT.md format + amendment/CONTEXT freshness vs PLAN.md.**

This step performs four sub-checks: (3.1a) presence of `PLAN*.md` and `API-CONTRACTS.md`, (3.1a.5) interface-standards generation + validation so every executor reads the same API/FE/CLI envelope, (3.1b) CONTEXT.md decision-format validation for `feature` profile (decision count > 0; Endpoints / Test Scenarios sub-sections preferred), (3.1c) amendment-vs-blueprint mtime drift, and (3.1d) CONTEXT.md-vs-PLAN.md mtime drift. Mtime checks here are KEEP-FLAT — they consult file timestamps and grep counters, never read flat artifacts into AI context.

```bash
vg-orchestrator step-active 3_validate_blueprint

### 3a: Check core artifacts exist

PLANS=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | head -1)
CONTRACTS=$(ls "${PHASE_DIR}"/API-CONTRACTS.md 2>/dev/null)

# Missing PLAN → BLOCK: "Run `/vg:blueprint {phase}` first."
# Missing CONTRACTS → WARNING: "No API contracts. Executors will build without contract guidance. Continue? (y/n)"

### 3a.5: Interface standards gate
# Before any executor receives a task, materialize and validate the phase's
# API/FE/CLI communication contract. This prevents each agent from inventing
# its own response envelope or toast/error convention.

INTERFACE_GEN="${REPO_ROOT}/.claude/scripts/generate-interface-standards.py"
INTERFACE_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-interface-standards.py"
if [ -f "$INTERFACE_GEN" ]; then
  "${PYTHON_BIN:-python3}" "$INTERFACE_GEN" \
    --phase-dir "${PHASE_DIR}" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}"
fi
if [ -f "$INTERFACE_VAL" ]; then
  mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
  "${PYTHON_BIN:-python3}" "$INTERFACE_VAL" \
    --phase-dir "${PHASE_DIR}" \
    --profile "${PROFILE:-${CONFIG_PROFILE:-web-fullstack}}" \
    > "${PHASE_DIR}/.tmp/interface-standards-build.json" 2>&1
  INTERFACE_RC=$?
  cat "${PHASE_DIR}/.tmp/interface-standards-build.json"
  if [ "$INTERFACE_RC" -ne 0 ]; then
    echo "⛔ INTERFACE-STANDARDS gate failed before build."
    echo "   Fix the API/FE/CLI communication standard before spawning executors."
    exit 1
  fi
fi

### 3b: CONTEXT.md format validation (v1.14.4+ — R2 enforcement)
# Executor rules require commits cite `D-XX` / `P{phase}.D-XX` decisions.
# If CONTEXT.md missing or legacy format (no Endpoints / Test Scenarios
# sub-sections), executor cites stale decisions and commit-msg hook either
# fails or lets weak citations through.

# Only enforce for feature profile — other profiles (infra/hotfix/docs) skip CONTEXT per phase-profile rules
PHASE_PROFILE_FOR_CTX="${PHASE_PROFILE:-feature}"
if [ "$PHASE_PROFILE_FOR_CTX" = "feature" ]; then
  CONTEXT_FILE="${PHASE_DIR}/CONTEXT.md"

  if [ ! -f "$CONTEXT_FILE" ]; then
    echo "⛔ CONTEXT.md missing cho phase ${PHASE_NUMBER} (feature profile cần CONTEXT.md)."
    echo "   Run: /vg:scope ${PHASE_NUMBER} trước khi build."
    exit 1
  fi

  # Parse CONTEXT structure
  DECISION_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-[0-9]+' "$CONTEXT_FILE" 2>/dev/null || echo 0)
  ENDPOINT_SECTIONS=$(grep -c '^\*\*Endpoints:\*\*' "$CONTEXT_FILE" 2>/dev/null || echo 0)
  TEST_SECTIONS=$(grep -c '^\*\*Test Scenarios:\*\*' "$CONTEXT_FILE" 2>/dev/null || echo 0)

  if [ "$DECISION_COUNT" -eq 0 ]; then
    echo "⛔ CONTEXT.md có 0 decisions — phase chưa scoped đúng."
    echo "   Expected: '### D-01', '### D-02', ... hoặc '### P${PHASE_NUMBER}.D-01' format."
    echo "   Run: /vg:scope ${PHASE_NUMBER}"
    exit 1
  fi

  if [ "$ENDPOINT_SECTIONS" -eq 0 ] && [ "$TEST_SECTIONS" -eq 0 ]; then
    # Legacy format — warn but allow (blueprint step 2a also warns)
    echo "⚠ CONTEXT.md legacy format (không có 'Endpoints:' hoặc 'Test Scenarios:' sub-sections)."
    echo "   Executor sẽ cite decision IDs nhưng thiếu context cụ thể."
    echo "   Khuyến nghị: /vg:scope ${PHASE_NUMBER} để re-enrich."
    # Log to override-debt (technical debt tracking)
    if type -t log_override_debt >/dev/null 2>&1; then
      log_override_debt "build-context-legacy" "${PHASE_NUMBER}" "CONTEXT.md legacy format — no Endpoints/Test sections" "$PHASE_DIR"
    fi
  fi

  echo "✓ CONTEXT.md: ${DECISION_COUNT} decisions, ${ENDPOINT_SECTIONS} endpoint blocks, ${TEST_SECTIONS} test blocks"
fi

### 3c: Amendment freshness check (harness v2.7-fixup-C1)
# Why: /vg:amend writes AMENDMENT-LOG.md mid-phase. If user runs amend AFTER
# blueprint but BEFORE build, PLAN.md / API-CONTRACTS.md are stale relative
# to the amendment. Build would silently execute the pre-amendment plan.
# This gate detects mtime drift and blocks unless user explicitly overrides.

# C1 fix — Amendment freshness check
# Detect /vg:amend ran between blueprint and build → BLOCK with re-blueprint guidance.
AMENDMENT_FILE="${PHASE_DIR}/AMENDMENT-LOG.md"
if [ -f "$AMENDMENT_FILE" ]; then
  PLAN_FILE="${PHASE_DIR}/PLAN.md"
  CONTRACTS_FILE="${PHASE_DIR}/API-CONTRACTS.md"
  STALE=""
  if [ -f "$PLAN_FILE" ] && [ "$AMENDMENT_FILE" -nt "$PLAN_FILE" ]; then
    STALE="PLAN.md"
  fi
  if [ -f "$CONTRACTS_FILE" ] && [ "$AMENDMENT_FILE" -nt "$CONTRACTS_FILE" ]; then
    STALE="${STALE:+$STALE+}API-CONTRACTS.md"
  fi
  if [ -n "$STALE" ]; then
    echo "⛔ Amendment freshness BLOCK — AMENDMENT-LOG.md is newer than $STALE"
    echo "   Mid-phase amendment landed after last blueprint pass."
    echo "   Re-run: /vg:blueprint ${PHASE_NUMBER} --from=2a"
    echo "   (or override via --override-reason if amendment is doc-only)"
    if [[ ! "${ARGUMENTS}" =~ --override-reason ]]; then
      exit 1
    fi
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "amendment-stale-blueprint" "${PHASE_NUMBER}" \
        "amendment newer than blueprint; user override" "$PHASE_DIR"
    echo "⚠ --override-reason set — proceeding with stale plan, debt logged"
  fi
fi

### 3d: CONTEXT.md freshness vs PLAN.md (harness v2.7-fixup-M4)
# Why: Step 3b validates CONTEXT.md format + decision count, but does NOT
# detect when user manually edits CONTEXT.md after blueprint completed.
# Mid-phase decision tweak (e.g., adding D-15 directly to CONTEXT.md without
# /vg:amend) leaves PLAN.md stale referencing the pre-edit decision set.
# Build executes against an inconsistent decision graph. This gate compares
# mtimes and forces a re-blueprint or explicit override.

# M4 fix — CONTEXT.md mtime freshness check
# Detects post-blueprint edits to CONTEXT.md → BLOCK with re-blueprint or /vg:amend guidance.
if [ "$PHASE_PROFILE_FOR_CTX" = "feature" ] && [ -f "$CONTEXT_FILE" ]; then
  PLAN_FILE="${PHASE_DIR}/PLAN.md"
  if [ -f "$PLAN_FILE" ] && [ "$CONTEXT_FILE" -nt "$PLAN_FILE" ]; then
    echo "⛔ CONTEXT.md modified after PLAN.md — re-blueprint or run /vg:amend"
    echo "   PLAN.md is stale relative to current CONTEXT.md decisions."
    echo "   Run: /vg:blueprint ${PHASE_NUMBER} --from=2a   (re-plan from current CONTEXT)"
    echo "   OR:  /vg:amend ${PHASE_NUMBER}                  (capture change as amendment)"
    echo "   Override (NOT RECOMMENDED): re-run with --override-reason=\"...\""
    if [[ ! "${ARGUMENTS}" =~ --override-reason ]]; then
      exit 1
    fi
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "context-stale-plan" "${PHASE_NUMBER}" \
        "CONTEXT newer than PLAN; user override" "$PHASE_DIR"
    echo "⚠ --override-reason set — proceeding with stale plan, debt logged"
  fi
fi

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 3_validate_blueprint 2>/dev/null || true
```

Result routing (3a-3d combined):
- Missing PLAN → HARD BLOCK
- Missing CONTRACTS → WARN (executors run without contract guidance)
- Interface-standards validator non-zero → HARD BLOCK
- Feature profile + CONTEXT.md missing OR 0 decisions → HARD BLOCK
- Feature profile + legacy CONTEXT format → WARN + override-debt
- AMENDMENT-LOG newer than PLAN/CONTRACTS + no `--override-reason` → HARD BLOCK
- CONTEXT.md newer than PLAN.md + no `--override-reason` → HARD BLOCK
- Either freshness check + `--override-reason` set → WARN + override-debt
- Non-feature profile → CONTEXT checks skipped (3a/3a.5 still enforced)

---

## STEP 3.2 — handle branching (5_handle_branching)

**Per-config branch checkout — `branching_strategy=phase|milestone|none`.**

OHOK Batch 4 B6 (2026-04-22): replaced prose "checkout branch" with real bash. Previously the step had ZERO code — marker was touched blindly regardless of whether the branch existed, checkout succeeded, or git was in a conflicted state. Now gated on a clean working tree (worktree AND staged) before any `git checkout` runs (CrossAI Round 6 finding: `git diff --quiet` alone ignores staged-only files).

```bash
vg-orchestrator step-active 5_handle_branching

BRANCH_STRATEGY=$(vg_config_get branching_strategy "none" 2>/dev/null || echo "none")

case "$BRANCH_STRATEGY" in
  phase|milestone)
    BRANCH_NAME="phase/${PHASE_NUMBER}"
    if [ "$BRANCH_STRATEGY" = "milestone" ]; then
      # milestone strategy → branch per milestone (first phase of milestone creates, others reuse)
      MILESTONE_NUM=$(echo "$PHASE_NUMBER" | cut -d. -f1)
      BRANCH_NAME="milestone/${MILESTONE_NUM}"
    fi

    # Pre-flight: no uncommitted changes that would block checkout.
    # Check BOTH worktree AND staged (index) changes — `git diff --quiet` alone
    # ignores staged-only files (CrossAI Round 6 finding).
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
      echo "⛔ Uncommitted changes (worktree or staged) — cannot checkout ${BRANCH_NAME}" >&2
      git status --short 2>/dev/null | head -10 >&2
      echo "   Commit or stash first: git stash save --include-untracked 'pre-build-${PHASE_NUMBER}'" >&2
      exit 1
    fi

    CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [ "$CURRENT" = "$BRANCH_NAME" ]; then
      echo "✓ Already on ${BRANCH_NAME}"
    elif git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
      if ! git checkout "${BRANCH_NAME}" 2>&1; then
        echo "⛔ git checkout ${BRANCH_NAME} failed" >&2
        exit 1
      fi
      echo "✓ Checked out existing branch ${BRANCH_NAME}"
    else
      if ! git checkout -b "${BRANCH_NAME}" 2>&1; then
        echo "⛔ git checkout -b ${BRANCH_NAME} failed" >&2
        exit 1
      fi
      echo "✓ Created + checked out new branch ${BRANCH_NAME}"
    fi
    ;;
  none|"")
    echo "↷ branching_strategy=none — staying on current branch ($(git rev-parse --abbrev-ref HEAD 2>/dev/null))"
    ;;
  *)
    echo "⚠ Unknown branching_strategy='${BRANCH_STRATEGY}' — skipping (expected: phase|milestone|none)" >&2
    ;;
esac

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_handle_branching" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_handle_branching.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 5_handle_branching 2>/dev/null || true
```

Result routing:
- `branching_strategy=phase` + clean tree → checkout `phase/${PHASE_NUMBER}` (create if absent)
- `branching_strategy=milestone` + clean tree → checkout `milestone/${MILESTONE_NUM}` (create if absent)
- `branching_strategy=none` (or unset) → stay on current branch
- Dirty tree (worktree or staged) under `phase|milestone` → HARD BLOCK
- Unknown `branching_strategy` value → WARN, no checkout

---

## STEP 3.3 — validate phase (6_validate_phase)

**Phase-level state update — report plan count and write `PIPELINE-STATE.json`.**

This step is the seam between blueprint validation and plan discovery: once the build is committed to running on this phase, `PIPELINE-STATE.json` is flipped to `status=building` so external observers (e.g., `/vg:progress`, `/vg:health`) see the phase advancing into build. The state write is idempotent — the merge preserves any unrelated keys already present in the file.

```bash
vg-orchestrator step-active 6_validate_phase

# VG-native state update (no GSD dependency)
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
${PYTHON_BIN} -c "
import json; from pathlib import Path
p = Path('${PIPELINE_STATE}')
s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
s['status'] = 'building'; s['pipeline_step'] = 'build'
s['phase_number'] = '${PHASE_NUMBER}'; s['phase_name'] = '${PHASE_NAME}'
s['plan_count'] = '${PLAN_COUNT}'
s['updated_at'] = __import__('datetime').datetime.now().isoformat()
p.write_text(json.dumps(s, indent=2))
" 2>/dev/null

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6_validate_phase" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_validate_phase.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 6_validate_phase 2>/dev/null || true
```

---

## STEP 3.4 — discover plans (7_discover_plans)

**Enumerate task files for the build queue. Filter by `has_summary`, `--gaps-only`, `--wave N`, `--only`.**

This step builds the work queue that step 8 will dispatch. R1a UX baseline (Req 1) prefers the per-task split form via `vg-load --artifact plan --list` over a directory `ls` of `PLAN*.md`, because the split form's `PLAN/index.md` carries `has_summary` flags and per-task metadata that an `ls` cannot see. The fallback `ls` below is preserved for legacy phases that still ship a single flat `PLAN.md`. Per-task content access (rare in this discovery step — content is consumed by later steps) uses `vg-load --artifact plan --task NN`.

```bash
vg-orchestrator step-active 7_discover_plans

# VG-native plan index (no GSD dependency)
PLAN_INDEX=$(ls -1 "${PHASE_DIR}"/PLAN*.md 2>/dev/null)

# Filter: skip `has_summary: true`. If `--gaps-only`: skip non-gap_closure. If `--wave N`: skip non-matching.
# Report execution plan table.

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_discover_plans" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/7_discover_plans.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 7_discover_plans 2>/dev/null || true
```

Result routing:
- Zero plans discovered → BLOCK downstream waves (step 8 has nothing to dispatch)
- All plans `has_summary: true` → empty queue, build short-circuits to step 9
- `--gaps-only` filter → keep only `gap_closure`-flagged plans
- `--wave N` filter → keep only plans tagged with wave N
- `--only` filter → restrict to the explicit task list passed in `$ARGUMENTS`

---

### vg-load convention for plan discovery (R1a UX baseline Req 1)

When this step (or any downstream step in the validate-blueprint group) needs to enumerate task IDs, prefer:

```
vg-load --phase ${PHASE_NUMBER} --artifact plan --list
```

This returns task filenames from `PLAN/index.md` without reading the flat `PLAN.md` blob. The loader falls back to a flat parse only when the split form is missing. For per-task content (rare in this step — content access happens in later steps such as 4d task-section extraction and step 8 capsule assembly), use:

```
vg-load --phase ${PHASE_NUMBER} --artifact plan --task NN
```

Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md` (rows for backup lines 494-657, 1014-1108), the four steps in this group do KEEP-FLAT operations only — `ls`-based presence checks, `grep -c` decision counters, mtime comparisons, awk filters, and echo strings. None of them feed flat artifact bodies into AI context, so no MIGRATE replacements were required during extraction.

---

After all four step markers are touched, return to entry `build.md` → STEP 4 (execute waves: `8_execute_waves`).
