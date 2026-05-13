# Batch 11 — Amend invalidation + CrossAI accept + Review ledger (F4+F5+F11+F12) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 4 audit findings (2 HIGH, 2 MEDIUM) from `docs/plans/2026-05-13-flow-chain-audit.md`.

- **F4 (HIGH)**: CrossAI blueprint findings stranded — accept never reads `${PHASE_DIR}/crossai/`. Wire accept-time read + BLOCK on HIGH unacknowledged.
- **F5 (HIGH)**: `/vg:amend` cascade informational-only. LIFECYCLE-SPECS.json not invalidated after D-XX change. Write `.amend-invalidation.json` artifact.
- **F11 (MEDIUM)**: Review lane has no step-status ledger (only test has it post-Batch 9). Mirror C5 pattern to review lane.
- **F12 (MEDIUM)**: `/vg:accept` doesn't compare amend timestamp vs SANDBOX-TEST.md `tested` field. Add cross-check.

**Tech Stack:** Python + bash.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "amend or crossai or review_ledger or f4 or f5 or f11 or f12"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: F5+F12 — Amend writes .amend-invalidation.json + accept checks

**Files:**
- Modify: `commands/vg/amend.md` (Phase 4 close — write artifact)
- Modify: `commands/vg/_shared/accept/preflight.md` (read artifact, BLOCK if amend post-dates test)
- Mirrors
- Test: `tests/test_f5_f12_amend_invalidation.py`

**Step 1: Failing test**

```python
"""tests/test_f5_f12_amend_invalidation.py — F5+F12 amend cascade enforcement."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
AMEND = REPO / "commands" / "vg" / "amend.md"
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "accept" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_amend_writes_invalidation_artifact():
    body = _read(AMEND)
    assert ".amend-invalidation.json" in body, (
        "F5: /vg:amend Phase 4 (close) must write ${PHASE_DIR}/.amend-invalidation.json "
        "with {amended_at, changed_goals, changed_decisions} so downstream phases "
        "can detect 'test results pre-date amend'"
    )
    # Must include changed_decisions / changed_goals payload
    assert "changed_decisions" in body or "changed_goals" in body or "decision_refs" in body, (
        "F5: invalidation artifact must enumerate WHICH decisions/goals changed"
    )


def test_amend_invalidation_includes_timestamp():
    body = _read(AMEND)
    assert "amended_at" in body, (
        "F5: invalidation artifact must include amended_at ISO timestamp for "
        "accept-time comparison vs SANDBOX-TEST.md tested field"
    )


def test_accept_preflight_checks_amend_invalidation():
    body = _read(PREFLIGHT)
    assert ".amend-invalidation.json" in body, (
        "F12: accept/preflight.md must read .amend-invalidation.json and "
        "compare amended_at vs SANDBOX-TEST.md tested timestamp"
    )
    assert "amended_at" in body, (
        "F12: accept preflight must check amended_at against tested timestamp"
    )


def test_accept_preflight_blocks_when_amend_postdates_test():
    body = _read(PREFLIGHT)
    # The check must lead to BLOCK or exit non-zero
    assert "BLOCK" in body or "exit 1" in body or "amend_invalidation_block" in body, (
        "F12: when amended_at > SANDBOX-TEST.md.tested, accept preflight must "
        "BLOCK with message 'Test results pre-date amend; re-run /vg:test'"
    )
```

**Step 2: Run** → 3-4 fail.

**Step 3: Implement**

In `commands/vg/amend.md` Phase 4 (close), add new block:

```bash
# F5 Batch 11: write amend-invalidation artifact so downstream phases can
# detect stale test results post-amendment.
${PYTHON_BIN:-python3} - <<PYEOF
import json
from pathlib import Path
from datetime import datetime, timezone

invalidation = {
    "amended_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "changed_goals": ${CHANGED_GOALS_JSON:-'[]'},
    "changed_decisions": ${CHANGED_DECISIONS_JSON:-'[]'},
    "amend_session": "${VG_RUN_ID:-amend-$(date +%s)}",
    "phase": "${PHASE_NUMBER}",
}
out = Path("${PHASE_DIR}/.amend-invalidation.json")
out.write_text(json.dumps(invalidation, indent=2), encoding="utf-8")
print(f"✓ Wrote amend invalidation marker: {out}")
print(f"  Test/accept phases will BLOCK until /vg:test is re-run for phase {invalidation['phase']}")
PYEOF
```

