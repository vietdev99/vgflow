# build context loading (STEP 2)

2 steps: `2_initialize` (resolve phase vars) + `4_load_contracts_and_context`
(materialize ALL context-injection inputs the wave executor pipeline reads
before spawning task executors in step 8).

<HARD-GATE>
You MUST run STEP 2.1 then STEP 2.2 in exact order. STEP 2.2 produces the
inputs that `pre-executor-check.py` (called later in step 8) consumes when
materializing per-task `.task-capsules/task-${N}.capsule.json` files. The
PreToolUse Agent hook BLOCKS spawn of any `vg-build-task-executor` whose
capsule file is missing — and the capsule cannot be assembled without the
artifacts STEP 2.2 produces (`.wave-context/siblings-task-{N}.json`,
`.wave-tasks/task-{N}.md`, `.callers.json`, design-resolver state). You
CANNOT spawn executors without first running this step.

The PreToolUse Bash hook gates `vg-orchestrator step-active` calls. Each
step's bash MUST be wrapped with `step-active` before its real work and
`mark-step` after.
</HARD-GATE>

---

## STEP 2.1 — initialize (2_initialize)

**VG-native phase init — resolves `PHASE_DIR`, `PHASE_NUMBER`, `PHASE_NAME`, `PLAN_COUNT`, `INCOMPLETE_COUNT` from the planning directory.**

Models come from config-loader (`$MODEL_EXECUTOR`, `$MODEL_PLANNER`, `$MODEL_DEBUGGER`). VG-native does not depend on GSD agent-skills — executor rules are injected inline via `vg-executor-rules.md`.

Errors: `PHASE_DIR` empty → stop. `PLAN_COUNT=0` → stop.

```bash
vg-orchestrator step-active 2_initialize

# VG-native phase init (no GSD dependency)
PHASE_DIR=$(ls -d ${PLANNING_DIR}/phases/*${PHASE_ARG}* 2>/dev/null | head -1)
PHASE_NUMBER=$(echo "${PHASE_DIR}" | grep -oP '\d+(\.\d+)*' | head -1)
PHASE_NAME=$(basename "${PHASE_DIR}" | sed "s/^[0-9.]*-//")
PLAN_COUNT=$(ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null | wc -l)
INCOMPLETE_COUNT=$PLAN_COUNT
# VG-native: executor rules injected inline via vg-executor-rules.md (no GSD agent-skills needed)
AGENT_SKILLS=""

mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 2_initialize 2>/dev/null || true
```

Parse from resolved vars: `phase_dir`, `phase_number`, `phase_name`, `plan_count`, `incomplete_count`.

---

## STEP 2.2 — load contracts and context (4_load_contracts_and_context)

**Load artifacts + resolve all context-injection variables BEFORE spawning executors.**

This step materializes the per-task context inputs that `pre-executor-check.py` (invoked from step 8 wave dispatch) reads when assembling each task's capsule. The capsule is the contract executors read — every artifact this step produces (`.wave-context/siblings-task-{N}.json`, `.wave-tasks/task-{N}.md`, `.callers.json`, design-resolver state, blueprint CrossAI summary) is consumed during capsule assembly. Drift here breaks the wave executor pipeline.

**Resume-safe:** This step MUST run even on `--resume` if its artifacts are missing. Prior builds may have lacked graphify context — new build needs step 4 data.

<HARD-GATE>
On `--resume`, this step MUST re-run UNLESS user explicitly passes
`--skip-context-rebuild`. Reason: graphify may have been rebuilt since
prior run, config may have changed, and stale sibling/caller context
causes cross-module breaks. Reusing is OPT-IN, not default.

You MUST NOT skip this step before any `vg-build-task-executor` spawn.
The PreToolUse Agent hook checks for `.task-capsules/task-${N}.capsule.json`
existence and BLOCKS spawn if missing. The capsule cannot be assembled
without the artifacts produced here — bypassing this step means
`pre-executor-check.py` has no inputs, capsules never get written, the
spawn-guard fires, and the run halts.
</HARD-GATE>

