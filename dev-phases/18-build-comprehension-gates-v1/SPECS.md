# Phase 18 — Build Comprehension Gates — SPECS

**Version:** v1 (draft 2026-04-27)
**Total decisions:** 3 (D-01..D-03)
**Source:** `DECISIONS.md` (this folder)
**Critical reality check:** Phase 15 T11.2 đã persist prompt body to `${PHASE_DIR}/.build/wave-${N}/executor-prompts/${TASK_NUM}.md`; Phase 16 T1.2 persist `.meta.json` sidecar with task body SHA256. Phase 18 piggy-backs cùng directory — no new directory schema needed.

---

## Existing infra audit (CRITICAL — đọc trước SPECS body)

| Component | Current state | P18 action |
|---|---|---|
| `commands/vg/_shared/vg-executor-rules.md` (540 lines) | Steps 1-9: read context blocks → typecheck → commit. No comprehension proof step. | EXTEND — insert step 9a "comprehension echo" before "9. Implement the task". |
| `commands/vg/build.md` step 8c (lines 1500-1674) | Composes executor prompt với 9 context blocks; persists body + meta sidecar (P15+P16). Then `Agent(prompt=...)` spawn. | EXTEND — insert validator call BETWEEN persist and spawn. Skip-and-collect-blocked pattern (don't hard exit on first BLOCK; collect and report all). |
| `commands/vg/build.md` step 8d (lines 1689-2620) | Wave completion gate: R5 spawn-plan check, commit count, attribution audit. ALL run AFTER all wave tasks finished. | EXTEND — append goal-coverage `--wave` `--block` call after attribution audit. |
| `commands/vg/build.md` step 10 (lines 3213-3294) | Post-mortem sanity: phase-level goal-coverage `--advisory`. | KEEP — unchanged (acts as belt-and-suspenders fallback). Per-wave is now the primary gate. |
| `scripts/verify-goal-coverage-phase.py` | Reads PLAN tasks + TEST-GOALS, checks each G-XX has task impl. Currently phase-level, has `--advisory` flag. | EXTEND — add `--wave N` flag scoping check to goals impacted by this wave; respect `--block` (already there). |
| `scripts/validators/registry.yaml` | Validator catalog. Phase 16 added 3 entries (`task-schema`, `crossai-output`, `task-fidelity`). | EXTEND — append 2 entries: `prompt-completeness` (severity: block, domain: artifact), `comprehension-echo` (severity: block, domain: artifact). Goal-coverage already registered. |
| `${PHASE_DIR}/.build/wave-${N}/executor-prompts/` | Created by P15 T11.2; populated with `<task>.md` + `<task>.meta.json` per spawned executor. | NEW sibling: `${PHASE_DIR}/.build/wave-${N}/comprehension/${TASK_NUM}.json` for echo capture. |
| `${PHASE_DIR}/.build-progress.json` | Created by `build-progress.sh`; tracks tasks_in_flight + tasks_committed. P16 extended schema with commit_sha + typecheck. | READ — verify-goal-coverage-phase.py `--wave N` reads tasks belonging to this wave from here. |

**Critical implication:** No new files in critical path. Phase 18 = 1 doc edit (executor-rules.md), 1 new script (~80 LOC), 1 wire in build.md step 8c (~15 lines), 1 wire in step 8d (~15 lines), 1 flag extension on existing script (~30 LOC). Total ~140 LOC.

---

## D-01 — Pre-execution comprehension echo

### Input contract — `vg-executor-rules.md` change

Insert between current step 8 ("Read `<downstream_callers>`") and step 9 ("Implement the task"):

```markdown
9a. **Comprehension echo (MANDATORY before any code).**

    Emit ONE line to stdout via `bash -c 'echo "VG_COMPREHENSION:<json>"'`.
    JSON is single-line (no pretty-print) so orchestrator grep is reliable.
    Schema:

    ```json
    {
      "task_id": "T-3",
      "phase": "7.14.3",
      "wave": 2,
      "requirements_understood": ["G-12","G-15","P7.14.3.D-04"],
      "contract_endpoints": ["POST /api/v1/sites","GET /api/v1/sites/:id"],
      "design_tokens_to_apply": ["color.primary","spacing.lg"],
      "components_used": ["Button:primary","Modal"],
      "edge_cases_recognized": ["empty","error","loading"],
      "files_to_modify": ["apps/web/src/sites/SitesList.tsx"]
    }
    ```

    Rules for the executor:
    - Echo BEFORE any Edit/Write tool call.
    - Each entry MUST come from a context block — do NOT fabricate.
    - If a block is empty (e.g., `<sibling_context>NONE</sibling_context>`), omit
      the corresponding key OR use empty array `[]`.
    - One single line, no embedded newlines, valid JSON parseable by `json.loads()`.

    Why: orchestrator validator `verify-comprehension-echo.py` parses this
    line + diffs against your injected context blocks. Mismatch >20% (refs
    you should have understood but did NOT echo) = wave 8d BLOCK.

    Skipping this step = your task BLOCKs at wave end.
```

### Output contract — orchestrator capture (build.md step 8c)

After `Agent(prompt=...)` returns, parse Agent stdout for lines matching `^VG_COMPREHENSION:` and persist:

```bash
# At end of executor agent return handling
mkdir -p "${PHASE_DIR}/.build/wave-${N}/comprehension"
ECHO_LINE=$(echo "$AGENT_STDOUT" | grep -m1 '^VG_COMPREHENSION:' | sed 's/^VG_COMPREHENSION://')
if [ -n "$ECHO_LINE" ]; then
  echo "$ECHO_LINE" > "${PHASE_DIR}/.build/wave-${N}/comprehension/${TASK_NUM}.json"
else
  echo "{}" > "${PHASE_DIR}/.build/wave-${N}/comprehension/${TASK_NUM}.json"
  echo "⚠ Task ${TASK_NUM} did not emit VG_COMPREHENSION echo — wave 8d will BLOCK"
fi
```

### Validator — `scripts/validators/verify-comprehension-echo.py`

Input: `--phase-dir`, `--wave N`. Output: exit 0 PASS / 1 BLOCK with findings.

Logic:
```python
for task_num in wave_tasks_from_progress_json(phase_dir, wave):
    echo_path = f"{phase_dir}/.build/wave-{wave}/comprehension/{task_num}.json"
    prompt_path = f"{phase_dir}/.build/wave-{wave}/executor-prompts/{task_num}.md"
    meta_path  = f"{phase_dir}/.build/wave-{wave}/executor-prompts/{task_num}.meta.json"

    echo = json.loads(read(echo_path) or "{}")
    if not echo:
        findings.append(("MISSING_ECHO", task_num))
        continue

    prompt_body = read(prompt_path)

    # Extract refs from injected blocks (regex per block)
    injected_goals = regex_findall(r"\bG-\d+\b", extract_block(prompt_body, "goals_context"))
    injected_decisions = regex_findall(r"\bP[\d.]+\.D-\d+\b|\bF-\d+\b",
                                        extract_block(prompt_body, "decision_context"))
    injected_endpoints = regex_findall(r"\b(?:POST|GET|PUT|DELETE|PATCH)\s+/[^\s`'\"]+",
                                        extract_block(prompt_body, "contract_context"))

    # Compute echo coverage
    echo_refs = set(echo.get("requirements_understood", []))
    expected_refs = set(injected_goals + injected_decisions)
    if expected_refs:
        coverage = len(echo_refs & expected_refs) / len(expected_refs)
        if coverage < 0.80:
            findings.append(("LOW_COVERAGE", task_num, coverage, expected_refs - echo_refs))

    echo_endpoints = set(echo.get("contract_endpoints", []))
    expected_endpoints = set(injected_endpoints)
    missing = expected_endpoints - echo_endpoints
    if missing and len(missing) > len(expected_endpoints) * 0.20:
        findings.append(("MISSING_ENDPOINTS", task_num, missing))

