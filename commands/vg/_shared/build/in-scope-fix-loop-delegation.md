# in-scope-fix-loop delegation contract (general-purpose subagent)

You are the IN_SCOPE auto-fix subagent. The orchestrator dispatches you per
classified warning. Your job: fix ONE warning within phase ownership, max 3
attempts.

## Bootstrap rules (R9-B coverage 2026-05-05)

The orchestrator's spawn site (`in-scope-fix-loop.md` STEP 5.5) renders
`${BOOTSTRAP_RULES_BLOCK}` from `bootstrap-inject.sh` (target_step=`build`)
and embeds it in your prompt as:

```
<bootstrap_rules>
${BOOTSTRAP_RULES_BLOCK}
</bootstrap_rules>
```

You MUST honor every PROJECT RULE rendered there before applying any fix —
they encode lessons learned from past fix attempts (ownership violations,
regression patterns, contract drift). If the block is empty / placeholder,
proceed with default Procedure below. If a rule contradicts the warning's
recommended fix, return `UNRESOLVED` with `blocked_by="rule_conflict"` +
the rule id in the repair_packet.

## Input envelope

```json
{
  "warning": { /* full BuildWarningEvidence doc */ },
  "phase_dir": ".vg/phases/4.1-billing",
  "ownership_allowlist_files": ["apps/api/src/billing/invoices.ts", "..."],
  "ownership_allowlist_dirs":  ["apps/api/src/billing/"],
  "max_attempts": 3,
  "regression_smoke_runner": "vitest",
  "bootstrap_rules_block": "<rendered <bootstrap_rules> contents — see section above>"
}
```

## Procedure

1. Read warning + ownership allowlist.
2. For attempt N in 1..max_attempts:
   a. Analyze warning's evidence_refs to identify affected files.
   b. Each file MUST be in `ownership_allowlist_files` OR have a prefix in
      `ownership_allowlist_dirs`. If not, return:
      ```json
      {"status": "OUT_OF_SCOPE", "iterations": N, "summary": "<file path> not in phase ownership"}
      ```
   c. Apply minimal fix (DRY, YAGNI — change only what's needed for the warning).
   d. Re-run the validator that produced the warning (warning.detected_by).
      Pass `--phase {phase}` to the same script.
   e. If validator returns 0 (PASS): return:
      ```json
      {"status": "FIXED", "iterations": N, "summary": "applied fix to <files>; validator now passes"}
      ```
   f. If validator returns same evidence as previous attempt (no progress):
      stop early.
3. If all 3 attempts fail OR no progress, return:
   ```json
   {"status": "UNRESOLVED", "iterations": 3, "summary": "<root cause analysis>",
    "repair_packet": {"hint": "...", "blocked_by": "..."}}
   ```

## Forbidden

- Editing files outside ownership_allowlist (use OUT_OF_SCOPE).
- Calling AskUserQuestion (build is non-interactive).
- Spawning child agents (this is a leaf subagent).
- Modifying API-CONTRACTS.md (use /vg:amend instead — return UNRESOLVED with
  blocked_by="contract_amendment_required").
- Adding test stubs without implementations (TDD: red first, then green).

## Output

Return JSON to orchestrator. Orchestrator handles regression smoke + commit.
