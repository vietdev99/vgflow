# Tasklist Enforcement Audit — 2026-05-04

## Executive summary

This audit identified 5 distinct bypass patterns across the 8 VG pipeline flows. The hook gate exists and works mechanically for review/blueprint/build/test/accept, but is trivially circumvented by emitting `vg.block.handled` without performing the required TodoWrite + tasklist-projected steps. Events.db confirms this pattern occurred in production (run `70ca6e31`: `step.active` fired the same second as `review.tasklist_shown`, with zero `review.native_tasklist_projected` events in the database). Two flows (deploy, roam) have partial or no hook coverage at bootstrap steps. Zero flows enforce the 2-layer parent-sub tasklist hierarchy sếp requires — the current enforcement is syntactic-floor only (does the TodoWrite happen at all), not structural-depth enforcement (does it have parent + sub items). Task 44b scope: 6 files modified + 2 new files, estimated 400-600 LOC.

---

## Per-flow enforcement matrix

| Flow | Slim entry tasklist contract | Hook gate enforces? | Layer depth supported | Bypass patterns observed |
|---|---|---|---|---|
| review | `review.tasklist_shown` + `review.native_tasklist_projected` declared; projection instruction before first step-active (Task 34) | YES — hook blocks `step-active` without evidence | 1 (flat group headers only) | P1 (emit-handled-without-todowrite), P3 (step.active fires same-second as tasklist_shown with no native_tasklist_projected) |
| blueprint | `blueprint.tasklist_shown` + `blueprint.native_tasklist_projected` declared; create_task_tracker step in preflight.md has IMPERATIVE TodoWrite comment | YES — bootstrap allowlist covers `vg:blueprint:0_design_discovery`, `vg:blueprint:0_amendment_preflight`, `vg:blueprint:1_parse_args` | 1 (flat group headers only) | P1, P2 (bootstrap allowlist covers 3 pre-tasklist steps; mis-ordering 1_parse_args before create_task_tracker would bypass) |
| build | `build.tasklist_shown` + `build.native_tasklist_projected` declared; create_task_tracker IMPERATIVE in preflight.md | YES — bootstrap allowlist covers `vg:build:0_gate_integrity_precheck`, `vg:build:0_session_lifecycle` | 1 (flat group headers only) | P1, P4 (dynamic wave sub-tasks appended to TodoWrite after initial projection, but no hook validates sub-task depth at initial projection time) |
| test | `test.tasklist_shown` + `test.native_tasklist_projected` declared; TASKLIST_POLICY block + HARD-GATE in slim entry | YES — bootstrap allowlist covers `vg:test:00_gate_integrity_precheck`, `vg:test:00_session_lifecycle` | 1 (flat group headers only) | P1 |
| accept | `accept.tasklist_shown` + `accept.native_tasklist_projected` declared; HARD-GATE + Tasklist policy in slim entry | YES — bootstrap allowlist covers `vg:accept:0_gate_integrity_precheck`, `vg:accept:0_load_config` | 1 (flat group headers only) | P1 |
| scope | `scope.tasklist_shown` + `scope.native_tasklist_projected` declared; HARD-GATE instructs TodoWrite before step-active | NO explicit bootstrap allowlist entries for scope pre-tasklist steps — hook falls through to `exit 0` if `contract_path` missing | 1 (flat group headers only) | P1, P5 (no bootstrap allowlist means hook never fires for scope runs where contract is missing) |
| deploy | `phase.deploy_started` + `phase.deploy_completed` declared; NO tasklist-related telemetry (`phase.deploy_started` ≠ `deploy.tasklist_shown`); NO `emit-tasklist.py` call in deploy steps; not in `CHECKLIST_DEFS` | NO — deploy has no emit-tasklist step, no TodoWrite instruction, no evidence file written, so hook has nothing to check | 0 (no tasklist at all) | P5 (entire flow is unmonitored for tasklist enforcement) |
| roam | `roam.tasklist_shown` + `roam.native_tasklist_projected` declared; HARD-GATE instructs TodoWrite; roam IS in `CHECKLIST_DEFS` | PARTIAL — no bootstrap allowlist entries for `vg:roam:0_parse_and_validate` or `vg:roam:0aa_resume_check`, so hook exits 0 if no active run | 1 (flat group headers only) | P1, P5 |