# Exit
if findings:
    print_findings(findings)
    sys.exit(1)
sys.exit(0)
```

### Acceptance
- Fixture phase với 3 task, all echo correctly → PASS.
- Fixture với 1 task missing echo entirely → exit 1, finding `MISSING_ECHO`.
- Fixture với task echoes G-12 but injected G-12 + G-15 → coverage 50%, exit 1, finding `LOW_COVERAGE` listing G-15.

`[T-1.1 implements echo step in rules; T-1.2 implements capture in build.md; T-1.3 implements validator; T-5.1 acceptance verifies]`

---

## D-02 — Spawned prompt completeness audit

### Input contract — `verify-prompt-completeness.py`

Args:
- `--phase-dir <PATH>` (required)
- `--wave N` (required)
- `--task <NUM>` (optional — if absent, scan all tasks in wave)
- `--strict` (default off — adds line-count thresholds beyond just block-presence)

Read:
- `${PHASE_DIR}/.build/wave-${N}/executor-prompts/${TASK_NUM}.md`
- `${PHASE_DIR}/.build/wave-${N}/executor-prompts/${TASK_NUM}.meta.json` (P16 sidecar)
- Original task block from PLAN (via `pre-executor-check.extract_task_section_v2()` re-call) to know which `<*-refs>` should appear

### Block presence check

For each block name in the executor prompt body, parse content between tags `<NAME>...</NAME>`:

| Block | Required when | Min content (default) | Min content (`--strict`) |
|---|---|---|---|
| `<task_context>` | always | non-empty | ≥50 lines body, OR ≥3 task fields visible (description, file-path, contract-refs/goals-covered) |
| `<contract_context>` | task has `<contract-refs>` in PLAN | ≥10 lines | ≥3 code blocks (auth + schema + error per executor-rules.md "3 code blocks per endpoint") |
| `<goals_context>` | task has `<goals-covered>` | non-empty + each G-XX string-present | each G-XX has ≥1 acceptance line nearby |
| `<decision_context>` | task has `<context-refs>` | non-empty + each ID string-present | each ID has ≥1 body line of decision text |
| `<design_context>` | task has `<design-ref>` slug | screenshot path → file bytes >0 | + structural HTML present + interactions.md present |
| `<ui_spec_context>` | profile is web-fullstack/web-frontend-only AND task touches UI file | non-empty | Design Tokens table present |
| `<sibling_context>` | always | tolerated empty (signals "no peers") | (same — empty OK) |
| `<downstream_callers>` | always | tolerated empty (signals "no shared symbols") | (same — empty OK) |
| `<wave_context>` | wave has ≥2 tasks | non-empty | lists all peer tasks in wave |

### Output

Findings JSON:
```json
{
  "task": "T-3",
  "wave": 2,
  "verdict": "BLOCK|PASS",
  "findings": [
    {
      "block": "decision_context",
      "issue": "EMPTY_BUT_REQUIRED",
      "evidence": "task has <context-refs>P7.D-04</context-refs> but block is empty (0 lines)",
      "recommendation": "check ${PHASE_DIR}/CONTEXT.md exists + decision P7.D-04 present"
    }
  ]
}
```

### Wire in `build.md` step 8c — POST persist + PRE spawn

Insert AFTER Phase 15 T11.2 prompt persistence + Phase 16 T1.2 meta persistence,
BEFORE the `Agent(prompt=...)` invocation.

```bash
# Phase 18 D-02 — verify spawned prompt completeness BEFORE Agent() spawn
if ! ${PYTHON_BIN} scripts/validators/verify-prompt-completeness.py \
     --phase-dir "${PHASE_DIR}" \
     --wave "${N}" \
     --task "${TASK_NUM}" \
     ${STRICT_FLAG} > "${PHASE_DIR}/.build/wave-${N}/.completeness-${TASK_NUM}.json" 2>&1; then

  if [[ "$ARGUMENTS" =~ --allow-prompt-gap ]]; then
    type log_override_debt >/dev/null 2>&1 && \
      log_override_debt "prompt-completeness" "${PHASE_NUMBER}" \
        "task ${TASK_NUM} prompt incomplete" "$PHASE_DIR"
    echo "⚠ --allow-prompt-gap set — spawning task ${TASK_NUM} despite incomplete prompt"
  else
    echo "⛔ Prompt completeness BLOCK for task ${TASK_NUM} — see .completeness-${TASK_NUM}.json"
    BUILD_BLOCKED_TASKS+=("${TASK_NUM}")
    continue   # skip Agent() spawn for this task
  fi
