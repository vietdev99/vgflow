# build waves (STEP 4 — HEAVY)

<!-- # Exception: oversized ref (~1155 lines) — extracted verbatim from backup
     spec line 1882; ceiling raised to 1200 in test_build_references_exist.py
     per audit doc docs/audits/2026-05-04-build-flat-vs-split.md. Keeping
     verbatim avoids drift risk on R2 build pilot ship; future refactor
     splits 8d post-spawn aggregation into its own ref. -->

This is the orchestrator-side body of the build pipeline's wave-execution
step (`8_execute_waves`) plus the per-wave bootstrap-reflection sub-step
(`8_5_bootstrap_reflection_per_wave`). It is heavy: backup spec ~880 lines,
multiple verifier sub-steps, mobile gate matrix, debugger retry loop, and
post-wave reconciliation.

Read `waves-delegation.md` for the input/output JSON contract of the
`vg-build-task-executor` subagent. This file describes the orchestrator's
responsibilities ONLY — pre-spawn checklist, spawn site narration,
post-spawn aggregation, gate matrix, retry handling, marker emission.

<HARD-GATE>
You MUST spawn N parallel `vg-build-task-executor` subagents in ONE
assistant message — where N = `expected.length` from
`.vg/runs/${RUN_ID}/.wave-spawn-plan.json` (parallel batch only;
sequential_groups serialize as documented in 8c).
You CANNOT execute tasks inline. You MUST NOT paraphrase the task body
into your own implementation — every plan task is a subagent spawn.

The PreToolUse Agent hook (`scripts/vg-agent-spawn-guard.py`, Task 1
commit `6135701`) DENIES the Agent tool call when:
  - `subagent_type` != `vg-build-task-executor` (wrong agent type or typo)
  - `task_id` missing from prompt envelope
  - `task_id` not in `remaining[]` of `.vg/runs/${RUN_ID}/.spawn-count.json`
  - capsule file `.task-capsules/task-${N}.capsule.json` missing on disk

The `vg-orchestrator wave-complete` command asserts
`spawned.length == expected.length` post-wave by reading
`.vg/runs/${RUN_ID}/.spawn-count.json` (R2 round-2 — `cmd_wave_complete`
in `scripts/vg-orchestrator/__main__.py`). A shortfall (N-1 spawned, N
expected) BLOCKs `wave.completed` with exit code 2 + emits
`wave.shortfall_blocked` to events.db; the operator sees the deny
message and must complete the missing spawn (or pass
`--allow-missing-commits --override-reason=<ticket>`) before the wave
closes. The Stop hook surfaces the same condition transitively via
`run-status --check-contract` since the missing `wave.completed` event
fails `must_emit_telemetry`.

You MUST narrate every spawn via `bash scripts/vg-narrate-spawn.sh`
(green pill per R1a UX baseline Req 2). Skipping narration breaks
operator UX visibility but does NOT block; missing spawn DOES block.
</HARD-GATE>

---

## Per-wave orchestration order

For each wave (subject to `WAVE_FILTER` gate):
1. **Pre-spawn checklist** (8a / 8a.5 / 8b / 8c PRE-FLIGHT) — wave context
   write, SUMMARY init, wave-start tag + progress init, capsule
   materialization via `pre-executor-check.py`, L1 design-pixel gate,
   spawn plan write to `.wave-spawn-plan.json`.
2. **Spawn site** (8c spawn block) — narrate + spawn ALL N parallel
   subagents in ONE assistant message, then narrate returns/failures.
3. **Post-spawn aggregation** (8d) — R5 spawn-plan honor check, commit
   count audit, attribution audit, integrity reconcile, UI-MAP injection
   audit, task-fidelity audit, gate matrix (typecheck/build/test/contract/
   goal-test-binding/utility-dup + mobile gates 6-10), debugger retry
   loop, wave-verify divergence check, fixture wave-verify, post-wave
   graphify refresh.
4. **Resume-recovery** branch when `--gaps-only` or `--resume` is set —
   uses `vg-load --artifact plan --task NN` instead of awk-extracting
   from flat `PLAN*.md` (per audit doc line 1232 migration).
5. **Step exit** — emit `wave.completed` event, write step marker.

After ALL waves complete (or after the single Wave N completes when
`WAVE_FILTER` is set), run sub-step `8_5_bootstrap_reflection_per_wave`
(reflect-after-each-wave), then exit step 8 and return to entry
`build.md` → STEP 5 (post-execution: `9_post_execution`).

---

## Per-wave pre-spawn checklist

Mark step active and gate on `WAVE_FILTER`:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 8_execute_waves

# WAVE_FILTER gate (v2.2): execute ONLY filtered wave then exit to step 9.
if [ -n "${WAVE_FILTER:-}" ]; then
  echo "▸ --wave ${WAVE_FILTER} mode: orchestrator will execute ONLY Wave ${WAVE_FILTER} then exit to step 9."
fi
```

### Step 1 — Load wave plan slice (R1a UX baseline Req 1, partial load)

Use the loader instead of `cat`-ing the flat PLAN file:

```bash
vg-load --phase ${PHASE_NUMBER} --artifact plan --wave ${N}
```

Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md`, this
replaces the historical flat-PLAN read pattern in resume-recovery (see
"Resume-recovery handling" below). The loader returns the wave's task
list and per-task plan slices without dumping the full PLAN.md into AI
context.

### Step 2 — Generate `wave-{N}-context.md` (8a)

Orchestrator writes `${PHASE_DIR}/wave-{N}-context.md` listing siblings.
Each executor in the wave reads this for cross-task field alignment.

```markdown
# Wave {N} Context — Phase {PHASE}

Tasks running in parallel this wave:

## Task <N1> — <task title from PLAN>
  File: <task.file_path>
  Endpoint: <method + path>           (if BE task — from <edits-endpoint> attribute)
  Request fields: <field list>         (from contract section)
  Response fields: <field list>
  Contract ref: API-CONTRACTS.md line <start>-<end>

## Task <N2> — <task title>
  File: <task.file_path>
  Consumes: <upstream endpoint> (Task <N1>)         (if FE task consuming a wave-mate's API)
  MUST use same field names as Task <N1> request
  Contract ref: API-CONTRACTS.md line <start>-<end>

## Task <N3> — <task title>
  File: <task.file_path>
  Shares <storage backend> collection/table with Task <N1>    (if relevant)
  Contract ref: API-CONTRACTS.md line <start>-<end>
```

Generated deterministically from PLAN*.md tasks (parse `<file-path>`,
`<edits-endpoint>`, `<contract-ref>`, `<edits-collection>` attributes —
no project hardcode). The `Contract ref: API-CONTRACTS.md line X-Y` is a
locator pointer string (KEEP-FLAT per audit doc) — the executor receives
it for traceability; no flat read happens.

### Step 2.1 — Cross-WORKFLOW block (Task 42, M2)

When any task in the wave has `capsule.workflow_id != null` AND
`${PHASE_DIR}/WORKFLOW-SPECS/<workflow_id>.md` exists, the orchestrator
appends a `Cross-WORKFLOW constraint:` block per such task. This block
cites siblings in other waves + the exact `state_after` value the workflow
declares for the current task's step.

Use the canonical helper:

```bash
python3 scripts/generate-wave-context.py \
  --phase-dir "${PHASE_DIR}" \
  --wave "${WAVE_ID}" \
  --tasks "$(IFS=,; echo "${WAVE_TASK_NUMS[*]}")" \
  --capsules-dir "${PHASE_DIR}/.task-capsules" \
  > "${PHASE_DIR}/wave-${WAVE_ID}-context.md"
```

The script:
- Reads each task's capsule (Task 41 schema) for `workflow_id` / `workflow_step` / `actor_role`
- Reads `WORKFLOW-SPECS/<workflow_id>.md` to resolve the `state_after` value for the task's step
- Indexes capsules across ALL waves to find siblings
- Emits HTML comment sentinel `<!-- vg-telemetry: build.cross_wave_workflow_cited -->` when the block was added — orchestrator greps this and emits the telemetry event

Backward-compat: phases without WORKFLOW-SPECS or all-null workflow_ids
skip the block silently. The script never errors on missing artifacts.

Example output:

```markdown
## Task 6 — tx_groups enum extension
  Workflow: WF-001 step 2 (USER)
  Cross-WORKFLOW constraint:
    - Task 12 (wave 5, ADMIN, step 4 of WF-001) writes state established by your step
    - Task 18 (wave 7, USER, step 5 of WF-001) reads state established by your step
    - Your `state_after` MUST be exactly `pending_admin_review` (per WORKFLOW-SPECS/WF-001.md state_machine.states)
```

### Step 3 — Initialize SUMMARY.md (first wave only) (8a.5)

```bash
SUMMARY_FILE="${PHASE_DIR}/SUMMARY.md"
if [ ! -f "$SUMMARY_FILE" ]; then
  cat > "$SUMMARY_FILE" << EOF
# Build Summary — Phase ${PHASE_NUMBER}

**Started:** $(date -Iseconds)
**Plan:** ${PLAN_FILE}
**Model:** ${MODEL_EXECUTOR}

EOF
  echo "SUMMARY.md initialized at ${SUMMARY_FILE}"
fi
```

Executors append their task summary sections to this file (per
`vg-executor-rules.md` "Task summary output"). After all waves, step 9
verifies every task has a section.

### Step 4 — Tag wave start + emit `wave.started` event + init progress file (8b)

