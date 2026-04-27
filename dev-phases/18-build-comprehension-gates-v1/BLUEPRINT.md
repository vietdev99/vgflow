# Phase 18 — Build Comprehension Gates — BLUEPRINT v1

**Lock date:** 2026-04-27
**Total tasks:** 10 across 5 waves
**Estimated effort:** 6–9h (single-day; bigger budget if fixtures run on real phase)
**Source:** `SPECS.md` (this folder)
**Pattern:** atomic commit per task with message `feat(phase-18-T<wave>.<task>): <subject>`.

---

## Wave plan

| Wave | Theme | Tasks | Effort | Parallelism | Depends on |
|------|-------|-------|--------|-------------|------------|
| 0 | Foundation: validator slots + fixture skeleton | T-0.1, T-0.2 | 1h | parallel | — |
| 1 | D-01 comprehension echo: rules edit + orchestrator capture + validator | T-1.1, T-1.2, T-1.3 | 2.5h | sequential within wave | W0 (registry) |
| 2 | D-02 prompt completeness: validator + build.md step 8c wire | T-2.1, T-2.2 | 2h | sequential within wave | W0 |
| 3 | D-03 wave goal-coverage: script extend + build.md step 8d wire | T-3.1, T-3.2 | 1.5h | sequential within wave | — (independent) |
| 4 | Acceptance + integration smoke + override-debt registration | T-5.1, T-5.2 | 2h | sequential | W1, W2, W3 |

**Critical path:** W0 → max(W1, W2, W3) → W4
**Wall-clock min (parallel W1+W2+W3 if 3 dev):** 1h + 2.5h + 2h = 5.5h
**Wall-clock max (sequential):** 1h + 2.5h + 2h + 1.5h + 2h = 9h

---

## Wave 0 — Foundation (1h)

### T-0.1 — Register 2 validator slots in registry.yaml
- **File:** `scripts/validators/registry.yaml`
- **Action:** Append entries for `comprehension-echo` + `prompt-completeness` per SPECS "Validator registry entries". `goal-coverage-phase` is already registered (Phase 13 era).
- **Validation:** YAML parses; `/vg:validators list` shows 2 new entries.
- **Commit:** `feat(phase-18-T0.1): register 2 P18 validator slots`
- **Effort:** 0.25h

### T-0.2 — Fixtures + early test scaffold
- **Files:**
  - `fixtures/phase18/prompts/well-formed-task.md` — full 9 blocks populated
  - `fixtures/phase18/prompts/empty-decision-context.md` — `<decision_context></decision_context>` rỗng nhưng task has `<context-refs>`
  - `fixtures/phase18/prompts/missing-design-asset.md` — `<design-ref>nonexistent-slug</design-ref>` nhưng asset không tồn tại
  - `fixtures/phase18/echos/full-coverage.json` — echo cover 100% injected refs
  - `fixtures/phase18/echos/partial-coverage.json` — echo cover 50% (below 80% threshold)
  - `fixtures/phase18/echos/missing-echo.json` — `{}` (executor không echo)
  - `fixtures/phase18/build-progress/wave-2-with-goals.json` — fixture cho `--wave N` test
  - `scripts/tests/root_verifiers/test_phase18_validators.py` — covers all 3 validators
- **Validation:** `pytest test_phase18_validators.py` — discovers fixtures, scaffolds expected (tests will be filled in W1-W3).
- **Commit:** `test(phase-18-T0.2): fixtures + test scaffold`
- **Effort:** 0.75h

---

## Wave 1 — D-01 comprehension echo (2.5h)

### T-1.1 — vg-executor-rules.md: insert step 9a comprehension echo
- **File:** `commands/vg/_shared/vg-executor-rules.md`
- **Action:** Insert SPECS D-01 "Input contract" markdown block between current step 8 and step 9. Update Identity / Execution flow header to mention echo step.
- **Validation:** Manual read; verify step number sequence intact (1, 2, ..., 8, 9a, 9, 10, ...). Mirror change to `codex-skills/vg-executor-rules/` if exists.
- **Commit:** `feat(phase-18-T1.1): vg-executor-rules.md — step 9a comprehension echo (D-01)`
- **Effort:** 0.5h