```bash
vg-orchestrator step-active 4_load_contracts_and_context

STEP4_NEEDED=true  # default: always run on resume
if [[ "$ARGUMENTS" =~ --skip-context-rebuild ]]; then
  # User explicitly opted out — check artifacts exist
  if [ -d "${PHASE_DIR}/.wave-context" ] \
     && [ -f "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" ]; then
    # Additional staleness check: compare graphify mtime vs marker mtime
    GRAPH_MTIME=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || echo 0)
    MARKER_MTIME=$(stat -c %Y "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" 2>/dev/null || stat -f %m "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done" 2>/dev/null || echo 0)
    if [ "$GRAPH_MTIME" -gt "$MARKER_MTIME" ]; then
      echo "⛔ Graphify rebuilt since step 4 last ran (graph=${GRAPH_MTIME} > marker=${MARKER_MTIME}). Forcing step 4 re-run despite --skip-context-rebuild."
      STEP4_NEEDED=true
    else
      STEP4_NEEDED=false
      echo "Step 4: SKIPPED via --skip-context-rebuild (artifacts fresh)."
    fi
  else
    echo "⛔ --skip-context-rebuild requested but artifacts missing — running step 4 anyway."
  fi
fi

if [ "$STEP4_NEEDED" = "true" ]; then
  echo "Step 4: building sibling + caller context (graphify: ${GRAPHIFY_ACTIVE:-false})..."
fi
```

### 4_pre: Graphify + cross-platform vars

Already resolved by `_shared/config-loader.md` helpers at command start. Available:
- `$PYTHON_BIN` — Python 3.10+ interpreter (validated)
- `$REPO_ROOT` — absolute repo root (git toplevel)
- `$GRAPHIFY_GRAPH_PATH` — absolute graph path (resolved from config)
- `$GRAPHIFY_ACTIVE` — "true" if enabled + graph exists
- `$VG_TMP` — cross-platform temp dir

Steps 4c, 4e, 8c read these vars. No duplicate parsing here.

**Graphify auto-rebuild (stale check):**

```bash
if [ "${GRAPHIFY_ENABLED:-false}" = "true" ]; then
  # Source graphify-safe helper (verifies mtime advances post-rebuild, retries once on stuck)
  source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/graphify-safe.sh"

  if [ ! -f "$GRAPHIFY_GRAPH_PATH" ]; then
    echo "Graphify: enabled but graph missing — cold-building before executor context"
    if vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-step4-cold"; then
      GRAPHIFY_ACTIVE="true"
    elif [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
      echo "⛔ Graphify cold build failed and fallback_to_grep=false"
      exit 1
    else
      echo "⚠ Graphify cold build failed; step 4 will use grep fallback"
    fi
  fi

  if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
    GRAPH_BUILD_EPOCH=$(stat -c %Y "$GRAPHIFY_GRAPH_PATH" 2>/dev/null || stat -f %m "$GRAPHIFY_GRAPH_PATH" 2>/dev/null)
    COMMITS_SINCE=$(git log --since="@${GRAPH_BUILD_EPOCH}" --oneline 2>/dev/null | wc -l | tr -d ' ')

    if [ "${COMMITS_SINCE:-0}" -gt 0 ]; then
      echo "Graphify: ${COMMITS_SINCE} commits since last build — rebuilding for fresh context"
      vg_graphify_rebuild_safe "$GRAPHIFY_GRAPH_PATH" "build-step4" || {
        if [ "${GRAPHIFY_FALLBACK:-true}" = "false" ]; then
          echo "⛔ Graphify rebuild failed and fallback_to_grep=false"
          exit 1
        fi
        echo "⚠ Graphify rebuild did not complete successfully; downstream sibling/caller context may be stale"
      }
    else
      echo "Graphify: up to date (0 commits since last build)"
    fi
  fi
fi
```

**Why always rebuild before build:** Graph is consumed by step 4c (siblings) and 4e (callers). Stale graph = wrong sibling suggestions = executor copies wrong patterns. Rebuild is fast (~10s for incremental) and runs once per build — cheap insurance vs debugging wrong sibling context.

