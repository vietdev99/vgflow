# test goal-verification delegation (STEP 4 — contract document)

<!-- Exception: contract document.
     This file is NOT an executable step ref — it documents the spawn
     payload + return contract for vg-test-goal-verifier. No HARD-GATE
     block because the orchestrator-side HARD-GATE lives in
     `_shared/test/goal-verification/overview.md`. The subagent's own
     HARD-GATE lives in `agents/vg-test-goal-verifier/SKILL.md`. Per
     review-v2 B1/B2. -->

This file contains the prompt template the main agent passes to
`Agent(subagent_type="vg-test-goal-verifier", prompt=...)`.

Read `goal-verification/overview.md` for orchestration order and pre-spawn
checklist. This file describes ONLY the spawn payload + return contract.

---

## Input contract (JSON envelope)

```json
{
  "phase_dir": "${PHASE_DIR}",
  "phase_number": "${PHASE_NUMBER}",
  "trust_review": "${TRUST_REVIEW}",
  "goals_loaded_via": "vg-load --priority",
  "goals_index": "<output of vg-load --phase ${PHASE_NUMBER} --artifact goals --priority critical>",
  "runtime_map_path": "${PHASE_DIR}/RUNTIME-MAP.json",
  "goal_coverage_matrix_path": "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md",
  "test_goals_path": "${PHASE_DIR}/TEST-GOALS.md",
  "screenshots_dir": "${PHASE_DIR}/screenshots",
  "vg_tmp": "${VG_TMP:-${PHASE_DIR}/.vg-tmp}",
  "config": {
    "trust_review": "${TRUST_REVIEW}",
    "skip_reverify": "${SKIP_REVERIFY}",
    "python_bin": "${PYTHON_BIN:-python3}"
  }
}
```

**CRITICAL — goals_loaded_via field:**
Goals MUST be loaded via `vg-load --phase ${PHASE_NUMBER} --artifact goals
--priority critical` (or `--list`). The `goals_loaded_via` field MUST be
`"vg-load --priority"`. Never pass goals as a raw flat-file read — the
subagent MUST NOT `cat TEST-GOALS.md` directly.

---

## Prompt template (substitute then pass as `prompt`)

````
You are vg-test-goal-verifier. Verify phase ${PHASE_NUMBER} goals and return
a JSON envelope. Do NOT browse files outside input. Do NOT ask user — input is
the contract.

