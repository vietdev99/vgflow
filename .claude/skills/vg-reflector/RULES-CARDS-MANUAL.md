# MANUAL RULES — vg-reflector (operator-curated)

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
  Reflector spawns FRESH-CONTEXT Haiku — zero parent context inheritance; if reflector inherits prior reasoning, candidates become echo chamber.
  *Added: 2026-04-26*

- **MANUAL-2** [remind]
  Inputs: events.db slice + step artifacts + user transcript — do not pull beyond declared inputs to avoid scope leakage.
  *Added: 2026-04-26*

- **MANUAL-3** [enforce] → `verify-learn-promotion`
  Output candidates emit to .vg/bootstrap/candidates/ jsonl with shadow_mode + phase_pattern + tier (A/B/C); missing field rejected.
  *Added: 2026-04-26*

- **MANUAL-4** [remind]
  Max 2-3 candidates surfaced per phase after dedupe; if step generates 10+, dedupe is broken or step is anomalous — flag for operator.
  *Added: 2026-04-26*

- **MANUAL-5** [remind]
  Anti-echo-chamber checklist runs BEFORE writing any candidate; reject candidates that just restate parent context decisions.
  *Added: 2026-04-26*

### Step: `Step_2_classify_signals`


- **MANUAL-6** [remind]
  Classify signals into bug | preference | convention | progress | decision; multi-classification = candidate is too broad, split or skip.
  *Added: 2026-04-26*

### Step: `Step_3_draft_candidate`


- **MANUAL-7** [remind]
  Each candidate gets actionable body + suggested target surface (which skill/step it would patch); abstract candidates rejected.
  *Added: 2026-04-26*

### Step: `Step_4_dedupe`


- **MANUAL-8** [enforce] → `verify-learn-promotion`
  Dedupe against existing accepted rules (.vg/bootstrap/rules/*.md) AND prior candidate jsonl; never emit accepted dup.
  *Added: 2026-04-26*

### Step: `Step_5_append`


- **MANUAL-9** [remind]
  Append-only to OUT_FILE jsonl, never overwrite; reflector runs cumulatively across phases for trend analysis.
  *Added: 2026-04-26*

### Step: `Step_3_draft_candidate` — Anti-patterns


- **ANTI-1** ❌ Restate parent step's decision as 'lesson learned' — fake learning, candidate auto-rejected at /vg:learn.
  *Incident: Bootstrap reflection mandatory feedback (2026-04-26): echo candidates were spam until anti-echo-chamber added*
  *Added: 2026-04-26*
## Overrides (auto-rule tag corrections)

_(none yet — use `edit-rule-cards.py override` to add)_