### 4_pre_b: Read pre-build CrossAI verdict (harness v2.7-fixup-M6)

**Why:** Blueprint step 2d-6 emits `${PHASE_DIR}/crossai/result-blueprint-review*.xml`
(MUST_WRITE per blueprint frontmatter). Build's own CrossAI loop (step 11) writes
into a SEPARATE directory and has zero awareness of the pre-build verdict. If the
blueprint pass flagged unresolved major/critical issues that minor auto-fix didn't
land, the executor is unaware of them. Surface that verdict here so the operator
sees continuity across blueprint→build, and downstream prompts can tag the warning.

```bash
# M6 fix — surface blueprint-review CrossAI verdict + unresolved flag count
BLUEPRINT_CROSSAI_DIR="${PHASE_DIR}/crossai"
if [ -d "$BLUEPRINT_CROSSAI_DIR" ]; then
  # shellcheck disable=SC2086
  RESULT_XMLS=$(ls "$BLUEPRINT_CROSSAI_DIR"/result-blueprint-review*.xml 2>/dev/null)
  if [ -n "$RESULT_XMLS" ]; then
    # shellcheck disable=SC2086
    BLUEPRINT_VERDICT=$(grep -h -oP '<verdict>\K[^<]+' $RESULT_XMLS 2>/dev/null \
      | sort -u | head -3 | tr '\n' ',' | sed 's/,$//')
    # shellcheck disable=SC2086
    BLUEPRINT_FLAGS=$(grep -ch 'severity="major"\|severity="critical"' $RESULT_XMLS 2>/dev/null \
      | awk '{s+=$1} END{print s+0}')
    echo "📋 Blueprint CrossAI verdict: ${BLUEPRINT_VERDICT:-none} (${BLUEPRINT_FLAGS} unresolved major/critical)"
    # Surface to executor — appended to TASK_CONTEXT later if non-empty
    export VG_BLUEPRINT_CROSSAI_SUMMARY="verdict=${BLUEPRINT_VERDICT:-none} unresolved=${BLUEPRINT_FLAGS}"
  else
    echo "📋 Blueprint CrossAI: no result-blueprint-review*.xml found (skip-crossai or pre-2d phase)"
  fi
fi
```

Result routing:
- result-blueprint-review*.xml present → log verdict + unresolved count, export VG_BLUEPRINT_CROSSAI_SUMMARY
- No XMLs (skip-crossai run, or older phases without blueprint CrossAI) → silent skip
- Verdict==BLOCK with unresolved>0 → not auto-blocked here (build proceeds), but surfaced loudly so operator can abort

### 4a: Contract context

Per plan task, run `vg-load --phase ${PHASE_NUMBER} --artifact contracts --task NN --endpoint <slug>` to obtain only the endpoint slice the task touches. The loader handles the per-endpoint split (`API-CONTRACTS/<endpoint>.md`) and falls back to the flat contracts file only when the split form is missing. `pre-executor-check.py` (invoked in step 8 capsule assembly) uses the same loader semantics — `${CONTRACT_CONTEXT}` injected into the executor prompt is the JSON-shaped per-endpoint slice, NOT a full-file read. Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md` (line 783 row), the historical full-file contract read instruction is replaced by this loader call — there must be no flat read of the contracts artifact from this step's AI-context paths.

### 4b: Design context paths (fixes G4)

```bash
# Resolve DESIGN_OUTPUT_DIR from config (fallback to default)
DESIGN_OUTPUT_DIR=$(vg_config_get design_assets.output_dir "${PLANNING_DIR}/design-normalized")  # OHOK-9 round-4
DESIGN_MANIFEST="${DESIGN_OUTPUT_DIR}/manifest.json"

