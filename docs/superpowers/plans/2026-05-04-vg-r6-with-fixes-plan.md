# R6 — VG harness "with fixes" implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 7 Critical + 14 Important findings from the 2026-05-04 codex 7-workflow audit so all 7 mainline workflows move from "production-ready WITH fixes" to "production-ready" verdict.

**Architecture:** No new infrastructure. Each task touches existing slim entries / refs / validators / agents per role-standard compliance. Critical fixes are alignment/wire issues (XML wrappers, schema match, hook enforcement). Important fixes add bounded retry caps + TDD discipline + telemetry.

**Tech Stack:** bash (lifecycle wiring), Python 3 (validators + tests), pytest, Claude Code Agent tool, sqlite3 (events.db).

**Spec sources:**
- `docs/superpowers/specs/2026-05-04-workflow-audit-MASTER.md` (synthesis)
- `docs/superpowers/specs/2026-05-04-workflow-audit-{specs,scope,blueprint,build,review,test,accept}.md` (per-workflow audits)

**Branch:** `feat/rfc-v9-followup-fixes` (current). Tasks commit incrementally.

**Total scope:** 21 findings → 16 actionable tasks (some Critical findings combine into one task since they share fix surface).

---

## Phase A — Critical fixes (block production confidence)

### Task 1: Wire blueprint 3 missing markers (`2b6d_fe_contracts`, `2b8_rcrurdr_invariants`, `2b9_workflows`)

**Why critical:** All 3 declared in `runtime_contract.must_touch_markers` but have no lifecycle bash + no STEP 4 routing. Stop hook won't block (severity=warn) but markers never fire → AI silently skips designer-level architecture work for web profiles.

**Files:**
- Modify: `commands/vg/blueprint.md` (STEP 4 — add routing for 3 sub-steps after edge-cases)
- Modify: `commands/vg/_shared/blueprint/fe-contracts-overview.md` (add bash lifecycle)
- Create: `commands/vg/_shared/blueprint/rcrurdr-overview.md` (NEW — currently missing)
- Modify: `commands/vg/_shared/blueprint/workflows-overview.md` (add bash lifecycle)
- Test: `scripts/tests/test_blueprint_marker_lifecycle.py` (new — assert 3 markers wired)

**Steps:**

- [ ] **Step 1: Write failing test** at `scripts/tests/test_blueprint_marker_lifecycle.py`

```python
"""Assert 3 blueprint markers have full lifecycle wiring (contract + routing + bash)."""
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("marker,ref_basename", [
    ("2b6d_fe_contracts", "fe-contracts-overview"),
    ("2b8_rcrurdr_invariants", "rcrurdr-overview"),
    ("2b9_workflows", "workflows-overview"),
])
def test_blueprint_marker_has_lifecycle_bash(marker, ref_basename):
    ref = REPO_ROOT / "commands/vg/_shared/blueprint" / f"{ref_basename}.md"
    assert ref.exists(), f"Ref missing: {ref.relative_to(REPO_ROOT)}"
    text = ref.read_text(encoding="utf-8")
    assert f"step-active {marker}" in text or f'"{marker}"' in text, (
        f"{ref.name} must have `vg-orchestrator step-active {marker}` bash call"
    )
    assert f"mark-step blueprint {marker}" in text, (
        f"{ref.name} must have `vg-orchestrator mark-step blueprint {marker}` bash call"
    )

def test_blueprint_step4_routes_three_subrefs():
    blueprint_md = (REPO_ROOT / "commands/vg/blueprint.md").read_text(encoding="utf-8")
    assert "fe-contracts-overview.md" in blueprint_md, "STEP 4 must route fe-contracts ref"
    assert "rcrurdr-overview.md" in blueprint_md, "STEP 4 must route rcrurdr ref"
    assert "workflows-overview.md" in blueprint_md, "STEP 4 must route workflows ref"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_blueprint_marker_lifecycle.py -v
# Expected: 4 FAIL (refs lack bash, slim entry lacks routing, rcrurdr-overview.md missing)
```

- [ ] **Step 3: Add lifecycle bash to `fe-contracts-overview.md`**

