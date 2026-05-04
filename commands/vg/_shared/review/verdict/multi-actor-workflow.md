# Multi-actor workflow replay (Shared Reference, R7 Task 5 / G9)

Wires `scripts/lib/workflow_replay.py` + `scripts/validators/verify-workflow-replay.py`
into the review verdict pipeline. Runs AFTER Phase 4.0b phase-goal gate
(R8-C 2026-05-05) and BEFORE the final 4f gate decision.

This is **defense-in-depth**:

- Build-side R7 Task 4 (`verify-workflow-implementation.py`) catches static
  state-literal absent at build time (handler does not reference the state
  declared in WORKFLOW-SPECS).
- Review-side R7 Task 5 (THIS) catches the runtime class — multi-actor bugs
  that pass static checks but fail when actually replayed across roles
  (cross-role visibility broken, authz negative paths permissive, side
  effects missing).

## Trigger

The block fires when:

```
${PHASE_DIR}/WORKFLOW-SPECS/WF-*.md exists AND
${PHASE_DIR}/WORKFLOW-SPECS/index.md does NOT contain "flows: []" AND
${ARGUMENTS} does NOT contain --skip-multi-actor-replay
```

Skip path: an empty `flows: []` index (or no WORKFLOW-SPECS dir) silently
short-circuits — the validator emits an `info` entry and exits PASS.

## Wiring (insert in review verdict pipeline)

Insert this block in the dispatched verdict sub-ref (web-fullstack.md /
profile-branches.md) AFTER the matrix-merger gate at step 4c, BEFORE the 4d
inline triage. The validator is fast (file existence + JSON parse) — it
should not delay the gate decision more than ~100ms.

```bash
# ─── R7 Task 5 — Multi-actor workflow replay gate ─────────────────────
WF_DIR="${PHASE_DIR}/WORKFLOW-SPECS"
if [ -d "$WF_DIR" ] && [ -n "$(find "$WF_DIR" -maxdepth 1 -name 'WF-*.md' -print -quit 2>/dev/null)" ]; then
  if [[ "$ARGUMENTS" =~ --skip-multi-actor-replay ]]; then
    if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then
      echo "⛔ --skip-multi-actor-replay requires --override-reason=<text>"
      exit 1
    fi
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator override \
      --flag "--skip-multi-actor-replay" \
      --reason "Multi-actor workflow replay skipped (phase ${PHASE_NUMBER})" \
      >/dev/null 2>&1 || true
    type -t log_override_debt >/dev/null 2>&1 && \
      log_override_debt "multi-actor-replay-skipped" "${PHASE_NUMBER}" \
        "Workflow replay deferred — verify build-side gate passed" \
        "$PHASE_DIR"
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.multi_actor_replay_skipped" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
    echo "⚠ --skip-multi-actor-replay set — workflow replay gate bypassed (override-debt logged)"
  else
    # ── Drive replay for every WF-NN.md ────────────────────────────────
    # Layer 4 status: when Playwright MCP runtime is wired into the review
    # orchestrator, this loop calls workflow_replay.execute_replay() with
    # live executors. When MCP is unavailable (sandbox-only env, or batch
    # review with no browser session), execute_replay() emits PARTIAL +
    # TODO notes — validator WARNs and does NOT block.
    mkdir -p "${PHASE_DIR}/.runs"
    REPLAY_RC=0

    DEPLOYED_URL="$(vg_config_get review.multi_actor_deployed_url '' 2>/dev/null || echo '')"
    [ -z "$DEPLOYED_URL" ] && [ -f "${PHASE_DIR}/DEPLOY-STATE.json" ] && \
      DEPLOYED_URL=$("${PYTHON_BIN:-python3}" -c "
import json, sys
try:
    d = json.load(open('${PHASE_DIR}/DEPLOY-STATE.json'))
    print(d.get('deployed', {}).get('staging', {}).get('url', '') or
          d.get('deployed', {}).get('sandbox', {}).get('url', ''))
except Exception:
    pass
" 2>/dev/null)

    EXEC_MODE="mock"
    [ -n "${VG_PLAYWRIGHT_MCP_AVAILABLE:-}" ] && EXEC_MODE="live"

    for WF_PATH in "$WF_DIR"/WF-*.md; do
      [ -f "$WF_PATH" ] || continue
      WF_ID=$(basename "$WF_PATH" .md)
      EVIDENCE_PATH="${PHASE_DIR}/.runs/${WF_ID}.replay.json"

      # Skip if evidence already fresh (built by orchestrator's MCP loop)
      if [ -f "$EVIDENCE_PATH" ]; then
        EX_VERDICT=$("${PYTHON_BIN:-python3}" -c "
import json
try:
    d = json.load(open('$EVIDENCE_PATH'))
    print(d.get('overall_verdict', 'UNKNOWN'))
except Exception:
    print('MALFORMED')
" 2>/dev/null)
        echo "  ${WF_ID}: existing replay evidence — overall_verdict=${EX_VERDICT}"
      else
        # Bootstrap evidence file via library helper. Real per-step
        # execution requires the orchestrator to drive Playwright MCP —
        # this CLI fallback emits PARTIAL with TODO notes so the
        # validator surface still runs.
        "${PYTHON_BIN:-python3}" - "$WF_PATH" "$PHASE_DIR" "$DEPLOYED_URL" "$EXEC_MODE" "$WF_ID" <<'PY' || REPLAY_RC=1
import sys
from pathlib import Path
sys.path.insert(0, str(Path('scripts/lib').resolve()))
from workflow_replay import (
    parse_workflow_spec, build_replay_plan, execute_replay,
    write_replay_evidence,
)
wf_path, phase_dir, deployed_url, mode, wf_id = sys.argv[1:6]
spec = parse_workflow_spec(Path(wf_path))
plan = build_replay_plan(spec)
result = execute_replay(
    plan, Path(phase_dir),
    deployed_url=deployed_url or None,
    mode=mode if mode in ("live", "mock", "dry-run") else "mock",
    workflow_id=wf_id, spec=spec,
)
write_replay_evidence(result, Path(phase_dir) / ".runs" / f"{wf_id}.replay.json")
print(f"{wf_id}: {result['overall_verdict']} ({len(result['steps'])} steps, mode={mode})")
PY
      fi
    done

    "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-workflow-replay.py \
      --phase-dir "$PHASE_DIR" \
      > "${PHASE_DIR}/.tmp/workflow-replay.json" 2>&1
    REPLAY_VAL_RC=$?

    if [ "$REPLAY_VAL_RC" -ne 0 ]; then
      cat "${PHASE_DIR}/.tmp/workflow-replay.json"
      echo ""
      echo "⛔ Multi-actor workflow replay gate FAILED"
      echo "   Build-side gate (R7 Task 4) catches static state-literal absent;"
      echo "   this gate verifies runtime cross-role behavior at review verdict."
      echo "   Inspect: ${PHASE_DIR}/.runs/WF-*.replay.json"
      echo "   Override: --skip-multi-actor-replay --override-reason \"<text>\""
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.multi_actor_replay_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
      exit 1
    fi

    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.multi_actor_replay_passed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
    echo "✓ Multi-actor workflow replay gate passed"
  fi
fi
```

