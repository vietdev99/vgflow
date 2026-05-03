<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 33: 2-leg blocking-gate-prompt wrapper + refactor 13 review *_blocked sites

**Files:**
- Create: `commands/vg/_shared/lib/blocking-gate-prompt-contract.md`
- Create: `commands/vg/_shared/lib/review-fix-loop-delegation.md`
- Create: `scripts/lib/blocking-gate-prompt.sh`
- Modify: `commands/vg/review.md` (refactor 13 `*_blocked exit 1` sites)
- Test: `tests/test_blocking_gate_prompt.py`

**Why:** PV3 dogfood revealed review's halt-on-detect UX kills iterative work. User restart from scratch every BLOCK. Bug A spec (lines 52-135) defines 2-leg wrapper presenting AskUserQuestion 4 options.

**Codex round-1 finding #1**: 13 in-scope sites, NOT 20+. Selection rule = (1) `emit-event "review.<X>_blocked"` within 5 lines OR matches frontmatter `must_emit_telemetry` warn-tier `*_blocked` declarations, (2) site has user-facing fix-path message. Non-blocking guards stay `exit 1`.

**Codex round-2 acceptance criteria** addressed: severity vocab mapping (error→high, warn→medium, critical→critical), `--non-interactive` auto-abort, subagent forbidden API-CONTRACTS edit short-circuits to `[r]`, exit code 4 for re-prompt path.

- [ ] **Step 1: Write the contract document**

Create `commands/vg/_shared/lib/blocking-gate-prompt-contract.md`:

```markdown
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

\`\`\`bash
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
\`\`\`
```

- [ ] **Step 2: Write the review-side subagent delegation contract**

Create `commands/vg/_shared/lib/review-fix-loop-delegation.md`:

```markdown
# Review fix-loop subagent delegation contract (Task 33 option [a])

Input envelope (rendered as Agent prompt):

\`\`\`json
{
  "gate_id": "api_precheck",
  "phase_dir": ".vg/phases/4.1-billing",
  "evidence_path": ".vg/api-precheck-evidence.json",
  "fix_hint_path": ".vg/api-precheck-detail.txt",
  "ownership_allowlist_files": ["apps/api/src/billing/**", "apps/web/src/billing/**"],
  "ownership_allowlist_dirs": ["apps/api/src/billing/", "apps/web/src/billing/"],
  "max_attempts": 3,
  "deployed_app_url": "http://localhost:3010",
  "auth_fixture_path": ".vg/test-credentials/admin.json"
}
\`\`\`

## Procedure

For attempt N in 1..max_attempts:

1. Read evidence + fix_hint to understand the gate failure.
2. Decide target:
   - API gates (api_precheck, asserted_drift, replay_evidence,
     mutation_submit) → run against deployed app (curl + write
     handler/migration/restart service)
   - Drift gates (matrix_staleness, foundation_drift,
     rcrurd_post_state) → edit artifacts (CONTEXT.md, drift register,
     RUNTIME-MAP.json)
3. Apply minimal fix.
4. Re-run the validator that produced the gate failure.
5. If validator returns 0 (PASS) → return `{"status": "FIXED",
   "iterations": N, "summary": "..."}`
6. If validator still fails AND attempt < max → continue.
7. If validator still fails AND attempt == max → return
   `{"status": "UNRESOLVED", "iterations": max, "summary": "...",
    "repair_packet": {"hint": "...", "blocked_by": "..."}}`

## Forbidden actions

- Editing files outside `ownership_allowlist_*` → return
  `{"status": "OUT_OF_SCOPE", ...}`.
- Calling `AskUserQuestion` (review is wrapped already; subagent is leaf).
- Spawning child agents.
- Modifying `API-CONTRACTS.md` → return UNRESOLVED with
  `blocked_by: "contract_amendment_required"` (wrapper short-circuits
  to option `[r]`).
- Adding test stubs without implementations.

## Output

Return JSON envelope to wrapper Leg 2. Wrapper handles validator
re-run + commit + telemetry.
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_blocking_gate_prompt.py`:

```python
"""Task 33 — 2-leg blocking-gate-prompt wrapper tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts/lib/blocking-gate-prompt.sh"


def _bash(cmd: str, env_extra: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=15)


def test_leg1_emits_json_with_4_options(tmp_path: Path) -> None:
    """Leg 1 emits structured JSON; 4 options; severity normalized."""
    evidence = tmp_path / "ev.json"
    evidence.write_text('{"category":"api_precheck","summary":"missing endpoint"}', encoding="utf-8")
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_emit '
                   f'"api_precheck" "{evidence}" "error"', cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gate_id"] == "api_precheck"
    assert payload["severity"] == "error"
    assert len(payload["options"]) == 4
    keys = {o["key"] for o in payload["options"]}
    assert keys == {"a", "s", "r", "x"}


def test_leg1_non_interactive_auto_aborts(tmp_path: Path) -> None:
    """When --non-interactive in $ARGUMENTS, Leg 1 emits abort directly."""
    evidence = tmp_path / "ev.json"
    evidence.write_text('{}', encoding="utf-8")
    result = _bash(f'export ARGUMENTS="--non-interactive"; source "{WRAPPER}"; '
                   f'blocking_gate_prompt_emit "g" "{evidence}" "error"', cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload.get("non_interactive_auto_abort") is True


def test_leg2_skip_with_override_exits_1(tmp_path: Path) -> None:
    """Leg 2 with --user-choice=s exits 1 + emits override + debt."""
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=s --override-reason="legacy phase, skip OK"', cwd=tmp_path)
    assert result.returncode == 1


def test_leg2_route_to_amend_exits_2(tmp_path: Path) -> None:
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=r', cwd=tmp_path)
    assert result.returncode == 2


def test_leg2_abort_exits_3(tmp_path: Path) -> None:
    result = _bash(f'source "{WRAPPER}"; blocking_gate_prompt_resolve "g" '
                   f'--user-choice=x', cwd=tmp_path)
    assert result.returncode == 3


def test_severity_vocab_mapping(tmp_path: Path) -> None:
    """Wrapper severity (error/warn/critical) maps to debt vocab (high/medium/critical)."""
    result = _bash(f'source "{WRAPPER}"; '
                   f'echo "$(_map_severity_to_debt error) "'
                   f'"$(_map_severity_to_debt warn) "'
                   f'"$(_map_severity_to_debt critical)"', cwd=tmp_path)
    assert result.stdout.strip() == "high medium critical", result.stdout


def test_review_md_wrapper_call_sites_count() -> None:
    """After refactor, review.md must have ≥10 wrapper invocations
    matching `blocking_gate_prompt_emit`."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    invocations = text.count("blocking_gate_prompt_emit")
    assert invocations >= 10, (
        f"expected ≥10 wrapper invocations after refactor, found {invocations}"
    )


def test_review_md_no_orphan_blocked_exit_1() -> None:
    """No `emit-event review.<X>_blocked` should be immediately followed
    by `exit 1` after refactor — must call wrapper instead."""
    import re
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Find every emit-event review.X_blocked, look for exit 1 within 6 lines after
    bad_patterns = re.findall(
        r'emit-event "review\.[a-z_]+_blocked"[^\n]*\n(?:[^\n]*\n){0,6}\s*exit 1',
        text
    )
    assert not bad_patterns, (
        f"found {len(bad_patterns)} `*_blocked emit + exit 1` patterns "
        f"(should be wrapper calls):\n" + "\n---\n".join(bad_patterns[:3])
    )
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_blocking_gate_prompt.py -v
```

