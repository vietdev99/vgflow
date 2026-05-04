# build post-execution (STEP 5 — HEAVY)

<!-- # Exception: oversized ref (~948 lines) — extracted verbatim from backup
     spec lines 3030-3925; ceiling 980 in test_build_references_exist.py
     per audit doc docs/audits/2026-05-04-build-flat-vs-split.md. Verbatim
     preserves the i18n/a11y/cross-phase-ripple/L2-L6 fidelity sequence
     intact; future refactor splits the L2-L6 gate slate into its own ref.
     R2 round-2 expanded the post-spawn validator with BUILD-LOG layer
     enforcement (build_log_path/sha/index/sub_files). -->

This is the orchestrator-side body of the build pipeline's
post-execution step (`9_post_execution`). It is heavy: backup spec
~896 lines (backup lines 3030-3925), drives the i18n/a11y UX gates,
cross-phase ripple analysis, reflection-coverage verification, final
full-repo gate matrix (typecheck/build/unit/regression/spec-sync),
SUMMARY.md aggregation + commit, schema validation, API-DOCS
generation, and the L2/L3/L5/L6 design-fidelity gates.

Read `post-execution-delegation.md` for the input/output JSON
contract of the `vg-build-post-executor` subagent. This file
describes the orchestrator's responsibilities ONLY — pre-spawn
checklist, spawn site narration, post-spawn validation of returned
JSON, marker emission.

<HARD-GATE>
You MUST spawn ONE `vg-build-post-executor` subagent (NOT parallel —
this verifier walks all task results sequentially). You MUST NOT
verify inline. Single Agent() call in this step. The spawn-guard
(`scripts/vg-agent-spawn-guard.py`) enforces single-spawn for
`vg-build-post-executor` (R6 Task 3): a 2nd
`Agent(subagent_type="vg-build-post-executor")` call in the same run
is hard-denied. Counter persisted at
`.vg/runs/<run_id>/.post-executor-spawns.json`.

You MUST narrate the spawn via `bash scripts/vg-narrate-spawn.sh`
(green pill per R1a UX baseline Req 2) — `spawning` before the
Agent() call, `returned` on success, `failed` on error JSON. Skipping
narration breaks operator UX visibility but does NOT block.

The post-executor returns a JSON envelope. You MUST validate that
`gates_passed[]` includes `L2`, `L3` (when any task carried
`design_ref`), `L5`, `L6` (when any task carried `design_ref`), and
`truthcheck` BEFORE writing the step marker. You MUST also validate
that `summary_path` exists on disk and `sha256sum ${summary_path}`
matches `summary_sha256`. Marker write WITHOUT this validation is a
HARD VIOLATION — review/test/accept downstream consumes
SUMMARY.md and trusts gates_passed; drift here corrupts the entire
phase tail.
</HARD-GATE>

---

## Step ordering

1. **Pre-spawn checklist** (this file, sections below) — mark step
   active, run UX gates (i18n/a11y), cross-phase ripple, reflection
   coverage verify, step-marker check, final-gate matrix
   (typecheck/build/unit/regression), aggregate per-task results,
   verify per-task fingerprints exist (fail-fast), enumerate inputs
   for the subagent envelope.
2. **Spawn site** — narrate + spawn ONE `vg-build-post-executor` in a
   single Agent() call, then narrate return/failure.
3. **Post-spawn validation** — validate returned JSON shape, gates,
   summary path + sha256, then commit SUMMARY.md + state files,
   schema-validate SUMMARY.md, generate API-DOCS.md, write step
   marker.

---


---

## Section map (Anthropic Skill progressive disclosure)

This file is the slim entry. Heavy content lives in two sibling refs;
read them in order:

1. **`post-execution-spawn.md`** — Pre-spawn checklist (Steps 1-11) +
   Spawn site (single Agent() call + Codex variant). Contains all the
   bash gates that run BEFORE the post-executor subagent fires:
   per-wave aggregate, UX gates (i18n + a11y), cross-phase ripple,
   reflection coverage, step filter marker check, final gate matrix
   (typecheck/build/unit), regression gate, spec sync, VG-native
   state update, per-task fingerprint existence (fail-fast),
   subagent envelope inputs.

2. **`post-execution-validation.md`** — Post-spawn validation of the
   returned JSON (R2 round-2 BUILD-LOG layer enforcement: `gates_passed`
   coverage, summary path + sha256 match, `build_log_path/sha/index/sub_files`
   contract), L4a deterministic phase-level gates (FE↔BE call graph,
   contract shape, spec drift), SUMMARY.md commit, schema validation,
   API-DOCS.md generation + coverage verify.

After both sub-refs complete, write the `9_post_execution` marker
using the snippet at the end of THIS file (`## Step exit + marker`).

---

## Pre-spawn checklist

→ See `post-execution-spawn.md`. Run all 11 sub-steps in order.

---

## Spawn site

→ See `post-execution-spawn.md` (Spawn site section). Single
`Agent(subagent_type="vg-build-post-executor")` call. Spawn-guard
(`scripts/vg-agent-spawn-guard.py`) hard-denies a 2nd spawn per
`vg-build-post-executor` (R6 Task 3).

---

## Post-spawn validation

→ See `post-execution-validation.md`. Validate returned JSON BEFORE
writing the step marker. Do NOT skip — review/test/accept downstream
trusts the validated SUMMARY.md and BUILD-LOG layer artifacts.

---

## Step exit + marker

```bash
# v2.2 — step marker for runtime contract
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "9_post_execution" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/9_post_execution.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 9_post_execution 2>/dev/null || true
```

After step 9 marker touched, return to entry `build.md` → STEP 6
(`10_postmortem_sanity`).
