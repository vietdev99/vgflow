# Batch 6 — Review observability bug fixes (H2+H6+H8) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 3 review/test observability gaps where bug fixes ship as dead code or stderr-only warnings.

**Source:** `docs/plans/2026-05-13-pipeline-flow-audit.md` gaps H2, H6, H8.

**Tech Stack:** Bash + Python. No deps.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/commands/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "fe_be or manifest or codex_fix or h2 or h6 or h8"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: H2 — Fix FE-BE drift advisory dead exit code

**Files:**
- Modify: `commands/vg/_shared/review/preflight.md` (lines 547-559)
- Mirror: `.claude/commands/vg/_shared/review/preflight.md`
- Test: `tests/test_h2_fe_be_advisory_exit_code.py`

**Step 1: Failing test**

```python
"""tests/test_h2_fe_be_advisory_exit_code.py — H2 dead advisory fix."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "review" / "preflight.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_fe_be_validator_call_does_not_mask_exit():
    body = _read(CANON)
    fe_be_idx = body.find("verify-fe-be-call-graph.py")
    assert fe_be_idx > 0
    # The validator invocation block must NOT chain `|| true` BEFORE FE_BE_RC capture
    block = body[fe_be_idx:fe_be_idx + 1500]
    # Find the actual python invocation
    py_call = block.find('"$FE_BE_VAL"')
    assert py_call > 0
    py_block = block[py_call:py_call + 500]
    # The redirect line that runs the validator should NOT contain `|| true`
    # The next line should capture $? immediately
    lines_after_py = py_block.split("\n")
    # First non-empty line ending with redirect or the validator args end
    redirect_line_idx = None
    for i, line in enumerate(lines_after_py):
        if "2>&1" in line:
            redirect_line_idx = i
            break
    assert redirect_line_idx is not None, "Could not locate redirect line"
    redirect_line = lines_after_py[redirect_line_idx]
    assert "|| true" not in redirect_line, (
        f"H2: validator redirect line MUST NOT contain `|| true` — that masks "
        f"exit code, making FE_BE_RC always 0 and the advisory warning dead.\n"
        f"Got: {redirect_line!r}"
    )


def test_fe_be_advisory_warning_branch_reachable():
    body = _read(CANON)
    # The warning branch + emit-event must be present AFTER the FE_BE_RC check
    assert 'if [ "$FE_BE_RC" -ne 0 ]' in body or 'if [ ${FE_BE_RC} -ne 0 ]' in body
    assert "verify-fe-be-call-graph.py advisory" in body
    assert "review.fe_be_drift_warn" in body


def test_mirror_byte_identical():
    if MIRROR.is_file():
        assert _read(CANON) == _read(MIRROR)
```

**Step 2: Run** → 1-2 fail (line 547 currently has `... || true` masking exit).

**Step 3: Implement**

In `commands/vg/_shared/review/preflight.md` around line 542-548, change:

OLD:
```bash
  "${PYTHON_BIN:-python3}" "$FE_BE_VAL" \
    --fe-root "$_FE_ROOT" \
    --be-root "$_BE_ROOT" \
    --phase "${PHASE_NUMBER:-${PHASE_ARG:-unknown}}" \
    --evidence-out "${PHASE_DIR}/.tmp/fe-be-call-graph-advisory.json" \
    > "${PHASE_DIR}/.tmp/fe-be-call-graph-advisory.diag" 2>&1 || true
  FE_BE_RC=$?
```

NEW (drop `|| true` so $? captures real exit; protect outer script via subshell + set +e):
```bash
  set +e
  "${PYTHON_BIN:-python3}" "$FE_BE_VAL" \
    --fe-root "$_FE_ROOT" \
    --be-root "$_BE_ROOT" \
    --phase "${PHASE_NUMBER:-${PHASE_ARG:-unknown}}" \
    --evidence-out "${PHASE_DIR}/.tmp/fe-be-call-graph-advisory.json" \
    > "${PHASE_DIR}/.tmp/fe-be-call-graph-advisory.diag" 2>&1
  FE_BE_RC=$?
  set -e
```

**Step 4: Run tests** → pass.

**Step 5: Mirror**

```bash
cp commands/vg/_shared/review/preflight.md .claude/commands/vg/_shared/review/preflight.md
```

**Step 6: Commit**

