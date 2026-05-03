---
name: lens-modal-state
description: Modal lifecycle and state hygiene — ESC dismissal, focus trap, parent state isolation, multi-modal stacking, reopen idempotency
bug_class: ui-mechanic
applies_to_element_classes:
  - modal_trigger
applies_to_phase_profiles:
  - feature
  - feature-legacy
  - hotfix
strix_reference: (no Strix equiv — VG-specific UI mechanic)
severity_default: warn
estimated_action_budget: 25
output_schema_version: 3
---

# Lens: Modal State

## Threat model

Modals are an interaction primitive whose correctness lives entirely in
client-side state — they have no canonical server response, so they are
invisible to backend-only test passes and trivial to break during view
refactors. The bug class spans: modal cannot be dismissed via ESC (a11y
+ trap risk); focus trap missing (Tab cycles into the underlying page
mid-modal, mixing focus contexts); parent view state mutated as a side-
effect of opening / closing the modal (filter cleared, scroll reset, form
draft lost); multi-modal stacking misbehavior (opening a confirm-modal
inside an edit-modal closes the parent or breaks Tab order); reopen-
after-close re-uses stale state (stale form values, leaked validation
errors); modal blocks the page but its backdrop is click-through; close-
on-outside-click discards unsaved input without warning. These bugs are
not "security" in the classic sense but are first-class VG findings —
they directly degrade UX on the most-used interactions, and a wide-area
view audit naturally catches them. White-box VG workers can drive the
modal lifecycle deterministically (open, ESC, Tab, click outside,
re-open) and observe DOM state transitions, focus position, and parent-
view mutations.

## Activation context (auto-injected by VG)

The dispatcher (`scripts/spawn-recursive-probe.py`) substitutes these
placeholders before handing the prompt to the worker subprocess. Reference them
via `${VAR}` exactly as written; never hard-code values.

- View: `${VIEW_PATH}`
- Element: `${ELEMENT_DESCRIPTION}` (selector: `${SELECTOR}`)
- Element class: `${ELEMENT_CLASS}`
- Resource: `${RESOURCE}` (scope: `${SCOPE}`)
- Role: `${ROLE}` with auth token `${TOKEN_REF}`
- Base URL: `${BASE_URL}`
- Peer credentials (cross-tenant probe, nullable): `${PEER_TOKEN_REF}`
- Run artifact output path: `${OUTPUT_PATH}`
- Action budget: `${ACTION_BUDGET}` browser actions max
- Recursion depth: `${DEPTH}`
- Wall-clock budget: 5 minutes

## Probe-only contract (HARD CONSTRAINT — read this first)

You are a probe + report worker. You are NOT a judge, NOT a fixer.

Worker MUST NOT:

- Propose code fixes or remediation ("To fix this, change X to Y" — NO).
- Assign severity ("This is critical / high / medium" — NO).
- Reason about exploit chains ("If combined with bug Z, attacker could…" — NO).
- Recommend further probing beyond this lens's declared scope.

Worker MUST:

- Explore freely within the action budget.
- Report factual `steps[].status = pass|fail|inconclusive`.
- Capture raw `observed` evidence (status code, body excerpt, DOM diff).
- Append a `finding_fact` to `runs/.broker-context.json` when a step fails —
  facts only:

```json
{"lens": "lens-modal-state", "view": "${VIEW_PATH}", "element": "${ELEMENT_DESCRIPTION}", "step": "<short name>", "status": "fail", "observed_excerpt": "<1-2 line raw>"}
```

NO severity field, NO summary, NO recommendation. Severity rollup is the
aggregator + `derive-findings.py` job downstream, computed from
`lens.severity_default` × `step.status` and cross-cutting context.

## Objective (exploratory)

Find modal-state hygiene defects affecting `${ELEMENT_DESCRIPTION}` and
any nested / sibling modals you discover during exploration. The interest
is whether the modal opens, dismisses, traps focus, isolates state from
its parent view, and stacks correctly with other modals. You are a
quality researcher, not a test runner. Click anything that looks
promising, follow the workflow, dig into anomalies. Adapt to what you
observe — do not follow a fixed sequence.

## Reconnaissance (1-2 steps to start)

Just enough to land on the trigger and snapshot the parent view's pre-
modal state. Not a full script.

1. browser_navigate(`${BASE_URL}${VIEW_PATH}`) with `Authorization: Bearer ${TOKEN_REF}`
2. browser_snapshot — locate `${SELECTOR}`. Capture parent-view state:
   filter / sort selections, scroll position, any in-progress form draft,
   currently-focused element. This is the "should-be-restored" state you
   compare against after the modal closes.

Then START EXPLORING (see Probe ideas).

## Probe ideas (suggestions — pick what fits, combine freely)

- ESC dismiss: open the modal via `${SELECTOR}`, press ESC. Expect
  modal closes. Failure modes: ESC does nothing (a11y broken), ESC
  closes but a backdrop remains (zombie state), ESC closes both modal
  and an unrelated parent overlay.