```bash
git tag "vg-build-${PHASE}-wave-${N}-start" HEAD
WAVE_TAG="vg-build-${PHASE}-wave-${N}-start"

# Emit canonical wave.started event (orchestrator helper). Required by
# build.md frontmatter must_emit_telemetry — Stop hook fails run-complete
# without ≥1 wave.started event in events.db. Idempotent: same wave N
# rejected if already started in this run.
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator wave-start "${N}" 2>/dev/null \
  || echo "⚠ wave-start emit failed (or wave ${N} already started) — continuing" >&2

# Init compact-safe progress file — survives context compacts + crashes.
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/typecheck-light.sh"

# Bootstrap typecheck cache once per build session (cold 3-5 min, but makes
# subsequent per-task + wave-gate checks fast 10-30s). Heuristic: distinct
# app names from PLAN file-paths.
BOOTSTRAP_PKGS=$(grep -hoE '<file-path>apps/[^/]+' "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
  | sed 's|<file-path>apps/||' | sort -u)
for pkg in $BOOTSTRAP_PKGS; do
  if vg_typecheck_should_bootstrap "$pkg"; then
    echo "▸ Bootstrapping typecheck cache for $pkg (1-shot, ~3-5 min)..."
    vg_typecheck_bootstrap "$pkg"
  fi
done

# Apply --only filter if set (resume subset of wave tasks)
WAVE_TASK_LIST="${WAVE_TASKS[@]}"
if [ -n "${ONLY_TASKS:-}" ]; then
  FILTERED=""
  for t in $WAVE_TASK_LIST; do
    if echo "$ONLY_TASKS" | tr ',' '\n' | grep -qx "$t"; then
      FILTERED="${FILTERED} $t"
    fi
  done
  WAVE_TASK_LIST="${FILTERED# }"
  echo "▸ --only filter — running tasks: $WAVE_TASK_LIST (skipping others)"
fi

vg_build_progress_init "$PHASE_DIR" "$N" "$WAVE_TAG" $WAVE_TASK_LIST
export VG_BUILD_PHASE_DIR="$PHASE_DIR"
```

### Step 5 — Pre-flight: verify step 4 artifacts (8c PRE-FLIGHT)

Before spawning, the orchestrator MUST verify step 4 artifacts exist. If
missing, run step 4 NOW:

```
CHECK these files exist (not empty):
  1. ${PHASE_DIR}/.callers.json     (from step 4e — semantic regression)
  2. ${PHASE_DIR}/.wave-context/    (from step 4c — sibling detection)

IF EITHER missing:
  1. Read .claude/vg.config.md — extract graphify.enabled, semantic_regression.enabled
  2. Run step 4c: find-siblings.py for each task (creates .wave-context/siblings-task-{N}.json)
  3. Run step 4e: build-caller-graph.py (creates .callers.json)
  4. Run step 4d: vg-load --artifact plan --task NN per task in wave
     (per-task split is the canonical source; loader falls back to flat
      parse only if split missing — per audit doc 2026-05-04 line 1232)

This prevents resume from skipping context injection — executor without
sibling/caller context produces code that may break cross-module dependencies.
```

### Step 6 — File conflict detection + spawn plan write

Parse `<file-path>` from each task in the current wave. If 2+ tasks edit
the SAME file, those tasks MUST run sequentially (not parallel) to
prevent git staging race conditions.

```bash
# Collect file paths per task in wave
WAVE_FILES=()
for task_num in "${WAVE_TASKS[@]}"; do
  TASK_FILE="${PHASE_DIR}/.wave-tasks/task-${task_num}.md"
  if [ -f "$TASK_FILE" ]; then
    FILE_PATH=$(grep -oP '<file-path>\K[^<]+' "$TASK_FILE" | head -1)
  else
    # Fallback: vg-load per-task slice when wave-tasks shard missing
    FILE_PATH=$(vg-load --phase ${PHASE_NUMBER} --artifact plan --task ${task_num} 2>/dev/null \
      | grep -oP '<file-path>\K[^<]+' | head -1)
  fi
  [ -n "$FILE_PATH" ] && WAVE_FILES+=("${task_num}:${FILE_PATH}")
done

# R6 Task 15 — collect cross-task DAG edges from each task's plan file.
# Same-file conflicts (above) auto-serialize via sequential_groups; this
# captures cross-FILE logical deps (e.g., Task 04 consumes API from Task 01)
# declared via optional `depends_on:` field (see plan-overview.md).
# Format: WAVE_DEPS entry = "task-NN:task-XX,task-YY" (downstream:upstream-csv).
WAVE_DEPS=()
for task_num in "${WAVE_TASKS[@]}"; do
  TASK_PLAN="${PHASE_DIR}/PLAN/task-${task_num}.md"
  # Fallback to .wave-tasks shard when PLAN/task-NN.md missing (flat PLAN.md case)
  [ -f "$TASK_PLAN" ] || TASK_PLAN="${PHASE_DIR}/.wave-tasks/task-${task_num}.md"
  if [ -f "$TASK_PLAN" ]; then
    # Accept three syntaxes: YAML frontmatter `depends_on:`, markdown
    # `**depends_on:**`, or XML-tag `<depends_on>` — first match wins.
    DEPS_LINE=$(grep -E "^(depends_on:|\*\*depends_on:\*\*|<depends_on>)" "$TASK_PLAN" | head -1)
    if [ -n "$DEPS_LINE" ]; then
      DEPS=$(echo "$DEPS_LINE" | grep -oE 'task-[0-9]+' | sort -u | tr '\n' ',' | sed 's/,$//')
      [ -n "$DEPS" ] && WAVE_DEPS+=("task-${task_num}:${DEPS}")
    fi
  fi
done

# Detect conflicts — same file in 2+ tasks
SEEN_FILES=$(printf '%s\n' "${WAVE_FILES[@]}" | cut -d: -f2 | sort | uniq -d)
if [ -n "$SEEN_FILES" ]; then
  echo "⚠ File conflict in wave ${N}:"
  for file in $SEEN_FILES; do
    TASKS=$(printf '%s\n' "${WAVE_FILES[@]}" | grep ":${file}$" | cut -d: -f1 | tr '\n' ',')
    echo "  ${file} → Tasks ${TASKS}"
  done
  echo "  → Conflicting tasks will run SEQUENTIALLY within this wave."
fi

# R5 enforcement: write explicit spawn plan (orchestrator MUST honor)
# Two artifacts:
#   1. ${PHASE_DIR}/.wave-spawn-plan.json — phase-local R5 enforcement view
#      (parallel/sequential_groups with integer task numbers + conflict_files)
#   2. .vg/runs/${RUN_ID}/.wave-spawn-plan.json — guard-readable schema
#      (expected: [task-NN, ...]) consumed by scripts/vg-agent-spawn-guard.py
#      to validate per-spawn task_id and assert spawned == expected at Stop.
# Schema for (2) is locked R5 contract — guard reads `expected` key.
SPAWN_PLAN="${PHASE_DIR}/.wave-spawn-plan.json"
RUN_ID=$(${PYTHON_BIN} -c "import json,os; sid=os.environ.get('CLAUDE_HOOK_SESSION_ID','default'); p='.vg/active-runs/'+sid+'.json'; print(json.load(open(p))['run_id']) if os.path.exists(p) else (json.load(open('.vg/current-run.json'))['run_id'] if os.path.exists('.vg/current-run.json') else '')" 2>/dev/null || echo "")
GUARD_PLAN=""
if [ -n "$RUN_ID" ]; then
  mkdir -p ".vg/runs/${RUN_ID}" 2>/dev/null
  GUARD_PLAN=".vg/runs/${RUN_ID}/.wave-spawn-plan.json"
fi

PYTHONIOENCODING=utf-8 GUARD_PLAN_OUT="$GUARD_PLAN" ${PYTHON_BIN} - <<PY > "$SPAWN_PLAN"
import json, os, sys
wave_files = """$(printf '%s\n' "${WAVE_FILES[@]}")"""
wave_deps = """$(printf '%s\n' "${WAVE_DEPS[@]}")"""
pairs = [line.split(':', 1) for line in wave_files.strip().split('\n') if ':' in line]
file_to_tasks = {}
for t, f in pairs:
    try:
        file_to_tasks.setdefault(f, []).append(int(t))
    except ValueError:
        pass
seq_groups = [sorted(set(tasks)) for tasks in file_to_tasks.values() if len(tasks) >= 2]
seq_flat = {t for grp in seq_groups for t in grp}
all_tasks = []
for t, _ in pairs:
    try:
        all_tasks.append(int(t))
    except ValueError:
        pass
parallel = sorted(set(all_tasks) - seq_flat)

# R6 Task 15 — parse WAVE_DEPS into dag_edges {downstream-task-id: [upstream-task-ids]}
dag_edges = {}
for line in wave_deps.strip().split('\n'):
    if ':' not in line:
        continue
    downstream, upstream_csv = line.split(':', 1)
    downstream = downstream.strip()
    upstreams = [u.strip() for u in upstream_csv.split(',') if u.strip()]
    if downstream and upstreams:
        dag_edges[downstream] = upstreams

plan = {
    "wave": "${N:-unknown}",
    "parallel": parallel,
    "sequential_groups": seq_groups,
    "conflict_files": sorted(set(f for f, tasks in file_to_tasks.items() if len(tasks) >= 2)),
    "dag_edges": dag_edges,
}
print(json.dumps(plan, indent=2))

# Write guard-schema variant (when RUN_ID resolves) — locked contract:
# `expected` is the full ordered task-NN list (parallel first, then each
# sequential group's tasks in order). The guard pops from `remaining[]`
# per spawn and asserts `spawned == expected` at wave Stop hook.
# R6 Task 15 — `dag_edges` mirrored into guard schema so spawn-guard's
# _enforce_dag_dependencies() can pre-spawn block tasks whose upstream
# deps haven't committed yet (no fingerprint on disk).
guard_out = os.environ.get("GUARD_PLAN_OUT") or ""
if guard_out:
    expected_ids = [f"task-{n:02d}" for n in parallel]
    for grp in seq_groups:
        expected_ids.extend(f"task-{n:02d}" for n in grp)
    guard_plan = {
        "wave_id": ${N:-0},
        "expected": expected_ids,
        "dag_edges": dag_edges,
    }
    with open(guard_out, "w", encoding="utf-8") as fh:
        json.dump(guard_plan, fh, indent=2)
PY

echo "✓ Wave ${N} spawn plan (R5 phase-local): $SPAWN_PLAN"
[ -n "$GUARD_PLAN" ] && echo "✓ Wave ${N} spawn plan (guard schema): $GUARD_PLAN"
```