```bash
git add commands/vg/_shared/review/preflight.md \
        .claude/commands/vg/_shared/review/preflight.md \
        tests/test_h2_fe_be_advisory_exit_code.py
git commit -m "fix(review): H2 — un-mask FE-BE drift advisory exit code (Batch 6)

Audit Gap H2 (HIGH): verify-fe-be-call-graph.py invocation in review/
preflight.md:547 chained '|| true' BEFORE FE_BE_RC=\$? capture, making
\$? always 0. The 'if [ \"\$FE_BE_RC\" -ne 0 ]' warning branch (echo +
review.fe_be_drift_warn event) was dead code. v4.1 shipped this as
advisory but it never fired — false confidence in pipeline.

Fix: replace '|| true' with explicit 'set +e ... set -e' wrap so FE_BE_RC
captures real exit code. Outer script protected via set +e/-e bracket.

Tests: tests/test_h2_fe_be_advisory_exit_code.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: H6 — Manifest emit visible failures

**Files:**
- Modify: `commands/vg/_shared/test/fix-loop-and-verdict.md` (lines 969, 976)
- Mirror: `.claude/commands/vg/_shared/test/fix-loop-and-verdict.md`
- Test: `tests/test_h6_manifest_emit_visible_fail.py`

**Step 1: Failing test**

```python
"""tests/test_h6_manifest_emit_visible_fail.py — H6 silent manifest emit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "test" / "fix-loop-and-verdict.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_manifest_emit_drops_quiet_for_runtime_map():
    body = _read(CANON)
    rt_idx = body.find('--path "${PHASE_DIR}/RUNTIME-MAP.json"')
    assert rt_idx > 0
    # Look in next 500 chars for the emit block
    block = body[rt_idx:rt_idx + 500]
    # New behavior: must NOT use --quiet || true silent pattern
    assert "--quiet || true" not in block, (
        "H6: RUNTIME-MAP.json manifest emit must NOT swallow output via "
        "'--quiet || true'. On failure, partial emit fails silently → "
        "run-complete blocks with 'manifest missing for X' but user has "
        "no idea which emit failed."
    )


def test_manifest_emit_drops_quiet_for_goal_coverage():
    body = _read(CANON)
    gc_idx = body.find('--path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"')
    assert gc_idx > 0
    block = body[gc_idx:gc_idx + 500]
    assert "--quiet || true" not in block, (
        "H6: GOAL-COVERAGE-MATRIX.md manifest emit must NOT use "
        "'--quiet || true' silent pattern."
    )


def test_manifest_emit_fail_surfaces_warning():
    body = _read(CANON)
    # Failure path must emit a visible warning + event
    assert "review.manifest_emit_failed" in body or "manifest_emit_fail" in body or "manifest emit failed" in body, (
        "H6: failure path must emit review.manifest_emit_failed event + "
        "visible echo so user sees which path failed."
    )
```

**Step 2: Run** → 3 fail.

**Step 3: Implement**

In `commands/vg/_shared/test/fix-loop-and-verdict.md` around lines 963-977. Replace:

OLD:
```bash
if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/RUNTIME-MAP.json" \
      --producer "vg:review phase2b3_runtime_map" \
      --source-inputs "${PHASE_DIR}/nav-discovery.json,${PHASE_DIR}/TEST-GOALS.md" \
      --quiet || true
fi
if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" \
      --producer "vg:review step7_matrix_verdict" \
      --source-inputs "..." \
      --quiet || true
fi
```

NEW:
```bash
if [ -f "${PHASE_DIR}/RUNTIME-MAP.json" ]; then
    set +e
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/RUNTIME-MAP.json" \
      --producer "vg:review phase2b3_runtime_map" \
      --source-inputs "${PHASE_DIR}/nav-discovery.json,${PHASE_DIR}/TEST-GOALS.md"
    EMIT_RC=$?
    set -e
    if [ "$EMIT_RC" -ne 0 ]; then
      echo "⚠ manifest emit failed for RUNTIME-MAP.json (rc=${EMIT_RC})" >&2
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "review.manifest_emit_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"path\":\"RUNTIME-MAP.json\",\"rc\":${EMIT_RC}}" >/dev/null 2>&1 || true
    fi
fi
if [ -f "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" ]; then
    set +e
    "${PYTHON_BIN:-python3}" "$EMIT_MANIFEST" \
      --path "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md" \
      --producer "vg:review step7_matrix_verdict" \
      --source-inputs "${PHASE_DIR}/TEST-GOALS.md,${PHASE_DIR}/RUNTIME-MAP.json,${PHASE_DIR}/.surface-probe-results.json,${PHASE_DIR}/DEEP-TEST-SPECS.md,${PHASE_DIR}/LIFECYCLE-SPECS.json,${PHASE_DIR}/TEST-FIXTURE-DAG.json,${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
    EMIT_RC=$?
    set -e
    if [ "$EMIT_RC" -ne 0 ]; then
      echo "⚠ manifest emit failed for GOAL-COVERAGE-MATRIX.md (rc=${EMIT_RC})" >&2
      "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "review.manifest_emit_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"path\":\"GOAL-COVERAGE-MATRIX.md\",\"rc\":${EMIT_RC}}" >/dev/null 2>&1 || true
    fi
fi
```

**Step 4-6:** Run pass + mirror + commit:

```bash
git add commands/vg/_shared/test/fix-loop-and-verdict.md \
        .claude/commands/vg/_shared/test/fix-loop-and-verdict.md \
        tests/test_h6_manifest_emit_visible_fail.py
git commit -m "fix(review): H6 — manifest emit failures visible (Batch 6)

Audit Gap H6 (MEDIUM): test/fix-loop-and-verdict.md lines 969, 976 used
'--quiet || true' on emit-evidence-manifest calls for RUNTIME-MAP.json +
GOAL-COVERAGE-MATRIX.md. Partial emit failure silent — run-complete then
blocks with 'manifest missing for X' but user has no debug trail.

Fix: drop --quiet, capture EMIT_RC per call, surface warning + emit
review.manifest_emit_failed event with phase + path + rc on non-zero.
Failure visible without affecting pipeline (advisory).

Tests: tests/test_h6_manifest_emit_visible_fail.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: H8 — codex-spawn fix-agent failure event

**Files:**
- Modify: `commands/vg/_shared/test/fix-loop-and-verdict.md` (lines 184-194)
- Mirror: `.claude/commands/vg/_shared/test/fix-loop-and-verdict.md`
- Test: `tests/test_h8_codex_fix_failure_event.py`

**Step 1: Failing test**

```python
"""tests/test_h8_codex_fix_failure_event.py — H8 stderr-only codex failure."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "test" / "fix-loop-and-verdict.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_codex_spawn_failure_emits_event():
    body = _read(CANON)
    cx_idx = body.find("codex-spawn.sh")
    assert cx_idx > 0
    block = body[cx_idx:cx_idx + 2000]
    # Failure path must emit event
    assert "test.codex_fix_failed" in body or "codex_fix_failed" in body, (
        "H8: codex-spawn fix-agent failure must emit test.codex_fix_failed "
        "event (not just stderr echo)"
    )