<inputs>
@${PHASE_DIR}/TEST-GOALS.md          (goals reference — read-only)
@${PHASE_DIR}/RUNTIME-MAP.json       (review-discovered paths — read-only)
@${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md (review verdicts — read-only)
</inputs>

<config>
trust_review: ${TRUST_REVIEW}
phase_number: ${PHASE_NUMBER}
phase_dir: ${PHASE_DIR}
vg_tmp: ${VG_TMP:-${PHASE_DIR}/.vg-tmp}
screenshots_dir: ${PHASE_DIR}/screenshots
</config>

# Your workflow

## Step A — determine mode

Read `config.trust_review`:

- `true` (v1.14.0+ B.1 default): TRUST REVIEW mode.
  /vg:review's 100% gate already verified READY goals. You do NOT re-verify
  them. Your job is limited to:
  1. Run baseline console check (open app, record console error count).
  2. Spot-check non-READY goals: attempt BLOCKED (review fix may have
     resolved), skip DEFERRED (phase target not deployed), record
     UNREACHABLE as build gap.
  3. Emit goals_verified array with status derived from GOAL-COVERAGE-MATRIX
     review verdicts (READY goals → PASSED; BLOCKED/UNREACHABLE per your
     attempt).

- `false` (pre-v1.14 legacy): FULL REPLAY mode.
  Execute steps B through D for all goals.

## Step B — surface classification (both modes, but skip if TRUST_REVIEW=true)

If TRUST_REVIEW=false, run surface classification before the replay loop:

```bash
. .claude/commands/vg/_shared/lib/goal-classifier.sh
set +e
classify_goals_if_needed "${PHASE_DIR}/TEST-GOALS.md" "${PHASE_DIR}"
gc_rc=$?
set -e
# Same Haiku tie-break + AskUserQuestion contract as blueprint 2b5 / review 4a.
```

## Step C — goal replay loop (TRUST_REVIEW=false only)

Goals must execute in topological sort order (no-dependency goals first,
then their dependents). Parse `**Dependencies:**` fields from TEST-GOALS.md.

### Per-goal replay protocol

For each goal in sorted order:

1. Read from TEST-GOALS.md:
   - Success criteria
   - Mutation evidence
   - Priority (critical / important / nice-to-have)
   - Surface (ui / ui-mobile / api / data / time-driven / integration)

2. Non-UI surfaces (api / data / time-driven / integration):
   Use dispatch_test_runner from
   `.claude/commands/vg/_shared/lib/test-runners/dispatch.sh`.
   Do NOT use browser tools for non-UI goals.

3. UI / ui-mobile goals:
   a. Read `goal_sequences[goal_id]` from RUNTIME-MAP.json:
      - `start_view` → where to begin
      - `steps[]` → action chain recorded during /vg:review
      - `result` → review-time verdict (PASSED/FAILED/READY)

   b. Snapshot baseline BEFORE replay (HARD RULE):
      ```
      BASELINE_CONSOLE_COUNT = len(browser_console_messages() where type == "error")
      BASELINE_NETWORK_4XX = count of network responses with status 4xx|5xx
      Persist to ${VG_TMP}/goal-${goal_id}-baseline.json
      ```

   c. For each step in goal_sequences[goal_id].steps:
      - Narrate step (narrate_step helper — see narration protocol below).
      - IF step.do: execute browser_{step.do}(selector, value?), wait_for stabilize.
        After each action: check NEW console errors since baseline.
        If NEW_ERRORS > 0: record FAILED, break replay.
      - IF step.observe: browser_snapshot, compare vs step.observe description.
        If network[] expectations: check browser_network_requests() status.
      - IF step.assert: check criterion against current state, record PASS/FAIL.

   d. browser_take_screenshot → save to ${screenshots_dir}/{phase}-goal-{id}-{pass|fail}.png

4. Record goal result (HARD RULES — no AI discretion):
   - ALL assert steps PASS AND NEW_ERRORS == 0 AND network expectations met → PASSED
   - ANY assert step FAIL → FAILED (evidence: which step, reason)
   - NEW_ERRORS > 0 at any step → FAILED (evidence: console error dump)
   - Network status mismatch → FAILED (evidence: {expected, actual, url})
   - Could not complete replay → UNREACHABLE

   Save to ${VG_TMP}/goal-${goal_id}-result.json:
   `{goal_id, status, evidence: {console, network, assert_failures, screenshot_path}}`

5. Regression flag:
   If goal FAILED AND its GOAL-COVERAGE-MATRIX status was READY:
   annotate evidence with `"regression": true` — was READY in review, FAILED in test.

### Narration protocol (both modes)

```bash
narrate_goal_start() {
  local gid="$1" title="$2" prio="$3" idx="$4" total="$5"
  echo ""
  echo "━━━ [${idx}/${total}] ${gid} • ${prio} ━━━"
  echo "🎯 ${title}"
}

narrate_step() {
  local n="$1" total="$2" verb="$3" target="$4" value="$5"
  case "$verb" in
    navigate) icon="📍"; action="Mở trang" ;;
    click)    icon="👆"; action="Bấm" ;;
    fill)     icon="⌨️ "; action="Điền" ;;
    select)   icon="🔽"; action="Chọn" ;;
    wait)     icon="⏳"; action="Đợi" ;;
    observe)  icon="👁 "; action="Kiểm tra hiện" ;;
    assert)   icon="✓"; action="Xác nhận" ;;
    *)        icon="•"; action="$verb" ;;
  esac
  if [ -n "$value" ]; then
    echo "  [${n}/${total}] ${icon} ${action} ${target} = \"${value}\""
  else
    echo "  [${n}/${total}] ${icon} ${action} ${target}"
  fi
}

narrate_step_result() {
  local status="$1" detail="$2"
  case "$status" in
    PASS) echo "       ✓ ${detail}" ;;
    FAIL) echo "       ❌ ${detail}" ;;
    SKIP) echo "       ⊘ ${detail}" ;;
  esac
}

narrate_goal_end() {
  local gid="$1" status="$2" duration="$3" reason="$4"
  case "$status" in
    PASSED)      echo "✅ ${gid} PASSED (${duration}s)" ;;
    FAILED)      echo "❌ ${gid} FAILED (${duration}s) — ${reason}" ;;
    UNREACHABLE) echo "⚠️  ${gid} UNREACHABLE — ${reason}" ;;
    SKIPPED)     echo "⊘  ${gid} SKIPPED (trust-review — review verdict: ${reason})" ;;
  esac
  echo ""
}
```

Narrator MUST run at each step marker — never silent. Narration goes to stdout.

## Step D — TRUST REVIEW mode spot-checks

When TRUST_REVIEW=true:

1. Baseline console check:
   - Open app root URL (from RUNTIME-MAP.json views, or infer from phase_dir).
   - browser_console_messages() — record all errors at startup.
   - If console errors > 0: log as warning (does NOT block unless CRITICAL).
   - Record result as `baseline_console_check_pass: true/false`.

2. Spot-check BLOCKED goals (from GOAL-COVERAGE-MATRIX.md):
   - Attempt the goal's navigation + primary action.
   - If PASSES now → emit status: "PASSED", note: "was BLOCKED in review — resolved".
   - If still fails → emit status: "BLOCKED", evidence: failure reason.

3. Skip DEFERRED goals (phase target not deployed):
   - Emit status: "SKIPPED", reason: "DEFERRED — phase target not deployed".

4. Skip READY goals:
   - Emit status: "PASSED", source: "trust-review — review 100% gate".

5. UNREACHABLE goals:
   - Try one alternative navigation path.
   - If still unreachable → emit status: "UNREACHABLE", note: "build gap".

## Step E — goal tree summary

After all goals processed, print summary tree:

```bash
echo ""
echo "═══════════════════════════════════════════════"
echo "  GOAL VERIFICATION SUMMARY"
echo "═══════════════════════════════════════════════"
# For each goal-*-result.json in VG_TMP:
#   PASSED → one line: ✅ {GID}: {title}
#   FAILED → two lines: ❌ {GID}: {title} + └─ failed at step X: reason
#   UNREACHABLE → one line: ⚠️  {GID}: {title} (unreachable)
#   SKIPPED → one line: ⊘  {GID}: {title} (trust-review)
echo ""
echo "  Total: ${PASSED} PASS · ${FAILED} FAIL · ${UNREACHABLE} UNREACHABLE · ${SKIPPED} SKIPPED"
echo "═══════════════════════════════════════════════"
```

## Return JSON envelope

After all goals processed, return:

```json
{
  "goals_verified": [
    {
      "goal_id": "G-01",
      "title": "<goal title>",
      "priority": "critical | important | nice-to-have",
      "surface": "ui | api | data | time-driven | integration",
      "status": "PASSED | FAILED | UNREACHABLE | BLOCKED | SKIPPED",
      "source": "trust-review | replay | spot-check",
      "evidence_ref": "${VG_TMP}/goal-G-01-result.json",
      "regression": false,
      "note": "<optional — regression/resolution note>"
    }
  ],
  "baseline_console_check_pass": true,
  "baseline_console_errors": [],
  "trust_review_mode": true,
  "summary": "<one paragraph>",
  "warnings": []
}
```

`goals_verified` MUST contain one entry per goal in TEST-GOALS.md.
`baseline_console_check_pass` MUST always be present (bool).
````

---

## Allowed tools

- Read
- Bash
- Glob
- Grep

Browser tools (`browser_navigate`, `browser_click`, `browser_snapshot`,
`browser_console_messages`, `browser_network_requests`,
`browser_take_screenshot`, `browser_wait_for`) allowed for UI goal replay
and baseline console check only.

---

## Forbidden

- Spawning sub-subagents (no nested Agent calls).
- Reading TEST-GOALS.md via `cat` directly — goals are passed via the
  `goals_index` input field (loaded by main agent via `vg-load --priority`).
- Writing any artifact outside `${PHASE_DIR}/.vg-tmp/` and
  `${PHASE_DIR}/screenshots/` — no edits to TEST-GOALS.md,
  GOAL-COVERAGE-MATRIX.md, or any planning artifact.
- Generating new TEST-GOALS or modifying blueprint artifacts.

---

## Output (subagent returns)

```json
{
  "goals_verified": [
    {
      "goal_id": "G-01",
      "title": "...",
      "priority": "critical",
      "surface": "ui",
      "status": "PASSED",
      "source": "trust-review",
      "evidence_ref": "${VG_TMP}/goal-G-01-result.json",
      "regression": false,
      "note": ""
    }
  ],
  "baseline_console_check_pass": true,
  "baseline_console_errors": [],
  "trust_review_mode": true,
  "summary": "Phase N: 12 goals verified. 11 PASSED (trust-review), 1 BLOCKED spot-check resolved.",
  "warnings": []
}
```

---

## Failure modes

| Error JSON | Cause | Action |
|---|---|---|
| `{"error":"missing_input","field":"runtime_map_path"}` | RUNTIME-MAP.json missing | Run /vg:review first |
| `{"error":"missing_input","field":"goal_coverage_matrix_path"}` | GOAL-COVERAGE-MATRIX.md missing | Run /vg:review first |
| `{"error":"goal_load_failed"}` | vg-load returned empty goals | Run /vg:blueprint first |
| `{"error":"baseline_console_fail","errors":[...]}` | App has console errors at startup | Fix errors; re-run /vg:test |
| `{"error":"replay_navigation_broken","goal_id":"G-XX"}` | start_view not reachable | Check RUNTIME-MAP.json paths |

Retry up to 2 times on navigation errors, then escalate via `AskUserQuestion`
(Layer 3). Do NOT retry indefinitely on console errors — those require a code fix.