**SPAWN PLAN ENFORCEMENT (orchestrator MUST follow):**

Read `${PHASE_DIR}/.wave-spawn-plan.json` and spawn in 2 groups:
1. **`parallel[]`** — spawn `vg-build-task-executor` for every task in
   ONE assistant message (multiple Agent tool calls in the same turn).
   Wait for all returns before next message.
2. **`sequential_groups[][]`** — within each inner group, spawn one
   task, wait for return, then spawn next.

```
Example plan:
{
  "parallel": [1, 2, 5],
  "sequential_groups": [[3, 4], [6, 7, 8]]
}
Spawn order:
  Message 1: Agent(task 1) + Agent(task 2) + Agent(task 5)   # parallel batch
  Message 2: Agent(task 3), wait, Agent(task 4)             # group [3,4] serial
  Message 3: Agent(task 6), wait, Agent(task 7), wait, Agent(task 8)   # group [6,7,8] serial
```

Step 8d (post-spawn) compares `.build-progress.json` timestamps vs
plan. If `sequential_groups` overlap (parallel execution) → R5
violation, BLOCK wave.

### Step 7 — Materialize per-task capsules via `pre-executor-check.py`

For EACH task in the wave (parallel or sequential), run
`pre-executor-check.py` to write the per-task capsule that the spawn-guard
validates BEFORE allowing the Agent tool call:

```bash
# Record task as in-flight BEFORE Agent() spawn (compact-safe)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
vg_build_progress_start_task "$PHASE_DIR" "$TASK_NUM" "pending-agent"

# Materialize capsule — pre-executor-check.py is the deterministic
# producer of .task-capsules/task-${N}.capsule.json. The PreToolUse Agent
# hook (vg-agent-spawn-guard, Task 1 commit 6135701) BLOCKS spawn when
# this capsule file is missing on disk.
# Canonical path per build.md HARD-GATE + waves-delegation.md envelope:
#   ${PHASE_DIR}/.task-capsules/task-${N}.capsule.json
TASK_CAPSULE_DIR="${PHASE_DIR}/.task-capsules"
mkdir -p "$TASK_CAPSULE_DIR" 2>/dev/null
TASK_CAPSULE_PATH="${TASK_CAPSULE_DIR}/task-${TASK_NUM}.capsule.json"
CONTEXT_JSON=$(${PYTHON_BIN} .claude/scripts/pre-executor-check.py \
  --phase-dir "${PHASE_DIR}" \
  --task-num ${TASK_NUM} \
  --config .claude/vg.config.md \
  --capsule-out "$TASK_CAPSULE_PATH")

# Bug E (Codex P1) 2026-05-04 — capsule double-load fix.
#
# The canonical capsule lives at "$TASK_CAPSULE_PATH" on disk. The subagent
# reads it via `@${capsule_path}` reference in waves-delegation.md (line ~137).
# Previously this block extracted 11 bash variables from CONTEXT_JSON via
# Python one-liners (TASK_CONTEXT, CONTRACT_CONTEXT, GOALS_CONTEXT,
# TASK_CONTEXT_CAPSULE, etc.) for "spawn payload substitution" — but
# delegation.md template never substituted them. Audit confirmed 9/11 vars
# were dead code: ~3-5K tokens of redundant subprocess output per task,
# multiplied by task count (Phase 4.2 = 26 tasks → 80-130K tokens wasted).
#
# Only DESIGN_IMAGE_PATHS + DESIGN_IMAGE_REQUIRED are needed downstream
# for the L1 design-pixel gate (Step 8 below).
DESIGN_IMAGE_PATHS=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('design_image_paths', []) or []))")
DESIGN_IMAGE_REQUIRED=$(echo "$CONTEXT_JSON" | ${PYTHON_BIN} -c "import sys,json; print('1' if json.load(sys.stdin).get('design_image_required') else '0')")
```

### Step 8 — L1 design-pixel gate (per task with `<design-ref>`)

```bash
if [ "$DESIGN_IMAGE_REQUIRED" = "1" ]; then
  if [ -z "$DESIGN_IMAGE_PATHS" ]; then
    echo "⛔ L1 design-pixel gate: task ${TASK_NUM} declares <design-ref> but no PNG resolved." >&2
    echo "   Likely cause: slug missing from manifest. Run: /vg:design-extract --refresh" >&2
    if [[ ! "$ARGUMENTS" =~ --skip-design-pixel-gate ]]; then exit 1; fi
    # R2 round-3 (A5) — declared forbidden flag must emit override.used.
    # Hard-block when no operator-provided --override-reason: cmd_override
    # rejects autogenerated reasons (no resolvable ticket/URL/SHA), and the
    # autogenerated string was being silently swallowed by `2>&1 || echo` —
    # so override.used was never logged → run-complete saw a forbidden flag
    # without a closure event → false-positive proceed. Fail closed instead.
    OVERRIDE_REASON=""
    if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
      OVERRIDE_REASON="${BASH_REMATCH[1]}"
    fi
    if [ -z "$OVERRIDE_REASON" ]; then
      echo "⛔ --skip-design-pixel-gate requires --override-reason=<ticket-or-URL-or-SHA>." >&2
      echo "   Reason: forbidden_without_override contract requires a real audit trail." >&2
      echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-design-pixel-gate --override-reason=\"<issue-id>: PNG slug unresolved task-${TASK_NUM}\"" >&2
      exit 1
    fi
    if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag=--skip-design-pixel-gate \
      --reason="build.l1-design-pixel task-${TASK_NUM} ${OVERRIDE_REASON} — PNG slug unresolved from manifest; executor proceeding blind ts=$(date -u +%FT%TZ); see ${PHASE_DIR}/build-state.log"; then
      echo "⛔ vg-orchestrator override emit FAILED for --skip-design-pixel-gate — refusing silent skip." >&2
      exit 1
    fi
    echo "⚠ --skip-design-pixel-gate set — executor will be blind to layout." >&2
  else
    L1_MISSING=""
    while IFS= read -r p; do
      [ -z "$p" ] && continue
      [ ! -f "$p" ] && L1_MISSING="${L1_MISSING}\n  - ${p}"
    done <<< "$DESIGN_IMAGE_PATHS"
    if [ -n "$L1_MISSING" ]; then
      echo -e "⛔ L1 design-pixel gate: required PNG(s) missing on disk:${L1_MISSING}" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-design-pixel-gate ]]; then exit 1; fi
      # R2 round-3 (A5) — second skip path (PNG missing on disk).
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-design-pixel-gate requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-design-pixel-gate --override-reason=\"<issue-id>: PNG missing on disk task-${TASK_NUM}\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-design-pixel-gate \
        --reason="build.l1-design-pixel task-${TASK_NUM} ${OVERRIDE_REASON} — PNG missing on disk (paths logged) ts=$(date -u +%FT%TZ); see ${PHASE_DIR}/build-state.log"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-design-pixel-gate — refusing silent skip." >&2
        exit 1
      fi
    else
      L1_COUNT=$(printf '%s\n' "$DESIGN_IMAGE_PATHS" | grep -c .)
      echo "✓ L1 design-pixel gate: ${L1_COUNT} PNG(s) verified on disk for task ${TASK_NUM}"
      if type -t emit_telemetry_v2 >/dev/null 2>&1; then
        emit_telemetry_v2 "build_l1_design_pixel" "${PHASE_NUMBER}" "build.8c" \
          "design_pixel_verified" "PASS" "{\"task\":${TASK_NUM},\"png_count\":${L1_COUNT}}"
      fi
    fi
  fi
fi
```

### Step 9 — Capsule existence gate (HARD BLOCK)

This is the spawn-guard's dependency. Without a capsule on disk, the
PreToolUse Agent hook denies the spawn — surface that locally so the
build fails fast instead of waiting for the deny message:

```bash
if [ ! -s "$TASK_CAPSULE_PATH" ]; then
  echo "⛔ Task context capsule missing for task ${TASK_NUM}: $TASK_CAPSULE_PATH" >&2
  echo "   pre-executor-check.py must write this before spawning. Do not spawn with ad-hoc context." >&2
  exit 1
fi
```

---

## Spawn site (8c spawn block)

For the `parallel[]` task list from `.wave-spawn-plan.json`, in a SINGLE
assistant message the orchestrator emits:

```bash
bash scripts/vg-narrate-spawn.sh vg-build-task-executor spawning "task-${N} wave-${W}"
```

then calls (one Agent tool per task, all in the same assistant turn):

```
Agent(subagent_type="vg-build-task-executor", prompt=<rendered from waves-delegation.md template>)
```

> **Tier 2 D — JSON Schema soft enforcement (future):** when the Claude
> Code Agent tool exposes `--json-schema` for subagent invocation, the
> spawn above SHOULD pass
> `--json-schema=.claude/schemas/vg-build-task-executor-return.v1.json`
> (the schema is committed today; spawn-site adoption is gated on Agent
> tool support). The schema enforces the return-JSON contract at the
> subagent layer — invalid output triggers automatic retry instead of
> falling through to the orchestrator's post-spawn validators. Hard
> enforcement deferred to a follow-up; current spawn sites continue to
> rely on post-spawn output validation.

After each subagent returns, the orchestrator narrates the outcome:

```bash
# On success
bash scripts/vg-narrate-spawn.sh vg-build-task-executor returned "task-${N} commit ${SHA}"

# On failure (subagent returned error JSON)
bash scripts/vg-narrate-spawn.sh vg-build-task-executor failed "task-${N}: <one-line cause>"
```

Read `waves-delegation.md` for the EXACT input envelope, prompt
template, and output JSON contract.

### Codex runtime spawn path

If the runtime is Codex, apply
`commands/vg/_shared/codex-spawn-contract.md` instead of calling the
Claude-only `Agent(...)` syntax. For every task in `parallel[]` or
`sequential_groups[][]`:

1. Render the `waves-delegation.md` prompt into
   `${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/wave-${W}/task-${N}.prompt.md`.
