# scope discussion-deep-probe (STEP 2 / Deep Probe Loop)

> Mandatory minimum 5 probes after Round 5.
> Per-answer challenger pattern: see `discussion-overview.md` §A.

<HARD-GATE>
Final sub-step of STEP 2. You MUST run minimum 5 probes after R5. This
ref is the **single owner** of `1_deep_discussion` mark-step (Critical-3
fix — was duplicated in `discussion-overview.md` §D, now removed there).

`step-active 1_deep_discussion` is fired at STEP 2 START inside
`discussion-overview.md` so the 5 rounds + deep probe all execute under
an active marker (Critical-4 r2 fix). This file ONLY fires `mark-step`
at STEP 2 END.
</HARD-GATE>

## Purpose

Rounds 1-5 capture the KNOWN decisions. This loop discovers what's UNKNOWN — gray areas, edge cases, implicit assumptions the AI made, conflicts between decisions.

## Rules

1. AI asks ONE focused question per turn, with its own recommendation
2. Do NOT ask "do you have anything else?" — AI drives the investigation, not user
3. Target minimum 10 total probes (5 structured rounds + 5+ deep probes)
4. User adds extra ideas in their answers — AI integrates and continues probing
5. Stop only when AI genuinely cannot find more gray areas (not when user seems done)

## Probe generation strategy — AI self-analyzes locked decisions for:

- **CONFLICTS:** D-XX says "use Redis cache" but D-YY says "minimize infrastructure" → which wins?
- **IMPLICIT ASSUMPTIONS:** D-XX assumes "user is logged in" but login flow not in scope → clarify
- **MISSING ERROR PATHS:** D-XX defines happy path but not what happens on failure
- **EDGE CASES:** D-XX says "max 20 items" but exactly 20? Migrating from >20?
- **PERMISSION GAPS:** endpoints have auth but role escalation not discussed
- **DATA LIFECYCLE:** create and read discussed but archive/purge/retention not
- **CONCURRENCY:** what if 2 users do the same thing simultaneously?
- **MIGRATION:** existing data compatibility with new schema
- **PERFORMANCE:** scaling implications of chosen approach
- **SECURITY:** input validation, rate limiting, injection risks

## Probe format

```
AskUserQuestion:
  header: "Deep Probe #{N}"
  question: |
    Analyzing decisions so far, I found a gray area:

    **{specific concern}**

    Context: {D-XX says this, but {what's unclear}}

    **My recommendation:** {AI's suggested resolution}

    Agree with recommendation, or different approach?
  (open text)
```

## Per-answer challenger

Apply pattern from `discussion-overview.md` §A after each user answer in the loop.
- `ROUND="deep-probe-${N}"`, `ROUND_TOPIC="Deep probe"`

## Termination condition

After each answer: lock/update the affected decision. Generate next probe from remaining gray areas. Continue until:
- AI has probed ≥ 5 times after Round 5 (10 total interactions minimum)
- AND AI genuinely cannot identify more gray areas in the locked decisions

When exhausted, AI states: *"I've analyzed all {N} decisions for conflicts, edge cases, and gaps. {M} gray areas resolved through probes. Proceeding to artifact generation."*

→ Proceed to STEP 3 (env preference) — no confirmation question; AI decides scope is thorough enough.

## Mark step (END of STEP 2)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step scope 1_deep_discussion
```

> Critical-3 fix: this is the **single owner** for `mark-step 1_deep_discussion`.
> `discussion-overview.md` §D used to also mark the same step — removed
> there to avoid double-touch.
>
> Critical-4 r2 fix: `step-active 1_deep_discussion` moved to STEP 2 START
> in `discussion-overview.md` so the 5 rounds + deep probe all execute
> under an active marker. This block previously fired step-active here at
> STEP 2 END, immediately before mark-step — leaving the rounds untracked.

Read `_shared/scope/env-preference.md` next.
