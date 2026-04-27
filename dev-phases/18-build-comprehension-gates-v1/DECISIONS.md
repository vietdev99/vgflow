# Phase 18 — Build Comprehension Gates — DECISIONS (draft)

**Lock status:** DRAFT — chờ user review từng D-XX trước khi viết SPECS detail.
**Source:** Audit 2026-04-27 dialogue identified 3 P0 leak points trong blueprint→build handoff. Phase 16 đã lock task body fidelity (orchestrator KHÔNG paraphrase). Phase 18 lock executor side: prompt completeness pre-spawn + comprehension proof pre-code + goal coverage BLOCK at wave end.

---

## D-01 — Pre-execution comprehension echo (LEAK 1)

**Why:** Sub-agent reads ~2200 lines context across 9 blocks (`<task_context>`, `<contract_context>`, `<ui_spec_context>`, `<goals_context>`, `<design_context>`, `<sibling_context>`, `<downstream_callers>`, `<wave_context>`, `<decision_context>`) rồi nhảy thẳng vào "9. Implement the task" theo `vg-executor-rules.md:14-30`. Không có checkpoint nào prove executor thực sự parsed all blocks.

Failure mode quan sát: executor skim, pick pattern-matchable parts, write code "looks right". Validator downstream (citation, endpoint presence) chỉ catch miss thô — không catch subtle skim ("UI-SPEC said Zustand for slice X, agent used React Context vì sibling did").

**What:**
- Insert step 9a vào `vg-executor-rules.md` BEFORE "9. Implement the task":
  ```
  9a. Comprehension echo (MANDATORY before any code).
      Emit single JSON line to stderr via `bash -c 'echo "VG_COMPREHENSION:" + json'`:
      {
        "task_id": "T-3",
        "requirements_understood": ["G-12", "G-15", "P7.D-04"],
        "contract_endpoints": ["POST /api/v1/sites"],
        "design_tokens_to_apply": ["color.primary", "spacing.lg"],
        "components_used": ["Button:primary", "Modal"],
        "edge_cases_recognized": ["empty", "error", "loading"],
        "files_to_modify": ["apps/web/src/sites/SitesList.tsx"]
      }
  ```
- Build orchestrator captures executor output → parses lines starting with `VG_COMPREHENSION:` → persists to `${PHASE_DIR}/.build/wave-${N}/comprehension/${TASK_NUM}.json`.
- New validator `verify-comprehension-echo.py` (wave 8d) diffs echo against injected blocks:
  - Each `requirements_understood` ID MUST be present in `<goals_context>` OR `<decision_context>` of that task's prompt.
  - Each `contract_endpoints` MUST appear in `<contract_context>`.
  - `files_to_modify` MUST match task `<file-path>` (single source) OR `<edits-*>` glob.
  - >20% mismatch (count of injected refs not echoed back) → BLOCK with diff evidence.

**Acceptance:**
- Fixture: executor outputs valid echo with all refs covered → PASS.
- Fixture: executor outputs echo missing 50% goals → BLOCK with "Echo coverage 50% < 80% threshold".
- Fixture: executor skips echo entirely → BLOCK with "Comprehension echo missing for task T-N".

**Risk:** LOW — pure add-only. If echo absent on legacy phases (pre-P18), validator emits WARN for 1 release cycle then BLOCKs.

---

## D-02 — Spawned prompt completeness audit (LEAK 2)

**Why:** `commands/vg/build.md:1565-1674` lắp executor prompt bằng shell variable interpolation (`${DECISION_CONTEXT}`, `${TASK_SIBLINGS}`, `${TASK_CALLERS}`...). Nếu một biến không expand đúng (e.g., `<context-refs>` rỗng + fallback path không trigger), executor nhận block `<decision_context></decision_context>` rỗng — và **không ai báo**. Agent build code không decision context, ship.

Phase 15 T11.2 đã persist prompt body sang `${PHASE_DIR}/.build/wave-${N}/executor-prompts/${TASK_NUM}.md`. Phase 16 T1.2 persist .meta.json sidecar. Phase 18 leverages cùng path để verify completeness BEFORE Agent() được spawn.

**What:**
- New `scripts/validators/verify-prompt-completeness.py`:
  - Input: `${PHASE_DIR}/.build/wave-${N}/executor-prompts/${TASK_NUM}.md` + `.meta.json`
  - Parse each `<...>` block in body. Check presence + min content:
    - `<task_context>`: ≥50 lines (else "task body suspiciously short")
    - `<contract_context>`: required if task has `<contract-refs>` in PLAN; min 10 lines
    - `<goals_context>`: required if task has `<goals-covered>`; each G-XX must be string-present
    - `<decision_context>`: required if task has `<context-refs>`; each ID must be string-present
    - `<design_context>`: required if task has `<design-ref>`; each slug → file bytes >0
    - `<sibling_context>`: tolerated empty (signals "first module in area")
    - `<downstream_callers>`: tolerated empty (signals "no shared symbols")
  - Empty/missing required block → exit 1 (BLOCK) with structured findings.
  - `--strict` mode: also require non-trivial line count per block (configurable thresholds).