2. Run `codex-spawn.sh --tier executor --sandbox workspace-write
   --spawn-role vg-build-task-executor --task-id task-${N} --wave ${W}` with
   `--out ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/codex-spawns/wave-${W}/task-${N}.json`.
3. Keep the same pre/post `vg-narrate-spawn.sh` calls.
4. Treat non-zero exit, empty output, malformed JSON, or missing task
   commit evidence as a HARD BLOCK.

For `parallel[]`, Codex may start independent `codex-spawn.sh` processes in
the background and `wait` for all. For `sequential_groups[][]`, Codex MUST
wait for each task before starting the next. Do NOT execute wave tasks inline
on Codex.

For `sequential_groups[][]`, repeat the narrate→spawn→narrate cycle one
task at a time, waiting for each return before the next spawn.

**WAVE_CONTEXT block also injected into each spawn:** the orchestrator
reads `${PHASE_DIR}/wave-${N}-context.md` (written in Step 2 above) and
includes it in the rendered prompt — this is how parallel wave-mates
align field names. See waves-delegation.md prompt template for the
literal injection point.

---

## Post-spawn aggregation (8d)

**⛔ MANDATORY — orchestrator MUST run ALL steps below after EVERY wave.
Skipping = build on broken code.**

After ALL N subagents return (across both `parallel` and
`sequential_groups`), validate spawn-budget contract before any gate
runs (R5 spawn-count check enforced by spawn-guard's Stop hook check —
Task 1 commit `6135701`).

### 8d.0 — R5 spawn plan honor check (MANDATORY, run FIRST)

Verify orchestrator honored `.wave-spawn-plan.json` —
`sequential_groups` must have run one-at-a-time (no timestamp overlap).
If violated → commit race likely → BLOCK before commit count check
masks the issue.

```bash
SPAWN_PLAN_FILE="${PHASE_DIR}/.wave-spawn-plan.json"
PROGRESS_FILE="${PHASE_DIR}/.build-progress.json"

if [ -f "$SPAWN_PLAN_FILE" ] && [ -f "$PROGRESS_FILE" ]; then
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN} - "$SPAWN_PLAN_FILE" "$PROGRESS_FILE" <<'PY'
import json, sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
progress = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))

tasks_info = {}
for t in progress.get('tasks', []):
    try:
        tid = int(t.get('task_num', 0))
    except (TypeError, ValueError):
        continue
    tasks_info[tid] = {
        'started_at': t.get('started_at') or '',
        'finished_at': t.get('finished_at') or '',
    }

seq_groups = plan.get('sequential_groups') or []
if not seq_groups:
    print("✓ R5 check: no sequential groups in this wave (all parallel)")
    sys.exit(0)

violations = []
for group in seq_groups:
    with_ts = [(t, tasks_info.get(t, {})) for t in group]
    with_ts = [(t, info) for t, info in with_ts if info.get('started_at')]
    if len(with_ts) < 2:
        continue
    with_ts.sort(key=lambda x: x[1]['started_at'])
    for i in range(len(with_ts) - 1):
        t_curr, info_curr = with_ts[i]
        t_next, info_next = with_ts[i+1]
        curr_end = info_curr.get('finished_at') or ''
        next_start = info_next.get('started_at') or ''
        if curr_end and next_start and next_start < curr_end:
            violations.append(
                f"Tasks {t_curr} + {t_next} overlapped: "
                f"task-{t_curr} finished={curr_end}, task-{t_next} started={next_start}"
            )

if violations:
    print(f"⛔ R5 VIOLATION: {len(violations)} sequential group(s) ran in PARALLEL despite spawn plan:")
    for v in violations:
        print(f"   - {v}")
    sys.exit(1)
else:
    print(f"✓ R5 check: all {len(seq_groups)} sequential group(s) ran one-at-a-time")
PY

  R5_RC=$?
  if [ "$R5_RC" != "0" ]; then
    echo "R5-violation wave=${N} phase=${PHASE_NUMBER} at=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
    if [[ "$ARGUMENTS" =~ --allow-r5-violation ]]; then
      # R2 round-3 (A5) — emit canonical override.used so run-complete's
      # forbidden_without_override check (build.md frontmatter) clears.
      # Hard-block when no operator --override-reason: cmd_override rejects
      # autogenerated reasons.
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --allow-r5-violation requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --allow-r5-violation --override-reason=\"<issue-id>: R5 breach wave-${N} accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--allow-r5-violation \
        --reason="build.r5-violation wave-${N} ${OVERRIDE_REASON} — sequential group ran in parallel, commit race possible (operator-accepted at $(date -u +%FT%TZ); ref build-state.log)"; then
        echo "⛔ vg-orchestrator override emit FAILED for --allow-r5-violation — refusing silent skip." >&2
        exit 1
      fi
      type -t log_override_debt >/dev/null 2>&1 && \
        log_override_debt "build-r5-violation" "${PHASE_NUMBER}" "sequential group ran in parallel, commit race possible" "$PHASE_DIR"
      echo "⚠ --allow-r5-violation set — proceeding despite R5 breach, logged to debt register."
    else
      exit 1
    fi
  fi
fi
```

### 8d.1 — Commit count audit + spawn-budget validation (MANDATORY)

After all wave agents complete, count commits since wave tag. Each task
MUST produce exactly 1 commit. The spawn-guard's Stop hook ALSO checks
`spawned == expected`; this gate provides the orchestrator-side
correlation with git log.

```bash
WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"
EXPECTED_COMMITS=${#WAVE_TASKS[@]}
ACTUAL_COMMITS=$(git log --oneline "${WAVE_TAG}..HEAD" | wc -l | tr -d ' ')

# Sync progress file with actual git log (compact-safe).
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/build-progress.sh"
while IFS= read -r line; do
  sha="${line%% *}"
  subject="${line#* }"
  if [[ "$subject" =~ ^[a-z]+\([0-9]+(\.[0-9]+)*-([0-9]+)\): ]]; then
    tnum="${BASH_REMATCH[2]}"
    vg_build_progress_commit_task "$PHASE_DIR" "$tnum" "$sha"
  fi
done < <(git log --format='%H %s' "${WAVE_TAG}..HEAD" 2>/dev/null)

# Mark expected-but-missing tasks as failed
for task_num in "${WAVE_TASKS[@]}"; do
  if ! git log --oneline "${WAVE_TAG}..HEAD" | grep -q "${PHASE_NUMBER}-$(printf '%02d' $task_num)"; then
    vg_build_progress_fail_task "$PHASE_DIR" "$task_num" "no-commit-found"
  fi
done

if [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]; then
  echo "⛔ COMMIT MISMATCH: wave ${N} expected ${EXPECTED_COMMITS} commits, got ${ACTUAL_COMMITS}"
  MISSING_TASKS=""
  for task_num in "${WAVE_TASKS[@]}"; do
    if ! git log --oneline "${WAVE_TAG}..HEAD" | grep -q "${PHASE_NUMBER}-$(printf '%02d' $task_num)"; then
      echo "  - Task ${task_num}: NO COMMIT FOUND"
      MISSING_TASKS="${MISSING_TASKS} ${task_num}"
    fi
  done

  # Tightened 2026-04-17: silent agent failure = silent bad wave.
  # Block-resolver L1 attempts re-dispatch; if still short → exit 1.
  if [[ "$ARGUMENTS" =~ --allow-missing-commits ]]; then
    RATGUARD_RESULT=$(rationalization_guard_check "wave-commits" \
      "Gate blocks wave if commits < tasks. Silent agent failures cause broken waves if bypassed without concrete reason." \
      "missing_tasks=[${MISSING_TASKS}] user_arg=--allow-missing-commits")
    if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "wave-commits" "--allow-missing-commits" "$PHASE_NUMBER" "build.wave-${N}" "${MISSING_TASKS}"; then
      exit 1
    fi
    # R2 round-3 (A5) — emit canonical override.used so run-complete clears
    # forbidden_without_override (build.md frontmatter declares this flag).
    OVERRIDE_REASON=""
    if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
      OVERRIDE_REASON="${BASH_REMATCH[1]}"
    fi
    if [ -z "$OVERRIDE_REASON" ]; then
      echo "⛔ --allow-missing-commits requires --override-reason=<ticket-or-URL-or-SHA>." >&2
      echo "   Re-run: /vg:build ${PHASE_NUMBER} --allow-missing-commits --override-reason=\"<issue-id>: wave-${N} commit shortfall accepted\"" >&2
      exit 1
    fi
    if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag=--allow-missing-commits \
      --reason="build.wave-${N} ${OVERRIDE_REASON} — commit shortfall accepted: missing tasks=[${MISSING_TASKS}], expected=${EXPECTED_COMMITS}, actual=${ACTUAL_COMMITS} ts=$(date -u +%FT%TZ); see ${PHASE_DIR}/build-state.log"; then
      echo "⛔ vg-orchestrator override emit FAILED for --allow-missing-commits — refusing silent skip." >&2
      exit 1
    fi
    echo "⚠ --allow-missing-commits set — recording missing tasks and proceeding."
    echo "wave-${N}: MISSING_COMMITS tasks=[${MISSING_TASKS}] allowed-by=--allow-missing-commits ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
  else
    source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
    if type -t block_resolve >/dev/null 2>&1; then
      export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="build.wave-${N}"
      BR_CTX="Wave ${N} expected ${EXPECTED_COMMITS} commits, got ${ACTUAL_COMMITS}. Silent agent failure possible — re-dispatch missing tasks before treating as fatal."
      BR_EV=$(printf '{"expected":%d,"actual":%d,"missing_tasks":"%s","wave":%d}' "$EXPECTED_COMMITS" "$ACTUAL_COMMITS" "${MISSING_TASKS}" "$N")
      BR_CANDS='[{"id":"redispatch-missing","cmd":"echo L1-SAFE: orchestrator would re-dispatch missing tasks via Agent tool; skipping in shell resolver safe mode","confidence":0.55,"rationale":"missing commits usually = transient agent failure, safe to retry once"}]'
      BR_RES=$(block_resolve "wave-commits" "$BR_CTX" "$BR_EV" "$PHASE_DIR" "$BR_CANDS")
      BR_LVL=$(echo "$BR_RES" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
      if [ "$BR_LVL" = "L1" ]; then
        echo "✓ Block resolver L1 re-dispatched missing tasks — re-count commits"
        ACTUAL_COMMITS=$(git log --oneline "${WAVE_TAG}..HEAD" | wc -l | tr -d ' ')
        [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ] && { echo "⛔ Still short after L1 retry ($ACTUAL_COMMITS / $EXPECTED_COMMITS)"; exit 1; }
      elif [ "$BR_LVL" = "L2" ]; then
        block_resolve_l2_handoff "wave-commits" "$BR_RES" "$PHASE_DIR"
        exit 2
      else
        echo "  Fix: re-run missing tasks manually, then /vg:build ${PHASE_NUMBER} --resume"
        exit 1
      fi
    else
      echo "  Fix: re-run missing tasks manually, then /vg:build ${PHASE_NUMBER} --resume"
      exit 1
    fi
  fi
fi
```

