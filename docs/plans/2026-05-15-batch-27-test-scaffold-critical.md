# Batch 27 — Test phase CRITICAL scaffold fixes (write_report + regression + security) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 most critical /vg:test scaffold gaps from Codex audit `2026-05-15-codex-test-flow-audit.md`.

- **G1 CRITICAL**: `write_report` never writes `${PHASE_DIR}/SANDBOX-TEST.md`. close.md:148-217 shows markdown template via prose, no bash Write op. `must_write` contract claims file but file may not exist.
- **G2 CRITICAL**: `5e_regression` captures no Playwright rc. `REGRESSION_STATUS` defaults to PASS at line 258 → mark fires PASS even when tests fail.
- **G3 CRITICAL**: `5f_security_audit` Tier 0/1 findings set vars then mark PASS default. Critical/high findings don't trigger FAIL.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "write_report or regression_rc or security_audit_fail or batch_27"`
- Single Co-Authored-By trailer per commit
- Global paths pattern

---

## Task 1: G1 — write_report actually writes SANDBOX-TEST.md

**Files:**
- Modify: `commands/vg/_shared/test/close.md` (between line 144 `.verdict-computed.json` write and line 215 `git add`)
- Mirror
- Test: `tests/test_batch27_write_report_artifact.py`

**Step 1: Failing test**

```python
"""tests/test_batch27_write_report_artifact.py — G1 write_report SANDBOX-TEST.md."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "commands" / "vg" / "_shared" / "test" / "close.md"


def test_close_has_bash_write_sandbox_test():
    body = CLOSE.read_text(encoding="utf-8")
    # Must have actual bash cat > or python Path().write_text writing SANDBOX-TEST.md
    # NOT just a prose template
    sandbox_idx = body.find("SANDBOX-TEST.md")
    assert sandbox_idx > 0
    # Find any bash block that ACTUALLY writes the file
    has_real_write = (
        ('cat > "${PHASE_DIR}/SANDBOX-TEST.md"' in body) or
        ("write_text" in body and "SANDBOX-TEST" in body) or
        ('SANDBOX_TEST="${PHASE_DIR}/SANDBOX-TEST.md"' in body and "EOF" in body)
    )
    assert has_real_write, (
        "G1 Batch 27: close.md must contain BASH that writes "
        "${PHASE_DIR}/SANDBOX-TEST.md (not just prose markdown template). "
        "AI can extend later — bash MUST create the file with at least "
        "frontmatter + verdict so Stop hook must_write passes."
    )


def test_sandbox_test_creation_before_git_add():
    body = CLOSE.read_text(encoding="utf-8")
    git_add_idx = body.find('git add "${PHASE_DIR}/SANDBOX-TEST.md"')
    if git_add_idx < 0:
        git_add_idx = body.find('git add ${PHASE_DIR}/SANDBOX-TEST.md')
    assert git_add_idx > 0
    # Before git add, must have write operation
    pre_add = body[:git_add_idx]
    has_write_before = (
        'cat > "${PHASE_DIR}/SANDBOX-TEST.md"' in pre_add or
        ('SANDBOX_TEST=' in pre_add and 'EOF' in pre_add)
    )
    assert has_write_before, (
        "G1: bash Write op for SANDBOX-TEST.md must come BEFORE git add"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/test/close.md` BEFORE the `git add` block, insert bash that writes a real SANDBOX-TEST.md (template stays as instruction for AI to enrich):