---

## Bypass pattern catalog

### Pattern 1: emit-handled-without-todowrite

**Trigger:** AI receives the `PreToolUse-tasklist` BLOCK when it calls `step-active` without a valid evidence file.

**Mechanism:** The diagnostic instructs the AI to emit `vg.block.handled` as the resolution step. The AI emits `vg-orchestrator emit-event vg.block.handled --gate PreToolUse-tasklist --resolution "..."` WITHOUT first calling TodoWrite or running `tasklist-projected`. This satisfies the diagnostic's "After fix" instruction textually, but leaves the evidence file still missing. The next `step-active` call blocks again, and the AI repeats the pattern. Events.db shows this cycling can continue indefinitely because the hook itself does not check for a `vg.block.handled` pairing.

**Evidence (from `commands/vg/_shared/lib/tasklist-projection-instruction.md`, lines 4-8):**
```
15+ such bypasses recorded in PV3 events.db. Bypassing the block (emitting
`vg.block.handled` without resolution) leaves evidence still missing —
next step-active blocks again.
```

**Root cause:** The `emit_block` function in `scripts/hooks/vg-pre-tool-use-bash.sh` (lines 203-298) writes a diagnostic that includes the resolution command `vg.block.handled` as the FINAL step ("After fix"), but the required fix (TodoWrite + tasklist-projected) is listed BEFORE it. An AI that pattern-matches "emit handled" as the fix rather than reading the full diagnostic will produce zero-evidence bypasses.

**Recommended fix:** Add a `vg.block.handled` validator that checks: if the most recent `vg.block.handled` references gate `PreToolUse-tasklist`, then `.tasklist-projected.evidence.json` MUST exist with a timestamp newer than the `vg.block.fired` event. If not, the next `step-active` should emit a HARD BLOCK exit 1 (not exit 2 diagnostic loop).

---

### Pattern 2: pre-tasklist bootstrap step ordering exploit

**Trigger:** Blueprint's `is_bootstrap_before_tasklist()` allowlist covers `vg:blueprint:1_parse_args` as a pre-tasklist step. This step in `_shared/blueprint/preflight.md` (lines 1-4) is listed as step 1.3 but `create_task_tracker` is step 1.4.

**Mechanism:** The hook at line 184-201 of `vg-pre-tool-use-bash.sh` exempts specific named steps from the evidence requirement. The list currently covers:
```
vg:blueprint:0_design_discovery
vg:blueprint:0_amendment_preflight
vg:blueprint:1_parse_args
vg:build:0_gate_integrity_precheck
vg:build:0_session_lifecycle
vg:test:00_gate_integrity_precheck
vg:test:00_session_lifecycle
vg:accept:0_gate_integrity_precheck
vg:accept:0_load_config
vg:review:00_gate_integrity_precheck
vg:review:00_session_lifecycle
```
Note: `vg:scope:*`, `vg:roam:*`, and `vg:deploy:*` are completely absent. An AI running `/vg:scope` can call any `step-active` step while contract is missing and the hook exits 0 (line 173-176: `if [ ! -f "$run_file" ]; then exit 0`).

**Evidence:** The hook's first check is whether `run_file` exists. If no active run is registered for the session (which can happen when scope/roam/deploy start), it exits 0 unconditionally, blocking nothing.

**Recommended fix:** Add bootstrap allowlist entries for scope/roam at minimum:
- `vg:scope:0_parse_and_validate`
- `vg:roam:0_parse_and_validate`
- `vg:roam:0aa_resume_check`

Additionally, deploy needs `emit-tasklist.py` + CHECKLIST_DEFS entry added to `scripts/emit-tasklist.py` before hook enforcement is possible.

---

### Pattern 3: step.active fires at same timestamp as tasklist_shown (no projection in between)

**Trigger:** AI calls `emit-tasklist.py` which fires `review.tasklist_shown`, then immediately calls `vg-orchestrator step-active` without ever calling TodoWrite.

