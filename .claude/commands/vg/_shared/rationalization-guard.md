---
name: vg:_shared:rationalization-guard
description: Rationalization Guard (Shared Reference) — spawns isolated Haiku subagent with zero parent context to adjudicate gate-skip requests. Same-model guard was 4/4 CrossAI CRITICAL — replaced with separate model.
---

# Rationalization Guard — Shared Helper (v1.9.0 — subagent isolation)

When an executing agent wants to skip a hard gate (via `--allow-*` / `--skip-*` / `--override-reason=`), a **separate Haiku subagent** with **zero parent context** adjudicates. The subagent reads only: (a) gate spec, (b) skip reason supplied by executor. It returns PASS / FLAG / ESCALATE.

## Why this changed (v1.9.0)

Prior versions used a same-model "rationalization table" — the executing agent self-checked against a markdown cheat-sheet. Under pressure the model classified its own skip as "acceptable" (confirmation bias). 4/4 CrossAI Round 2 flagged this CRITICAL after v1.8.0 added 4 new gate types (artifact manifest, override resolution, drift WARN, gate-integrity) — rationalization surface grew faster than defenses.

**New mechanism:** distinct subagent session (different model, fresh context, no transcript history). It cannot see what the executor is trying to accomplish — only the gate rule and the proposed justification.

## API

```
rationalization_guard_check(gate_id, gate_spec_text, skip_reason) → {verdict, reason, confidence}
```

- `gate_id` (str): telemetry gate id (e.g. `"not-scanned-defer"`, `"wave-commits"`, `"design-check"`).
- `gate_spec_text` (str): the gate's own spec — what it enforces + why. Copy from command markdown.
- `skip_reason` (str): raw justification supplied via `--reason=` (or auto-derived — e.g. `"missing=[12,14]"`).
- **Returns** (structured — one line of stdout, strict JSON):
  - `verdict`: `"PASS"` | `"FLAG"` | `"ESCALATE"`
  - `reason`: 1-sentence justification from subagent
  - `confidence`: `"low"` | `"medium"` | `"high"`

### Caller contract (how to act on each verdict)

| Verdict | Meaning | Caller action |
|---------|---------|---------------|
| `PASS` | Justification is concrete + gate-appropriate | Proceed with override + `log_override_debt` as normal |
| `FLAG` | Justification is vague / generic / rationalizing but not actively wrong | Proceed BUT log debt as `severity: critical` (force resolution sooner), emit telemetry `gate_id`+`verdict=FLAG` |
| `ESCALATE` | Subagent believes override is structurally wrong (e.g. "should work now" with no evidence, scope creep, time pressure excuse) | BLOCK — prompt user via AskUserQuestion with subagent's reason. User may override with fresh `--reason='<concrete-justification>'` that re-triggers guard |

## Implementation