## Sub-references

- Per-actor session primitive — `commands/vg/_shared/review/verdict/multi-actor-session.md`
- Replay engine — `scripts/lib/workflow_replay.py`
- Evidence schema — `schemas/workflow-replay.v1.schema.json`
- Validator — `scripts/validators/verify-workflow-replay.py`
- Build-side sibling — `scripts/validators/verify-workflow-implementation.py` (R7 Task 4)
- Workflow spec source — `commands/vg/_shared/blueprint/workflows-overview.md`

## Override flag

`--skip-multi-actor-replay` MUST be paired with `--override-reason "<text>"`.
Logged as `kind=multi-actor-replay-skipped` in OVERRIDE-DEBT register; resolved
when a subsequent review run produces evidence with `overall_verdict=PASSED`.

Genuine defer cases (NOT a rationalization opportunity):

- Phase deploys to an env where one actor cannot reach (admin-only operation
  on a production-isolated cluster).
- Workflow involves third-party integration (Stripe webhook, OAuth callback)
  that cannot be replayed in review env without polluting upstream state.
- Hotfix phase patches a non-workflow surface but inherits WORKFLOW-SPECS
  from base phase — already validated upstream.

Rationalization patterns (REJECTED by guard):

- "MCP not available" → install Playwright MCP, do not skip.
- "Build gate already passed" → static gate ≠ runtime gate; this is the whole
  point of defense-in-depth.
- "No time" → not a valid reason; either accept the phase ships incomplete or
  do the work.

## Layer 4 status (live MCP execution)

The CLI fallback in this file emits PARTIAL evidence — sufficient for the
validator to fire and confirm the artifact pipeline is plumbed. Live
per-step Playwright MCP execution requires the orchestrator (this file's
caller) to wire `step_executor`, `visibility_executor`, `authz_executor`
callables into `workflow_replay.execute_replay()` from inside the AI
context where MCP tools are available.

A future task (next R-cycle) will add the inline AI-driven MCP execution
loop. For R7, the partial path keeps the gate honest: build-side gate is
mandatory, review-side gate is best-effort with a documented escape hatch.