# v2.30+ design resolver gate. This is the active path: build uses the same
# resolver as pre-executor-check.py and L3/L5/L6 validators, so phase-local
# `design/`, transitional `designs/`, shared, and legacy roots resolve
# consistently before any executor sees a UI task.
if grep -l "<design-ref" "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  mkdir -p "${PHASE_DIR}/.tmp"
  DESIGN_CHECK_JSON="${PHASE_DIR}/.tmp/design-ref-check.json"
  PYTHONPATH="${REPO_ROOT}/.claude/scripts/lib:${REPO_ROOT}/scripts/lib:${PYTHONPATH:-}" \
    "${PYTHON_BIN:-python3}" "${REPO_ROOT}/.claude/scripts/design-ref-check.py" \
      --phase-dir "${PHASE_DIR}" \
      --repo-root "${REPO_ROOT}" \
      --config "${REPO_ROOT}/.claude/vg.config.md" \
      --wave-tasks-dir "${PHASE_DIR}/.wave-tasks" \
      --output "${DESIGN_CHECK_JSON}" >/dev/null

  SLUG_REFS=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(' '.join(d.get('slug_refs') or []))" "$DESIGN_CHECK_JSON")
  MISSING_DESIGN=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('; '.join(f\"task-{m['task']}:{m['slug']} ({m['reason']})\" for m in d.get('missing') or []))" "$DESIGN_CHECK_JSON")
  DESCRIPTIVE_REFS=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('|'.join(d.get('descriptive_refs') or []))" "$DESIGN_CHECK_JSON")
  NO_ASSET_REFS=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('|'.join(d.get('no_asset_refs') or []))" "$DESIGN_CHECK_JSON")
  DESIGN_REF_STALE_WAVE=$("${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('1' if d.get('wave_tasks_stale') else '0')" "$DESIGN_CHECK_JSON")

  if [ -n "$DESCRIPTIVE_REFS" ]; then
    echo "ℹ Descriptive design-refs (code-pattern guidance, NOT required assets):"
    IFS='|' read -ra REFS_ARR <<< "$DESCRIPTIVE_REFS"
    for r in "${REFS_ARR[@]}"; do [ -n "$r" ] && echo "    \"$r\""; done
  fi
  if [ -n "$NO_ASSET_REFS" ]; then
    echo "⚠ Explicit Form B design gaps found:"
    IFS='|' read -ra NO_ASSET_ARR <<< "$NO_ASSET_REFS"
    for r in "${NO_ASSET_ARR[@]}"; do [ -n "$r" ] && echo "    $r"; done
  fi
  if [ "$DESIGN_REF_STALE_WAVE" = "1" ]; then
    echo "⚠ .wave-tasks design-ref signature is stale vs PLAN.md; regenerating task capsules before executor spawn."
    rm -rf "${PHASE_DIR}/.wave-tasks"
  fi

  if [ -n "$MISSING_DESIGN" ]; then
    echo "⛔ BLOCK: Tasks reference design slugs but required PNG assets are missing: $MISSING_DESIGN"
    echo "   Resolver report: $DESIGN_CHECK_JSON"
    echo "   Search order: PHASE_DIR/design, PHASE_DIR/designs, design_assets.shared_dir, design_assets.output_dir, .vg/.planning design-normalized"
    echo "   Fix: /vg:design-scaffold then /vg:design-extract, or restore the missing phase-local PNG."
    echo "   Override (NOT RECOMMENDED): /vg:build {phase} --skip-design-check"
    if [[ ! "$ARGUMENTS" =~ --skip-design-check ]]; then
      source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/block-resolver.sh" 2>/dev/null || true
      if type -t block_resolve >/dev/null 2>&1; then
        export VG_CURRENT_PHASE="$PHASE_NUMBER" VG_CURRENT_STEP="build.design-ref-resolve"
        BR_GATE_CONTEXT="Tasks in PLAN reference design slugs (${SLUG_REFS}), but PNG assets did not resolve through the 2-tier resolver. Executor needs ground-truth UI pixels before it can build."
        BR_EVIDENCE=$(printf '{"missing":"%s","report":"%s"}' "$MISSING_DESIGN" "$DESIGN_CHECK_JSON")
        BR_CANDIDATES='[{"id":"auto-design-scaffold-extract","cmd":"echo \"Run /vg:design-scaffold then /vg:design-extract for the missing slug(s)\" && exit 1","confidence":0.7,"rationale":"scaffold/extract is the canonical way to produce phase-local PNGs before build"}]'
        BR_RESULT=$(block_resolve "build-design-missing" "$BR_GATE_CONTEXT" "$BR_EVIDENCE" "$PHASE_DIR" "$BR_CANDIDATES")
        BR_LEVEL=$(echo "$BR_RESULT" | ${PYTHON_BIN} -c "import json,sys; print(json.loads(sys.stdin.read()).get('level',''))" 2>/dev/null)
        case "$BR_LEVEL" in
          L1) echo "✓ L1 design assets resolved — continuing" >&2 ;;
          L2) block_resolve_l2_handoff "build-design-missing" "$BR_RESULT" "$PHASE_DIR"; exit 2 ;;
          *)  exit 1 ;;
        esac
      else
        exit 1
      fi
    else
      RATGUARD_RESULT=$(rationalization_guard_check "design-check" \
        "Gate requires concrete PNG assets for slug-form design-ref tasks. Skipping = executor builds UI without seeing the design." \
        "missing_design=${MISSING_DESIGN} user_arg=--skip-design-check report=${DESIGN_CHECK_JSON}")
      if ! rationalization_guard_dispatch "$RATGUARD_RESULT" "design-check" "--skip-design-check" "$PHASE_NUMBER" "build.design-ref-resolve" "$MISSING_DESIGN"; then
        exit 1
      fi
      echo "⚠ --skip-design-check set — proceeding WITHOUT design pixels. Design fidelity compromised."
      echo "skip-design-check: $(date -u +%FT%TZ) MISSING=$MISSING_DESIGN REPORT=$DESIGN_CHECK_JSON" >> "${PHASE_DIR}/build-state.log"
    fi
  fi