### 8d.2 — Commit attribution audit (MANDATORY after count check)

Catches the parallel-executor `.git/index` race (agent A's add lands
before agent B's commit → agent B absorbs A's files silently). Count
passes (N=N), but attribution is corrupted.

```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/override-debt.sh" 2>/dev/null || \
  echo "⚠ override-debt.sh missing — overrides will log to build-state.log only"

ATTR_SCRIPT=".claude/scripts/verify-commit-attribution.py"
if [ -f "$ATTR_SCRIPT" ]; then
  if ! ${PYTHON_BIN:-python} "$ATTR_SCRIPT" \
       --phase-dir "${PHASE_DIR}" \
       --wave-tag "${WAVE_TAG}" \
       --wave-number "${N}" \
       --strict; then
    echo "⛔ Commit attribution violations detected in wave ${N}."
    OVERRIDE_REASON=""
    if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
      OVERRIDE_REASON="${BASH_REMATCH[1]}"
    fi
    if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
      echo "⚠ Attribution gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
      echo "attribution-violations: wave-${N} override=${OVERRIDE_REASON} ts=$(date -u +%FT%TZ)" >> "${PHASE_DIR}/build-state.log"
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--override-reason" "$PHASE_NUMBER" "build.attribution.wave-${N}" "$OVERRIDE_REASON" "build-attribution-wave-${N}"
    else
      exit 1
    fi
  fi
else
  echo "⚠ verify-commit-attribution.py missing — skipping attribution audit (older install)"
fi
```

### 8d.3 — Wave integrity reconciliation (MANDATORY, survives crashes)

Runs `verify-wave-integrity.py` against progress file + git log +
filesystem. Catches crash scenarios where agent work exists on disk but
progress file never recorded it.

```bash
INTEGRITY_SCRIPT=".claude/scripts/verify-wave-integrity.py"
if [ -f "$INTEGRITY_SCRIPT" ]; then
  echo "━━━ Wave ${N} integrity reconciliation ━━━"
  ${PYTHON_BIN:-python3} "$INTEGRITY_SCRIPT" \
    --phase-dir "${PHASE_DIR}" --wave "${N}" --repo-root "${REPO_ROOT:-.}"
  INTEG_EXIT=$?
  case "$INTEG_EXIT" in
    0) echo "✓ Integrity verdict: clean" ;;
    *)
      echo "⛔ Integrity verdict: corruption detected (exit ${INTEG_EXIT})."
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -n "$OVERRIDE_REASON" ] && [ ${#OVERRIDE_REASON} -ge 4 ]; then
        echo "⚠ Integrity gate OVERRIDDEN (reason: $OVERRIDE_REASON)"
        type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
          "--override-reason" "$PHASE_NUMBER" "build.integrity.wave-${N}" "$OVERRIDE_REASON" "build-integrity-wave-${N}"
      else
        exit 1
      fi
      ;;
  esac
fi
```

### 8d.4 — UI-MAP + design-ref injection audit (Phase 15 D-12a)

Audits the executor prompts persisted at spawn time to confirm BOTH
`## UI-MAP-SUBTREE-FOR-THIS-WAVE` and `## DESIGN-REF` H2 sections were
injected for every UI-touching task.

```bash
INJ_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-uimap-injection.py"
WAVE_PROMPT_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
if [ -x "$INJ_VAL" ] && [ -d "$WAVE_PROMPT_DIR" ]; then
  ${PYTHON_BIN} "$INJ_VAL" --phase "${PHASE_NUMBER}" \
      --prompts-dir "$WAVE_PROMPT_DIR" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-injection-w${N}.json" 2>&1 || true
  IV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-injection-w${N}.json" 2>/dev/null)
  case "$IV" in
    PASS|WARN) echo "✓ D-12a UI-MAP+design-ref injection audit: $IV" ;;
    BLOCK)
      echo "⛔ D-12a injection audit: BLOCK — see ${VG_TMP}/uimap-injection-w${N}.json" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-uimap-injection-audit ]]; then exit 1; fi
      # R2 round-3 (A5) — declared forbidden flag must emit override.used.
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-uimap-injection-audit requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-uimap-injection-audit --override-reason=\"<issue-id>: D-12a wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-uimap-injection-audit \
        --reason="build.uimap-injection wave-${N} ${OVERRIDE_REASON} — D-12a BLOCK accepted ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/uimap-injection-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-uimap-injection-audit — refusing silent skip." >&2
        exit 1
      fi
      ;;
    *) echo "ℹ D-12a injection audit: $IV" ;;
  esac
fi
```

### 8d.5 — Task fidelity audit (Phase 16 D-06)

Post-spawn 3-way hash audit: re-extracted PLAN task block vs `.meta.json`
sidecar vs `.body.md` prompt body. Detects orchestrator paraphrase /
truncation of task body.

```bash
TF_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-task-fidelity.py"
WAVE_PROMPT_DIR="${PHASE_DIR}/.build/wave-${N}/executor-prompts"
if [ -x "$TF_VAL" ] && [ -d "$WAVE_PROMPT_DIR" ]; then
  ${PYTHON_BIN} "$TF_VAL" --phase "${PHASE_NUMBER}" \
      --prompts-dir "$WAVE_PROMPT_DIR" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-fidelity-w${N}.json" 2>&1 || true
  TFV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-fidelity-w${N}.json" 2>/dev/null)
  case "$TFV" in
    PASS|WARN) echo "✓ D-06 task fidelity audit: $TFV" ;;
    BLOCK)
      echo "⛔ D-06 task fidelity audit: BLOCK — orchestrator likely paraphrased task body" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-task-fidelity-audit ]]; then exit 1; fi
      # R2 round-3 (A5) — declared forbidden flag must emit override.used.
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-task-fidelity-audit requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-task-fidelity-audit --override-reason=\"<issue-id>: D-06 wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-task-fidelity-audit \
        --reason="build.task-fidelity wave-${N} ${OVERRIDE_REASON} — D-06 BLOCK accepted: orchestrator paraphrase tolerated ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/task-fidelity-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-task-fidelity-audit — refusing silent skip." >&2
        exit 1
      fi
      ;;
    *) echo "ℹ D-06 task fidelity audit: $TFV" ;;
  esac
fi
```

### 8d.5b — TDD evidence audit (R6 Task 9)

Post-spawn TDD discipline check: for each task with capsule
`tdd_required=true`, verify both red + green test-evidence files exist
under `${PHASE_DIR}/.test-evidence/`, with red.exit_code != 0,
green.exit_code == 0, and red.captured_at < green.captured_at.
Tasks with `tdd_required` false/missing are skipped (back-compat).

```bash
TDD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-tdd-evidence.py"
if [ -x "$TDD_VAL" ]; then
  ${PYTHON_BIN} "$TDD_VAL" --phase "${PHASE_NUMBER}" --wave-id "${N}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/tdd-evidence-w${N}.json" 2>&1 || true
  TDDV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/tdd-evidence-w${N}.json" 2>/dev/null)
  case "$TDDV" in
    PASS|WARN) echo "✓ R6 Task 9 TDD evidence audit: $TDDV" ;;
    BLOCK)
      echo "⛔ R6 Task 9 TDD evidence audit: BLOCK — task with tdd_required=true is missing red/green evidence, has wrong exit codes, or wrong temporal order" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-tdd-evidence ]]; then exit 1; fi
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-tdd-evidence requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-tdd-evidence --override-reason=\"<issue-id>: R6 Task 9 wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-tdd-evidence \
        --reason="build.tdd-evidence wave-${N} ${OVERRIDE_REASON} — R6 Task 9 BLOCK accepted: TDD red/green evidence gap tolerated ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/tdd-evidence-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-tdd-evidence — refusing silent skip." >&2
        exit 1
      fi
      ;;
    *) echo "ℹ R6 Task 9 TDD evidence audit: $TDDV" ;;
  esac
fi
```

### 8d.5c — RCRURD implementation audit (R7 Task 3 — G1)

Heuristic post-spawn check that handler implementations honor RCRURD
invariants (Read-After-Create / Update / Delete + error-shape contracts).
Pairs with R7 Task 2 (G7 — `yaml-rcrurd` inline fence source unification).

The validator scans each task capsule with non-empty
`rcrurd_invariants_paths[]`, parses the per-goal yaml, and grep-audits
the handler files in `BUILD-LOG/task-NN.md`'s `Files modified` list:

  - DELETE invariants → expect 404 / NotFoundError marker. WARN on
    miss; BLOCK on contradiction (handler hardcodes status 200 on the
    not-found branch).
  - POST/PUT/PATCH invariants → expect a leaf field from `assert[].path`
    to appear in modified handler text. WARN on miss.
  - Malformed yaml → WARN (graceful degradation, no crash).

Static analysis cannot prove invariant compliance — this gate is
heuristic. WARN does NOT stop the wave; only BLOCK rc=1 halts.

