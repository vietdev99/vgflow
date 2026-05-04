# review crossai (STEP 8 — UNCHANGED behavior)

Single step `crossai_review` invokes the cross-AI verification loop on
the review verdict (RUNTIME-MAP + GOAL-COVERAGE-MATRIX + TEST-GOALS).
Per spec §1.5 non-goals, **R3 does NOT refactor CrossAI** — content
extracted verbatim. CrossAI loop refactor is a separate concern post-R3.

vg-load convention: any AI-context loads of phase artifacts inside the
shared crossai-invoke.md helper (e.g., per-goal verification when
council members ask for context) should call
`vg-load --phase ${PHASE_NUMBER} --artifact <plan|contracts|goals> --goal G-NN`
instead of flat reads. Update happens inside crossai-invoke.md (out of
scope for this ref) or in council member prompts (Phase A — deferred).

---

## STEP 8 — crossai_review

<step name="crossai_review" mode="full">
## CrossAI Review (mandatory when CLIs are configured)

**If config.crossai_clis is empty, emit an explicit skip note and continue.**
**If --skip-crossai is present, it must have override-debt evidence because
objective review is otherwise a silent quality downgrade.**

Prepare context with RUNTIME-MAP + GOAL-COVERAGE-MATRIX + TEST-GOALS.
Set `$LABEL="review-check"`. Follow crossai-invoke.md.

Required evidence when not skipped:
- `${PHASE_DIR}/crossai/review-check.xml`
- `crossai.verdict` telemetry event
</step>