In `commands/vg/_shared/accept/preflight.md`, add check before existing SANDBOX-TEST.md read:

```bash
# F12 Batch 11: amend-invalidation cross-check — test results MUST be fresher than amend
AMEND_INVAL="${PHASE_DIR}/.amend-invalidation.json"
SANDBOX_TEST="${PHASE_DIR}/SANDBOX-TEST.md"
if [ -f "$AMEND_INVAL" ] && [ -f "$SANDBOX_TEST" ]; then
  ${PYTHON_BIN:-python3} - <<PYEOF
import json, re, sys
from pathlib import Path
from datetime import datetime

inv = json.loads(Path("${AMEND_INVAL}").read_text(encoding="utf-8"))
amended_at = inv.get("amended_at", "")

# Parse SANDBOX-TEST.md frontmatter for 'tested' field
sb = Path("${SANDBOX_TEST}").read_text(encoding="utf-8")
m = re.search(r'^tested:\s*"?([^"\n]+)"?$', sb, flags=re.M)
tested_at = m.group(1).strip() if m else ""

if amended_at and tested_at and amended_at > tested_at:
    print(f"⛔ F12 BLOCK: amend ({amended_at}) post-dates last test ({tested_at})")
    print(f"   Test results stale. Re-run: /vg:test ${PHASE_NUMBER}")
    print(f"   Changed decisions: {inv.get('changed_decisions', [])}")
    print(f"   Changed goals: {inv.get('changed_goals', [])}")
    sys.exit(1)
print(f"✓ F12: test ({tested_at}) is fresher than amend ({amended_at or 'none'})")
PYEOF
  AMEND_FRESHNESS_RC=$?
  if [ "$AMEND_FRESHNESS_RC" != "0" ]; then
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
      "accept.amend_invalidation_block" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"amend_invalidation\":\"$(cat $AMEND_INVAL)\"}" \
      >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/amend.md \
        commands/vg/_shared/accept/preflight.md \
        .claude/commands/vg/amend.md \
        .claude/commands/vg/_shared/accept/preflight.md \
        tests/test_f5_f12_amend_invalidation.py
git commit -m "feat(amend+accept): F5+F12 — amend cascade enforcement (Batch 11)

Flow-chain audit Findings 5 (HIGH) + 12 (MEDIUM): /vg:amend cascade was
informational-only. LIFECYCLE-SPECS.json not invalidated after D-XX change.
SANDBOX-TEST.md still showed PASSED from pre-amend test run. /vg:accept
shipped phase with stale behavioral contract.

Fix:
- amend.md Phase 4: writes \${PHASE_DIR}/.amend-invalidation.json with
  {amended_at, changed_goals, changed_decisions, amend_session, phase}.
- accept/preflight.md: parses SANDBOX-TEST.md frontmatter 'tested' field,
  compares vs amended_at. If amend post-dates test → BLOCK with
  'Re-run /vg:test \${PHASE_NUMBER}'. Emits accept.amend_invalidation_block
  event.

Closes amend → test contract gap. Without this, mid-phase decision changes
silently shipped stale test results.

Tests: tests/test_f5_f12_amend_invalidation.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F4 — Accept reads CrossAI findings

**Files:**
- Modify: `commands/vg/_shared/accept/audit.md` (or gates.md — pick the one with phase F gate logic)
- Mirror
- Test: `tests/test_f4_accept_reads_crossai.py`

**Step 1: Failing test**

```python
"""tests/test_f4_accept_reads_crossai.py — F4 accept consumes CrossAI findings."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "commands" / "vg" / "_shared" / "accept" / "audit.md"
GATES = REPO / "commands" / "vg" / "_shared" / "accept" / "gates.md"


def test_accept_reads_crossai_findings():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Must reference CrossAI artifact paths
    assert ("crossai/review-check" in combined or 
            "review-check.report.json" in combined or 
            "crossai_findings" in combined), (
        "F4: accept/audit.md or gates.md must read CrossAI findings from "
        "${PHASE_DIR}/crossai/review-check.{xml,report.json} OR ${PHASE_DIR}/crossai/"
    )


def test_accept_blocks_on_unacknowledged_high_findings():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Must have BLOCK semantics on HIGH+ unacknowledged
    assert ("HIGH" in combined and ("BLOCK" in combined or "exit 1" in combined)) or "crossai_findings_block" in combined, (
        "F4: must BLOCK accept when CrossAI HIGH findings count > 0 unless "
        "--allow-crossai-findings override with debt logged"
    )


def test_accept_supports_crossai_override_flag():
    audit_body = AUDIT.read_text(encoding="utf-8")
    gates_body = GATES.read_text(encoding="utf-8")
    combined = audit_body + gates_body
    # Override flag for cases where findings are reviewed + accepted
    assert "--allow-crossai-findings" in combined or "skip-crossai" in combined or "ack-crossai" in combined, (
        "F4: accept must support an override flag (--allow-crossai-findings or "
        "similar) so reviewer-acknowledged findings can pass + log to debt"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/accept/audit.md`, add new section/gate:

```bash
# F4 Batch 11: CrossAI findings cross-check — gap-hunt output must not ship
# unacknowledged through accept. HIGH/CRITICAL severity findings BLOCK unless
# --allow-crossai-findings override (logged as debt).
CROSSAI_DIR="${PHASE_DIR}/crossai"
CROSSAI_REPORT="${CROSSAI_DIR}/review-check.report.json"
if [ -d "$CROSSAI_DIR" ] && [ -f "$CROSSAI_REPORT" ]; then
  ${PYTHON_BIN:-python3} - <<PYEOF
import json, sys
from pathlib import Path
data = json.loads(Path("${CROSSAI_REPORT}").read_text(encoding="utf-8"))
findings = data.get("findings", [])
high_findings = [f for f in findings if (f.get("severity","") or "").upper() in ("HIGH", "CRITICAL")]
print(f"CrossAI findings: total={len(findings)}, HIGH+={len(high_findings)}")
if not high_findings:
    sys.exit(0)
allow = "--allow-crossai-findings" in "${ARGUMENTS:-}"
if allow:
    print(f"⚠ {len(high_findings)} HIGH CrossAI findings allowed via --allow-crossai-findings (debt logged)")
    # Log to OVERRIDE-DEBT.md
    sys.exit(0)
print(f"⛔ F4 BLOCK: {len(high_findings)} unacknowledged HIGH/CRITICAL CrossAI findings")
for f in high_findings[:5]:
    print(f"  - [{f.get('severity')}] {f.get('title','(no title)')}")
print(f"   Override: re-run /vg:accept with --allow-crossai-findings (logs debt)")
sys.exit(1)
PYEOF
  CROSSAI_RC=$?
  if [ "$CROSSAI_RC" != "0" ]; then
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
      "accept.crossai_findings_block" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"report\":\"${CROSSAI_REPORT}\"}" \
      >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

```bash
git commit -m "feat(accept): F4 — accept gates read CrossAI findings (Batch 11)

Flow-chain audit Finding 4 (HIGH): CrossAI gap-hunt findings written to
\${PHASE_DIR}/crossai/review-check.report.json by review lane were silently
discarded by accept. A 50-phase project with 3 HIGH CrossAI findings would
ship all 3 unacknowledged.

Fix: accept/audit.md new F4 gate. Reads crossai/review-check.report.json,
filters HIGH/CRITICAL severity findings. BLOCK if any unacknowledged
findings present. Override via --allow-crossai-findings (logs to
OVERRIDE-DEBT.md). Emits accept.crossai_findings_block event on BLOCK.

Tests: tests/test_f4_accept_reads_crossai.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: F11 — Review lane step-status ledger

**Files:**
- Modify: review sub-step files (`commands/vg/_shared/review/*.md`) to emit ledger entries
- Modify: review verdict computation (`commands/vg/_shared/test/fix-loop-and-verdict.md` close path) to consume ledger
- Mirrors
- Test: `tests/test_f11_review_step_status_ledger.py`

**Step 1: Failing test**

```python
"""tests/test_f11_review_step_status_ledger.py — F11 review lane ledger."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