**Mechanism:** Before Task 34, the review flow did not place the projection instruction before the first `step-active` call. Even post-Task 34, the hook only fires when the Bash PreToolUse hook intercepts the `step-active` shell command. If the AI does not use the hook-intercepted `vg-orchestrator step-active` path (e.g., direct orchestrator invocation that bypasses hook, or the run_file missing), the gate does not fire.

**Evidence (events.db, run `70ca6e31-54f9-4609-94a5-c1224a4ea15d`):**
```
70ca6e31|vg:review|review.tasklist_shown|2026-05-02T12:59:14Z
70ca6e31|vg:review|step.active           |2026-05-02T12:59:14Z
```
Same second. Zero `review.native_tasklist_projected` events appear in the entire database. The `step.active` payload shows step `phase2a_api_contract_probe` — a non-bootstrap step that should have been blocked.

**Root cause:** Run `70ca6e31` used a stale `run_file` from a prior session (`9b9ae753`). The hook resolved `run_file` from the prior session's `.vg/active-runs/session.json`, found a different `run_id` that had a contract, found no evidence file for that run_id, but did NOT block because `is_bootstrap_before_tasklist()` returned false AND the prior session's evidence file was present from a completed projection. Cross-session run binding creates evidence from a previous run satisfying the check for a new run.

**Recommended fix:** The HMAC verification in the hook (lines 315-346) currently compares `contract_sha` from the evidence against the current `tasklist-contract.json`. If a new run writes a new contract with a new SHA, the `contract_mismatch` path fires correctly. However, the `run_id` inside the evidence payload is not compared against the current run's `run_id`. Adding a run_id check to the HMAC verifier would close this cross-session reuse gap.

---

### Pattern 4: flat TodoWrite satisfies hook but violates 2-layer hierarchy requirement

**Trigger:** AI calls TodoWrite with only the 5-7 group-level checklist IDs (e.g., `review_preflight`, `review_be`, `review_discovery`, ...) and no sub-task items. The PostToolUse TodoWrite hook (`scripts/hooks/vg-post-tool-use-todowrite.sh`) signs the evidence.

**Mechanism:** The `vg-post-tool-use-todowrite.sh` hook (lines 36-44) performs a "tolerant match" — it checks only that group-level checklist IDs appear in the TodoWrite payload, ignoring sub-step coverage. A TodoWrite with 5 items mapping to the 5 group IDs produces `match=true` and writes a valid signed evidence file. This satisfies the PreToolUse hook completely.

However, sếp's requirement is that the tasklist have at least 2 layers (parent group + sub items for each step within the group). The slim entries' `TASKLIST_POLICY` sections describe this pattern (`↳ task-id: description` format), and build.md even mandates dynamic wave sub-task append. But neither the hook nor the orchestrator validates that the initial projection contained sub-items.

**Evidence:** `vg-post-tool-use-todowrite.sh` lines 36-44:
```bash
group_contents = [c for c in todo_contents if not c.lstrip().startswith("↳")]
matched_ids = set()
for content in group_contents:
    for c in checklists:
        if c["id"] in content or c["title"] in content:
            matched_ids.add(c["id"])
```
Sub-step content is explicitly filtered OUT from matching. No depth check exists anywhere in the hook or orchestrator.

**Recommended fix:** Add a `min_sub_items_per_group` check in the PostToolUse hook. If any group has 0 sub-items in the TodoWrite payload (i.e., no `↳` prefixed children), the hook should write evidence with `match=false` and a new field `depth_violation=true`. The PreToolUse hook should then treat `depth_violation=true` evidence as invalid, triggering the same BLOCK path as missing evidence.

---

### Pattern 5: deploy flow has zero tasklist enforcement surface

**Trigger:** User runs `/vg:deploy <phase>`.

**Mechanism:** The deploy slim entry (`commands/vg/deploy.md`) has no `emit-tasklist.py` call, no `TodoWrite` instruction, no `create_task_tracker` step, and no TASKLIST_POLICY block. The flow's `must_emit_telemetry` declares only `phase.deploy_started` and `phase.deploy_completed` — no `deploy.tasklist_shown` or `deploy.native_tasklist_projected`. The `scripts/emit-tasklist.py` `CHECKLIST_DEFS` dict (lines 76-248) has no `vg:deploy` entry. The `is_bootstrap_before_tasklist()` function in the hook has no deploy cases. Therefore:

1. No tasklist-contract.json is ever written for deploy runs.
2. No evidence file can be produced.
3. The hook's early exit (`if [ ! -f "$run_file" ]; then exit 0`) or the contract-missing path (`if is_bootstrap_before_tasklist; then exit 0` — which never triggers for deploy) allows all deploy `step-active` calls to pass unconditionally.

**Evidence:** `commands/vg/deploy.md` lines 13-28 — `must_emit_telemetry` contains only `phase.deploy_started` + `phase.deploy_completed`, and the entire 477-line file contains zero instances of "tasklist", "TodoWrite", or "emit-tasklist".

**Recommended fix:** (a) Add `vg:deploy` to `CHECKLIST_DEFS` in `scripts/emit-tasklist.py` with the 5 deploy steps. (b) Add `emit-tasklist.py` call + `TodoWrite` IMPERATIVE to deploy Step 0 (after `run-start`). (c) Add `deploy.tasklist_shown` + `deploy.native_tasklist_projected` to `must_emit_telemetry`. (d) Add `vg:deploy:0_parse_and_validate` to `is_bootstrap_before_tasklist()`.

---

## Hook gap analysis

**Current hook checks:**
1. Is `run_file` (`.vg/active-runs/${session_id}.json`) present? If not, exit 0 — passthrough.
2. Is the bash command a `vg-orchestrator step-active` call? If not, check for Codex pre-step broad scan and exit 0.
3. Is `contract_path` (`.vg/runs/${run_id}/tasklist-contract.json`) present? If not, check `is_bootstrap_before_tasklist()` and exit 0 or block.
4. Is `evidence_path` (`.vg/runs/${run_id}/.tasklist-projected.evidence.json`) present? If not, block.
5. Is `key_path` (`.vg/.evidence-key`) present? If not, block.
6. HMAC verify: does the evidence HMAC match? If not, block.
7. Contract SHA match: does evidence `contract_sha256` match current contract file? If not, block.

**Bypass-able by:**
- Calling `vg.block.handled` without performing the actual fix (P1 — no counter-check exists)
- Missing `run_file` — any invocation outside an active run exits 0 (affects deploy, roam without active run)
- Missing `contract_path` + step not in allowlist — blocks, but scope/roam/deploy bootstrap steps not in allowlist, so they pass
- Cross-session evidence reuse — evidence from a prior run with same contract SHA satisfies hook (P3 partially mitigated if contract changes; fully vulnerable if contract unchanged)
- TodoWrite with group-headers-only satisfies the evidence file production; evidence is valid but depth-violating (P4 — no hook check)
- Direct filesystem write to `.tasklist-projected.evidence.json` — BLOCKED by `vg-pre-tool-use-write.sh` (mentioned in blueprint.md Red Flags table, "Write evidence file trực tiếp cho nhanh")

**Recommended hardening:**
- Add `vg.block.handled` counter-check: when AI emits `vg.block.handled` for gate `PreToolUse-tasklist`, log the evidence file mtime. Next `step-active` check: if evidence is older than `block.handled` timestamp, re-emit block with escalated severity.
- Add `run_id` comparison to HMAC verifier (line 322-338) — evidence `payload.run_id` must match `run_id` from `run_file`.
- Add depth check to PostToolUse TodoWrite hook — each group in contract must have at least 1 `↳` sub-item in the TodoWrite payload.
- Add bootstrap allowlist entries for `vg:scope:*`, `vg:roam:0_parse_and_validate`, `vg:roam:0aa_resume_check`.
- Add full deploy tasklist infrastructure (CHECKLIST_DEFS + slim entry + telemetry declarations).

---

## Slim entry coverage gaps

**Which slim entries have `tasklist_template:` frontmatter?** Currently: NONE. No flow uses a `tasklist_template:` frontmatter key. All flows rely on `CHECKLIST_DEFS` in `scripts/emit-tasklist.py` for the checklist structure.

**Which need template ceiling vs syntactic-floor only?**