- Focus trap: with modal open, press Tab repeatedly. Focus should cycle
  within modal-only focusable elements. Failure modes: focus escapes
  into the underlying page, focus lands on a `display: none` invisible
  control, focus is lost (`document.activeElement === body`).
- Initial focus: when modal opens, the first focusable element (or
  declared `autofocus`) should receive focus. Failure: focus stays on
  the trigger button under the backdrop.
- Outside-click dismiss: click on the backdrop. Modal should close OR
  prompt to confirm if unsaved changes exist. Failure: closes silently
  and discards input; or backdrop is click-through onto a parent
  control.
- Parent state isolation: close the modal (any method). Compare against
  the captured parent-view state. Failure: filter cleared, scroll reset
  to top, form draft lost, focus dropped to body instead of the trigger.
- Reopen idempotency: open → close → open again. Modal should present a
  clean state (form fields empty or pre-filled with current resource
  values). Failure: stale form values from the previous session, lingering
  validation errors, the modal opens but nothing displays.
- Multi-modal stacking: if the modal contains a button that opens a
  second modal (e.g. nested confirm), open the child modal. Expect
  parent stays mounted under child; ESC on child closes child only.
  Failure: child closes parent too, focus trap leaks across modals,
  scroll lock removed when child closes (parent's lock state lost).
- Concurrent open: rapidly click the trigger 3-5 times. Expect single
  modal instance. Failure: multiple stacked instances, animation glitch,
  React-style state desync (open=true but DOM hidden).
- Browser back / forward: open modal, click back. Expect modal closes
  (route restored) OR back is captured to dismiss. Failure: full page
  navigation while modal stays in DOM, or modal stays open across route
  change.
- Long content / overflow: if modal has scrollable content, scroll it,
  then open a sub-modal or close. Scroll position handling on close /
  reopen should be sane (typically reset on reopen).

## How to explore recursively (anti-script discipline)

- Drive each modal-lifecycle action (open, ESC, Tab, click-outside,
  reopen). After each, browser_snapshot — capture DOM diff, focus
  position, scroll, form draft state.
- After each action, look for nested triggers that open further modals →
  recurse into them with the same probe set (within this element's
  reach).
- If a probe yields an anomaly (focus escaped, parent state mutated,
  stale state on reopen) → DIG: try the same probe with keyboard-only
  navigation (no mouse), test responsive viewport (mobile breakpoint
  often re-renders modals as fullscreen with a different lifecycle).
- DO NOT follow a fixed click sequence. Adapt to what you observe.
- DO NOT skip "boring-looking" confirm modals without at least 1 ESC +
  1 outside-click probe — confirm modals are the highest-volume modal
  class and the most regression-prone.

## Stopping criteria

Stop and write the artifact when ANY of:

- Action budget `${ACTION_BUDGET}` exhausted
- Wall-clock 5 minutes reached
- High-confidence finding captured + ≥3 supporting probes done
- 2 consecutive actions yield no new anomaly AND no new clickables —
  diminishing returns

## Run artifact write

After exploration ends (stopping criteria triggered), write JSON to `${OUTPUT_PATH}`:

```json
{
  "schema_version": 3,
  "worker_tool": "gemini" | "codex" | "claude",
  "run_id": "<element-slug>-lens-modal-state-<role>-<depth>",
  "lens": "lens-modal-state",
  "resource": "${RESOURCE}",
  "role": "${ROLE}",
  "element_class": "${ELEMENT_CLASS}",
  "selector_hash": "<sha256[:8]>",
  "view": "${VIEW_PATH}",
  "depth": ${DEPTH},
  "actions_taken": <int>,
  "stopping_reason": "budget" | "timeout" | "confidence" | "diminishing_returns",
  "steps": [
    {
      "name": "<short description of what you did/observed>",
      "status": "pass" | "fail" | "inconclusive",
      "observed": { "status_code": <int>, "body_excerpt": "<1-2 line raw>", "dom_diff": "<optional>" },
      "evidence_ref": ["<network_log_entry_id>", ...]
    }
  ],
  "coverage": {"passed": N, "failed": M, "inconclusive": K},
  "replay_manifest": {
    "commit_sha": "<auto>",
    "worker_prompt_version": "lens-modal-state-v1",
    "fixtures_used": ["${TOKEN_REF}", "${PEER_TOKEN_REF}"],
    "request_sequence": [...]
  },
  "goal_stub": {
    "id": "G-RECURSE-<behavior_class_hash>",
    "lens": "lens-modal-state",
    "view": "${VIEW_PATH}",
    "element_class": "${ELEMENT_CLASS}",
    "resource": "${RESOURCE}",
    "parent_goal_id": "<from CRUD-SURFACES if matchable, else null>"
  }
}
```

`priority` is NOT included in worker output — aggregator assigns post-run from
`lens.severity_default` × `step.status` mapping.

## Termination

- After exploration ends → write the run artifact → call browser_close →
  output `DONE`.
- DO NOT navigate to other views (the VG manager handles cross-view recursion).
- DO NOT spawn child agents (deterministic dispatcher only).
- If action budget is exhausted before exploration feels complete, write a
  partial artifact with `stopping_reason: "budget"` — that is normal and the
  aggregator handles it.