REVIEW_STEP_FILES = [
    "commands/vg/_shared/review/preflight.md",
    "commands/vg/_shared/review/api-and-discovery.md",
    "commands/vg/_shared/review/code-scan.md",
    "commands/vg/_shared/review/lens-and-findings.md",
    "commands/vg/_shared/review/url-and-error.md",
    "commands/vg/_shared/review/matrix-intent.md",
]


def test_at_least_one_review_step_emits_ledger():
    """Review lane must have at least 2 step ledger emits — symmetry with test C5."""
    emits = 0
    for rel in REVIEW_STEP_FILES:
        body = (REPO / rel).read_text(encoding="utf-8")
        if "step-status-ledger.py" in body or "review-step-status" in body:
            emits += 1
    assert emits >= 2, (
        f"F11: at least 2 review sub-steps must emit step-status ledger entries "
        f"(symmetric with C5 test lane). Got {emits}."
    )


def test_review_close_reads_ledger():
    body = (REPO / "commands/vg/_shared/review/close.md").read_text(encoding="utf-8")
    assert ".review-step-status.json" in body or "step-status-ledger" in body or "REVIEW_STEP_LEDGER" in body, (
        "F11: review/close.md must read review step-status ledger for "
        "verdict computation (symmetric with test/close.md from C5 Batch 9)"
    )