```bash
RCRURD_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-rcrurd-implementation.py"
if [ -x "$RCRURD_VAL" ]; then
  ${PYTHON_BIN} "$RCRURD_VAL" --phase "${PHASE_NUMBER}" --wave-id "${N}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurd-implementation-w${N}.json" 2>&1 || true
  RCRURDV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurd-implementation-w${N}.json" 2>/dev/null)
  case "$RCRURDV" in
    PASS|WARN) echo "✓ R7 Task 3 RCRURD implementation audit: $RCRURDV" ;;
    BLOCK)
      echo "⛔ R7 Task 3 RCRURD implementation audit: BLOCK — handler implementation contradicts RCRURD invariant (e.g. DELETE goal asserts 404 but handler hardcodes 200)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-rcrurd-implementation-audit ]]; then exit 1; fi
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-rcrurd-implementation-audit requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-rcrurd-implementation-audit --override-reason=\"<issue-id>: R7 Task 3 wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-rcrurd-implementation-audit \
        --reason="build.rcrurd-implementation wave-${N} ${OVERRIDE_REASON} — R7 Task 3 BLOCK accepted: RCRURD invariant contradiction tolerated ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/rcrurd-implementation-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-rcrurd-implementation-audit — refusing silent skip." >&2
        exit 1
      fi
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--skip-rcrurd-implementation-audit" "$PHASE_NUMBER" "build.rcrurd-implementation.wave-${N}" "$OVERRIDE_REASON" "build-rcrurd-implementation-audit-skipped"
      ;;
    *) echo "ℹ R7 Task 3 RCRURD implementation audit: $RCRURDV" ;;
  esac
fi
```

### 8d.5d — Workflow implementation audit (R7 Task 4 — G2)

Heuristic post-spawn check that handler implementations actually
transition to the state declared by WORKFLOW-SPECS state_machine.
Pairs with R7 Task 5 (G9 — review replay of workflow runtime probe).

Codex audit failure mode (G2): Blueprint generates
WORKFLOW-SPECS/<WF-NN>.md (multi-actor flows: actor A → state X →
actor B → state Y). Build inject context to executor via
capsule.workflow_id + workflow_step BUT does NOT verify implementation
actually transitions state. Build typecheck/tests pass while the task
implements `approved` instead of `pending_admin_review`. Review may
catch via runtime probe — but late.

The validator scans each task capsule with non-null `workflow_id` AND
`workflow_step`, parses WORKFLOW-SPECS/<wf>.md state_machine to
resolve the expected `state_after` literal for that step, and
grep-audits the modified files in BUILD-LOG/task-NN.md:

  - PASS: state literal found in handler / route / state / store /
    reducer / service file (modified).
  - WARN: state literal found ONLY in *.spec.ts / *.test.ts files —
    test asserts the state but production code never writes it.
  - WARN: malformed WORKFLOW-SPECS yaml (graceful degradation).
  - BLOCK: workflow_id declared but expected state literal NOT found
    in ANY modified file. Strong signal of spec/impl divergence.

Static analysis cannot prove state-machine correctness — this gate is
heuristic. WARN does NOT stop the wave; only BLOCK rc=1 halts.

```bash
WFIMPL_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-workflow-implementation.py"
if [ -x "$WFIMPL_VAL" ]; then
  ${PYTHON_BIN} "$WFIMPL_VAL" --phase "${PHASE_NUMBER}" --wave-id "${N}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/workflow-implementation-w${N}.json" 2>&1 || true
  WFIMPLV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/workflow-implementation-w${N}.json" 2>/dev/null)
  case "$WFIMPLV" in
    PASS|WARN) echo "✓ R7 Task 4 workflow implementation audit: $WFIMPLV" ;;
    BLOCK)
      echo "⛔ R7 Task 4 workflow implementation audit: BLOCK — handler does not implement WORKFLOW-SPECS state transition (e.g. capsule says step expects pending_admin_review but no modified file contains that literal)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-workflow-implementation-audit ]]; then exit 1; fi
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-workflow-implementation-audit requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-workflow-implementation-audit --override-reason=\"<issue-id>: R7 Task 4 wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-workflow-implementation-audit \
        --reason="build.workflow-implementation wave-${N} ${OVERRIDE_REASON} — R7 Task 4 BLOCK accepted: workflow state literal divergence tolerated ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/workflow-implementation-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-workflow-implementation-audit — refusing silent skip." >&2
        exit 1
      fi
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--skip-workflow-implementation-audit" "$PHASE_NUMBER" "build.workflow-implementation.wave-${N}" "$OVERRIDE_REASON" "build-workflow-implementation-audit-skipped"
      ;;
    *) echo "ℹ R7 Task 4 workflow implementation audit: $WFIMPLV" ;;
  esac
fi
```

### 8d.5e — Edge-case implementation coverage audit (R7 Task 7 — G3)

Build-time gate verifying executor honored the `// vg-edge-case: <variant_id>`
marker contract from `waves-delegation.md` lines 152-159. Sister to 8d.5c
(RCRURD) and 8d.5d (workflow) — same canonical override pattern.

Codex audit failure mode (G3): Blueprint generated EDGE-CASES per profile
(e.g. `G-04-b1` empty-domain → 400, `G-04-a1` tenant-boundary). The
delegation prompt instructed the executor to add `// vg-edge-case:
<variant_id>` comments at the relevant code site so coverage is auditable.
But before R7 Task 7 there was NO build-side gate verifying these markers
landed — `verify-edge-cases-contract.py` validates the artifact STRUCTURE
(variant_id format, count budget), NOT implementation coverage.

The validator scans each task capsule with non-empty `edge_cases_for_goals[]`,
parses the per-goal EDGE-CASES variant table (variant_id + priority), and
grep-audits the modified files in BUILD-LOG/task-NN.md:

  - PASS: every critical variant has a `vg-edge-case:` marker, AND
    high-priority coverage ≥ 80%.
  - WARN: high-priority coverage < 80% (commonly framework-handled edges)
    OR stale capsule referencing a pruned per-goal file (graceful
    degradation, no crash).
  - BLOCK: any critical variant has no marker in any modified file.
    Critical-only-on-BLOCK is intentional: critical variants are auth /
    data-integrity / cross-tenant boundary cases — a missing marker
    means the executor likely skipped a security-relevant code path.

Static analysis cannot prove edge coverage without symbolic execution —
this gate is heuristic. WARN does NOT stop the wave; only BLOCK rc=1 halts.

```bash
EDGEV_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-edge-case-coverage.py"
if [ -x "$EDGEV_VAL" ]; then
  ${PYTHON_BIN} "$EDGEV_VAL" --phase "${PHASE_NUMBER}" --wave-id "${N}" \
      > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/edge-case-coverage-w${N}.json" 2>&1 || true
  EDGEV=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
       "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/edge-case-coverage-w${N}.json" 2>/dev/null)
  case "$EDGEV" in
    PASS|WARN) echo "✓ R7 Task 7 edge-case coverage audit: $EDGEV" ;;
    BLOCK)
      echo "⛔ R7 Task 7 edge-case coverage audit: BLOCK — critical edge-case variant has no \`// vg-edge-case: <variant_id>\` marker in modified files (likely missing code path for auth / data-integrity edge)" >&2
      if [[ ! "$ARGUMENTS" =~ --skip-edge-case-coverage-audit ]]; then exit 1; fi
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --skip-edge-case-coverage-audit requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --skip-edge-case-coverage-audit --override-reason=\"<issue-id>: R7 Task 7 wave-${N} BLOCK accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--skip-edge-case-coverage-audit \
        --reason="build.edge-case-coverage wave-${N} ${OVERRIDE_REASON} — R7 Task 7 BLOCK accepted: missing critical edge-case marker tolerated ts=$(date -u +%FT%TZ); see ${VG_TMP:-${PHASE_DIR}/.vg-tmp}/edge-case-coverage-w${N}.json"; then
        echo "⛔ vg-orchestrator override emit FAILED for --skip-edge-case-coverage-audit — refusing silent skip." >&2
        exit 1
      fi
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--skip-edge-case-coverage-audit" "$PHASE_NUMBER" "build.edge-case-coverage.wave-${N}" "$OVERRIDE_REASON" "build-edge-case-coverage-audit-skipped"
      ;;
    *) echo "ℹ R7 Task 7 edge-case coverage audit: $EDGEV" ;;
  esac
fi
```

### 8d.6 — Post-wave gate matrix (typecheck/build/test/contract/goals/utility)

Run gates 1-5 in order, BLOCK on first failure. Adaptive typecheck
auto-selects full vs narrow per package size + OOM history.