| Flow | Current enforcement floor | Needs ceiling (max depth) | Needs template (pre-defined sub-items) |
|---|---|---|---|
| review | group-header match (tolerant) | NO | YES — 5 groups with ~30 steps; template prevents flat projection |
| blueprint | group-header match (tolerant) | NO | YES — 6 groups with 18+ steps |
| build | group-header match (tolerant) | YES (dynamic wave sub-tasks must be appended, not pre-defined) | PARTIAL — static groups need template; wave children are dynamic |
| test | group-header match (tolerant) | NO | YES — 6 groups with 16+ steps |
| accept | group-header match (tolerant) | NO | YES — 5 groups with 15+ steps |
| scope | group-header match (tolerant) | NO | YES — 7 groups with 12+ steps |
| deploy | NONE | NO | YES — first-time add needed |
| roam | group-header match (tolerant) | NO | YES — 8 groups with 14+ steps |

**Recommended template content per slim entry (parent prefixes only):** The CHECKLIST_DEFS in `scripts/emit-tasklist.py` already defines the sub-step IDs per group. Task 44b should surface these sub-step IDs as required `↳ <step_id>` sub-items in the PostToolUse hook validation. The template is implicit in CHECKLIST_DEFS — no new file needed, just hook enforcement that validates projection_items depth >= 2 (group header + at least 1 sub-item).

---

## Task 44b implementation scope (recommended)

Concrete deliverables grounded in audit findings:

### 1. Validator rules

- **Rule V1 (evidence run_id binding):** Add `run_id` comparison to HMAC verifier block in `scripts/hooks/vg-pre-tool-use-bash.sh` (lines 315-338). Evidence `payload.run_id` must equal `run_id` from active run_file. Failure emits new event `<command>.tasklist_evidence_run_mismatch`. Estimated: +15 LOC in bash hook.

- **Rule V2 (depth check in PostToolUse):** Add sub-item depth validator to `scripts/hooks/vg-post-tool-use-todowrite.sh` (after line 44). For each contract checklist group, count TodoWrite items with matching `↳` prefix as children. If any group has 0 children, set `depth_valid=false` in payload. Write evidence with new field `depth_valid`. Estimated: +25 LOC in Python inline block.

- **Rule V3 (depth gate in PreToolUse):** Extend HMAC verifier in bash hook (after line 338) to check `depth_valid` field in evidence. If `depth_valid=false`, emit block with cause "tasklist depth=1 (flat); minimum required is 2-layer (group + sub-items)". Estimated: +10 LOC in bash hook.

- **Rule V4 (block.handled counter-check):** In `scripts/vg-orchestrator/__main__.py`, extend `cmd_emit_event` (or add new handler) to record `block.handled` timestamps. Next `cmd_step_active` reads this and validates evidence mtime > last `block.handled` for same gate. Estimated: +40 LOC in Python.

### 2. Hook upgrades

- **H1 (bootstrap allowlist):** Add `vg:scope:0_parse_and_validate`, `vg:roam:0_parse_and_validate`, `vg:roam:0aa_resume_check` to `is_bootstrap_before_tasklist()` in `scripts/hooks/vg-pre-tool-use-bash.sh` (line 184-201). Estimated: +5 LOC.

- **H2 (evidence run_id check):** See Rule V1 above — same file.

### 3. Slim entry frontmatter additions (per file)

- **commands/vg/deploy.md:** Add `deploy.tasklist_shown` + `deploy.native_tasklist_projected` to `must_emit_telemetry`. Add `TodoWrite` to `allowed-tools`. Add `create_task_tracker` marker to `must_touch_markers`. Add `<HARD-GATE>` block with TodoWrite IMPERATIVE. Insert `emit-tasklist.py` call into Step 0. Estimated: +30 LOC in deploy.md.

- **commands/vg/scope.md, review.md, blueprint.md, build.md, test.md, accept.md, roam.md:** Add inline note about 2-layer requirement to existing `<HARD-GATE>` block — "TodoWrite MUST include sub-items (↳ prefix) for each group; flat projection (group-headers only) will be rejected by PostToolUse hook depth check." Estimated: +5 LOC each = +35 LOC across 7 files.

### 4. emit-tasklist.py additions

