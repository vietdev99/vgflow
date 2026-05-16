# Codex Audit — B68 Cascade Post-Build Gates

**Date:** 2026-05-16
**Verdict:** BLOCK

## BLOCKER findings (must fix before tag v4.56.0)

1. **`postmortem_done` is read but never enforced.** The hook sets it at `scripts/hooks/vg-stop.sh:98-99`, but 4c only checks `crossai_done` and `run_complete_done` at `scripts/hooks/vg-stop.sh:122`. A run with CrossAI + run_complete markers but no `10_postmortem_sanity.done` passes B68 Stop, violating `close.md:14-26`. Fix: block when `postmortem_done=0 || run_complete_done=0`, or add 4d.

2. **`12_run_complete.done` is not truly canonical.** B68 treats it as done at `scripts/hooks/vg-stop.sh:120-123`, but `close.md` touches it at `commands/vg/_shared/build/close.md:275-277`, before later validators and actual `vg-orchestrator run-complete` at `close.md:818-821`. If AI stops after marker write but before real run-complete, 4c will not fire. Fix: move marker after run-complete or check completed run state/event.

## MAJOR concerns

1. **CrossAI evidence is marker-only in B68.** 4b checks only `11_crossai_build_verify_loop.done` (`scripts/hooks/vg-stop.sh:96-115`). The docs require events.db evidence (`crossai-loop.md:10-17`, `:31-37`), and the validator requires `build.crossai_iteration_started` plus terminal event (`scripts/validators/build-crossai-required.py:9-18`, `:129-133`). B68 does not catch marker-without-events unless STEP 7.2 is reached. Also 4b says `crossai.verdict`, but build emits `build.crossai_iteration_*` / `build.crossai_loop_complete` (`scripts/vg-build-crossai-loop.py:23-30`, `:478`, `:606`, `:622`).

2. **Tests are shallow.** `tests/test_batch68_cascade_post_build_gates.py:47-124` checks strings/order/mirror parity, not state combinations: postmortem missing, CrossAI marker without events, early `12_run_complete.done`, or missing `.is-final-wave` on partial waves.

## MINOR concerns

- `is_final_wave=true` default protects full builds but can false-block if a mid-wave stop happens before `.is-final-wave=false` is written (`vg-stop.sh:102-103`, `waves-overview.md:1325-1367`).
- Prompt clarity is close, but 4b should name real build events/validator, and 4c should not call the marker canonical until moved after actual run-complete.
- Mirror parity is OK; both hook copies match and test asserts equality at `tests/test_batch68_cascade_post_build_gates.py:102-103`.

## Checklist
| Concern | Status |
|---|---|
| Cascade ordering | OK |
| is_final_wave default | RISK |
| postmortem_sanity gap | BLOCK |
| crossai.verdict event vs marker | RISK |
| Mirror parity | OK |
| Profile skip legitimate | OK |
| Partial-wave guard | OK |
| Mid-build Stop FP | RISK |
| Marker race | RISK |
| Prompt clarity | RISK |
| Reflector scope | OK |
| Frontend-only CrossAI skip | OK |

---
**Auditor:** Codex CLI v0.130.0 (--tier adversarial --sandbox read-only). 2026-05-16. Content emitted to stdout due to sandbox; orchestrator persisted.