### T-1.2 — build.md step 8c: capture VG_COMPREHENSION echo from agent stdout
- **File:** `commands/vg/build.md` (around line 1674, after Agent invocation)
- **Action:** Insert SPECS D-01 "Output contract" bash block. Persist `${PHASE_DIR}/.build/wave-${N}/comprehension/${TASK_NUM}.json`. Emit warning if echo missing.
- **Constraints:** Must run AFTER Agent() returns, BEFORE wave 8d gate. Cannot break existing flow when executor doesn't echo (legacy phases).
- **Validation:** Run /vg:build on Phase 17 fixture (test-session-reuse-v1) — comprehension/ dir populated for each spawned task.
- **Commit:** `feat(phase-18-T1.2): build.md step 8c — capture VG_COMPREHENSION echo (D-01)`
- **Effort:** 1h

### T-1.3 — verify-comprehension-echo.py validator + wire in step 8d
- **Files:**
  - `scripts/validators/verify-comprehension-echo.py` (new, ~80 LOC)
  - `commands/vg/build.md` step 8d (around line 1900, after attribution audit, before D-03 goal coverage call)
- **Action:**
  - Implement validator per SPECS D-01 logic (parse echo + extract injected refs from prompt + diff).
  - Wire in step 8d:
    ```bash
    echo "━━━ Wave ${N} comprehension echo audit ━━━"
    ${PYTHON_BIN} scripts/validators/verify-comprehension-echo.py \
      --phase-dir "${PHASE_DIR}" --wave "${N}" --threshold 0.80
    ECHO_RC=$?
    if [ "$ECHO_RC" -ne 0 ] && ! [[ "$ARGUMENTS" =~ --allow-echo-gap ]]; then
      exit 1
    fi
    ```
- **Validation:** Pytest 3 fixtures (full / partial / missing) + 1 wired e2e on Phase 17 fixture.
- **Commit:** `feat(phase-18-T1.3): verify-comprehension-echo.py + build.md step 8d wire (D-01)`
- **Effort:** 1h

---

## Wave 2 — D-02 prompt completeness (2h)

### T-2.1 — verify-prompt-completeness.py validator
- **File:** `scripts/validators/verify-prompt-completeness.py` (new, ~120 LOC)
- **Action:** Per SPECS D-02 logic.
  - argparse: `--phase-dir`, `--wave`, `--task` (optional), `--strict`
  - Block presence + min content table per SPECS
  - Cross-reference task PLAN block (re-call `extract_task_section_v2` from P16) to know which `<*-refs>` are required
  - Output structured findings JSON to stdout; exit 0/1
- **Constraints:**
  - Reuse P16 `pre-executor-check.extract_task_section_v2` — do NOT reimplement task extraction
  - File LOC ≤ 150
- **Validation:** Pytest 3 fixtures (well-formed / empty-decision-context / missing-design-asset).
- **Commit:** `feat(phase-18-T2.1): verify-prompt-completeness.py — pre-spawn block audit (D-02)`
- **Effort:** 1.25h

### T-2.2 — build.md step 8c: pre-spawn validator wire + skip-and-collect pattern
- **File:** `commands/vg/build.md` step 8c (BETWEEN P15 T11.2 persist and Agent() spawn)
- **Action:**
  - Insert SPECS D-02 "Wire in build.md step 8c" bash block.
  - Use skip-and-collect pattern: don't hard-exit on first BLOCK; collect blocked tasks, after wave-loop check sum, exit 1 if any.
  - Add `--allow-prompt-gap` flag handling (override-debt log).
- **Constraints:** Must NOT break legacy phases (pre-P18 prompts may have minor gaps); add `--legacy-warn-only` mode keyed on `vg.config.phase_cutover` (similar to existing `--skip-context-rebuild` cutover pattern).
- **Validation:** Run /vg:build on Phase 17 fixture with deliberately broken prompt (set CONTEXT.md missing) — wave loops skips that task with BLOCK message, completes other tasks, exits 1 at wave end.
- **Commit:** `feat(phase-18-T2.2): build.md step 8c — verify-prompt-completeness wire (D-02)`
- **Effort:** 0.75h

---

## Wave 3 — D-03 wave goal-coverage (1.5h)