```bash
# Check if rationalization guard is enabled for this gate (config-driven)
rationalization_guard_enabled() {
  local gate_id="$1"
  [ "${CONFIG_RATIONALIZATION_GUARD_ENABLED:-true}" = "true" ] || return 1
  # Optional per-gate allowlist via config; if not set, guard applies to ALL gates
  local allowed="${CONFIG_RATIONALIZATION_GUARD_GATES:-*}"
  [ "$allowed" = "*" ] && return 0
  case " $allowed " in *" $gate_id "*) return 0 ;; *) return 1 ;; esac
}

# Main API — spawn isolated Haiku subagent to adjudicate a gate-skip
# Usage: result=$(rationalization_guard_check "$gate_id" "$gate_spec_text" "$skip_reason")
# Result format (single line): {"verdict":"PASS|FLAG|ESCALATE","reason":"...","confidence":"low|medium|high"}
rationalization_guard_check() {
  local gate_id="$1"
  local gate_spec_text="$2"
  local skip_reason="$3"

  if ! rationalization_guard_enabled "$gate_id"; then
    echo '{"verdict":"PASS","reason":"guard disabled for this gate","confidence":"low"}'
    return 0
  fi

  local subagent_model="${CONFIG_RATIONALIZATION_GUARD_MODEL:-haiku}"

  # Spawn subagent via Task tool with ZERO parent context.
  # The orchestrator layer calling this function MUST use the Task tool with:
  #   subagent_type: "general-purpose"
  #   model: $subagent_model  (default: haiku)
  #   prompt: <<PROMPT below — embedded only, no reference to session state>>
  #
  # Because shell cannot invoke Task directly, callers embed the prompt file path and
  # the orchestrator (VG command) invokes Task before this helper returns. See
  # "Caller integration" section below for the required wrapper pattern.
  #
  # This function writes the prompt to a tmp file and emits the path on fd 3 so the
  # VG command can pick it up, dispatch to Task, and pipe the subagent's output back.

  local prompt_path="${VG_TMP:-/tmp}/ratguard-$(date +%s)-$$.txt"
  mkdir -p "$(dirname "$prompt_path")" 2>/dev/null || true
  cat > "$prompt_path" <<PROMPT
You are a Rationalization Guard subagent. You have ZERO context about the parent session.
Your ONLY job: decide whether a proposed gate-skip justification is concrete enough to proceed.

═════════════════════════════════════════════════════════════════════════
GATE UNDER REVIEW (id: ${gate_id})
═════════════════════════════════════════════════════════════════════════
${gate_spec_text}

═════════════════════════════════════════════════════════════════════════
PROPOSED SKIP JUSTIFICATION (from executor)
═════════════════════════════════════════════════════════════════════════
${skip_reason}

═════════════════════════════════════════════════════════════════════════
YOUR DECISION
═════════════════════════════════════════════════════════════════════════
Classify the justification as exactly ONE of:

• PASS — reason is CONCRETE and gate-appropriate. Examples: cites issue ID/URL, names
  specific failing test + known flakiness, identifies infra blocker beyond this phase.

• FLAG — reason is plausible but VAGUE or partially rationalizing. Examples:
  "tests were green yesterday", "minor issue", "will fix next phase", "not blocking".
  Override proceeds but debt escalated to critical severity.

• ESCALATE — reason is a RATIONALIZATION pattern. Examples:
  "should work now" (no verification), "agent reported success" (no independent check),
  "small fix, won't hurt" (scope creep), "confident it passes" (confidence ≠ evidence),
  "I'll verify later" (later = never), "close enough", time-pressure excuses,
  unrelated to the actual gate.

Also consider confidence: "low" if reason ambiguous, "medium" if reason typical-but-checkable,
"high" if reason clearly concrete OR clearly rationalizing.

OUTPUT FORMAT — exactly ONE line of strict JSON, no prose before/after:
{"verdict":"PASS|FLAG|ESCALATE","reason":"<one sentence ≤ 120 chars>","confidence":"low|medium|high"}
PROMPT

  # Emit prompt path on fd 3 for orchestrator to pick up; also on stderr for debugging
  echo "$prompt_path" >&3 2>/dev/null || true
  echo "ratguard-prompt: $prompt_path" >&2

  # Orchestrator (VG command) is responsible for:
  #   1. Reading the prompt at $prompt_path
  #   2. Dispatching Task tool (subagent_type=general-purpose, model=$subagent_model)
  #   3. Capturing subagent stdout (one JSON line)
  #   4. Returning that JSON to the caller
  #
  # When called from inside the Claude harness (not raw shell), the VG command MUST
  # replace this shell function with a direct Task-tool invocation — see pattern below.
  #
  # Fallback for pure-shell contexts (no Task available): return ESCALATE to force
  # user adjudication rather than silently passing (fail-closed).
  echo '{"verdict":"ESCALATE","reason":"Task tool unavailable — guard failed closed, user must adjudicate","confidence":"high"}'
}

# Post-verdict dispatcher — call immediately after rationalization_guard_check
# Usage: rationalization_guard_dispatch "$result_json" "$gate_id" "$flag" "$phase" "$step" "$skip_reason"
# Returns: 0 if override may proceed (PASS or FLAG), 1 if must block (ESCALATE)
rationalization_guard_dispatch() {
  local result="$1" gate_id="$2" flag="$3" phase="$4" step="$5" skip_reason="$6"
  local verdict reason confidence subagent_model="${CONFIG_RATIONALIZATION_GUARD_MODEL:-haiku}"
  verdict=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('verdict',''))" "$result" 2>/dev/null || echo "")
  reason=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('reason',''))" "$result" 2>/dev/null || echo "")
  confidence=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.loads(sys.argv[1]).get('confidence',''))" "$result" 2>/dev/null || echo "")

  # Telemetry — event type MUST be "rationalization_guard_check"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "rationalization_guard_check" "$phase" "$step" "$gate_id" "$verdict" \
      "{\"flag\":\"$flag\",\"confidence\":\"$confidence\",\"subagent_model\":\"$subagent_model\",\"subagent_reason\":\"${reason//\"/\\\"}\"}"
  fi

  case "$verdict" in
    PASS)
      echo "✓ Rationalization guard (bảo vệ biện minh): PASS — ${reason}"
      return 0
      ;;
    FLAG)
      echo "⚠ Rationalization guard (bảo vệ biện minh): FLAG — ${reason}"
      echo "   Override sẽ proceed nhưng debt ghi nhận ở severity CRITICAL (thay vì default)."
      # Caller log_override_debt will tag severity=critical via env var
      export VG_RATGUARD_FORCE_CRITICAL=1
      return 0
      ;;
    ESCALATE)
      echo "⛔ Rationalization guard (bảo vệ biện minh): ESCALATE — ${reason}"
      echo "   Subagent (${subagent_model}) phát hiện pattern biện minh — gate không được bỏ qua tự động."
      echo "   Options:"
      echo "     (a) Fix gate-ly bằng cách xử lý issue thực tế (recommended)"
      echo "     (b) Cung cấp --reason='<justification cụ thể hơn, có issue ID/URL>' và re-run"
      echo "     (c) Nếu chắc chắn muốn bỏ qua, confirm qua user prompt (AskUserQuestion)"
      return 1
      ;;
    *)
      # Malformed subagent output — fail closed
      echo "⛔ Rationalization guard: malformed subagent response — failing closed. Raw: $result"
      return 1
      ;;
  esac
}

# ═══════════════════════════════════════════════════════════════════════
# DEPRECATED — kept for backward compatibility (v1.8.x call sites)
# ═══════════════════════════════════════════════════════════════════════
# Old same-model guard. Emits WARN and returns PASS (non-blocking) so legacy
# call sites don't break while migrating. New code MUST use
# rationalization_guard_check + rationalization_guard_dispatch.
rationalization_guard() {
  echo "⚠ DEPRECATED: rationalization_guard() — same-model guard removed in v1.9.0." >&2
  echo "   Migrate to rationalization_guard_check() + rationalization_guard_dispatch()." >&2
  echo "   Legacy call will proceed without separate-model adjudication (INSECURE)." >&2
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "rationalization_guard_check" "${2:-}" "${3:-}" "${1:-legacy}" "LEGACY_SKIP" \
      "{\"deprecated\":true}"
  fi
  return 0
}
```