fi

```

### 4c: Sibling module detection — hybrid script (graphify + filesystem + git)

**Why script not MCP**: graphify's AST extractor doesn't resolve path aliases (e.g., TS `@/hooks/useAuth` → `src/hooks/useAuth`). Pure MCP query misses alias-imported relationships → wrong community → wrong siblings. The hybrid script (`find-siblings.py`) combines filesystem walk (alias-independent) + git activity + graphify community signal (optional) for accurate peer detection on any stack.

**Run `find-siblings.py` for each task with file-path:**

OHOK Batch 4 B7 (2026-04-22): subprocess failure now exits build. Previously
script failure was silent — executor got empty sibling context without
orchestrator knowing.

```bash
mkdir -p "${PHASE_DIR}/.wave-context"

SIBLINGS_FAILED=()
for task in "${WAVE_TASKS[@]}"; do
  # task iteration gives TASK_NUM + TASK_FILE_PATH
  SIBLING_OUT="${PHASE_DIR}/.wave-context/siblings-task-${TASK_NUM}.json"

  GRAPHIFY_FLAG=""
  if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
    GRAPHIFY_FLAG="--graphify-graph $GRAPHIFY_GRAPH_PATH"
  fi

  if ! ${PYTHON_BIN} .claude/scripts/find-siblings.py \
       --file "$TASK_FILE_PATH" \
       --config .claude/vg.config.md \
       --top-n 3 \
       $GRAPHIFY_FLAG \
       --output "$SIBLING_OUT" 2>&1; then
    # Non-fatal per-task — new modules legitimately have no siblings.
    # But track + emit telemetry so pattern surfacing on a whole wave triggers review.
    SIBLINGS_FAILED+=("${TASK_NUM}:${TASK_FILE_PATH}")
    # Write stub so downstream 8c doesn't crash on missing JSON
    echo '{"siblings":[],"source":"find-siblings-failed"}' > "$SIBLING_OUT"
  fi
done

# If ALL tasks failed, something is systemically wrong — BLOCK.
if [ "${#SIBLINGS_FAILED[@]}" -gt 0 ] && \
   [ "${#SIBLINGS_FAILED[@]}" -eq "${#WAVE_TASKS[@]}" ]; then
  echo "⛔ find-siblings.py failed for ALL ${#WAVE_TASKS[@]} tasks in wave — systemic issue" >&2
  echo "   Failures: ${SIBLINGS_FAILED[@]}" >&2
  echo "   Check: (a) find-siblings.py exists + executable, (b) config valid," >&2
  echo "          (c) graphify graph path correct if GRAPHIFY_ACTIVE=true" >&2
  exit 1