### T-3.1 — verify-goal-coverage-phase.py: add --wave N flag
- **File:** `scripts/verify-goal-coverage-phase.py`
- **Action:**
  - Add argparse `--wave N` (optional int)
  - Implement `compute_wave_goals()` per SPECS D-03 logic (read `.build-progress.json`, extract goals from wave's tasks)
  - When `--wave` set, filter coverage matrix to wave_goals; otherwise full phase scope
  - `--block` already exists; ensure wave mode honors it
- **Constraints:**
  - Backward compat: existing call sites without `--wave` keep current full-phase semantics
  - Reuse P16 `extract_all_tasks` helper (do NOT reimplement)
- **Validation:** Pytest fixtures: phase with 3 waves, G-12 only in wave 2 → `--wave 2` + missing impl → exit 1; `--wave 3` (G-12 not in this wave) → exit 0.
- **Commit:** `feat(phase-18-T3.1): verify-goal-coverage-phase.py — --wave N scope (D-03)`
- **Effort:** 1h

### T-3.2 — build.md step 8d: wire wave goal-coverage --block
- **File:** `commands/vg/build.md` step 8d (around line 1900, after attribution audit)
- **Action:**
  - Insert SPECS D-03 "Wire in build.md step 8d" bash block (`--wave N --block`)
  - Add `--allow-goal-gap` flag handling
  - Demote step 10 phase-end call from `--advisory` to `--advisory --legacy-fallback` (functionally same; intent docs)
- **Validation:** Run /vg:build on Phase 17 fixture with TEST-GOALS declaring G-12 but no impl → wave 2 BLOCKS at 8d. Run again with `--allow-goal-gap` → proceeds, debt logged.
- **Commit:** `feat(phase-18-T3.2): build.md step 8d — wave goal-coverage --block + --allow-goal-gap (D-03)`
- **Effort:** 0.5h

---

## Wave 4 — Acceptance + integration smoke (2h)

### T-5.1 — End-to-end acceptance test
- **File:** `scripts/tests/root_verifiers/test_phase18_acceptance.py` (new)
- **Action:** 3 acceptance scenarios mirroring DECISIONS.md Acceptance lists:
  1. (D-01) Fixture wave: executor skip echo → 8d gate FAIL with `MISSING_ECHO`.
  2. (D-02) Fixture wave: prompt with empty `<decision_context>` → pre-spawn BLOCK before Agent().
  3. (D-03) Fixture wave: 5/5 commits but 1 G-XX zero impl → 8d BLOCK with `WAVE_GOAL_GAP`.
- Each test sets up minimal fixture phase, runs validators directly (no full /vg:build), asserts exit code + finding shape.
- **Validation:** `pytest test_phase18_acceptance.py -v` — 3 scenarios pass.
- **Commit:** `test(phase-18-T5.1): end-to-end acceptance for 3 P0 patches`
- **Effort:** 1.5h

### T-5.2 — Override-debt + telemetry events registration + CHANGELOG
- **Files:**
  - `commands/vg/_shared/override-debt.md` (if it lists kinds, add `prompt-completeness`, `wave-goal-coverage`, `comprehension-echo`)
  - `CHANGELOG.md` — append Phase 18 entry under v2.12.0
- **Action:**
  - Verify rationalization-guard adjudicates new override flags (it dispatches via gate name; make sure new gate names are in the registry).
  - CHANGELOG entry with link to this folder.
  - Bump `VGFLOW-VERSION` to 2.12.0 if Phase 17 hasn't already.
- **Validation:** Run `/vg:validators list` — 2 new validators listed. Run `/vg:doctor` — no new gate errors.
- **Commit:** `chore(phase-18-T5.2): override-debt + CHANGELOG + version bump`
- **Effort:** 0.5h

---

## Cross-cutting concerns

### Backward compat
- Echo step (D-01) absent on legacy phases (pre-P18) → wave 8d emits WARN for 1 release cycle (until v2.13.0), then BLOCKs.
- Prompt completeness (D-02) — phases with `phase_cutover` config can opt into `--legacy-warn-only` mode.
- Wave goal-coverage (D-03) — fully backward compat; flag is additive.

### Telemetry events
New events emitted:
- `comprehension_echo_check` (PASS|FAIL with coverage %)
- `prompt_completeness_check` (PASS|FAIL with finding count)
- `wave_goal_block` (FAIL only — PASS path silent to reduce noise)

### Failure modes documented
- T-1.2 capture: agent stdout might be empty if Agent() crashed → handled (`{}` written + warning).
- T-2.2 wire: race condition if persist + completeness check overlap with concurrent waves → not applicable (waves sequential; tasks within wave parallel but each writes own file).
- T-3.2 wire: `.build-progress.json` might not yet have current wave's tasks listed → wire runs AFTER attribution audit which already syncs progress; safe.

### Mirror to codex-skills
After all P18 commits land, `scripts/generate-codex-skills.sh` regenerates `codex-skills/vg-build/SKILL.md` etc. — covered by existing CI hook, no manual mirror needed.