## Config (add to `.claude/vg.config.md`)

```yaml
rationalization_guard:
  enabled: true
  model: "haiku"                         # claude-haiku — cheap, fast, low context leak
  gates: "*"                             # "*" = all gates, OR space-separated list
  # Example allowlist for progressive rollout:
  # gates: "wave-commits not-scanned-defer build-hard-gate design-check"
```

## Caller integration pattern (inside VG commands)

At every gate-skip branch where `--allow-*` / `--skip-*` / `--override-reason=` is accepted, the orchestrator MUST invoke the guard BEFORE calling `log_override_debt`. Because the Task tool runs in the Claude harness (not raw shell), the idiomatic pattern is:

```markdown
If user supplies `--allow-intermediate`, BEFORE honoring it:

1. Read the gate spec block (embedded above in this command's markdown).
2. Invoke Task tool:
   - subagent_type: "general-purpose"
   - model: ${config.rationalization_guard.model}
   - prompt: <prompt built from rationalization_guard_check template — gate_id, gate_spec_text, skip_reason>
3. Parse subagent stdout (single JSON line): {verdict, reason, confidence}
4. Dispatch per verdict:
   - PASS → proceed with override + log_override_debt (normal severity)
   - FLAG → proceed with override + log_override_debt, but tag severity=critical
   - ESCALATE → BLOCK. Emit reason, offer AskUserQuestion. If user supplies new --reason, re-run guard.
5. Emit telemetry event `rationalization_guard_check` with {gate_id, verdict, confidence, subagent_model}.
```

## Integration points (patched in v1.9.0 T1)

| Command | Step | Flag | Gate ID |
|---------|------|------|---------|
| `build` | `4_design_manifest_check` | `--skip-design-check` | `design-check` |
| `build` | wave post-commit verify | `--allow-missing-commits` | `wave-commits` |
| `build` | wave test-infra | `--allow-no-tests` | `test-infra` |
| `build` | wave hard-gate | `--override-reason=` | `build-hard-gate` |
| `review` | `4c-pre` NOT_SCANNED | `--allow-intermediate` | `not-scanned-defer` |
| `test` | dynamic-id check | `--allow-dynamic-ids` | `dynamic-ids` |
| `accept` | unreachable triage | `--allow-unreachable` | `unreachable-triage` |
| `accept` | override-resolution | `--allow-unresolved-overrides` | `override-resolution-gate` |

Each of the above branches wraps its existing `if [[ "$ARGUMENTS" =~ --flag ]]` acceptance in a `rationalization_guard_check + dispatch` call.

## Rationalization patterns the subagent watches for

(These are the same patterns the old same-model table encoded — now enforced by an agent who can't see the context. Reference table for humans only; subagent infers from prompt.)

- "Should work now" / "I'm confident" — no evidence
- "Tests passed earlier" — stale, didn't re-run
- "Agent reported success" — no independent verification
- "Just this one time" — exception normalization
- "Close enough" / "minor" — quantitative hand-wave
- "I'll fix it later" / "cover in --deepen" — deferred-never pattern
- "Small fix, won't hurt" — scope-creep through auto-fix
- "CrossAI will catch it" — offloading to downstream gate
- Time pressure excuses (explicit or implicit)
- Unrelated justification (reason doesn't match gate)

## Success criteria

- Zero same-model self-audit remaining in VG gate paths
- Every gate-skip emits one `rationalization_guard_check` telemetry event
- ESCALATE verdicts block until user supplies concrete `--reason=` (re-triggers guard)
- FLAG verdicts auto-upgrade debt severity to critical
- Haiku subagent receives ONLY prompt contents — no repo state, no transcript, no session history
- Backward-compat: `rationalization_guard()` legacy name prints WARN and returns PASS (fail-open for migration window only — remove in v2.0.0)