fi
```

### Output format (`.wave-context/siblings-task-{N}.json`)

Step 8c reads this file when assembling the `<sibling_context>` executor prompt block. Format (~15-20 lines vs ~100 grep dump):

```
// <module_dir> (sibling — entry: <entry_file>)
<kind> <name>                  [L<line>]
// <module_dir> (sibling)
<kind> <name>                  [L<line>]
```

### Fallback behavior

If script exits non-zero OR `siblings` list is empty → orchestrator injects `<sibling_context>NONE — no peer modules at this directory level</sibling_context>` (correct signal for "first module in new architectural area", not an error).

**No MCP**: script is deterministic and alias-independent — works on any project regardless of TS path aliases, Python sys.path tweaks, or custom module resolution.

### 4d: Task section extraction (fixes G6)

For each task in PLAN*.md, pre-extract its slice via the canonical loader
so executor gets only that task, not the entire plan. The loader resolves
the per-task split form `${PHASE_DIR}/PLAN/task-${N}.md` first (canonical),
falling back to a flat `PLAN*.md` parse only when the split form is
missing — keeps consumer filename `${TASKS_DIR}/task-${N}.md` stable for
downstream readers (pre-executor-check.py, find-siblings.py).

Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md` row for
backup line 1232 (MIGRATE), the historical awk-over-flat-PLAN parse is
replaced by `vg-load --artifact plan --task ${TASK_NUM}` per task. This
removes the last AI-context-feeding flat read of `PLAN*.md` from the
build pipeline.

```bash
TASKS_DIR="${PHASE_DIR}/.wave-tasks"
mkdir -p "$TASKS_DIR"

# Discover task numbers from PLAN tasks. Use vg-load --list when available
# (canonical), otherwise grep the per-task split dir or flat PLAN headings
# (deterministic — KEEP-FLAT, no AI context).
TASK_NUMS=""
if vg-load --phase "${PHASE_NUMBER}" --artifact plan --list-tasks 2>/dev/null > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/.plan-tasks.txt"; then
  TASK_NUMS=$(cat "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/.plan-tasks.txt" | tr '\n' ' ')
elif [ -d "${PHASE_DIR}/PLAN" ]; then
  TASK_NUMS=$(ls "${PHASE_DIR}/PLAN"/task-*.md 2>/dev/null \
    | sed -E 's|.*/task-0*([0-9]+)\.md|\1|' | sort -un | tr '\n' ' ')
else
  # Deterministic header scan over flat PLAN*.md (NOT AI context — feeds
  # vg-load invocation below per task).
  TASK_NUMS=$(grep -hoE '^#{2,3} Task [0-9]+' "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
    | sed -E 's/^#+ Task 0*([0-9]+).*/\1/' | sort -un | tr '\n' ' ')
fi

for TASK_NUM in $TASK_NUMS; do
  TASK_NUM_PADDED=$(printf '%02d' "$TASK_NUM")
  OUT="${TASKS_DIR}/task-${TASK_NUM_PADDED}.md"
  # Canonical loader — resolves split form, falls back to flat parse only
  # when split missing. Output goes to .wave-tasks/task-${N}.md (preserved
  # filename so downstream consumers keep working unchanged).
  vg-load --phase "${PHASE_NUMBER}" --artifact plan --task "${TASK_NUM}" \
    > "$OUT" 2>/dev/null || {
    echo "⚠ vg-load failed for task ${TASK_NUM} — capsule materialization may use stale slice" >&2
  }
done
```

Each executor now injects `@${TASKS_DIR}/task-{N}.md` (task-only, ~100-300 lines) instead of `@${PLAN_FILE}` (full file).

### 4e: Caller graph load (semantic regression) — dispatch by graphify

