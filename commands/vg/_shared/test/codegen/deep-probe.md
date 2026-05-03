# test deep-probe (STEP 5 deep-probe sub-step — orchestrator-side, UNCHANGED)

This step runs DIRECTLY in the main agent (orchestrator-side). It is NOT
delegated to a subagent. It is read and executed AFTER `vg-test-codegen`
returns (see `codegen/overview.md` STEP 5.6).

Profile: `web-fullstack`, `web-frontend-only`, `web-backend-only`, `cli-tool`, `library`

---

## 5d-deep-probe: EDGE-CASE VARIANTS (v1.14.0+ B.3)

**Goal:** Generate 3 edge-case variants per READY goal, spawn Sonnet primary
+ Codex/Gemini/Haiku adversarial cross-check, escalate Opus when disagree >30%.

**Config driver:** `test.deep_probe_enabled`, `test.deep_probe_model_primary`,
`test.deep_probe_adversarial_chain`, `test.deep_probe_max_opus_escalations_per_phase`.

**Skip condition:** `test.deep_probe_enabled: false` OR no READY goals → skip step.

---

### 5d-deep.1: Preflight — detect adversarial CLI

```bash
vg-orchestrator step-active 5d_deep_probe

DEEP_PROBE_ENABLED=$(${PYTHON_BIN:-python3} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_enabled\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'true')
except Exception:
    print('true')
")

if [ "$DEEP_PROBE_ENABLED" != "true" ]; then
  echo "ℹ Deep-probe disabled (config.test.deep_probe_enabled=false) — skip step 5d-deep."
else
  # Walk adversarial chain; pick first CLI available
  ADVERSARIAL_CLI=""
  for cli in codex gemini claude; do
    if command -v "$cli" >/dev/null 2>&1; then
      ADVERSARIAL_CLI="$cli"
      break
    fi
  done

  SKIP_IF_UNAVAIL=$(${PYTHON_BIN:-python3} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_adversarial_skip_if_unavailable\s*:\s*(true|false)', c)
    print(m.group(1) if m else 'false')
except Exception:
    print('false')
")

  if [ -z "$ADVERSARIAL_CLI" ]; then
    if [ "$SKIP_IF_UNAVAIL" = "true" ]; then
      echo "⚠ No CLI available in adversarial chain (codex/gemini/claude) — primary only."
      ADVERSARIAL_CLI="(none)"
    else
      echo "⛔ Adversarial chain has no available CLI — config.skip_if_unavailable=false → BLOCK."
      echo "   Fix: install codex/gemini/claude CLI, or set deep_probe_adversarial_skip_if_unavailable: true."
      exit 1
    fi
  fi
  echo "▸ Deep-probe adversarial CLI selected: ${ADVERSARIAL_CLI}"
fi
```

---

### 5d-deep.2: Spawn primary agent (Sonnet)

For each READY goal (read from `${VG_TMP}/goal-status.json` written by codegen step):

**Bootstrap rule injection** — before spawn, render project rules targeting `test` step:
```bash
source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "${BOOTSTRAP_PAYLOAD_FILE:-}" "test")
vg_bootstrap_emit_fired "${BOOTSTRAP_PAYLOAD_FILE:-}" "test" "${PHASE_NUMBER}"
```

```
Agent(subagent_type="general-purpose", model="sonnet",
      name="deep-probe-{goal-id}"):
  prompt: |
    Generate 3 edge-case variants BEYOND happy path for goal {goal-id}.

    <bootstrap_rules>
    ${BOOTSTRAP_RULES_BLOCK}
    </bootstrap_rules>

    Input:
    - SPECS.md, CONTEXT.md, API-CONTRACTS.md, GOAL-COVERAGE-MATRIX.md
    - Happy-path spec: apps/web/e2e/generated/{phase}/goal-{goal-id}.spec.ts

    Categories (auto-select by surface):
    - `ui`:          boundary values, auth-negative (wrong role), rapid-fire clicks
    - `api`:         malformed payload, rate-limit, injection (SQL/XSS)
    - `data`:        concurrent write, schema-drift, partition boundary
    - `time-driven`: just-before / just-after / exact-boundary timestamp

    Output: apps/web/e2e/generated/{phase}/goal-{goal-id}.deep.spec.ts
    Each variant annotated:
    - `.variant('hard')` — MUST pass (real bug if fail)
    - `.variant('advisory')` — MAY fail (edge case uncertain; CI reports but does not block)

    Reuse imports + helpers from happy-path file when available.
```

---

### 5d-deep.3: Adversarial cross-check

After primary generates → spawn adversarial agent (CLI selected in 5d-deep.1):

```bash
# Invoke adversarial CLI with same input + primary output, ask:
# 1. Are any variants testing invalid-by-design scenarios? → mark reject
# 2. Are any `hard` variants actually uncertain edge cases? → demote `advisory`
# 3. Are there edge-case categories primary missed? → suggest add
```

**Consensus rule:**
- Primary + adversarial agree 100% → keep as-is.
- Disagree on 1-2 variants → adversarial's demote/reject applied.
- Disagree >30% variants → **escalate Opus** (if
  `deep_probe_escalate_to_opus_on_conflict: true` and budget
  `deep_probe_max_opus_escalations_per_phase` not exhausted).

---

### 5d-deep.4: Opus escalation (budget-guarded)

```bash
OPUS_BUDGET=$(${PYTHON_BIN:-python3} -c "
import re
try:
    with open('.claude/vg.config.md', encoding='utf-8') as f:
        c = f.read()
    m = re.search(r'deep_probe_max_opus_escalations_per_phase\s*:\s*(\d+)', c)
    print(m.group(1) if m else '2')
except Exception:
    print('2')
")

# Track escalation count in .vg/phases/{phase}/.deep-probe-opus-count
OPUS_COUNT_FILE="${PHASE_DIR}/.deep-probe-opus-count"
OPUS_USED=$(cat "$OPUS_COUNT_FILE" 2>/dev/null || echo 0)

if [ "$OPUS_USED" -lt "$OPUS_BUDGET" ]; then
  # Spawn Opus with full context (primary + adversarial + conflict detail)
  # Opus decides final verdict — write goal-{id}.deep.spec.ts with correct variants
  echo "$((OPUS_USED + 1))" > "$OPUS_COUNT_FILE"
else
  echo "⚠ Opus escalation budget exhausted ($OPUS_BUDGET/phase) — fallback: keep primary output, annotate uncertain variants `advisory`."
fi
```

---

### 5d-deep.5: Variant annotation semantics

Generated file format:

```typescript
// === Deep-probe variants for goal {goal-id} ===
// Primary: sonnet, Adversarial: ${ADVERSARIAL_CLI}, Escalated: ${opus_escalation_status}

import { test, expect } from '@playwright/test';

test.describe('goal-{goal-id}.deep', () => {
  test('variant hard: boundary max length', async ({ page }) => {
    // MUST pass; fail = real bug
    // ...
  });

  test('variant advisory: rapid-fire double submit', async ({ page }) => {
    // MAY fail (UX race); CI warns but does not block
    test.info().annotations.push({ type: 'variant', description: 'advisory' });
    // ...
  });
});
```

CI reader (step 18+) processes:
- variant `hard` fail → test exit 1 + gate block.
- variant `advisory` fail → warn only, phase still passes.

---

### 5d-deep.6: Fallthrough

If `DEEP_PROBE_ENABLED=false` OR READY goal count = 0 → step 5d-deep.* is
skipped. Phase continues to regression.

Final action (regardless of skip or run):
```bash
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "5d_deep_probe" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/5d_deep_probe.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step test 5d_deep_probe 2>/dev/null || true
```