```bash
WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"
FAILED_GATE=""

# Gate 1: Typecheck (mandatory, adaptive per-package)
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/typecheck-light.sh" 2>/dev/null || true
if type -t vg_typecheck_adaptive >/dev/null 2>&1; then
  WAVE_PKGS=$(git diff --name-only "${WAVE_TAG}" HEAD -- 'apps/*/src/**' 'packages/*/src/**' 2>/dev/null \
    | sed -E 's|^(apps\|packages)/([^/]+)/.*|\2|' | sort -u)
  GATE1_FAIL=0
  for pkg in $WAVE_PKGS; do
    vg_typecheck_adaptive "$pkg" "${WAVE_TAG}" || GATE1_FAIL=$((GATE1_FAIL + 1))
  done
  [ "$GATE1_FAIL" -gt 0 ] && FAILED_GATE="typecheck"
else
  TYPECHECK_CMD=$(vg_config_get build_gates.typecheck_cmd "")
  [ -n "$TYPECHECK_CMD" ] && ! eval "$TYPECHECK_CMD" && FAILED_GATE="typecheck"
fi

# Gate 2: Build
if [ -z "$FAILED_GATE" ]; then
  BUILD_CMD=$(vg_config_get build_gates.build_cmd "")
  [ -n "$BUILD_CMD" ] && ! eval "$BUILD_CMD" && FAILED_GATE="build"
fi

# Gate 3: Unit tests (affected only)
if [ -z "$FAILED_GATE" ]; then
  UNIT_CMD=$(vg_config_get build_gates.test_unit_cmd "")
  UNIT_REQ=$(vg_config_get build_gates.test_unit_required "true")
  # ... [auto-detect from package.json + first-time bootstrap leniency,
  #     block-resolver handoff if test_unit_required=true + missing] ...
  if [ -n "$UNIT_CMD" ]; then
    CHANGED=$(git diff --name-only "${WAVE_TAG}" HEAD -- 'apps/**/src/**' 'packages/**/src/**' 2>/dev/null || true)
    AFFECTED_TESTS=""
    for f in $CHANGED; do
      MOD=$(dirname "$f")
      AFFECTED_TESTS="$AFFECTED_TESTS $(grep -rl "from.*${MOD}\|require.*${MOD}" \
        --include='*.test.ts' --include='*.test.tsx' \
        --include='*.spec.ts' --include='*.spec.tsx' \
        apps/ packages/ 2>/dev/null || true)"
    done
    AFFECTED_TESTS=$(echo "$AFFECTED_TESTS" | tr ' ' '\n' | sort -u | grep -v '^$' || true)
    if [ -n "$AFFECTED_TESTS" ]; then
      ! eval "$UNIT_CMD $AFFECTED_TESTS" && FAILED_GATE="test_unit"
    fi
  fi
fi

# Gate 4: Contract verify (grep built code vs API-CONTRACTS.md — KEEP-FLAT
# per audit doc line 2427: comment for contract_verify_grep validator,
# deterministic grep, not AI-context read)
if [ -z "$FAILED_GATE" ]; then
  CONTRACT_VERIFY_CMD=$(vg_config_get build_gates.contract_verify_grep "")
  [ -n "$CONTRACT_VERIFY_CMD" ] && ! eval "$CONTRACT_VERIFY_CMD" && FAILED_GATE="contract_verify"
fi

# Gate 5: Goal-test binding (mode: strict | warn | off)
if [ -z "$FAILED_GATE" ]; then
  GTB_MODE=$(vg_config_get build_gates.goal_test_binding "warn")
  if [ "$GTB_MODE" != "off" ]; then
    GTB_ARGS="--phase-dir ${PHASE_DIR} --wave-tag ${WAVE_TAG} --wave-number ${N}"
    [ "$GTB_MODE" = "warn" ] && GTB_ARGS="${GTB_ARGS} --lenient"
    if ! ${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py ${GTB_ARGS}; then
      FAILED_GATE="goal_test_binding"
    fi
  fi
fi

# Gate U: Utility duplication (wave-scope AST scan, threshold-block=3)
if [ -z "$FAILED_GATE" ] && [ -f ".claude/scripts/verify-utility-duplication.py" ]; then
  DUP_PROJECT_MD="${PLANNING_DIR}/PROJECT.md"
  if [ -f "$DUP_PROJECT_MD" ]; then
    ${PYTHON_BIN} .claude/scripts/verify-utility-duplication.py \
      --since-tag "${WAVE_TAG}" --project "$DUP_PROJECT_MD" \
      --repo-root "${REPO_ROOT:-.}" --threshold-block 3 --threshold-warn 2
    case $? in 0) ;; 2) echo "⚠ Utility duplication WARNs logged" ;; 1) FAILED_GATE="utility_duplication" ;; esac
  fi
fi
```

### 8d.7 — Mobile gate matrix (gates 6-10, mobile profiles only)

Fires when `$PROFILE` ∈ {mobile-rn, mobile-flutter, mobile-native-ios,
mobile-native-android, mobile-hybrid}. For web profiles these gates
silently skip.

- Gate 6: `verify-mobile-permissions.py` (iOS plist / Android manifest /
  Expo config)
- Gate 7: `verify-cert-expiry.py` (signing cert warn/block days)
- Gate 8: `verify-privacy-manifest.py` (privacy manifest consistency)
- Gate 9: `verify-native-modules.py` (autolinking / pods / gradle)
- Gate 10: `verify-bundle-size.py` (IPA / APK / AAB MB budget)

Each gate reads its config from `mobile.gates.<gate_name>` in
`.claude/vg.config.md` via the awk parser pattern preserved verbatim
from backup lines 2510-2693. Skipped silently when `enabled != true`.

### 8d.8 — Failure handling (max 2 debugger retries)

If `$FAILED_GATE` set, spawn `general-purpose` agent for debug retries
(allow-list-clean, framework-neutral; previously used gsd-debugger which
borrowed from GSD framework). Operator can also invoke `/vg:debug` interactively.

```
RETRY_COUNT=0
MAX_RETRIES=2

while [ "$FAILED_GATE" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  # R1a UX baseline Req 2 — narrate every Agent() spawn (green pill chip).
  bash scripts/vg-narrate-spawn.sh general-purpose spawning \
    "wave-${N} retry-${RETRY_COUNT}/${MAX_RETRIES} gate=${FAILED_GATE} (debug)"

  Agent(subagent_type="general-purpose", model="${MODEL_DEBUGGER}"):
    prompt: |
      Wave ${N} of phase ${PHASE_NUMBER} failed post-wave gate.
      Failed gate: ${FAILED_GATE}
      Wave tag (rollback point): ${WAVE_TAG}
      Plans executed in wave: ${WAVE_PLAN_LIST}

      Diagnose root cause and apply minimal fix. Commit with prefix
      `fix(${PHASE_NUMBER}-wave-${N}): `.

      Constraints:
      - Do NOT rewrite existing wave commits
      - Do NOT use --no-verify
      - Cite root cause in commit body: "Root cause: <1 sentence>"
      - Re-run failed gate after fix — your fix must make it pass

  # On success the gate re-run below clears FAILED_GATE; otherwise the next
  # loop iteration narrates a new spawning chip. Final outcome (returned vs
  # failed) is narrated AFTER the re-run so operators see whether the
  # debugger actually fixed the gate.

  # Re-run failed gate only
  case "$FAILED_GATE" in
    typecheck) CMD=$(vg_config_get build_gates.typecheck_cmd "") ;;
    build) CMD=$(vg_config_get build_gates.build_cmd "") ;;
    test_unit) CMD=$(vg_config_get build_gates.test_unit_cmd "") ;;
    contract_verify) CMD=$(vg_config_get build_gates.contract_verify_grep "") ;;
    goal_test_binding)
      CMD="${PYTHON_BIN} .claude/scripts/verify-goal-test-binding.py --phase-dir ${PHASE_DIR} --wave-tag ${WAVE_TAG} --wave-number ${N}"
      ;;
    mobile_permissions|cert_expiry|privacy_manifest|native_module_linking|bundle_size)
      # ... mobile-gate-specific re-run command ...
      ;;
  esac

  if eval "$CMD"; then
    FAILED_GATE=""
    echo "Gate recovered after retry ${RETRY_COUNT}."
    bash scripts/vg-narrate-spawn.sh general-purpose returned \
      "wave-${N} retry-${RETRY_COUNT} gate=${FAILED_GATE_PREV:-recovered}"
  else
    bash scripts/vg-narrate-spawn.sh general-purpose failed \
      "wave-${N} retry-${RETRY_COUNT} gate=${FAILED_GATE} still failing"
  fi
done

if [ -n "$FAILED_GATE" ]; then
  # HARD GATE: --override-reason required (≥4 chars), rationalization-guard
  # adjudicates concrete-enough; otherwise BLOCK with rollback fix paths.
  exit 1
fi
```

### 8d.9 — Wave-verify divergence + fixture wave-verify

Spawn isolated subprocess to re-run typecheck/tests/contract scoped to
wave's changed files. Compare with executor's claims in commit messages.
Divergence → rollback wave via `git reset --soft` + set FAILED_GATE.

```bash
if [ -z "$FAILED_GATE" ] && [ "${CONFIG_INDEPENDENT_VERIFY_ENABLED:-true}" = "true" ]; then
  WAVE_TAG="vg-build-${PHASE_NUMBER}-wave-${N}-start"
  VERIFY_OUT=$(${PYTHON_BIN:-python3} \
    .claude/scripts/validators/wave-verify-isolated.py \
    --phase "${PHASE_NUMBER}" --wave-tag "${WAVE_TAG}" 2>&1)
  VERIFY_RC=$?
  if [ "$VERIFY_RC" -ne 0 ]; then
    if [[ "$ARGUMENTS" =~ --allow-verify-divergence ]]; then
      echo "⚠ Wave ${N} verify divergence — OVERRIDE accepted"
      # R2 round-3 (A5) — declared forbidden flag must emit override.used
      # so run-complete's forbidden_without_override check clears.
      OVERRIDE_REASON=""
      if [[ "${ARGUMENTS:-}" =~ --override-reason=([^[:space:]]+) ]]; then
        OVERRIDE_REASON="${BASH_REMATCH[1]}"
      fi
      if [ -z "$OVERRIDE_REASON" ]; then
        echo "⛔ --allow-verify-divergence requires --override-reason=<ticket-or-URL-or-SHA>." >&2
        echo "   Re-run: /vg:build ${PHASE_NUMBER} --allow-verify-divergence --override-reason=\"<issue-id>: wave-${N} verify divergence accepted\"" >&2
        exit 1
      fi
      if ! "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
        --flag=--allow-verify-divergence \
        --reason="build.wave-${N}.verify ${OVERRIDE_REASON} — divergence accepted: executor claim vs isolated subprocess differ ts=$(date -u +%FT%TZ); see wave-verify-isolated.py output (ref ${PHASE_DIR}/build-state.log)"; then
        echo "⛔ vg-orchestrator override emit FAILED for --allow-verify-divergence — refusing silent skip." >&2
        exit 1
      fi
      type -t log_override_debt >/dev/null 2>&1 && log_override_debt \
        "--allow-verify-divergence" "$PHASE_NUMBER" "build.wave-${N}.verify" \
        "executor claim vs subprocess divergence accepted by user" \
        "build-wave-${N}-verify"
    else
      echo "⛔ Wave ${N} verify divergence — rolling back"
      git reset --soft "${WAVE_TAG}" 2>/dev/null
      FAILED_GATE="wave-verify-divergence"
    fi
  fi

  # RFC v9 PR-B fixture wave-verify — every mutation goal touched by this
  # wave must have FIXTURES/{G-XX}.yaml. BLOCKS on missing/parse-error.
  # Fixture verifier reads ${PHASE_DIR}/TEST-GOALS.md via [-f] presence
  # check + Python regex parse (KEEP-FLAT per audit doc line 2874, 2880 —
  # deterministic, not AI-context read).
  # ... [fixture-backfill script invocation, exit 1 unless --allow-missing-fixtures] ...
fi
```