Build or refresh `.callers.json` — maps each task's `<edits-*>` symbols to downstream callers across the repo. Executors read this to update or cite callers when changing shared symbols.

Output schema is identical regardless of source (graphify vs grep) — commit-msg hook reads same fields. Add `source: "graphify" | "grep"` field for traceability.

```bash
if [ "$(vg_config_get semantic_regression.enabled true)" = "true" ]; then  # OHOK-9 round-4
  CALLER_GRAPH="${PHASE_DIR}/.callers.json"

  # Regenerate if missing OR any PLAN*.md newer than graph
  NEEDS_REGEN=false
  [ ! -f "$CALLER_GRAPH" ] && NEEDS_REGEN=true
  if [ -f "$CALLER_GRAPH" ]; then
    for plan in "${PHASE_DIR}"/PLAN*.md; do
      [ "$plan" -nt "$CALLER_GRAPH" ] && NEEDS_REGEN=true && break
    done
  fi

  if [ "$NEEDS_REGEN" = "true" ]; then
    if [ "$GRAPHIFY_ACTIVE" = "true" ]; then
      # Graphify path — query MCP for callers per <edits-*> symbol
      # Tree-sitter AST catches dynamic imports, re-exports, type-only imports that grep misses
      echo "Building caller graph via graphify MCP..."

      # Extract all <edits-*> symbols from PLAN tasks
      EDITS=$(grep -hoE '<edits-(schema|function|endpoint|collection|topic)>[^<]+</edits-' "${PHASE_DIR}"/PLAN*.md 2>/dev/null \
        | sed -E 's/<edits-([^>]+)>([^<]+)<.*/\1\t\2/' | sort -u)

      # For each symbol, query graphify for callers (incoming edges)
      # Build .callers.json with same schema as grep path
      ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
        --phase-dir "${PHASE_DIR}" \
        --config .claude/vg.config.md \
        --graphify-graph "$GRAPHIFY_GRAPH_PATH" \
        --output "$CALLER_GRAPH"
      # Note: build-caller-graph.py auto-detects --graphify-graph flag and prefers MCP query
      # If MCP query fails per-symbol, falls back to grep for that symbol
    else
      # Grep fallback path — original implementation
      echo "Building caller graph via grep (graphify inactive)..."
      ${PYTHON_BIN} .claude/scripts/build-caller-graph.py \
        --phase-dir "${PHASE_DIR}" \
        --config .claude/vg.config.md \
        --output "$CALLER_GRAPH"
    fi
  fi

  # Per-task lookup: extract callers this task affects, store for step 8c injection
  # Orchestrator reads $CALLER_GRAPH, builds TASK_{N}_CALLERS env var per task
  # If task has no edits declared → TASK_{N}_CALLERS="NONE — no shared symbols edited"
else
  echo "semantic_regression.enabled=false → skipping caller graph"
fi
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_load_contracts_and_context" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done"`

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "4_load_contracts_and_context" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/4_load_contracts_and_context.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 4_load_contracts_and_context 2>/dev/null || true
```

---

### vg-load partial-load convention (R1a UX baseline Req 1)

When inspecting contracts, plans, or goals during this step (ad-hoc verification, not capsule generation), use partial loads instead of cat-ing flat files:

```
vg-load --phase ${PHASE_NUMBER} --artifact contracts --endpoint <slug>
vg-load --phase ${PHASE_NUMBER} --artifact contracts --task NN --endpoint <slug>
vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical
vg-load --phase ${PHASE_NUMBER} --artifact plan --task NN
```

Per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md`, the only explicit full-file contracts read instruction in this step (backup line 783) is replaced with the per-endpoint vg-load invocation in section 4a above. Other contracts/plan artifact references in this step (variable assignments for mtime checks, presence tests, deterministic Python script paths, echo strings, validator inputs, AWK transforms over `PLAN*.md`, pointer strings in templates) are KEEP-FLAT — they do not feed AI context directly.

---

After both step markers touched, return to entry `build.md` → STEP 3 (validate blueprint: `3_validate_blueprint` + `5_handle_branching` + `6_validate_phase` + `7_discover_plans`).