def test_codex_failure_writes_to_phase_dir():
    body = _read(CANON)
    # Failure must persist to phase dir (not just stderr noise)
    assert "CODEX-FIX-FAILURES" in body or "REVIEW-FEEDBACK.md" in body, (
        "H8: codex fix-agent failure must persist to phase dir artifact "
        "(CODEX-FIX-FAILURES.json or REVIEW-FEEDBACK.md entry)"
    )
```

**Step 2: Run** → 1-2 fail.

**Step 3: Implement**

In `commands/vg/_shared/test/fix-loop-and-verdict.md` find the codex-spawn invocation block around line 184-194. Replace the failure warning:

OLD:
```bash
bash commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor ... \
  || { echo "⚠ codex-spawn fix-agent failed for ${ERR_ID:-$idx} — escalate to REVIEW-FEEDBACK.md" >&2; }
```

NEW:
```bash
set +e
bash commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor ...
CODEX_FIX_RC=$?
set -e
if [ "$CODEX_FIX_RC" -ne 0 ]; then
  echo "⚠ codex-spawn fix-agent failed for ${ERR_ID:-$idx} (rc=${CODEX_FIX_RC}) — see CODEX-FIX-FAILURES.json + escalating to REVIEW-FEEDBACK.md" >&2
  # Persist failure record to phase dir
  ${PYTHON_BIN:-python3} - <<PYEOF