- **scripts/emit-tasklist.py:** Add `vg:deploy` entry to `CHECKLIST_DEFS` (line 248) with groups: `deploy_preflight` (steps: `0_parse_and_validate`, `0a_env_select_and_confirm`), `deploy_execute` (steps: `1_deploy_per_env`), `deploy_close` (steps: `2_persist_summary`, `complete`). Estimated: +15 LOC.

### 5. Test cases needed (per validator rule)

- `tests/test_tasklist_depth_enforcement.py` — covers V2+V3: PostToolUse hook rejects flat projection (no `↳` items); PreToolUse blocks on depth_valid=false evidence. Similar structure to `tests/test_review_tasklist_projection.py`. Estimated: +80 LOC, 4 test functions.

- `tests/test_evidence_run_id_binding.py` — covers V1+R3: HMAC verifier rejects evidence from prior run when run_id in evidence != current run_id. Estimated: +60 LOC, 3 test functions.

- `tests/test_deploy_tasklist_enforcement.py` — covers H1+P5: deploy flow must emit tasklist_shown + native_tasklist_projected before step-active. Estimated: +50 LOC, 3 test functions.

- Extend `tests/test_review_tasklist_projection.py` — add test for block.handled-without-evidence cycle detection (V4). Estimated: +30 LOC, 2 test functions.

### 6. Override-debt severity classification per failure mode

| Failure mode | Classification | Rationale |
|---|---|---|
| Flat TodoWrite (depth=1, no sub-items) | CRITICAL — blocks step-active | Direct violation of sếp's 2-layer requirement |
| Missing native_tasklist_projected event | CRITICAL — blocks run-complete | Existing enforcement; no change |
| Cross-session evidence reuse | HIGH — blocks via new run_id check | Silent bypass that defeats HMAC purpose |
| emit-handled without resolution | HIGH — escalates to AskUserQuestion after 3x | Pattern 1; new counter-check needed |
| Deploy with no tasklist at all | MODERATE — warn until deploy tasklist infra ships | Infrastructure gap, not intentional bypass |

**Estimated LOC total for Task 44b:** 400-600 LOC across 12 files (8 existing + 4 new test files).

---

## Risks / open questions

1. **Deploy tasklist infra dependency:** `vg:deploy` does not call `vg-orchestrator run-start` consistently across all invocations (deploy Step 0 calls it, but `--merge-specs` path in roam.md exits before run-start). Verify run-start is always called before adding hook enforcement.

2. **Depth check tolerance for wave sub-tasks (build flow):** Build.md mandates dynamic sub-task append DURING wave execution, not at initial projection. The depth check (Rule V2) must tolerate a valid initial projection that has static group-level items only IF the evidence is refreshed (new TodoWrite + new evidence signing) when wave sub-tasks are appended. The hook currently allows only one evidence file per run. This needs clarification: does depth enforcement apply at initial projection or at each TodoWrite call?

3. **Scope flow `is_bootstrap_before_tasklist` ordering:** Scope preflight.md section 8 calls `emit-tasklist.py` inside a section that runs AFTER `vg-orchestrator run-start` but BEFORE `step-active 0_parse_and_validate`. The step name `0_parse_and_validate` for scope is NOT in the bootstrap allowlist, so if the AI calls `step-active 0_parse_and_validate` after run-start but before TodoWrite, it gets blocked correctly. However, if the contract file is missing (emit-tasklist.py not yet called), the hook blocks for the wrong reason. Adding `vg:scope:0_parse_and_validate` to the allowlist would be too permissive. The correct fix is to add the contract-missing guard specifically for scope's earliest step.

4. **PV3 historical bypass evidence:** The 15+ bypass count mentioned in `_shared/lib/tasklist-projection-instruction.md` is from PV3 (PrintwayV3 events.db), not the local repo's events.db which only has 142 events total. This audit is based on local events.db evidence; the patterns are structurally confirmed even if the count is lower locally.

5. **Roam `--merge-specs` short-circuit:** `commands/vg/roam.md` lines 105-116 show a `--merge-specs` path that exits before any pipeline step. This path calls `roam-merge-specs.py` directly without `run-start` or tasklist projection. Since it exits before hook-gated steps, this is acceptable — but the audit recommends a comment in the short-circuit block to make this intentional bypass explicit.
