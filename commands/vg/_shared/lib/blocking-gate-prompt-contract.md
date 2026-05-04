# Blocking-gate-prompt 2-leg API (Task 33)

## Overview

Replaces `exit 1` in review.md `*_blocked` paths with a 4-option
AskUserQuestion flow. Bash cannot invoke AskUserQuestion directly
(controller-side tool call), so the wrapper splits into 2 legs:

1. **Leg 1 (`blocking_gate_prompt_emit`)** — bash function emits
   structured JSON describing the prompt (gate_id, fix_hint, severity,
   evidence_path, 4 options, repair_packet if re-prompt).
2. **AI controller** — reads stdout JSON, invokes `AskUserQuestion`
   with the title/options, captures user's choice letter.
3. **Leg 2 (`blocking_gate_prompt_resolve`)** — bash function dispatches
   based on `--user-choice=<a|s|r|x>`, returns exit code matching the
   downstream branch.

## Exit codes

| Code | Meaning | Caller action |
|---|---|---|
| 0 | Fixed (auto-fix subagent succeeded, gate validator now passes) | Re-run gate validator inline; continue if pass |
| 1 | Skip-with-override | Emit override.used, log debt, mark step done, continue |
| 2 | Route-to-amend | Emit `review.routed_to_amend`, exit cleanly with handoff message |
| 3 | Abort | Emit `review.aborted_by_user`, run-complete with `outcome: aborted_by_user` |
| 4 | Re-prompt-needed | Subagent UNRESOLVED; AI controller MUST re-call Leg 1 with appended repair_packet |
| 64+ | Wrapper internal error (BSD sysexits) | Hard fail; orchestrator surfaces stderr |

## Severity vocabulary mapping

Wrapper input `severity` ∈ {error, warn, critical}. Mapped to
override-debt vocab when option `[s]` chosen:

| Wrapper | Debt |
|---|---|
| critical | critical |
| error | high |
| warn | medium |

## --non-interactive mode

When `$ARGUMENTS` contains `--non-interactive`:
- Leg 1 short-circuits — skip emit, behave as user picked `[x]`
- Emit `review.aborted_non_interactive_block` (warn-tier)
- Exit code 3

## Subagent forbidden short-circuits

When option `[a]` subagent returns `{"status": "UNRESOLVED",
"blocked_by": "contract_amendment_required"}`:
- Wrapper Leg 2 short-circuits to option `[r]` automatically
- No re-prompt
- Exit code 2

## Calling pattern

Bash calling site:

```bash
# Source the wrapper
source scripts/lib/blocking-gate-prompt.sh

# Leg 1: emit JSON
blocking_gate_prompt_emit "api_precheck" \
  "${PHASE_DIR}/.vg/api-precheck-evidence.json" \
  "error" \
  "${PHASE_DIR}/.vg/api-precheck-detail.txt"

# AI controller reads stdout, calls AskUserQuestion, captures answer
USER_CHOICE="${VG_GATE_USER_CHOICE}"  # injected by controller

# Leg 2: resolve
blocking_gate_prompt_resolve "api_precheck" \
  --user-choice="${USER_CHOICE}" \
  --override-reason="${OVERRIDE_REASON:-}"
RC=$?

# Branch on exit code
case "$RC" in
  0) echo "✓ gate fixed"; continue ;;
  1) echo "⚠ skipped with override"; continue ;;
  2) echo "→ routed to /vg:amend"; exit 0 ;;
  3) echo "⛔ aborted by user"; exit 0 ;;
  4) echo "↻ re-prompt needed"; goto_leg1_again ;;
  *) echo "⛔ wrapper internal error"; exit "$RC" ;;
esac
```
