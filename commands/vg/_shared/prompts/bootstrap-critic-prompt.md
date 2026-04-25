<!--
  VG Bootstrap — Critic Prompt (v2.6 Phase A)

  Used by .claude/scripts/bootstrap-shadow-evaluator.py when invoked with
  --critic. Renders rule prose + 3 sample commit messages and asks Haiku
  for an advisory verdict on whether the rule is consistent with the
  cited references.

  Placeholders:
    {prose}    — full prose body of the candidate rule
    {commits}  — three commit message bodies, separated by `---`

  Output contract: a single JSON object with EXACTLY two fields:
    verdict: "supports" | "contradicts" | "insufficient"
    reason:  <= 200 character explanation
  Anything else in the response is ignored by the parser.
-->

You are auditing a proposed VG workflow rule against real commit evidence.

The rule was extracted from prior incidents and is currently in **shadow
mode** — telemetry is being gathered before the rule is allowed to
auto-promote to Tier A enforcement. Your job is to give an advisory
verdict that helps the operator decide whether to promote, defer, or
retire the candidate.

## Rule under evaluation

{prose}

## Commit evidence (up to 3 samples)

{commits}

## Question

When applied to phase work like the commits above, does this candidate
rule lead to outcomes consistent with the cited decision / contract /
goal references? Consider:

- Does the rule's prediction match what the commit actually cited?
- Are there commits that follow the rule but cite an unrelated reference
  (suggesting the rule's scope is too broad)?
- Are there commits that violate the rule but ship cleanly (suggesting
  the rule does not actually hold)?

If you cannot tell from the evidence shown, answer `insufficient`.
Do **not** guess. Insufficient is a useful signal — it tells the operator
to wait for more samples before promoting.

## Required output

Respond with **exactly one JSON object** and nothing else:

```json
{"verdict": "supports", "reason": "<at most 200 chars explaining the call>"}
```

Allowed `verdict` values: `supports`, `contradicts`, `insufficient`.
Keep `reason` under 200 characters. No prose outside the JSON.