import json
from pathlib import Path
from datetime import datetime, timezone
p = Path("${PHASE_DIR}/CODEX-FIX-FAILURES.json")
data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"failures": []}
data.setdefault("failures", []).append({
    "err_id": "${ERR_ID:-unknown}",
    "rc": ${CODEX_FIX_RC},
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "attempt": ${TOTAL_ITER:-0},
})
p.write_text(json.dumps(data, indent=2), encoding="utf-8")
PYEOF
  # Emit event
  "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event "test.codex_fix_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"err_id\":\"${ERR_ID:-unknown}\",\"rc\":${CODEX_FIX_RC},\"attempt\":${TOTAL_ITER:-0}}" >/dev/null 2>&1 || true
fi
```

(Note: heredoc syntax with bash + Python embed — preserve indent inside PYEOF block per existing style in the file.)

**Step 4-6:** pass + mirror + commit:

```bash
git add commands/vg/_shared/test/fix-loop-and-verdict.md \
        .claude/commands/vg/_shared/test/fix-loop-and-verdict.md \
        tests/test_h8_codex_fix_failure_event.py
git commit -m "fix(test): H8 — codex-spawn fix-agent failure surfaces (Batch 6)

Audit Gap H8 (MEDIUM): when VG_RUNTIME=codex, fix-loop iteration shells
out to codex-spawn.sh --tier executor. On failure, only stderr echo
'⚠ codex-spawn fix-agent failed ...'. No event, no marker, no manifest
entry. In CI / --auto-chain runs, this gets lost — entire fix-loop
iteration silently fails.

Fix: capture exit code via set +e/-e bracket. On non-zero:
- Persist failure record to ${PHASE_DIR}/CODEX-FIX-FAILURES.json (err_id,
  rc, ts, attempt) — appends if file exists, creates if not.
- Emit test.codex_fix_failed event with phase + err_id + rc + attempt.
- Stderr warning retained for interactive visibility.

Tests: tests/test_h8_codex_fix_failure_event.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Regression sweep + release v4.6.0

**Step 1:** Sweep:

```bash
python -m pytest tests/ -q --tb=no
```

Baseline: 32 pre-existing fail / 2148 pass. Must not exceed baseline.

**Step 2:** Bump VERSION `4.5.0` → `4.6.0`. Update `package.json`.

**Step 3:** CHANGELOG entry:

```markdown
## v4.6.0 — Review observability bug fixes (Batch 6 / H2+H6+H8) (2026-05-XX)

Audit Gaps H2 (HIGH), H6 (MEDIUM), H8 (MEDIUM) — observability bugs in
review + test fix-loop where failure paths silently swallowed errors.

### H2 — FE-BE drift advisory un-masked
review/preflight.md:547 chained '|| true' BEFORE FE_BE_RC capture →
$? always 0 → 'if FE_BE_RC ne 0' warning branch was dead code. Advisory
shipped in v4.1 but never fired.

Fix: explicit set +e/-e bracket, FE_BE_RC captures real exit.

### H6 — manifest emit failure visible
test/fix-loop-and-verdict.md:969,976 used '--quiet || true' on manifest
emit calls → partial failure silent → run-complete blocked downstream
with no debug trail.

Fix: drop --quiet, capture EMIT_RC per call, emit
review.manifest_emit_failed event + stderr warning on non-zero.

### H8 — codex-spawn fix-agent failure persists
test/fix-loop-and-verdict.md:184 codex-spawn failure only echoed to
stderr. CI runs lost the signal.

Fix: persist failure to ${PHASE_DIR}/CODEX-FIX-FAILURES.json (err_id,
rc, ts, attempt) + emit test.codex_fix_failed event.

Audit reference: docs/plans/2026-05-13-pipeline-flow-audit.md.
```

**Step 4:** Commit + tag + push:

```bash
git add VERSION package.json CHANGELOG.md
git commit -m "release: v4.6.0 — Batch 6 review observability (H2+H6+H8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git tag v4.6.0 -m "v4.6.0 — Batch 6 review observability fixes"
git push origin main v4.6.0
```

**Step 5:** Re-sync global install:

```bash
cp commands/vg/_shared/review/preflight.md ~/.vgflow/commands/vg/_shared/review/preflight.md
cp commands/vg/_shared/test/fix-loop-and-verdict.md ~/.vgflow/commands/vg/_shared/test/fix-loop-and-verdict.md
```

---

End of Batch 6 plan. Estimated 2 hours engineering wall-clock.
