# R2 Test Pilot Verdict

**Date:** 2026-05-03
**Phase:** 3.2 (target dogfood project: PrintwayV3)
**Pilot plan:** `docs/superpowers/plans/2026-05-03-vg-r2-test-pilot.md`
**Branch:** `feat/rfc-v9-followup-fixes`

## Static deliverables (Tasks 1-17) — DELIVERED ✅

| Item | Verified | Evidence |
|---|---|---|
| `commands/vg/.test.md.r2-backup` (4188 lines) | ✅ | commit `84c1033` |
| `commands/vg/test.md` slim entry (285 lines, ≤600 ceiling) | ✅ | commit `b654787` |
| 12 `_shared/test/` refs (2 nested dirs: `goal-verification/`, `codegen/`) | ✅ | commits b622259, a339967, 5264f30, 2ae7dee, 9ff7f8c, 942f7f3, 94d66d3, d57e733 |
| 2 custom subagents (`vg-test-codegen`, `vg-test-goal-verifier`) | ✅ | commits 5d7594b, 620ca88 |
| `Task` → `Agent` swap in `allowed-tools` | ✅ | b654787 |
| `test.native_tasklist_projected` declared in `must_emit_telemetry` | ✅ | preserved from backup, line 75 of slim entry |
| 5 R2 pytest files (29 passed + 5 xpassed = 34/34) | ✅ | commits 6164057, 8f74e93, 3fe0ad0, 23b97dc |
| L1/L2 binding gate spec in `codegen/delegation.md` | ✅ | commit 9ff7f8c, lines 315-370 |
| `5d_binding_gate` folded into subagent (NOT marked at orchestrator) | ✅ | commit 9ff7f8c (delegation.md F.3) |
| `vg-load` injection in `runtime.md` (5b contract enumeration) | ✅ | commit 5264f30 lines 33-47 |
| Dual-mode goal verification (TRUST_REVIEW=true default + legacy replay) | ✅ | commits 2ae7dee, 620ca88 |
| sync.sh covers test files + subagents (auto via tree sync, no change needed) | ✅ | sync.sh line 197 (`scripts/`) + line 256 (`agents/`) |
| `CHECKLIST_DEFS["vg:test"]` (6 groups, 27 markers) | ✅ | already present in `scripts/emit-tasklist.py` lines 181-206 |

## Task 18 dogfood (PrintwayV3 `/vg:test 3.2`) — PENDING

The 11 exit criteria require a live runtime invocation of `/vg:test 3.2` against PrintwayV3 from a Claude Code session opened in that project. This is a user-driven action, not an automated check.

### Operator runbook

```bash
# 1. Sync vgflow into PrintwayV3
cd /path/to/PrintwayV3
bash /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix/sync.sh

# 2. Open PrintwayV3 in Claude Code, then in chat:
/vg:test 3.2 --profile=web-fullstack
```

### 11 exit criteria (per spec §6.4)

| # | Criterion | Method |
|---|---|---|
| 1 | Tasklist visible in Claude Code UI immediately | Visual confirmation |
| 2 | **`test.native_tasklist_projected` event count ≥ 1** (baseline 0 — critical fix) | `vg-orchestrator query-events --event-type test.native_tasklist_projected` |
| 3 | All 13 hard-gate step markers touched without override | Inspect `${PHASE_DIR}/.step-markers/` |
| 4 | `SANDBOX-TEST.md` written with explicit pass/fail verdict per goal | `cat ${PHASE_DIR}/SANDBOX-TEST.md` |
| 5 | Codegen subagent invocation event present (spec.ts files written) | `ls ${PHASE_DIR}/tests/*.spec.ts` |
| 6 | Goal-verifier subagent invocation event present | `vg-orchestrator query-events --event-type ` test.goals_verified |
| 7 | Deep-probe spawn (existing pattern) still fires correctly | Inspect run log |
| 8 | Console monitoring fires after every action (existing log) | Inspect run log |
| 9 | Stop hook fires without exit 2 | Check session end |
| 10 | Manual: simulate skip TodoWrite → PreToolUse hook blocks | Manual test |
| 11 | Stop hook unpaired-block-fails-closed test passes | Existing test pattern |

### Critical gate

If criterion 2 still measures 0 events post-dogfood: R2 test pilot FAILS, slim entry's TodoWrite imperative requires investigation. Do NOT proceed to R3 review pilot.

## Verdict

**PENDING_DOGFOOD** — Static deliverables complete. Runtime verification (criterion 2 + the other 10 checks) requires manual `/vg:test 3.2` execution in PrintwayV3.

## Phase F Task 30 update

After PASS verdict lands, update `docs/superpowers/plans/2026-05-03-vg-r1a-blueprint-pilot.md` Phase F Task 30 to remove `vg:test` from scope (it's been absorbed via Tasks 5, 6, 7, 8, 15 of this pilot).

## Sequencing

R2 bundle = build pilot + test pilot. Test pilot static portion ✅ complete (this doc). Build pilot static portion was completed earlier on this branch (commit `766f044` etc). Both bundle items now await dogfood verification before R3 review pilot proceeds.

## Pre-existing test failures (not caused by R2 test pilot)

The full pytest sweep (`pytest scripts/tests/`) shows ~862 failures + 116 collection errors. Sample of these:
- `test_test_requirements.py` — looks for `/Users/dzungnguyen/Vibe Code/Code/.claude/scripts/...` (parent of repo root, not repo root)
- `test_tasklist_visibility.py` — 6 tests look for old projection-format strings (`test_preflight` literal id) replaced by friendly titles in commit `30c9a05 feat(tasklist): hierarchical projection`
- `test_allow_flag_signed_tokens.py`, `test_contract_antiforge.py`, `test_executor_context_scope.py`, `test_keychain_load.py`, `test_prompt_capture.py`, `test_skill_invariants.py` — same path-resolution bug

These are pre-existing drift in the test suite. R2 test pilot tests (`test_test_native_tasklist_projected.py`, `test_test_slim_size.py`, `test_test_references_exist.py`, `test_test_subagent_definitions.py`, `test_test_uses_vg_load.py`) all pass cleanly: 29 passed + 5 xpassed = 34/34.
