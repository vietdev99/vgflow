# Interactive UAT — STEP 5 (INLINE, NOT subagent)

Maps to step `5_interactive_uat` (213 lines in legacy accept.md). The
human tester reviews 50+ items across 6 sections via `AskUserQuestion`.

<HARD-GATE>
This step MUST execute INLINE in the main agent. DO NOT spawn a subagent
for interactive UAT.

Why: `AskUserQuestion` is a UI-presentation tool. Subagent context handoff
breaks UX continuity — the tester would see disjointed prompts with no
shared narrative state. UX requirement (spec §1.2 of
`docs/superpowers/specs/2026-05-03-vg-accept-design.md`).

You MUST write `${PHASE_DIR}/.uat-responses.json` after EACH of the 6
sections (anti-theatre, OHOK Batch 3 B4). Quorum gate (STEP 6) blocks if
the file is missing or any required section is empty.

NEVER paraphrase TEST-GOALS items during AskUserQuestion — refer to the
`UAT-NARRATIVE.md` rendered in STEP 4 for canonical phrasing.
</HARD-GATE>

---

<step name="5_interactive_uat">
**Run interactive checklist — one item at a time.**

For each section:

### A. Decisions
For each line in `${VG_TMP}/uat-decisions.txt`:
```
AskUserQuestion:
  "Decision {ID} (P{phase}.D-XX from CONTEXT, or legacy D-XX): {title}
   Was this implemented as specified in CONTEXT.md?

   [p] Pass — verified in code/runtime
   [f] Fail — not implemented correctly (note the issue)
   [s] Skip — cannot verify right now (deferred)"
```

### B. Goals
For each line in `${VG_TMP}/uat-goals.txt` where status = READY:
```
AskUserQuestion:
  "Goal {G-XX}: {title}   [STATUS: READY per coverage matrix]
   Verified working in runtime?

   [p] Pass — functions as TEST-GOALS.md success criteria
   [f] Fail — doesn't work / wrong behavior
   [s] Skip — not testable here (deferred)"
```

For BLOCKED/UNREACHABLE goals: show info block, no question asked:
```
  ⚠ Goal {G-XX}: {title}   [STATUS: BLOCKED/UNREACHABLE]
      Known gap — not gated here. Address in next phase or /vg:build --gaps-only.
```

### C. Ripple acknowledgment (MANDATORY if any HIGH callers)

**If `uat-ripples.txt` contains `RIPPLE_SKIPPED=true`** (graphify was unavailable):
```
⚠ Cross-module ripple analysis was SKIPPED (graphify unavailable during review).
  Downstream callers of changed symbols were NOT checked.
  Manual regression testing of affected modules is strongly advised.

  [y] Acknowledged — I will manually verify affected modules
  [s] Accept risk — proceed without ripple verification (recorded in UAT.md)
  [n] Abort — need to enable graphify and re-run /vg:review first
```

**Otherwise**, present the list, ask single acknowledgment question:
```
AskUserQuestion:
  "Ripple callers (HIGH severity) that were NOT updated in this phase:

   [list first 10, + '... and N more' if > 10]

   Each should have been manually reviewed or explicitly cited.
   Have you verified these callers still work with the changed symbols?

   [y] Yes — verified (per RIPPLE-ANALYSIS.md + code review)
   [n] No — need to review before accepting (ABORT UAT)
   [s] Skip — accept risk (record in UAT.md)"
```

If `n` → abort UAT, write UAT.md status = `DEFERRED_PENDING_RIPPLE_REVIEW`.

### D. Design fidelity (if design refs exist)

**P19 D-06 — strict 3-file inspection when L4 produced diffs.** If
`${PHASE_DIR}/visual-fidelity/{ref}.diff.png` exists (the L4 review SSIM
gate produced a baseline-vs-current diff), surface ALL THREE files in the
prompt so the user can open them side-by-side. Reject = phase not
acceptable (returns to /vg:build with override-debt logged).

For each unique design-ref in `${VG_TMP}/uat-designs.txt`:

```bash
# v2.30+ 2-tier resolver — try phase-scoped first, shared fallback, legacy last
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/design-path-resolver.sh"
BASELINE_PNG="$(vg_resolve_design_ref "{ref}" "screenshots/{ref}.default.png" "$PHASE_DIR" 2>/dev/null)"
if [ -z "$BASELINE_PNG" ]; then
  # Legacy compat absolute path for human-readable error
  DESIGN_DIR_REL_UAT="$(vg_design_legacy_dir 2>/dev/null || echo .vg/design-normalized)"
  BASELINE_PNG="${REPO_ROOT}/${DESIGN_DIR_REL_UAT}/screenshots/{ref}.default.png"
fi
DIFF_PNG="${PHASE_DIR}/visual-fidelity/{ref}.diff.png"
CURRENT_PNG="${PHASE_DIR}/visual-fidelity/{ref}.current.png"

if [ -f "$DIFF_PNG" ]; then
  PROMPT_BODY="Design ref: {ref}
   THREE files to open side-by-side (P19 D-06):
     baseline:  ${BASELINE_PNG}
     current:   ${CURRENT_PNG}
     diff:      ${DIFF_PNG}
   The diff PNG highlights pixel mismatches in red.
   Built output matches design (layout, spacing, components, copy)?"
else
  PROMPT_BODY="Design ref: {ref}
   Screenshot: ${REPO_ROOT}/${DESIGN_DIR_REL_UAT}/screenshots/{ref}.default.png
   (No L4 diff PNG produced — review browser may not have captured this view.)
   Built output matches screenshot (layout, spacing, components)?"
fi
```