```

**Step 2-6:** RED → implement.

Add ledger emit at end of preflight + api-and-discovery + matrix-intent. Use same `step-status-ledger.py` script but with `--ledger-name review-step-status.json` flag. (Need to extend script first.)

Actually simpler: use existing script with phase-dir + step name; ledger file is `.test-step-status.json` regardless. But that conflates lanes. Let me extend script to accept `--ledger PATH` override.

Wait — the existing script writes to `.test-step-status.json` (hardcoded). Need to add flag.

Update `scripts/step-status-ledger.py`:

```python
ap.add_argument("--ledger", default=".test-step-status.json", help="Output ledger filename (default: .test-step-status.json)")
# ...
ledger = args.phase_dir / args.ledger
```

Then review steps call:
```bash
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/step-status-ledger.py" \
  --phase-dir "${PHASE_DIR}" \
  --ledger ".review-step-status.json" \
  --step "phase2a_api_contract_probe" \
  --status "${PHASE2A_STATUS:-PASS}" \
  --reason "${PHASE2A_REASON:-}" || true
```

In review/close.md, add ledger read block similar to test/close.md C5 pattern.

```bash
git commit -m "feat(review): F11 — review lane step-status ledger (Batch 11)

Flow-chain audit Finding 11 (MEDIUM): C5 Batch 9 wired step-status ledger
for test lane. Review lane had no equivalent. Review sub-step failures
(api-and-discovery phase2a, matrix-intent compute, etc) did not propagate
to review verdict computation.

Fix:
- step-status-ledger.py: new --ledger PATH flag (default .test-step-status.json)
  so review can write to .review-step-status.json without conflating lanes.
- Review preflight, api-and-discovery, matrix-intent emit step-ledger
  entries on completion.
- review/close.md verdict computation reads .review-step-status.json
  before final verdict extraction. Symmetric with test/close.md C5 pattern.

Tests: tests/test_f11_review_step_status_ledger.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Regression sweep + release v4.14.0

Bump VERSION 4.13.0 → 4.14.0. CHANGELOG entry 4 findings. Tag v4.14.0. Push. Re-sync ~/.vgflow.

End of Batch 11 plan. Estimated 4 hours.