- Wire in `commands/vg/build.md` step 8c, **POST persist + PRE Agent() spawn**:
  ```bash
  if ! ${PYTHON_BIN} scripts/validators/verify-prompt-completeness.py \
       --phase-dir "${PHASE_DIR}" \
       --wave "${N}" \
       --task "${TASK_NUM}" \
       --strict; then
    echo "⛔ Prompt completeness BLOCK for task ${TASK_NUM} — skipping spawn"
    BUILD_BLOCKED_TASKS+=("${TASK_NUM}")
    continue   # do NOT spawn this executor
  fi
  ```
- Override: `--allow-prompt-gap` flag at /vg:build level → log to override-debt with kind=`prompt-completeness`.

**Acceptance:**
- Fixture phase với task có `<context-refs>` nhưng CONTEXT.md missing → prompt persist with empty `<decision_context>` → validator BLOCK pre-spawn.
- Fixture phase với task có `<design-ref>` slug `nonexistent-slug` → validator BLOCK with "design_context references nonexistent-slug.png missing".
- Fixture phase với well-formed prompt → validator PASS, executor spawned normally.

**Risk:** LOW — runs after persist (already implemented), before spawn. Worst case: false-positive BLOCK → user can `--allow-prompt-gap`.

---

## D-03 — Wave-level goal coverage BLOCK gate (LEAK 3)

**Why:** `commands/vg/build.md:3230-3233` chạy `verify-goal-coverage-phase.py --advisory` ở step 10 (phase-end), warn-only. /vg:review sau đó enforce `--block`. Sai chỗ về timing:

| Detection point | Cost to fix |
|---|---|
| Inside wave (step 8d, when build still running) | 1 task re-dispatch, ~5-15 min |
| End of phase (step 10, after all waves done) | Add new task / amend, ~30-60 min |
| At /vg:review phase | Re-run blueprint hoặc whole build, ~hours |

Goal coverage gap detection deferred = expensive. Catch sớm nhất có thể.

**What:**
- Extend `scripts/verify-goal-coverage-phase.py` với `--wave N` flag:
  - Currently: scan all tasks, all goals → emit phase-level coverage matrix.
  - With `--wave N`: scope to goals which have ≥1 task in this wave (read `.build-progress.json` for wave assignment), check those goals only.
  - Output: per-goal status (covered | partial | missing).
- Wire in `commands/vg/build.md` step 8d (after commit count + attribution audit, before next wave):
  ```bash
  echo "━━━ Wave ${N} goal coverage check ━━━"
  ${PYTHON_BIN} scripts/verify-goal-coverage-phase.py \
    --phase-dir "${PHASE_DIR}" \
    --repo-root "${REPO_ROOT}" \
    --wave "${N}" \
    --block   # was --advisory at phase-end; now --block at wave-end
  GOAL_RC=$?
  if [ "$GOAL_RC" -ne 0 ]; then
    if [[ "$ARGUMENTS" =~ --allow-goal-gap ]]; then
      log_override_debt "wave-goal-coverage" "${PHASE_NUMBER}" "wave-${N} goal gap" "$PHASE_DIR"
      echo "⚠ --allow-goal-gap set — proceeding"
    else
      exit 1
    fi
  fi
  ```
- Step 10 phase-level call STAYS (belt-and-suspenders) but switches to `--advisory` (per-wave already enforced).
- New override flag `--allow-goal-gap` (logs override-debt; rationalization-guard adjudicates).

**Acceptance:**
- Fixture wave: 5 tasks committed, all 3 G-XX in scope have file impl → PASS.
- Fixture wave: 5 tasks committed, G-12 declared in TEST-GOALS but no task touched G-12 file → BLOCK at end of wave (not at end of phase).
- Override path: same fixture + `--allow-goal-gap` → proceeds, debt logged in OVERRIDE-DEBT.md.

**Risk:** LOW — flag flip + position move. Existing script + existing wire pattern (step 8d already has commit count + attribution). Worst case: noisy first run on legacy phases → add `--legacy-warn-only` mode keyed on `vg.config.phase_cutover`.

---

## Deferred / explicit non-decisions

- **Reverse audit per wave** (LEAK 4): Haiku reads committed code, infers blueprint, diffs original. ~100 LOC, P1 priority. Defer to Phase 19 — needs prompt design + cost analysis.
- **JSON contracts song song markdown** (LEAK 5): goals.json/contracts.json/tasks.json. ~200 LOC, architectural. Defer to Phase 20 — schema design + migration path.
- **UI-SPEC tokens global inject** (LEAK 6): always inject Design Tokens table at top of `<ui_spec_context>`. P2, defer.
- **Descriptive design-ref auto-resolve** (LEAK 7): regex parse "Phase X.Y" → pull UI-MAP subtree. P2, defer.
- **Per-task contract shape validator** (LEAK 8): extend verify-contract-runtime to check field set. P2, defer.

Phase 18 = 3 P0 patches only. Smaller-scope-better-validated principle (per Phase 16 lesson "MEDIUM risk = need feature flag rollout").