Expected: 7 failures (wrapper file doesn't exist + review.md not yet refactored).

- [ ] **Step 5: Write the wrapper bash file**

Create `scripts/lib/blocking-gate-prompt.sh`:

```bash
#!/usr/bin/env bash
# Task 33 — Blocking-gate 2-leg wrapper. See _shared/lib/blocking-gate-prompt-contract.md.

# Severity → override-debt vocab mapping
_map_severity_to_debt() {
  case "$1" in
    critical) echo "critical" ;;
    error) echo "high" ;;
    warn) echo "medium" ;;
    *) echo "medium" ;;  # unknown defaults to medium (loud-fail-soft)
  esac
}

# Leg 1: emit structured prompt JSON
# Args: <gate_id> <evidence_path> <severity> [fix_hint_path]
blocking_gate_prompt_emit() {
  local gate_id="$1"
  local evidence_path="$2"
  local severity="${3:-error}"
  local fix_hint_path="${4:-}"

  if [[ -z "$gate_id" ]]; then
    echo "ERROR: blocking_gate_prompt_emit requires gate_id" >&2
    return 64
  fi
  if [[ "$severity" != "warn" && "$severity" != "error" && "$severity" != "critical" ]]; then
    echo "ERROR: severity must be warn|error|critical, got: $severity" >&2
    return 64
  fi

  # Non-interactive short-circuit
  if [[ "${ARGUMENTS:-}" =~ --non-interactive ]]; then
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
      "review.aborted_non_interactive_block" --actor user --outcome BLOCK \
      --payload "{\"gate\":\"${gate_id}\",\"reason\":\"non-interactive auto-abort\"}" \
      >/dev/null 2>&1 || true
    cat <<EOF
{"gate_id": "${gate_id}", "severity": "${severity}", "non_interactive_auto_abort": true, "options": []}
EOF
    return 0
  fi

  # Read evidence + fix_hint snippets (truncated for prompt budget)
  local evidence_snippet=""
  if [[ -f "$evidence_path" ]]; then
    evidence_snippet=$(head -c 2000 "$evidence_path" | "${PYTHON_BIN:-python3}" -c '
import json, sys
sys.stdout.write(json.dumps(sys.stdin.read()))
')
  fi
  local fix_hint_snippet=""
  if [[ -n "$fix_hint_path" && -f "$fix_hint_path" ]]; then
    fix_hint_snippet=$(head -c 1000 "$fix_hint_path" | "${PYTHON_BIN:-python3}" -c '
import json, sys
sys.stdout.write(json.dumps(sys.stdin.read()))
')
  fi

  # Emit JSON describing the 4 options
  cat <<EOF
{
  "gate_id": "${gate_id}",
  "severity": "${severity}",
  "evidence_path": "${evidence_path}",
  "fix_hint_path": "${fix_hint_path}",
  "evidence_snippet": ${evidence_snippet:-\"\"},
  "fix_hint_snippet": ${fix_hint_snippet:-\"\"},
  "options": [
    {"key": "a", "label": "Auto-fix now (spawn subagent, max 3 attempts)"},
    {"key": "s", "label": "Skip with override (logs override-debt)"},
    {"key": "r", "label": "Route to /vg:amend (clean exit)"},
    {"key": "x", "label": "Abort review (clean exit)"}
  ]
}
EOF
  return 0
}

# Leg 2: dispatch based on user choice
# Args: <gate_id> --user-choice=<a|s|r|x> [--override-reason=<text>]
blocking_gate_prompt_resolve() {
  local gate_id="$1"; shift
  local user_choice="" override_reason=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user-choice=*) user_choice="${1#--user-choice=}" ;;
      --override-reason=*) override_reason="${1#--override-reason=}" ;;
    esac
    shift
  done

  case "$user_choice" in
    a)
      # Caller (orchestrator) MUST handle the subagent spawn before
      # invoking Leg 2. This branch is reached AFTER subagent returned.
      # Caller passes status via $VG_AUTOFIX_STATUS env.
      case "${VG_AUTOFIX_STATUS:-}" in
        FIXED)
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "review.gate_autofix_attempted" --actor agent --outcome PASS \
            --payload "{\"gate\":\"${gate_id}\",\"status\":\"FIXED\"}" \
            >/dev/null 2>&1 || true
          return 0
          ;;
        UNRESOLVED)
          "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
            "review.gate_autofix_attempted" --actor agent --outcome FAIL \
            --payload "{\"gate\":\"${gate_id}\",\"status\":\"UNRESOLVED\"}" \
            >/dev/null 2>&1 || true
          return 4  # re-prompt needed
          ;;
        OUT_OF_SCOPE|*)
          # Includes blocked_by=contract_amendment_required (auto-route to amend)
          if [[ "${VG_AUTOFIX_BLOCKED_BY:-}" == "contract_amendment_required" ]]; then
            return 2
          fi
          return 4
          ;;
      esac
      ;;
    s)
      if [[ -z "$override_reason" || "${#override_reason}" -lt 10 ]]; then
        echo "ERROR: --override-reason required (≥10 chars) for --user-choice=s" >&2
        return 64
      fi
      local debt_severity
      debt_severity=$(_map_severity_to_debt "${VG_GATE_SEVERITY:-error}")
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.gate_skipped_with_override" --actor user --outcome WARN \
        --payload "{\"gate\":\"${gate_id}\",\"reason\":\"${override_reason}\",\"debt_severity\":\"${debt_severity}\"}" \
        >/dev/null 2>&1 || true
      # Log debt via the existing override-debt helper
      type log_override_debt >/dev/null 2>&1 && \
        log_override_debt "review.gate.${gate_id}" "${PHASE_NUMBER:-?}" "${override_reason}" >/dev/null 2>&1 || true
      return 1
      ;;
    r)
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.routed_to_amend" --actor user --outcome INFO \
        --payload "{\"gate\":\"${gate_id}\"}" \
        >/dev/null 2>&1 || true
      echo "→ Run \`/vg:amend ${PHASE_NUMBER:-<phase>}\` to address the underlying decision change, then re-run review."
      return 2
      ;;
    x)
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "review.aborted_by_user" --actor user --outcome WARN \
        --payload "{\"gate\":\"${gate_id}\"}" \
        >/dev/null 2>&1 || true
      return 3
      ;;
    *)
      echo "ERROR: --user-choice must be a|s|r|x, got: $user_choice" >&2
      return 64
      ;;
  esac
}
```

- [ ] **Step 6: Refactor 12 review.md `*_blocked` sites — explicit per-site mapping (Codex round-3 B2 fix)**

Confirm the current site count by re-running:

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
grep -nE 'emit-event "review\.[a-z_]+_blocked"' commands/vg/review.md
```

Empirically (2026-05-04 baseline): **12 sites across 10 distinct gate IDs**
(`review.api_precheck_blocked` appears at 3 sites — Phase 2a.5 first-pass,
recheck-after-amend, recheck-after-fix-loop). Round-1 spec said "13" but
includes 1 currently dead branch; refactor only the 12 live sites.

Per-site mapping table (executor MUST apply this verbatim — no
imagination):

| # | review.md line (2026-05-04) | gate_id (`<X>`) | severity | EVIDENCE_PATH suffix | Existing `echo "⛔..."` line above? | Notes |
|---|---|---|---|---|---|---|
| 1 | 2169 | `preflight_invariants` | error | `.vg/preflight-invariants-evidence.json` | yes — DELETE | preflight_invariants_blocked |
| 2 | 2249 | `rcrurd_preflight` | error | `.vg/rcrurd-preflight-evidence.json` | yes — DELETE | rcrurd_preflight_blocked |
| 3 | 2675 | `api_precheck` | error | `.vg/api-precheck-evidence.json` | yes — DELETE | First-pass Phase 2a.5 |
| 4 | 2758 | `api_precheck` | error | `.vg/api-precheck-evidence.json` | yes — DELETE | After-amend recheck (same evidence path; Leg 2 inspects existing evidence) |
| 5 | 2783 | `api_precheck` | error | `.vg/api-precheck-evidence.json` | yes — DELETE | After-fix-loop recheck |
| 6 | 7209 | `matrix_evidence_link` | warn | `.vg/matrix-evidence-link-evidence.json` | yes — DELETE | matrix_evidence_link_blocked |
| 7 | 7301 | `rcrurd_post_state` | error | `.vg/rcrurd-post-state-evidence.json` | yes — DELETE | rcrurd_post_state_blocked |
| 8 | 7331 | `matrix_staleness` | warn | `.vg/matrix-staleness-evidence.json` | yes — DELETE | Payload includes `suspected: <N>` |
| 9 | 7368 | `evidence_provenance` | error | `.vg/evidence-provenance-evidence.json` | yes — DELETE | evidence_provenance_blocked |
| 10 | 7395 | `mutation_submit` | error | `.vg/mutation-submit-evidence.json` | yes — DELETE | mutation_submit_blocked |
| 11 | 7416 | `rcrurd_depth` | warn | `.vg/rcrurd-depth-evidence.json` | yes — DELETE | rcrurd_depth_blocked |
| 12 | 7430 | `asserted_drift` | error | `.vg/asserted-drift-evidence.json` | yes — DELETE | asserted_drift_blocked |

(Re-verify line numbers with grep before editing — review.md may have
shifted by a few lines since this baseline was taken.)

For EACH row, perform this substitution. The before/after pattern is
identical across all 12 sites; only `<X>`, `<EVIDENCE_PATH>`, and
`<SEVERITY>` change per row.

**Before (typical 4-line block):**

```bash
echo "⛔ <gate-X> BLOCK — fix path: <existing hint>"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.<X>_blocked" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
exit 1
```

**After (per row above):**

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "review.<X>_blocked" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true

source scripts/lib/blocking-gate-prompt.sh
EVIDENCE_PATH="${PHASE_DIR}/<EVIDENCE_PATH suffix from table>"
mkdir -p "$(dirname "$EVIDENCE_PATH")"
cat > "$EVIDENCE_PATH" <<JSON
{
  "gate": "<X>",
  "summary": "<one-line cause taken from the deleted echo string>",
  "fix_hint": "<the fix-path: ... portion of the deleted echo string>"
}
JSON
blocking_gate_prompt_emit "<X>" "$EVIDENCE_PATH" "<SEVERITY from table>"
# AI controller calls AskUserQuestion → resolve via Leg 2.
# Leg 2 exit codes: 0=continue, 1=continue-with-debt, 2=route-amend (exit 0), 3=abort (exit 1), 4=re-prompt.
```

**Key notes:**
- DELETE the `echo "⛔ ..."` line above the emit-event call. Its content
  is now folded into the JSON evidence file's `summary` + `fix_hint`
  fields. Wrapper renders these to the user via AskUserQuestion.
- DELETE the trailing `exit 1`. Wrapper Leg 2 controls flow.
- Sites 3, 4, 5 (api_precheck triple) share `EVIDENCE_PATH`. That's
  intentional — wrapper writes a fresh evidence file each time, so
  late writes overwrite stale ones. Don't rename to `-1` / `-2` / `-3`.
- Severity vocab: `error` ⇒ override-debt severity `high`; `warn` ⇒
  override-debt severity `medium` (per the wrapper's
  `_map_severity_to_debt()` table).

Add a refactor-coverage assertion to `tests/test_blocking_gate_prompt.py`:

```python
def test_review_md_has_no_remaining_exit_1_after_blocked_emit() -> None:
    """Codex round-3 B2: every site that emits review.<X>_blocked MUST be
    followed by blocking_gate_prompt_emit, not exit 1."""
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    # Find each emit-event "review.<X>_blocked" call site
    for m in re.finditer(r'emit-event "review\.[a-z_]+_blocked"', text):
        # Look at the next ~20 lines for blocking_gate_prompt_emit before any exit 1
        tail = text[m.end():m.end() + 2000]
        first_emit = tail.find("blocking_gate_prompt_emit")
        first_exit_1 = tail.find("\nexit 1")
        assert first_emit != -1, f"site at offset {m.start()} missing blocking_gate_prompt_emit"
        if first_exit_1 != -1:
            assert first_emit < first_exit_1, \
                f"site at offset {m.start()} has exit 1 BEFORE wrapper invocation (un-refactored?)"
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/lib/blocking-gate-prompt.sh
python3 -m pytest tests/test_blocking_gate_prompt.py -v
```

Expected: 7 PASSed.

- [ ] **Step 7.5: Declare 5 NEW telemetry events in `commands/vg/review.md` `must_emit_telemetry` block (Codex round-3 B3 fix)**

Spec lines 770-781 mandate that every NEW event MUST appear in the slim
entry's `must_emit_telemetry` frontmatter — otherwise the Stop hook
silent-skips the event and `/vg:gate-stats` queries return empty.

Edit `commands/vg/review.md`. Locate `must_emit_telemetry:` (line 149).
Append these 5 entries (paste alongside the existing list):

```yaml
    # Task 33 — 2-leg blocking-gate wrapper (Bug A)
    - event_type: "review.gate_skipped_with_override"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.gate_autofix_attempted"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.gate_autofix_unresolved"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.routed_to_amend"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.aborted_by_user"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
    - event_type: "review.aborted_non_interactive_block"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

Add a test to `tests/test_blocking_gate_prompt.py`:

```python
def test_review_md_declares_all_wrapper_telemetry_events() -> None:
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    for event in [
        "review.gate_skipped_with_override",
        "review.gate_autofix_attempted",
        "review.gate_autofix_unresolved",
        "review.routed_to_amend",
        "review.aborted_by_user",
        "review.aborted_non_interactive_block",
    ]:
        assert event in text, \
            f"review.md must_emit_telemetry must declare '{event}' (else Stop hook silent-skips)"
```

Re-run pytest after this; the new test must pass.

- [ ] **Step 8: Sync mirrors**

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
python3 scripts/vg_sync_codex.py --apply 2>&1 | tail -2
```

- [ ] **Step 9: Commit**

```bash
git add commands/vg/_shared/lib/blocking-gate-prompt-contract.md \
        commands/vg/_shared/lib/review-fix-loop-delegation.md \
        scripts/lib/blocking-gate-prompt.sh \
        commands/vg/review.md \
        tests/test_blocking_gate_prompt.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(review): 2-leg blocking-gate wrapper + refactor 13 *_blocked sites (Task 33, Bug A)

Pre-fix: 13 review.md *_blocked emit-event paths immediately exit 1.
User must restart review from scratch every BLOCK iteration. PV3
events.db showed 5 review re-runs in one debug session.

Post-fix: 2-leg wrapper presents 4-option AskUserQuestion:
- [a] Auto-fix subagent (max 3 attempts, review-shaped contract)
- [s] Skip with override (logs override-debt, severity-vocab-mapped)
- [r] Route to /vg:amend (clean exit + handoff message)
- [x] Abort review (clean exit, run-complete with aborted_by_user)

Leg 1 emits JSON; AI controller calls AskUserQuestion; Leg 2
dispatches based on choice. Exit codes 0/1/2/3/4 documented in
blocking-gate-prompt-contract.md. --non-interactive mode
auto-aborts (CI-safe).

Subagent contract is review-shaped (deployed-app + artifacts scope),
NOT build-shaped (Task 10 ownership-window scope). Forbidden
API-CONTRACTS edits short-circuit to [r] route-to-amend.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