Modify `commands/vg/_shared/blueprint/fe-contracts-overview.md`. After the existing prose "Steps" section, append a `<step>` block:

```bash
<step name="2b6d_fe_contracts">
## STEP — FE consumer contracts (Pass 2, Task 38 Bug F)

```bash
# Skip-flag check
if [[ "$ARGUMENTS" =~ --skip-fe-contracts ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contracts_pass_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"--skip-fe-contracts\"}" 2>/dev/null || true
  exit 0
fi

# Profile-gate (web only)
case "${PHASE_PROFILE:-feature}" in
  web-fullstack|web-frontend-only) ;;
  *) echo "ℹ Profile ${PHASE_PROFILE} — skipping 2b6d_fe_contracts (web-only step)"; exit 0 ;;
esac

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2b6d_fe_contracts

# Spawn subagent (narrate-spawn per UX baseline R2)
bash .claude/scripts/vg-narrate-spawn.sh vg-blueprint-fe-contracts spawning "phase ${PHASE_NUMBER} FE BLOCK 5 generation"
# AI: spawn Agent(subagent_type="vg-blueprint-fe-contracts", prompt=<from fe-contracts-delegation.md>)
# AI: parse return JSON; for each endpoints[] entry, append BLOCK 5 to ${PHASE_DIR}/API-CONTRACTS/<slug>.md
# AI: run validator
"${PYTHON_BIN:-python3}" scripts/validators/verify-fe-contract-block5.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS"
VAL_RC=$?
if [ "$VAL_RC" -eq 0 ]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contracts_pass_completed" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
else
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.fe_contract_block5_blocked" --payload "{\"phase\":\"${PHASE_NUMBER}\",\"validator_rc\":${VAL_RC}}" 2>/dev/null || true
  exit 1
fi

# Lifecycle close
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2b6d_fe_contracts" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/2b6d_fe_contracts.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b6d_fe_contracts 2>/dev/null || true
```
</step>
```

- [ ] **Step 4: Create `rcrurdr-overview.md`** (NEW file, currently missing entirely)

```bash
# RCRURDR invariants generation (Task 39, Bug G)

## Position in pipeline
2b6d_fe_contracts → 2b7_flow_detect → 2b8_rcrurdr_invariants (THIS) → 2b9_workflows → 2c_verify

## Purpose
Generate per-goal RCRURD invariants from extracted ```yaml-rcrurd``` fences in
TEST-GOALS/G-NN.md. Output: ${PHASE_DIR}/RCRURD/G-NN.md per goal with full
lifecycle (Read empty → Create → Read populated → Update → Read updated →
Delete → Read after delete).

<step name="2b8_rcrurdr_invariants">
## STEP — RCRURDR invariants

```bash
if [[ "$ARGUMENTS" =~ --skip-rcrurdr ]]; then
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.rcrurdr_invariant_skipped" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"reason\":\"--skip-rcrurdr\"}" 2>/dev/null || true
  exit 0
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 2b8_rcrurdr_invariants

# Run RCRURDR generator script (extracts from TEST-GOALS yaml-rcrurd fences)
"${PYTHON_BIN:-python3}" scripts/generate-rcrurdr-invariants.py \
  --phase-dir "${PHASE_DIR}" \
  --output-dir "${PHASE_DIR}/RCRURD"
GEN_RC=$?
if [ "$GEN_RC" -ne 0 ]; then
  echo "⛔ RCRURDR generator failed (rc=${GEN_RC})" >&2
  exit 1
fi

# Emit per-goal events (informational)
GOAL_COUNT=$(ls "${PHASE_DIR}/RCRURD"/G-*.md 2>/dev/null | wc -l | tr -d ' ')
for f in "${PHASE_DIR}/RCRURD"/G-*.md; do
  [ -f "$f" ] || continue
  goal_id=$(basename "$f" .md)
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "blueprint.rcrurdr_invariant_emitted" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"goal\":\"${goal_id}\"}" 2>/dev/null || true
done

mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2b8_rcrurdr_invariants" "${PHASE_DIR}") || \
  touch "${PHASE_DIR}/.step-markers/2b8_rcrurdr_invariants.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step blueprint 2b8_rcrurdr_invariants 2>/dev/null || true
```
</step>
```

- [ ] **Step 5: Add lifecycle bash to `workflows-overview.md`** (mirror Step 3 pattern with `--skip-workflows` + profile gate `web-fullstack,web-frontend-only,backend-multi-actor`)

- [ ] **Step 6: Update `commands/vg/blueprint.md` STEP 4**

Find the existing `### STEP 4 — contracts (HEAVY)` section. After the `2b5e_edge_cases` block, append:

```markdown
After lens-walk + edge-cases, run `2b6d_fe_contracts` (web profile only):

Read `_shared/blueprint/fe-contracts-overview.md` and follow it exactly.
Spawn `Agent(subagent_type="vg-blueprint-fe-contracts", prompt=<from fe-contracts-delegation.md>)`.

Then run `2b8_rcrurdr_invariants` (skippable with `--skip-rcrurdr`):

Read `_shared/blueprint/rcrurdr-overview.md` and follow it exactly.
This is a deterministic generator (no subagent), runs `scripts/generate-rcrurdr-invariants.py`.

Then run `2b9_workflows` (web/multi-actor profiles only):

Read `_shared/blueprint/workflows-overview.md` and follow it exactly.
Spawn `Agent(subagent_type="vg-blueprint-workflows", prompt=<from workflows-delegation.md>)`.
```

- [ ] **Step 7: Run test to verify pass**

```bash
python3 -m pytest scripts/tests/test_blueprint_marker_lifecycle.py -v
# Expected: 4 PASS
```

- [ ] **Step 8: Commit**

```bash
git add commands/vg/blueprint.md \
        commands/vg/_shared/blueprint/{fe-contracts-overview,rcrurdr-overview,workflows-overview}.md \
        scripts/tests/test_blueprint_marker_lifecycle.py
git commit -m "fix(blueprint): R6 Task 1 — wire 3 missing markers (fe-contracts, rcrurdr, workflows)"
```

---

### Task 2: Specs schema/template alignment

**Why critical:** `commands/vg/_shared/specs/authoring.md:114` template emits `created` field; `.claude/schemas/specs.v1.json:7` validator requires `created_at`. Out-of-scope is H3 in template but H2 required by validator. Run-complete will FAIL the artifact-schema validator on every fresh specs run.

**Files:**
- Modify: `commands/vg/_shared/specs/authoring.md` (template lines 114-145)
- Audit: `.claude/schemas/specs.v1.json` (verify expected fields)
- Audit: `scripts/validators/verify-artifact-schema.py:64`
- Test: `scripts/tests/test_specs_template_schema_match.py` (new)

**Steps:**

- [ ] **Step 1: Read schema + validator + template** to identify exact field/heading deltas

- [ ] **Step 2: Write failing test** asserting template emits valid frontmatter per schema (use `python3 scripts/validators/verify-artifact-schema.py --phase test --artifact specs` against a synthetic SPECS.md generated from template).

- [ ] **Step 3: Update template** in `authoring.md`:
  - Change `created: {YYYY-MM-DD}` → `created_at: {YYYY-MM-DDTHH:MM:SSZ}`
  - Add `profile: ${PROFILE}` + `platform: ${PLATFORM}` to frontmatter
  - Promote `### In Scope` → `## In Scope` and `### Out of Scope` → `## Out of Scope`
  - Lowercase `## Success criteria` → match validator regex

- [ ] **Step 4: Run test** + commit.

---

### Task 3: Build post-executor spawn count enforcement

**Why critical:** Currently prompt-only ("DO NOT spawn more than once"). AI can override. Need hook-enforced gate.

**Files:**
- Modify: `scripts/hooks/vg-pre-tool-use-agent.sh` (add post-executor count check)
- Modify: `.claude/scripts/vg-orchestrator/__main__.py` (add events.db query for post-executor count)
- Test: `scripts/tests/test_post_executor_single_spawn.py` (new)

**Steps:**

- [ ] **Step 1: Write failing test** simulating 2nd spawn attempt — must be blocked.

- [ ] **Step 2: Implement hook check** in `vg-pre-tool-use-agent.sh`:
  - When `subagent_type == "vg-build-post-executor"`, query events.db for prior spawn count this run
  - If count ≥ 1, return `permissionDecision: "deny"` with reason `post_executor_already_spawned`

- [ ] **Step 3: Run test + commit.**

---

### Task 4: Accept missing XML step wrappers (`4_build_uat_checklist`, `7_post_accept_actions`)

**Why critical:** Codex audit found 2 markers in contract have lifecycle bash but no `<step name="...">` XML wrap. Test parity broken vs review (which has full XML). Stop hook still works (lifecycle present) but cross-pilot tests can't uniformly validate.

**Files:**
- Modify: `commands/vg/_shared/accept/uat/checklist-build/overview.md` (wrap body in XML)
- Modify: `commands/vg/_shared/accept/cleanup/overview.md` (wrap body in XML)
- Test: `scripts/tests/test_accept_xml_wrapper_parity.py` (new — assert all 17 markers have XML wrappers)

**Steps:**

- [ ] **Step 1: Write failing test** asserting 17 `<step name="..">` blocks in accept refs.

- [ ] **Step 2: Wrap** existing bash body in `<step name="4_build_uat_checklist">...</step>` (no logic change — just add tags).

- [ ] **Step 3: Wrap** `7_post_accept_actions` similarly.

- [ ] **Step 4: Test + commit.**

---

### Task 5: Test fix-loop / codegen order conflict

**Why critical:** `commands/vg/test.md:290-314` says codegen → fix-loop. `commands/vg/_shared/test/fix-loop.md:10,395` says return to `5d` (codegen). Logically circular when failures arise.

**Files:**
- Modify: either `commands/vg/test.md` (clarify order) OR `commands/vg/_shared/test/fix-loop.md` (remove return-to-5d wording)
- Test: `scripts/tests/test_test_workflow_step_order.py` (new — assert order consistency)

**Decision required:** sếp + audit author choose between (a) move fix-loop before codegen (fix-then-generate) or (b) keep codegen → fix-loop unidirectional (generate-then-fix-once).

**Steps:**

- [ ] **Step 1: Decision discussion** — read R2 test pilot rationale to understand original intent

- [ ] **Step 2: Write test** asserting consistent order

- [ ] **Step 3: Update both files to single source of truth**

- [ ] **Step 4: Commit**

---

### Task 6: Accept STEP 3 abort short-circuit + 6-section UAT enforcement

**Why critical:** STEP 3 abort says "later steps short-circuit" but contract still requires all 17 markers + `.uat-responses.json`. Run-complete BLOCKs on abort path. Plus UAT validator accepts ≥5 sections, weaker than ISTQB CT-AcT 6-section standard.

**Files:**
- Modify: `commands/vg/_shared/accept/uat/checklist-build/overview.md` (write minimal `.uat-responses.json` + skip-markers on abort)
- Modify: `scripts/validators/verify-uat-checklist-sections.py` (require canonical A/B/C/D/E/F enum, allow N/A)
- Test: `scripts/tests/test_accept_abort_path.py` (new)

**Steps:**

- [ ] **Step 1: Write failing test** for abort path + 6-section enforcement

- [ ] **Step 2: Update abort branch** to write minimal responses JSON + emit `accept.aborted_with_short_circuit` + touch all profile-applicable markers as `.skipped` files

- [ ] **Step 3: Update validator** to enforce 6-section enum

- [ ] **Step 4: Test + commit**

---

## Phase B — Important fixes (architectural improvements)

### Task 7: Bounded retry caps (3 paths)

**Why important:** Three workflows have unbounded adversarial retry paths.

**Files:**
- `commands/vg/_shared/scope/discussion-deep-probe.md:65` — add `scope.deep_probe_max=10`
- `commands/vg/_shared/blueprint/verify.md:613` — add `blueprint.crossai_remediation_max=3`
- `commands/vg/_shared/build/crossai-loop.md:165` — add `build.crossai_global_max=10`

Each cap exhaustion should:
- Emit `<workflow>.<path>_max_iter_reached` event
- Log to `OVERRIDE-DEBT.md` with operator-required acknowledgment
- Block run-complete unless override-debt entry resolved

**Steps:** TDD per path, parametric test, single commit per workflow.

---

### Task 8: Adversarial agents fail-closed (scope)

**Why important:** Challenger/expander crash currently treated as "no issue, continue". Defeats anti-rationalization purpose.

**Files:**
- `commands/vg/_shared/scope/discussion-overview.md:89,131` — change exit handler from "skip" → "block + override-debt entry"

---

### Task 9: Build TDD enforcement in executor return schema

**Why important:** `vg-build-task-executor` return JSON has `tests_passing` boolean but no red-then-green evidence. Allows commit without TDD.

**Files:**
- Modify: `agents/vg-build-task-executor/SKILL.md` (add `test_red_evidence` + `test_green_evidence` to return schema)
- Modify: `commands/vg/_shared/build/waves-delegation.md` (add to PROCEDURE)
- Modify: post-spawn validator (block commit if missing)

---

### Task 10: Review per-lens telemetry (R3 Phase A Tasks 1-2 — deferred)

**Why important:** `review.lens_plan_generated` fires but no per-lens dispatch verification. Stop hook can't catch silent skip of individual lens.

**Files:**
- Modify: `scripts/spawn_recursive_probe.py` (emit per-lens events)
- Add: contract entries `review.lens.<name>.dispatched` + `.completed` events
- Test: `scripts/tests/test_lens_telemetry_per_lens.py` (already drafted in R3 plan §A Task 1)

This is essentially R3 Phase A Task 1+2 from the existing R3 plan — pull forward.

---

### Task 11: Specs/scope tests update to handle slim entry routing

**Why important:** Existing tests parse only slim entry, miss step bodies in refs. Same pattern as `test_review_tasklist_projection.py` which em fixed in R3.

**Files:**
- `scripts/tests/test_specs_contract.py:27,112` — update to concatenate refs
- `scripts/tests/test_scope_*.py` — same pattern

---

### Task 12: CONTEXT template add explicit `## Goals / In-scope` section

**Why important:** Schema-check downstream (blueprint/build) expects this section.

**Files:**
- Modify: `commands/vg/_shared/scope/artifact-write.md:24,68`
- Modify: `scripts/validators/verify-context-schema.py` (if exists, add section)

---

### Task 13: Test trust-review replay enforcement

**Why important:** `agents/vg-test-goal-verifier/SKILL.md:57,200` lets READY goals pass via static review trust. Pro-tester standard requires automated replay for changed goals.

**Files:**
- Modify: `agents/vg-test-goal-verifier/SKILL.md` (require `replay_evidence` for changed goals)
- Test diff vs prior run baseline

---

### Task 14: Test mobile flow ordering (`5d_mobile_codegen` before `5c_mobile_flow`)

**Why important:** Currently `5c_mobile_flow` runs before `5d_mobile_codegen` — first run marks flow done with no Maestro files.

**Files:**
- Modify: `commands/vg/test.md` step routing (swap order)
- Modify: `commands/vg/_shared/test/runtime.md:279,284` (rerun flow if codegen produced files)

---

### Task 15: Build dependency DAG enforcement beyond same-file

**Why important:** Same-file conflict serializes, but cross-file dependency edges (PLAN/capsule) not enforced. Wave parallel spawn could violate task DAG.

**Files:**
- Modify: `commands/vg/_shared/build/waves-overview.md:273` (parse capsule dependency edges)
- Add: pre-spawn check blocks parallel spawn for tasks with unmet upstream

---

### Task 16: Specs hard-gate wording / Accept missing UAT pointer

**Why minor (combined cleanup):**
- Specs hard-gate says "every step" but only some have explicit step-active. Downgrade wording or wrap all.
- Accept override-debt block message lacks file path pointer to `OVERRIDE-DEBT.md`.

Both single-line documentation/wording fixes. Combine as one commit.

---

## Phase C — Static tests + sync

### Task 17: Run full pytest regression

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/ scripts/tests/ 2>&1 | tee /tmp/r6-regression.log
# Expected: all pre-existing pass + 16 new tests pass
# Allow: 19 known pre-existing failures (phase16 + tasklist_visibility) — those are unrelated stale tests
```

### Task 18: Sync to PV3 mirror

```bash
# Mirror all touched files to /Users/dzungnguyen/Vibe Code/Code/PrintwayV3/.claude/
```

### Task 19: Update audit master doc with shipped status

Add "R6 implementation status" table to `docs/superpowers/specs/2026-05-04-workflow-audit-MASTER.md` showing which Critical/Important fixes shipped.

### Task 20: Push + final commit message summarizing R6 round

---

## Implementation order (dependencies)

```
Task 1 (blueprint wires)  → independent (highest user impact: web-fullstack PV3 4.2)
Task 2 (specs schema)     → independent (run-complete blocker)
Task 3 (post-executor)    → independent (prevents future build flakiness)
Task 4 (accept XML)       → independent (test parity)
Task 5 (test order)       → DECISION REQUIRED before TDD
Task 6 (accept abort)     → independent

Task 7 (retry caps)       → after Tasks 5-6 (touches test/scope/build)
Task 8 (adversarial)      → after Task 7 (same files in scope)
Task 9 (TDD)              → after Task 3 (touches build executor)
Task 10 (lens telemetry)  → after Task 1 (modifies same probe script)
Task 11 (test infra)      → independent
Task 12 (CONTEXT schema)  → independent
Task 13 (replay)          → independent
Task 14 (mobile order)    → after Task 5 (test order)
Task 15 (DAG)             → after Task 3 (same waves-overview file)
Task 16 (wording cleanup) → independent

Tasks 17-20 (close)       → final
```

**Recommended ship batches:**

- **Batch 1** (Tasks 1, 2, 4, 6): independent Critical alignment fixes — 1 day
- **Batch 2** (Task 5 with decision, Tasks 3, 9): build/test pipeline — 2 days
- **Batch 3** (Tasks 7, 8, 14, 15): bounded retry + DAG — 2 days
- **Batch 4** (Tasks 10, 11, 12, 13, 16): telemetry + cleanup — 1 day
- **Batch 5** (Tasks 17-20): regression + sync + commit — 0.5 day

**Total estimate: ~6.5 days** for one focused implementer following subagent-driven-development pattern (one subagent per task, two-stage review per task).

---

## Success criteria

1. All 7 mainline workflows audit verdict moves from "production-ready WITH fixes" to "production-ready"
2. Codex re-audit (round 2) finds zero Critical, ≤2 Important across all 7 workflows
3. Pytest regression: all newly-added tests pass; pre-existing 19 known failures unchanged (or fixed as bonus)
4. Sếp dogfood `/vg:blueprint 4.3 → /vg:build 4.3 → /vg:test 4.3 → /vg:accept 4.3` runs all 17+ markers per workflow without silent skip on web-fullstack profile

---

## Risk + mitigation

| Risk | Likelihood | Mitigation |
|---|---|---|
| Task 1 RCRURDR generator script doesn't exist yet | High | Spec the script signature before Task 1 starts; if generator script is also missing, expand Task 1 to include `scripts/generate-rcrurdr-invariants.py` |
| Task 5 decision on test order requires sếp input | Medium | Block Task 5 + 14 until decision; other tasks proceed |
| Hook changes (Task 3) might affect existing build runs | Medium | Add canary test before deploy; allow `--allow-multiple-post-executor` override flag with debt entry |
| Bounded retry caps (Task 7) might be too aggressive | Low | Default cap from audit (10/3/10), allow per-project override via `.claude/vg.config.md` |
| 16 tasks may bloat single PR | Medium | Ship in 5 batches per ordering above; each batch independently mergeable |

---

## Audit metadata

- 7 codex CLI gpt-5.5 audit reports: `docs/superpowers/specs/2026-05-04-workflow-audit-{specs,scope,blueprint,build,review,test,accept}.md`
- Synthesis: `docs/superpowers/specs/2026-05-04-workflow-audit-MASTER.md`
- Already shipped (closes some audit findings): commits 87530d3, abc27cc, 7688736, 5c495aa, 1ee4a50, bd3a4df, 3dcf38a, 540e872, 54fc047, 286a550 + 4 subagent model downgrades