```bash
# G1 Batch 27: actually write SANDBOX-TEST.md so must_write contract satisfied.
# AI may extend with goal details, but bash MUST create file with frontmatter
# + verdict line for Stop hook to find.
SANDBOX_TEST="${PHASE_DIR}/SANDBOX-TEST.md"
TS=$(date -u +%FT%TZ)
DEPLOY_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
ENV_NAME="${ENV:-sandbox}"

cat > "$SANDBOX_TEST" <<EOF
---
phase: "${PHASE_NUMBER}"
tested: "${TS}"
status: "${VERDICT}"
deploy_sha: "${DEPLOY_SHA}"
environment: "${ENV_NAME}"
---

# Sandbox Test Report — Phase ${PHASE_NUMBER}

## Verdict: ${VERDICT}

Counters (from .verdict-computed.json):

\`\`\`json
$(cat "${PHASE_DIR}/.verdict-computed.json" 2>/dev/null || echo '{}')
\`\`\`

## Stage Markers

- 5a Deploy: $([ -f "${PHASE_DIR}/.step-markers/5a_deploy.done" ] && echo "✓ done" || echo "skipped")
- 5b Runtime Contract: $([ -f "${PHASE_DIR}/.step-markers/5b_runtime_contract_verify.done" ] && echo "✓ done" || echo "skipped")
- 5c Goal Verification: $([ -f "${PHASE_DIR}/.step-markers/5c_goal_verification.done" ] && echo "✓ done" || echo "skipped")
- 5e Regression: $([ -f "${PHASE_DIR}/.step-markers/5e_regression.done" ] && echo "✓ done — status=${REGRESSION_STATUS:-?}" || echo "skipped")
- 5f Security: $([ -f "${PHASE_DIR}/.step-markers/5f_security_audit.done" ] && echo "✓ done — status=${SECURITY_STATUS:-?}" || echo "skipped")

## Detail

AI controller MUST extend this report with per-goal pass/fail table,
fix-loop summary, and screenshots after computing verdict. The bash
above ensures the artifact EXISTS (Stop hook must_write satisfied) —
AI controller appends/refines.

See:
- \`${PHASE_DIR}/TEST-FAILURE-REPORT.md\` (H13 — per-failure detail)
- \`${PHASE_DIR}/.verdict-computed.json\` (canonical counters)
EOF

echo "✓ G1: wrote ${SANDBOX_TEST} (${VERDICT})"
```