```
AskUserQuestion:
  "${PROMPT_BODY}

   [p] Pass — visual match
   [f] Fail — significant drift (describe; logs override-debt kind=human-rejected-design)
   [s] Skip — no design ref available / cannot verify"
```

**Fail handling (P19 D-06):** if user picks `f` for any ref, write to
override-debt register (`kind=human-rejected-design`, severity=critical)
and abort UAT with status `REJECTED_DESIGN_DRIFT`. User must `/vg:build`
again to fix; debt entry resolved when rerun yields PASS.

**Mobile extension** (runs ONLY when `$PROFILE` matches `mobile-*`):
For each simulator/emulator screenshot in `${VG_TMP}/uat-mobile-screenshots.txt`:
```
AskUserQuestion:
  "Simulator capture: {path}
   Captured by /vg:review phase2_mobile_discovery. Compare against closest
   design-ref (above) — does the running app match the intended layout?

   [p] Pass — visual match vs design-ref
   [f] Fail — drift (typography, color, spacing, or content off)
   [s] Skip — no matching design-ref to compare against"
```
If no screenshots exist (host lacked simulator/emulator), inform user:
```
  ⚠ No mobile screenshots captured — host OS/tooling could not run simulator/emulator.
    Section D mobile sub-checks skipped (expected on Windows for iOS).
```

### E. Deliverables (informational only — no per-item question)
Present `${VG_TMP}/uat-summary.txt` as a final summary block. No questions.

### F. Mobile gates (mobile profiles only — skipped for web)

Present the gate table from `${VG_TMP}/uat-mobile-gates.txt`. Example:
```
  G6  permission_audit        passed
  G7  cert_expiry             skipped (disabled)
  G8  privacy_manifest        passed
  G9  native_module_linking   skipped (no-tool)
  G10 bundle_size             passed
```

Plus security audit findings (if any) from `${VG_TMP}/uat-mobile-security.txt`:
```
  CRITICAL|hardcoded_secrets|3 match(es) — see mobile-security/hardcoded-secrets.txt
  MEDIUM|weak_crypto|1 MD5 usage — see mobile-security/weak-crypto.txt
```

```
AskUserQuestion (once, covers entire Section F):
  "Mobile gate outcomes look correct for this phase?
   (e.g. 'cert_expiry skipped because no signing yet' = OK if pre-release;
    'hardcoded_secrets=3' requires explanation before accept)

   [y] Acknowledged — outcomes match phase intent
   [n] Not OK — gate output points to an actual issue (ABORT / REJECT)
   [s] Skip — accept risk (record in UAT.md)"
```

If `n` → abort UAT, set phase verdict = REJECTED with reason `mobile-gate-review-fail`.

After all sections, present totals:
```
UAT Progress:
  Decisions (A):     {N} passed / {N} failed / {N} skipped
  Goals (B):         {N} passed / {N} failed / {N} skipped (+ {N} known gaps)
  Ripples (C):       {acknowledged | abort | accepted-risk}
  Designs (D):       {N} passed / {N} failed / {N} skipped  ({Nmob} mobile screenshots)
  Mobile gates (F):  {acknowledged | rejected | risk-accepted}  [only for mobile-*]
```

### Final verdict question
```
AskUserQuestion:
  "Overall phase verdict?

   [a] ACCEPT — phase complete (all critical items pass)
   [r] REJECT — issues found, need /vg:build --gaps-only
   [d] DEFER — partial accept, revisit later (record open items)"
```

### Response persistence (OHOK Batch 3 B4 — REQUIRED for quorum gate)

**AI MUST write each AskUserQuestion response to `${PHASE_DIR}/.uat-responses.json` immediately after the user answers.** This is the source of truth read by step `5_uat_quorum_gate` below. Without persistence, the quorum gate BLOCKs (treats unset state as "user skipped everything").

Format:
```json
{
  "decisions": {"pass": 0, "fail": 0, "skip": 0, "items": [{"id": "P7.D-01", "verdict": "p|f|s", "ts": "..."}]},
  "goals": {"pass": 0, "fail": 0, "skip": 0, "items": [{"id": "G-01", "status_before": "READY", "verdict": "p|f|s", "ts": "..."}]},
  "ripples": {"verdict": "y|n|s|acknowledged|risk-accepted", "ts": "..."},
  "designs": {"pass": 0, "fail": 0, "skip": 0, "items": [{"ref": "sites-list.default", "verdict": "p|f|s", "ts": "..."}]},
  "mobile_gates": {"verdict": "y|n|s", "ts": "..."},
  "final": {"verdict": "ACCEPT|REJECT|DEFER", "ts": "..."}
}
```

AI can write/update this JSON via Bash heredoc after each section completes. Missing sections that are N/A for this profile (e.g. mobile_gates for web) should be omitted or set to `{"verdict": "n/a"}`.

```bash
mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5_interactive_uat" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5_interactive_uat.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step accept 5_interactive_uat 2>/dev/null || true
```
</step>