### 8d.10 — Post-wave graphify refresh

```bash
if [ -z "$FAILED_GATE" ] && [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"
  if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-wave-${N}-complete"; then
    GRAPHIFY_ACTIVE="true"
  elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
    echo "⛔ Graphify post-wave rebuild failed and fallback_to_grep=false"
    exit 1
  fi
fi
```

### 8d.11 — Record wave result + emit `wave.completed` event

```bash
echo "wave-${N}: ${FAILED_GATE:-passed} (retries: ${RETRY_COUNT})" >> "${PHASE_DIR}/build-state.log"

# Build wave-complete evidence envelope (canonical contract — accepted by
# vg-orchestrator wave-complete via stdin or --evidence-file).
WAVE_EVIDENCE=$(cat <<EVIDENCE_JSON
{
  "wave": ${N},
  "outcome": "${FAILED_GATE:-passed}",
  "retries": ${RETRY_COUNT:-0},
  "tasks": ${WAVE_TASKS_JSON:-"[]"},
  "wave_tag": "${WAVE_TAG:-}"
}
EVIDENCE_JSON
)
# R2 round-3 (E1) — wave-complete REQUIRES wave_n positional and propagates
# rc=2 on shortfall (HARD BLOCK). Previously this was silenced via 2>/dev/null
# which let `wave.completed` skip and the Stop hook's contract check to pass
# falsely. Stop hook only delegates `run-status --check-contract`; the real
# spawn-count vs expected reconciliation lives in cmd_wave_complete (see
# R2 round-2 shortfall block in scripts/vg-orchestrator/__main__.py).
echo "${WAVE_EVIDENCE}" | "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator wave-complete "${N}"
WAVE_COMPLETE_RC=$?
if [ "$WAVE_COMPLETE_RC" -eq 2 ]; then
  echo "⛔ wave-complete BLOCKED for wave ${N} (rc=2) — shortfall, integrity violation, or wave-attribution rejection." >&2
  echo "   See stderr above. Cannot proceed to next wave; the wave.completed event was NOT emitted." >&2
  exit 2
elif [ "$WAVE_COMPLETE_RC" -ne 0 ]; then
  echo "⛔ wave-complete FAILED for wave ${N} (rc=${WAVE_COMPLETE_RC}) — Stop hook will flag missing wave.completed event." >&2
  exit 1
fi
```

Only proceed to next wave if `$FAILED_GATE` empty.

---

## Resume-recovery handling (`--gaps-only` / `--resume`)

Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md` row for
backup line 1232 (MIGRATE), the historical resume-recovery instruction
"`Run step 4d: extract task sections from PLAN*.md`" used an awk parser
over the full flat PLAN file as AI-context input. This is replaced with
the per-task `vg-load` invocation:

**Before (backup line 1232):**
```
4. Run step 4d: extract task sections from PLAN*.md
```

**After (this ref):**
```
4. Run step 4d: vg-load --phase ${PHASE_NUMBER} --artifact plan --task <N>
   per task in wave (per-task split is the canonical source; loader falls
   back to flat parse only if split missing).
```

Concretely, when `$ARGUMENTS` contains `--gaps-only` or `--resume`:

```bash
if [[ "$ARGUMENTS" =~ --gaps-only|--resume ]]; then
  # For each remaining task in the resumed wave, load its slice via vg-load.
  # The loader resolves split form .vg/phases/${PHASE}/PLAN/task-${N}.md
  # first, falling back to flat PLAN.md AWK extract only if split missing.
  for task_num in "${WAVE_TASKS[@]}"; do
    if [ ! -f "${PHASE_DIR}/.wave-tasks/task-${task_num}.md" ]; then
      vg-load --phase ${PHASE_NUMBER} --artifact plan --task ${task_num} \
        > "${PHASE_DIR}/.wave-tasks/task-${task_num}.md"
    fi
  done

  # .callers.json + .wave-context/ regenerated via step 4e + 4c on demand
  # (see "Step 5 — Pre-flight" above).
fi
```

This keeps the resume path consistent with the fresh-build path: both
populate `.wave-tasks/task-${N}.md` before pre-executor-check.py reads
it for capsule assembly.

---

## Step exit + bootstrap reflection sub-step

After ALL waves complete (or after Wave N when `WAVE_FILTER` set):

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "8_execute_waves" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/8_execute_waves.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 8_execute_waves 2>/dev/null || true
```

### Sub-step `8_5_bootstrap_reflection_per_wave`

Unlike scope/blueprint/review (reflect once per step), `/vg:build`
reflects **after each wave completes** — build is long-running and
multiple learnings may emerge mid-step (typecheck OOM, test flakiness,
commit discipline).

Skip silently if `.vg/bootstrap/` absent. Per wave (orchestrator runs
this AFTER step 8d.11 emits `wave.completed` and BEFORE the loop
proceeds to the next wave):

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 8_5_bootstrap_reflection_per_wave

if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="wave-${WAVE_NUMBER}"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 End-of-wave ${WAVE_NUMBER} reflection..."

  # Explicit marker for orchestrator (v1.14.4+ — was implicit prose-only)
  echo "▸ REFLECTION_TRIGGER_REQUIRED step=${REFLECT_STEP} out=${REFLECT_OUT}"
  echo "  Orchestrator MUST: read .claude/commands/vg/_shared/reflection-trigger.md → Agent spawn vg-reflector"
  echo "  Skip allowed via: --skip-reflection (logs override-debt)"

  # Telemetry — reflection requested (will pair with reflection_completed in step 9 verify)
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "reflection_requested" "${PHASE_NUMBER}" "build.8_5" "wave-${WAVE_NUMBER}" "PENDING" \
      "{\"wave\":${WAVE_NUMBER},\"out\":\"${REFLECT_OUT}\"}"
  fi
fi

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "8_5_bootstrap_reflection_per_wave" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/8_5_bootstrap_reflection_per_wave.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 8_5_bootstrap_reflection_per_wave 2>/dev/null || true
```

**Rate limit:** max 1 reflection per wave. If 0 candidates → silent.

**Post-wave verify (deferred to step 9 `9_post_execution`):**
- If `.vg/bootstrap/` present + wave succeeded → `reflection-wave-N-*.yaml` MUST exist
- Missing reflection file = WARN (not block) + log telemetry `reflection_skipped`
- Override: `--skip-reflection` flag bypasses warn, logs override-debt

---

## Final-wave detection (post-step 8 / 8.5)

After the wave's 8 + 8.5 markers complete, the orchestrator decides whether to
**continue to STEP 5 post-execution** (when this is the *final* wave of the
phase, or `WAVE_FILTER` is unset = run-all-waves mode), or **exit gracefully**
(when this is a mid-wave run via `--wave N` and N < max).

```bash
# When --wave N is set, query the helper to discover whether this is the
# terminal wave. The helper parses PLAN/index.md to count total waves.
IS_FINAL_WAVE="true"     # default for run-all-waves mode (no --wave flag)
if [ -n "${WAVE_FILTER:-}" ]; then
  detect_json=$(bash .claude/scripts/vg-detect-final-wave.sh \
                  --phase "${PHASE_NUMBER}" --wave "${WAVE_FILTER}" \
                  --phases-dir "${PHASES_DIR:-.vg/phases}" 2>/dev/null) || {
    echo "⚠ vg-detect-final-wave failed for phase=${PHASE_NUMBER} wave=${WAVE_FILTER} — assuming partial wave" >&2
    IS_FINAL_WAVE="false"
  }
  if [ -n "$detect_json" ]; then
    IS_FINAL_WAVE=$(echo "$detect_json" \
                    | "${PYTHON_BIN:-python3}" -c "import json,sys;d=json.load(sys.stdin);print('true' if d.get('is_final') else 'false')")
  fi

  if [ "$IS_FINAL_WAVE" = "true" ]; then
    echo "▸ wave ${WAVE_FILTER} is the FINAL wave — proceeding to STEP 5 post-execution"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.final_wave_detected" \
      --phase "${PHASE_NUMBER}" \
      --payload "{\"wave\":${WAVE_FILTER},\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
  else
    echo "▸ wave ${WAVE_FILTER} is NOT the final wave (max_wave=$(echo "$detect_json" | "${PYTHON_BIN:-python3}" -c 'import json,sys;print(json.load(sys.stdin).get("max_wave"))')) — partial-wave run, skipping STEP 5/6/7"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.partial_wave_complete" \
      --phase "${PHASE_NUMBER}" \
      --payload "{\"wave\":${WAVE_FILTER},\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
  fi
fi

# Persist for subsequent steps (slim entry STEP 5 reads this)
mkdir -p ".vg/runs/${RUN_ID}" 2>/dev/null
echo "$IS_FINAL_WAVE" > ".vg/runs/${RUN_ID}/.is-final-wave"
```

After step 8 + 8.5 markers touched for ALL waves (or for the FINAL wave when
`WAVE_FILTER` is set):

- **`IS_FINAL_WAVE=true`** → return to entry `build.md` → STEP 5
  (`9_post_execution` → `10_postmortem_sanity` → `11_crossai_build_verify_loop`
  → `12_run_complete`). Contract validator expects all post-execution markers.
- **`IS_FINAL_WAVE=false`** (mid-wave) → emit `build.partial_wave_complete`
  and `run-complete` with `--partial-wave` flag. Contract validator's
  `is_partial_wave` exemption (in `vg-orchestrator/__main__.py` line ~4071+)
  waives the post-execution markers + `build.completed` event.

Slim entry `build.md` STEP 5 opener checks `.vg/runs/${RUN_ID}/.is-final-wave`
and skips STEP 5/6/7 when value is `false`.