fi

# (existing) Agent(prompt=...) spawn here
```

After all wave tasks processed, if `BUILD_BLOCKED_TASKS` non-empty:
```bash
if [ ${#BUILD_BLOCKED_TASKS[@]} -gt 0 ]; then
  echo "⛔ Wave ${N} BLOCK: ${#BUILD_BLOCKED_TASKS[@]} task(s) failed prompt completeness"
  echo "   Tasks blocked: ${BUILD_BLOCKED_TASKS[@]}"
  echo "   Fix: investigate the per-task .completeness-N.json findings, address root cause, then /vg:build ${PHASE_NUMBER} --wave ${N} --resume"
  exit 1
fi
```

### Acceptance
- Fixture phase: task có `<context-refs>P7.D-04</context-refs>` nhưng CONTEXT.md missing decision P7.D-04 → prompt persists with empty `<decision_context>` → validator BLOCK pre-spawn.
- Fixture phase: task có `<design-ref>nonexistent-slug</design-ref>` nhưng `${DESIGN_OUTPUT_DIR}/screenshots/nonexistent-slug.png` missing → BLOCK with finding `MISSING_DESIGN_ASSET`.
- Fixture phase: well-formed prompt with all required blocks populated → PASS, executor spawned normally.
- `--allow-prompt-gap`: above failing fixture → proceeds, override-debt logged.

`[T-2.1 implements validator; T-2.2 wires in build.md step 8c; T-5.1 acceptance verifies]`

---

## D-03 — Wave-level goal coverage BLOCK gate

### Input contract — `verify-goal-coverage-phase.py` extension

Add new optional flag:
- `--wave N` — restrict coverage check to goals which have ≥1 task assigned to wave N (read from `.build-progress.json`).

Logic:
```python
def compute_wave_goals(phase_dir: Path, wave: int) -> set[str]:
    """Return G-XX IDs whose implementing tasks belong to the given wave."""
    progress = json.loads((phase_dir / ".build-progress.json").read_text())
    wave_tasks = {t["task_num"] for t in progress.get("tasks", [])
                  if t.get("wave") == wave}

    # Re-parse PLAN to extract <goals-covered> per task
    tasks = extract_all_tasks(phase_dir / "PLAN.md")  # P16 helper exists
    wave_goals = set()
    for task in tasks:
        if task["task_num"] in wave_tasks:
            wave_goals |= set(task.get("goals_covered", []))
    return wave_goals
```

When `--wave N` set, filter coverage matrix to `wave_goals` only. Exit 1 if any `wave_goals` member has 0 implementing files in repo.

### Wire in `build.md` step 8d — AFTER attribution audit

Insert at end of step 8d (around line 1900, after "Step 0b — Commit attribution audit"):

```bash
# Phase 18 D-03 — wave-level goal coverage BLOCK gate
echo ""
echo "━━━ Wave ${N} goal coverage check ━━━"
${PYTHON_BIN} scripts/verify-goal-coverage-phase.py \
  --phase-dir "${PHASE_DIR}" \
  --repo-root "${REPO_ROOT}" \
  --wave "${N}" \
  --block
GOAL_RC=$?

if [ "$GOAL_RC" -ne 0 ]; then
  if [[ "$ARGUMENTS" =~ --allow-goal-gap ]]; then
    type log_override_debt >/dev/null 2>&1 && \
      log_override_debt "wave-goal-coverage" "${PHASE_NUMBER}" \
        "wave-${N} goal gap" "$PHASE_DIR"
    echo "⚠ --allow-goal-gap set — proceeding despite goal coverage gap"
  else
    echo "⛔ Wave ${N} BLOCK: goal coverage gap. Fix tasks then /vg:build ${PHASE_NUMBER} --wave ${N} --resume"
    if type emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "wave_goal_block" "${PHASE_NUMBER}" "build.8d" "wave_goal_block" "FAIL" "{\"wave\":${N}}"
    fi
    exit 1
  fi
fi
```

### Step 10 fallback (unchanged behavior, demoted to safety net)

`commands/vg/build.md:3230-3233` stays exactly as it is — `--advisory` at phase end. Per-wave gate is now primary; phase-end is duplicate fallback for legacy/skipped-wave runs.

### Acceptance
- Fixture wave: 5 tasks committed, all 3 G-XX in scope have file impl → PASS, build proceeds to next wave.
- Fixture wave: 5 tasks committed, G-12 declared in TEST-GOALS but 0 task touched G-12 file → BLOCK at end of wave 8d (not deferred to step 10).
- `--allow-goal-gap`: same fixture → proceeds, OVERRIDE-DEBT.md updated with kind=`wave-goal-coverage`.
- Phase-end step 10 with all waves clean → no double BLOCK (advisory only, no exit).

`[T-3.1 extends script with --wave; T-3.2 wires in build.md step 8d; T-5.1 acceptance verifies]`

---

## Validator registry entries (T-0.1)

Append to `scripts/validators/registry.yaml`:

```yaml
- id: comprehension-echo
  domain: artifact
  severity: block
  added_in: v2.12.0-phase-18
  path: scripts/validators/verify-comprehension-echo.py
  description: "Phase 18 — verifies executor emitted VG_COMPREHENSION echo + cross-checks against injected refs"
  triggers: [build.wave-end]

- id: prompt-completeness
  domain: artifact
  severity: block
  added_in: v2.12.0-phase-18
  path: scripts/validators/verify-prompt-completeness.py
  description: "Phase 18 — verifies persisted executor prompt has non-empty content for required context blocks"
  triggers: [build.pre-spawn]
```

`verify-goal-coverage-phase.py` already registered; only the wire-in changes.
