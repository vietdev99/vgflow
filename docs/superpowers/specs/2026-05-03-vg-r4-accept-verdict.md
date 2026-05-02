# R4 Accept Pilot Verdict (template)

**Date:** 2026-05-03
**Phase:** _<filled at dogfood time>_
**Pilot scope:** R4 — slim `commands/vg/accept.md` (2,429 → 273 lines) +
10 refs + 2 subagents + 5 static tests.

---

## Static verification (in-repo, automated)

| # | Check | Result |
|---|---|---|
| 1 | `commands/vg/accept.md` ≤ 600 lines | ✅ 273 lines |
| 2 | All 10 refs exist in `commands/vg/_shared/accept/` | ✅ |
| 3 | 3 nested dirs exist (`uat/`, `uat/checklist-build/`, `cleanup/`) | ✅ |
| 4 | 2 subagents valid (uat-builder + cleanup) | ✅ |
| 5 | NO `vg-accept-uat-interactive` subagent (spec §1.2) | ✅ |
| 6 | Slim entry STEP 5 has no `Agent(subagent_type=...)` | ✅ |
| 7 | `interactive.md` HARD-GATE forbids subagent extraction | ✅ |
| 8 | Subagent SKILLs use vg-load for goals + design-refs | ✅ |
| 9 | R4 spawn-site refs don't cat large artifacts flat | ✅ |
| 10 | Runtime_contract preserves 17 step markers + 4 telemetry | ✅ |
| 11 | `accept.native_tasklist_projected` in must_emit_telemetry (audit FAIL #9 fix) | ✅ |
| 12 | `CHECKLIST_DEFS["vg:accept"]` matches accept.md markers | ✅ 5 groups, 17 IDs |

**Static result: 12/12 PASS.**

Pytest run: `python3 -m pytest scripts/tests/test_accept_*.py -v`
Result: **22 passed in 0.07s** (5 modules × 22 tests).

---

## Empirical dogfood (PrintwayV3 — TODO at next deploy)

Pick a phase with completed `build` + `review` + `test` artifacts, then:
```bash
cd /path/to/PrintwayV3
bash /Users/dzungnguyen/Vibe\ Code/Code/vgflow-bugfix/sync.sh
/vg:accept <phase>
```

Verify ALL 12 dogfood exit criteria:

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Tasklist visible in Claude Code UI immediately | _ | _ |
| 2 | `accept.native_tasklist_projected` event count ≥ 1 (baseline 0) | _ | events.db query |
| 3 | All 17 step markers touched without override | _ | `.step-markers/*.done` |
| 4 | UAT.md written with Verdict line (content_min_bytes met) | _ | `${PHASE_DIR}/${PHASE_NUMBER}-UAT.md` |
| 5 | `.uat-responses.json` present with all 6 sections + final verdict | _ | file inspection |
| 6 | UAT-builder subagent invocation event present | _ | events.db query |
| 7 | Cleanup subagent invocation event present | _ | events.db query |
| 8 | **Interactive UAT happened in main agent (NOT delegated)** ⚠ | _ | AskUserQuestion calls in main, NOT subagent |
| 9 | Quorum gate verifies responses (event present) | _ | `5_uat_quorum_gate.done` |
| 10 | Override-debt resolution gate ran (event present) | _ | `3c_override_resolution_gate.done` |
| 11 | Stop hook fires without exit 2 | _ | run-complete log |
| 12 | Stop hook unpaired-block-fails-closed test passes | _ | hook log |

**Critical: criterion 8 is non-negotiable.** Interactive UAT delegation
breaks UX continuity (spec §1.2). If criterion 8 fails, R4 pilot
**FAILS** even if other 11 pass.

---

## Verdict (filled at dogfood time)

**Static: PASS.**
**Empirical: PENDING DOGFOOD.**
**Overall: STATIC PASS — awaiting empirical validation on PrintwayV3.**

---

## Phase F Task 30 update

After this verdict lands with empirical dogfood PASS, update blueprint plan
Phase F Task 30 to remove `vg:accept` from scope. The vg:accept portion is
absorbed via:
- Task 4 (checklist-build delegation) — vg-load for goals
- Task 5 (narrative ref) — verbatim from backup, vg-load already in legacy step
- Task 8 (audit ref) — vg-load --priority for goals when writing UAT.md
- Task 11 (cleanup subagent) — no flat reads of split artifacts
- Task 15 (vg-load test) — enforces no flat reads in R4 surfaces

KEEP-FLAT allowlist documented in `delegation.md` for small single-doc
artifacts (CONTEXT.md, FOUNDATION.md, CRUD-SURFACES.md, RIPPLE-ANALYSIS.md,
SUMMARY*.md, build-state.log, GOAL-COVERAGE-MATRIX.md).

---

## Completion rate (filled at dogfood time)

Baseline: 36% (4/11 in PrintwayV3 — recon §1.4).
Target: ↑ from 36%.

Actual: _<N/M after dogfood>_

If completion rate ↓ instead of ↑, investigate:
1. Subagent return JSON parse errors — surface in 3-line block?
2. UAT narrative mismatched expectations — string layout drift?
3. Quorum gate too strict for new layout?
4. Cleanup subagent verdict mismatch — UAT_VERDICT parse logic correct?

---

## Files modified (commit summary)

```
chore(r4-accept): backup accept.md before slim refactor (2429 lines)
feat(r4-accept): preflight ref — 4 light steps
feat(r4-accept): gates ref — 3-tier preflight gates
feat(r4-accept): checklist-build refs — overview + delegation (HEAVY)
feat(r4-accept): narrative ref — 4b autofire UAT-NARRATIVE.md
feat(r4-accept): interactive ref — STAYS INLINE (UX requirement)
feat(r4-accept): quorum ref — critical-skip threshold gate
feat(r4-accept): audit ref — security + learn + UAT.md write
feat(r4-accept): cleanup refs — overview + delegation (HEAVY)
feat(r4-accept): vg-accept-uat-builder subagent
feat(r4-accept): vg-accept-cleanup subagent + post-subagent gates
refactor(r4-accept): slim entry — 2429 → 273 lines
test(r4-accept): static tests — slim + refs + 2 subagents (NOT 3)
test(r4-accept): assert step 5 interactive UAT stays inline (CRITICAL)
test(r4-accept): assert vg-load for goals + design-refs (Phase F Task 30)
docs(r4-accept): pilot verdict template + 12 criteria checklist
```

15 atomic commits. Each commit covers one logical unit per plan task.

---

## Sequencing note

This pilot is R4 (after R1 blueprint, R2 build+test, R3 review). Accept
depends on artifacts from build + review + test → must wait for those to
stabilize. Override-debt patterns may emerge from R1-R3 dogfood; R4 gates
inherit those refinements verbatim (no new gate types per spec §6.1).

---

## References

- Spec: `docs/superpowers/specs/2026-05-03-vg-accept-design.md` (311 lines)
- Plan: `docs/superpowers/plans/2026-05-03-vg-r4-accept-pilot.md`
- Backup: `commands/vg/.accept.md.r4-backup` (2429 lines, restorable)
- Tests: `scripts/tests/test_accept_*.py` (5 modules, 22 tests)
- Slim entry: `commands/vg/accept.md` (273 lines)
- Refs: `commands/vg/_shared/accept/` (10 files, 3 nested dirs)
- Subagents: `agents/vg-accept-{uat-builder,cleanup}/SKILL.md`
