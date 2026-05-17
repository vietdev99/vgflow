# Codex Adversarial Audit Prompt — B70 Plan

You are an adversarial code reviewer auditing an implementation plan for VGFlow harness. Your job: find FLAWS, BLOCKERS, MAJORS, MINORS. Be skeptical. Do not validate; attack.

## Plan to audit

(See attached `dev-phases/B70-legacy-pipeline-state-migration/PLAN.md`)

## Context

VGFlow is a deterministic harness for SDLC pipeline (specs → scope → blueprint → build → review → test-spec → test → accept). Each phase has a slash command (`/vg:specs`, `/vg:scope`, etc.) and emits markers + state file (`PIPELINE-STATE.json`) consumed by next phase / `/vg:next` router.

B69 (already shipped v4.61.0/v4.61.1) added next_command emit to review/close.md → /vg:test-spec routing.

B70 (this plan) addresses 3 fallout issues:
1. Legacy phases pre-v4.61.0 never emit PIPELINE-STATE.next_command → backfill migration.
2. /vg:next fallback silent → BLOCK gate.
3. Stale .recon-state.json from prior phase step → invalidate on review close.

## Repo facts (relevant)

- Mirror: `commands/vg/*` mirrored to `.claude/commands/vg/*` (Claude Code) and `codex-skills/` (Codex). Mirror parity test enforced.
- Phase dir: `.vg/phases/${NN}-${slug}/`
- State files: `PIPELINE-STATE.json` (phase-level), `.recon-state.json` (per-step recon), `STATE.md` (project-level).
- Migrations dir: does NOT exist yet (B70 creates it).
- session-start hook: `scripts/hooks/vg-session-start.sh` (174 lines) — runs on every session start (matcher `startup|resume|clear|compact`).
- Tests: pytest, fixtures under `tests/fixtures/`.

## Audit deliverable

Output structured markdown:

```markdown
# B70 Plan — Codex Audit

**Verdict:** PASS | PASS-WITH-NOTES | FAIL

## BLOCKERS (must fix before B70a)
- **ID-1:** [title] — [problem] — [fix]
- ...

## MAJORS (integrate into batch scope)
- **ID-1:** [title] — [problem] — [recommendation]
- ...

## MINORS (note for follow-up)
- **ID-1:** [title] — [observation]
- ...

## Coverage gaps
- [test coverage missing for X]

## Risk assessment
- [overall risk + key concerns]
```

## Specific attack vectors to probe

1. **Heuristic correctness:** artifact-presence → step-done detection — what false positives/negatives can occur? E.g. phase has REVIEW.md from previous run but build failed mid-way → wrong next_command emitted?
2. **Race conditions:** session-start hook running migration while another session is mid-write to same file?
3. **Schema drift:** backfilled PIPELINE-STATE.json schema diverges from close.md write schema → consumers fail later?
4. **Idempotency:** running migration N times — does it stay stable? Edge cases (corrupted state file written by prior failed migration)?
5. **BLOCK gate edge cases:** What if user is mid-/vg:review (review.md exists but state mid-write)? BLOCK fires falsely?
6. **recon-state invalidate:** Are there legitimate cases where review/close should NOT invalidate the recon-state next_command? What if recon-state was just freshly written by review preflight?
7. **Mirror parity:** New file `scripts/migrations/v4.61.0_backfill_pipeline_state.py` — does it need mirroring? (Currently only `commands/` + `skills/` mirror, scripts/ does not — confirm.)
8. **Cross-platform:** Windows path handling in migration script + hook bash invocation.
9. **Version bump scheme:** v4.62.0 / v4.62.1 / v4.62.2 — is this canonical? Should they be one v4.62.0 bundle?
10. **Test count adequacy:** 14+6+5 = 25 tests. Coverage holes?

Output ONLY the markdown audit. No preamble.
