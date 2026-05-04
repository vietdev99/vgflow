# MANUAL RULES — vg-haiku-scanner (operator-curated)

> Edited by operator. Preserved across `extract-rule-cards.py` re-runs.
> Inject helper reads both this file AND auto RULES-CARDS.md at step start.
>
> Format conventions (header levels MUST match auto file format):
>   - Top-level rules:    `## Top-level (apply to ALL steps)`
>   - Per-step rules:     `### Step: \`step_name\``
>   - Anti-patterns:      `### Step: \`step_name\` — Anti-patterns`
>   - Overrides:          `## Overrides (auto-rule tag corrections)`

## Top-level (apply to ALL steps)



- **MANUAL-1** [remind]
  Exhaustive scanner — fixed 5-step protocol, zero discretion; never reorder, skip, or 'optimize' steps based on view complexity guess.
  *Added: 2026-04-26*

- **MANUAL-2** [remind]
  Layer 4 Persistence Probe is MANDATORY for every form submit — toast + console + data persisted check, never skip 'because data not critical'.
  *Added: 2026-04-26*

- **MANUAL-3** [remind]
  Inline orchestrator pattern, NOT spawned — Codex execution model is direct invocation, do not Task-spawn from inside scanner.
  *Added: 2026-04-26*

- **MANUAL-4** [enforce] → `verify-design-ref-honored`
  Mode=web takes login + sidebar suppression path; mode=mobile takes ADB+Maestro path; mismatch produces empty scan output.
  *Added: 2026-04-26*

### Step: `STEP_1_login_navigate`


- **MANUAL-5** [remind]
  Always login through form click flow, never direct URL with token; auth state must come from real form submission.
  *Added: 2026-04-26*

### Step: `STEP_2_scroll_full_page`


- **MANUAL-6** [remind]
  Scroll to bottom THEN scroll back to top before snapshot — lazy-loaded sections only render after viewport visit.
  *Added: 2026-04-26*

### Step: `STEP_4_visit_every_element`


- **MANUAL-7** [remind]
  Visit EVERY interactive element — no skipping based on 'looks similar to one already visited'; coverage is the contract.
  *Added: 2026-04-26*

### Step: `STEP_5_write_output`


- **MANUAL-8** [remind]
  Output schema fixed: scan-{view}.json with elements, modals, errors, persistence array; do not invent extra top-level keys.
  *Added: 2026-04-26*

### Step: `CLEANUP`


- **MANUAL-9** [enforce] → `verify-clean-failure-state`
  Cleanup runs even on error — close browser, release Playwright lock, write .codex/exit; never leave session locked.
  *Added: 2026-04-26*

### Step: `STEP_4_visit_every_element` — Anti-patterns


- **ANTI-1** ❌ Skip element because it 'looks identical' to a sibling — but state machines route on data, not visual similarity.
  *Incident: P7.14.3 advertiser scan missed expand-row variation, regression caught only after build*
  *Added: 2026-04-26*
## Overrides (auto-rule tag corrections)

_(none yet — use `edit-rule-cards.py override` to add)_