```bash
git commit -m "fix(test): G1 Batch 27 — close.md actually writes SANDBOX-TEST.md (CRITICAL)

Codex test audit G1: must_write contract claims SANDBOX-TEST.md but
close.md:148-217 only shows markdown TEMPLATE as prose. AI writer 'should'
embed values. No bash Write op. File may not exist when Stop hook checks
must_write.

Fix: bash heredoc creates file with frontmatter + verdict + stage marker
summary + reference to .verdict-computed.json + TEST-FAILURE-REPORT.md
BEFORE git add. AI can extend with detail tables/screenshots after.

Stop hook must_write satisfied without depending on AI follow-through.

Tests: tests/test_batch27_write_report_artifact.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: G2 — 5e_regression captures Playwright rc, marks FAIL on non-zero

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (line 180-261 playwright invocation + marker)
- Mirror
- Test: `tests/test_batch27_regression_rc_check.py`

**Step 1: Failing test**

```python
"""tests/test_batch27_regression_rc_check.py — G2 regression rc capture."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_playwright_rc_captured():
    body = RS.read_text(encoding="utf-8")
    pw_idx = body.find("npx playwright test")
    assert pw_idx > 0
    block = body[pw_idx:pw_idx + 2500]
    # After playwright invocation must capture rc
    assert ("PLAYWRIGHT_RC=$?" in block or "PIPESTATUS" in block), (
        "G2 Batch 27: regression-security.md must capture playwright exit "
        "code after invocation. Currently REGRESSION_STATUS defaults to PASS "
        "even when tests fail."
    )


def test_regression_status_set_from_rc():
    body = RS.read_text(encoding="utf-8")
    # REGRESSION_STATUS must be set to FAIL when rc != 0
    assert ('REGRESSION_STATUS="FAIL"' in body or 'REGRESSION_STATUS=FAIL' in body or
            'REGRESSION_STATUS = "FAIL"' in body), (
        "G2: REGRESSION_STATUS must be set to FAIL on non-zero playwright rc"
    )


def test_emit_event_on_regression_fail():
    body = RS.read_text(encoding="utf-8")
    assert "test.regression_failed" in body or "regression.failed" in body, (
        "G2: must emit test.regression_failed event when playwright rc != 0"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/test/regression-security.md` replace the playwright invocation block:

```bash
# G2 Batch 27: capture playwright exit code. Default REGRESSION_STATUS=PASS
# (line 258) → marks PASS even on test failure. Fix: capture rc, set
# REGRESSION_STATUS=FAIL on non-zero, emit event.
set +e
run_on_target "cd ${PROJECT_PATH} && \
  VG_HEADED=${VG_HEADED} VG_SLOW_MO=${SLOW_MO} \
  npx playwright test \
    --config ${GENERATED_TESTS_DIR}/playwright.config.generated.ts \
    ${PROJECT_FLAG} \
    ${PLAYWRIGHT_TARGETS}"
PLAYWRIGHT_RC=$?
set -e

if [ "$PLAYWRIGHT_RC" -ne 0 ]; then
  REGRESSION_STATUS="FAIL"
  REGRESSION_REASON="playwright exit code ${PLAYWRIGHT_RC}"
  echo "⛔ G2: regression FAIL — playwright rc=${PLAYWRIGHT_RC}" >&2
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "test.regression_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"rc\":${PLAYWRIGHT_RC}}" >/dev/null 2>&1 || true
else
  REGRESSION_STATUS="PASS"
fi
```

```bash
git commit -m "fix(test): G2 Batch 27 — 5e_regression captures Playwright rc + FAIL on non-zero (CRITICAL)

Codex test audit G2: 'npx playwright test' invocation didn't capture
\$? before mark. REGRESSION_STATUS defaulted to PASS at line 258
regardless of test outcome.

Fix: set +e around playwright call, capture PLAYWRIGHT_RC=\$?, branch:
- rc != 0 → REGRESSION_STATUS=FAIL + REGRESSION_REASON + emit
  test.regression_failed event
- rc == 0 → REGRESSION_STATUS=PASS

Marker now reflects actual playwright outcome. step-status-ledger
gets real status. Downstream verdict computation sees FAIL not PASS.

Tests: tests/test_batch27_regression_rc_check.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: G3 — 5f_security_audit Tier findings → mark FAIL not PASS default

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (around line 285 5f_security_audit step)
- Mirror
- Test: `tests/test_batch27_security_audit_fail.py`

**Step 1: Failing test**

```python
"""tests/test_batch27_security_audit_fail.py — G3 security audit FAIL on findings."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_security_status_default_not_unconditional_pass():
    body = RS.read_text(encoding="utf-8")
    sec_idx = body.find("5f_security_audit")
    assert sec_idx > 0
    block = body[sec_idx:sec_idx + 5000]
    # Must NOT have unconditional 'SECURITY_STATUS=PASS' as default after Tier check
    # Must set status based on findings count
    assert ("SECURITY_STATUS=FAIL" in block or "security_audit.failed" in block), (
        "G3 Batch 27: 5f_security_audit must set SECURITY_STATUS=FAIL when "
        "Tier 0/1/2 finds critical/high severity issues. Currently default "
        "PASS regardless of findings."
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Find existing Tier check block (around line 285-440) and insert summary FAIL logic:

```bash
# G3 Batch 27: aggregate Tier 0/1/2 critical+high findings → set
# SECURITY_STATUS. Default unconditional PASS removed.
SECURITY_CRITICAL_COUNT="${SECURITY_CRITICAL_COUNT:-0}"
SECURITY_HIGH_COUNT="${SECURITY_HIGH_COUNT:-0}"
SECURITY_TIER_FAIL="${SECURITY_TIER_FAIL:-0}"

if [ "${SECURITY_CRITICAL_COUNT:-0}" -gt 0 ] || [ "${SECURITY_HIGH_COUNT:-0}" -gt 0 ] || [ "${SECURITY_TIER_FAIL:-0}" -gt 0 ]; then
  SECURITY_STATUS="FAIL"
  SECURITY_REASON="${SECURITY_CRITICAL_COUNT} critical + ${SECURITY_HIGH_COUNT} high findings"
  echo "⛔ G3: security audit FAIL — ${SECURITY_REASON}" >&2
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "test.security_audit_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"critical\":${SECURITY_CRITICAL_COUNT},\"high\":${SECURITY_HIGH_COUNT}}" >/dev/null 2>&1 || true
else
  SECURITY_STATUS="PASS"
fi
```

(Insert AFTER all Tier 0/1/2/3 checks have set their respective `SECURITY_*_COUNT` vars, BEFORE the step-status-ledger + mark-step lines.)

```bash
git commit -m "fix(test): G3 Batch 27 — 5f_security_audit FAIL on Tier findings (CRITICAL)

Codex test audit G3: Tier 0/1/2 grep/curl validators set findings vars
but step marker fired with SECURITY_STATUS=PASS default. Critical/high
findings ignored.

Fix: aggregate SECURITY_CRITICAL_COUNT + SECURITY_HIGH_COUNT + Tier fail
flag. Set SECURITY_STATUS=FAIL when any > 0. Emit
test.security_audit_failed event with counts.

step-status-ledger now records real status. Downstream verdict sees FAIL.

Tests: tests/test_batch27_security_audit_fail.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Release v4.31.0

Bump VERSION 4.30.0 → 4.31.0. CHANGELOG. Tag v4.31.0. Push. Re-sync ~/.vgflow. Codex mirror verify; regen if drift.

End of Batch 27. Estimated 3 hours.
