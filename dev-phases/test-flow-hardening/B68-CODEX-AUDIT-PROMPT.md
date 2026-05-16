# Codex Audit — B68 Cascade Post-Build Continuation Gates

You audit a SHIPPED change BEFORE tag. Patch already applied at
`scripts/hooks/vg-stop.sh:77-138` (current HEAD, not committed yet).

## User pain (verbatim Vietnamese)

> "vẫn còn tình trạng bỏ quên các bước sau khi build trong flow build,
> không cross ai check, không làm các step sau mà chỉ thông báo là
> đã build xong"

User reports `/vg:build` flow still skips post-build steps. AI marks
STEP 5 (post_execution) done then ends turn — CrossAI never runs,
run_complete never written, "build done" announced prematurely.

## Prior fix gap

v4.21.0 hotfix d19403d added Stop hook check #4 catching STEP 5
missing. But ONLY STEP 5. After STEP 5 done, AI can still end turn
before STEP 6 (CrossAI) or STEP 7 (close). User's symptom matches
this case.

## B68 patch summary

scripts/hooks/vg-stop.sh post-wave block extended with 2 cascade checks:

- **4a (existing)**: waves_done > 0 + 9_post_execution missing +
  is_final_wave=true → BLOCK "STEP 5 not run"

- **4b (NEW)**: 9_post_execution done + 11_crossai_build_verify_loop
  missing + is_final_wave=true → BLOCK "STEP 6 CrossAI not run.
  References crossai-loop.md HARD-GATE. events.db crossai.verdict
  event required."

- **4c (NEW)**: 11_crossai_build_verify_loop done + 12_run_complete
  missing + is_final_wave=true → BLOCK "STEP 7 close not run.
  12_run_complete is CANONICAL build-truly-done marker. Don't
  announce 'build done' before run_complete exists."

Read the actual patch:
- `scripts/hooks/vg-stop.sh:77-138` (full post-wave block)

## Audit checklist

For each concern, mark OK / RISK / BLOCK:

1. **Cascade ordering**: 4a fires before 4b fires before 4c.
   Could AI race past multiple steps and skip checks? Stop hook
   re-fires each turn-end so cascade should work — verify reasoning.

2. **is_final_wave default = "true"**: When `.is-final-wave` file
   missing → default true. Could legitimately partial-wave run get
   blocked because file missing/race?

3. **10_postmortem_sanity marker not gated**: B68 added crossai_done +
   run_complete_done + postmortem_done VARS but doesn't actually
   block on postmortem missing. Bug — should add check 4d or fold
   into 4c.

4. **CrossAI as HARD-GATE**: crossai-loop.md says CrossAI is HARD-GATE
   with events.db `crossai.verdict` event required at run-complete.
   Does B68 catch case where 11_crossai marker exists BUT
   crossai.verdict event missing? Likely no — marker presence ≠
   verdict event.

5. **Cross-mirror parity**: vg-stop.sh has `.claude/scripts/hooks/`
   mirror. Mirrored?

6. **Profile mode interaction**: build.md supports profiles
   (web-fullstack | web-frontend-only | web-backend-only | mobile).
   Do all profiles require ALL 3 post-build steps? Or some legitimate
   skip?

7. **Partial-wave runs (mid-phase)**: When user runs `/vg:build
   --wave N` (N < final), `is_final_wave=false`. Should NOT trigger
   any cascade check. Verify each check's guard.

8. **Real-world false positive risk**: User stops mid-build for
   debugging — does cascade BLOCK incorrectly?

9. **Marker file race**: vg-orchestrator writes markers async. If
   user triggers Stop in narrow window between waves done and
   STEP 5 marker writing, false positive?

10. **AI continuation prompt clarity**: Messages tell AI what to do
    next (read X.md, spawn Y). Are messages specific enough that AI
    can resume without ambiguity?

11. **Reflector skill marker**: build.md close.md may spawn vg-reflector
    after run_complete. B68 doesn't cover that — out of scope?

12. **Profile filter — frontend-only / backend-only**: does CrossAI
    still required? If frontend-only phase has no backend code,
    CrossAI verify-loop may not need to run. Check crossai-loop.md
    skip conditions.

Read files:
- D:/Workspace/Messi/Code/vgflow-repo/scripts/hooks/vg-stop.sh:77-138
- D:/Workspace/Messi/Code/vgflow-repo/commands/vg/build.md (esp. line 4 profile list + lines 286-429 step sequence)
- D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/build/crossai-loop.md (HARD-GATE + skip conditions)
- D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/build/close.md (10_postmortem_sanity + 12_run_complete)
- D:/Workspace/Messi/Code/vgflow-repo/tests/test_batch68_cascade_post_build_gates.py

## Output

Write `dev-phases/test-flow-hardening/B68-CODEX-AUDIT.md`:

```
# Codex Audit — B68 Cascade Post-Build Gates

**Verdict:** PASS | PASS-WITH-NOTES | BLOCK

## BLOCKER findings (must fix before tag v4.56.0)

## MAJOR concerns

## MINOR concerns

## Checklist
| Concern | Status |
|---|---|
| Cascade ordering | OK/RISK/BLOCK |
| is_final_wave default | ... |
| postmortem_sanity gap | ... |
| crossai.verdict event vs marker | ... |
| Mirror parity | ... |
| Profile skip legitimate | ... |
| Partial-wave guard | ... |
| Mid-build Stop FP | ... |
| Marker race | ... |
| Prompt clarity | ... |
| Reflector scope | ... |
| Frontend-only CrossAI skip | ... |
```

Be specific. File paths + line numbers. Quote actual fragments. ≤ 1200 words.
