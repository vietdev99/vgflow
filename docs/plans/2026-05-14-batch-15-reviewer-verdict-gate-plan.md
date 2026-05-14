# Batch 15 — Reviewer verdict gates (F3 + F4 CRITICAL) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 2 CRITICAL audit findings — B1 spec compliance + B4 final review are scaffold-only. Documented Agent spawns are commented out. Markers fire unconditionally. Build passes "reviewed" without running.

**Source:** `docs/plans/2026-05-14-codex-blueprint-build-audit.md` F3+F4.

**Architecture:** Make markers conditional on verdict-file existence + content check. Hard-block if file missing or contains FAIL (unless escape flag).

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "spec_review or final_review or f3 or f4 or build_close or post_execution"`
- Single Co-Authored-By trailer per commit

---

## Task 1: F3 — B1 spec compliance verdict gate

**Files:**
- Modify: `commands/vg/_shared/build/post-execution-overview.md` (STEP 5.1 area, lines 1074-1120)
- Mirror
- Test: `tests/test_f3_b1_spec_review_verdict_gate.py`

**Step 1: Failing test**

```python
"""tests/test_f3_b1_spec_review_verdict_gate.py — F3 spec review verdict gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
PE = REPO / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_marker_touch_conditional_on_verdict_file():
    body = _read(PE)
    # Find STEP 5.1 marker touch block
    marker_idx = body.find("5_1_spec_compliance_review.done")
    assert marker_idx > 0
    # Look backwards 600 chars for verdict-file gate (NOT in the SKIP_SPEC_REVIEW branch)
    # The non-skip branch must check verdict file before touching marker
    body_segment = body[max(0, marker_idx - 1500):marker_idx]
    # Must reference verdict file path AND a guard (if/test) before marker
    assert ".spec-review" in body_segment or "spec-review" in body_segment, (
        "F3: post-execution-overview.md STEP 5.1 must reference per-task spec-review "
        "verdict directory (e.g. ${PHASE_DIR}/.spec-review/{task_id}.md) "
        "so verdict file existence can be gated before marker"
    )


def test_verdict_file_existence_check_present():
    body = _read(PE)
    # Locate per-task loop area
    loop_start = body.find('for task_id in "${WAVE_TASKS[@]}"')
    assert loop_start > 0
    loop_block = body[loop_start:loop_start + 2500]
    # Must guard marker write on verdict file presence
    assert ("[ -f" in loop_block or "test -f" in loop_block or "Path(" in loop_block), (
        "F3: per-task spec-review loop must check verdict file exists before "
        "proceeding (otherwise marker fires without evidence)"
    )


def test_fail_verdict_blocks():
    body = _read(PE)
    # Some FAIL handling must exist
    assert "FAIL" in body
    # And a block path
    assert ("exit 1" in body or "BLOCK" in body or "must be FAIL" in body), (
        "F3: FAIL verdict path must block (exit 1) unless --skip-spec-review override"
    )
```

**Step 2: Run** → 2-3 fail.

**Step 3: Implement**

In `commands/vg/_shared/build/post-execution-overview.md` STEP 5.1 area, replace the comment-only spawn block with verdict-file gate. Pattern:

```bash
else
  # WAVE_TASKS holds task IDs that produced commits in the current wave.
  SPEC_REVIEW_DIR="${PHASE_DIR}/.spec-review"
  mkdir -p "$SPEC_REVIEW_DIR"
  SPEC_REVIEW_FAILS=0
  for task_id in "${WAVE_TASKS[@]}"; do
    COMMIT_SHA=$(git log --grep="task-${task_id}\\|${task_id}:" -n1 --format=%H)
    if [ -z "$COMMIT_SHA" ]; then
      echo "⚠ STEP 5.1: no commit found for ${task_id} — skipping spec-review"
      continue
    fi
    bash scripts/vg-narrate-spawn.sh vg-build-spec-reviewer spawning "spec-review task-${task_id}"
    # AI orchestrator MUST call:
    #   Agent(subagent_type="vg-build-spec-reviewer",
    #         prompt=<rendered with task_id, commit_sha, phase_dir>)
    # The agent MUST write verdict to $SPEC_REVIEW_DIR/${task_id}.md with format:
    #   ---
    #   task_id: T-XX
    #   verdict: PASS | FAIL
    #   gaps: <markdown list>
    #   ---
    bash scripts/vg-narrate-spawn.sh vg-build-spec-reviewer returned "task-${task_id}: <verdict>"

    # F3 Batch 15: verdict-file existence + content gate
    VERDICT_FILE="$SPEC_REVIEW_DIR/${task_id}.md"
    if [ ! -f "$VERDICT_FILE" ]; then
      echo "⛔ STEP 5.1 F3: vg-build-spec-reviewer did not write $VERDICT_FILE for task ${task_id}" >&2
      echo "   The subagent MUST persist verdict to disk so marker is evidence-backed." >&2
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.spec_review_missing_verdict" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"task\":\"${task_id}\"}" >/dev/null 2>&1 || true
      SPEC_REVIEW_FAILS=$((SPEC_REVIEW_FAILS + 1))
      continue
    fi
    if grep -qE "^verdict:\s*FAIL" "$VERDICT_FILE"; then
      echo "⛔ STEP 5.1 F3: spec-review FAIL for task ${task_id}" >&2
      cat "$VERDICT_FILE" | head -20 >&2
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.spec_review_failed" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"task\":\"${task_id}\"}" >/dev/null 2>&1 || true
      SPEC_REVIEW_FAILS=$((SPEC_REVIEW_FAILS + 1))
    fi
  done

  if [ "$SPEC_REVIEW_FAILS" -gt 0 ]; then
    echo "⛔ STEP 5.1 F3: ${SPEC_REVIEW_FAILS} spec-review failure(s). Re-run /vg:build --skip-spec-review --override-reason=<text> to bypass (debt logged)." >&2
    exit 1
  fi
fi
```

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/build/post-execution-overview.md \
        .claude/commands/vg/_shared/build/post-execution-overview.md \
        tests/test_f3_b1_spec_review_verdict_gate.py
git commit -m "fix(build): F3 — B1 spec compliance verdict file gate (Batch 15)

Codex audit Finding F3 (CRITICAL): vg-build-spec-reviewer Agent spawn
was comment-only in post-execution-overview.md STEP 5.1. After narrate
calls, marker fired unconditionally. Build claimed 'spec review passed'
with zero evidence.

Fix: per-task loop now requires \${PHASE_DIR}/.spec-review/{task_id}.md
verdict file on disk. Missing file or 'verdict: FAIL' line → BLOCK with
emit-event(build.spec_review_failed). Escape: --skip-spec-review with
override-reason (existing path, unchanged).

Tests: tests/test_f3_b1_spec_review_verdict_gate.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F4 — B4 cumulative final review verdict gate

**Files:**
- Modify: `commands/vg/_shared/build/close.md` (STEP 7.1.5 area, lines 150-177)
- Mirror
- Test: `tests/test_f4_b4_final_review_verdict_gate.py`

**Step 1: Failing test**

```python
"""tests/test_f4_b4_final_review_verdict_gate.py — F4 final review verdict gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "commands" / "vg" / "_shared" / "build" / "close.md"


def test_final_review_verdict_file_check_before_marker():
    body = CLOSE.read_text(encoding="utf-8")
    final_review_idx = body.find("7_1_5_final_review")
    assert final_review_idx > 0
    block = body[final_review_idx:final_review_idx + 2500]
    # Must reference verdict file
    assert ".final-review/verdict.md" in block or "final-review" in block, (
        "F4: B4 final review block must reference verdict file path"
    )
    # Must check existence
    assert ("[ -f" in block or "test -f" in block or "is_file" in block), (
        "F4: must check verdict file exists before marker touch"
    )
    # Must parse PASS|PARTIAL|FAIL
    assert ("PASS" in block and "FAIL" in block), (
        "F4: must parse PASS|PARTIAL|FAIL verdict and block on FAIL"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/build/close.md` STEP 7.1.5, replace block after spawn narration with:

```bash
else
  BUILD_START_SHA=$(cat "${PHASE_DIR}/.build-start-sha" 2>/dev/null || git rev-parse HEAD~10)
  COMMIT_RANGE="${BUILD_START_SHA}..HEAD"

  bash scripts/vg-narrate-spawn.sh vg-build-final-reviewer spawning "cumulative review ${COMMIT_RANGE}"
  # AI orchestrator MUST call:
  #   Agent(subagent_type="vg-build-final-reviewer",
  #         prompt=<rendered with phase_dir + commit_range>)
  # The agent MUST write verdict to ${PHASE_DIR}/.final-review/verdict.md
  # with frontmatter format:
  #   ---
  #   verdict: PASS | PARTIAL | FAIL
  #   commit_range: <range>
  #   gaps: <markdown list>
  #   ---

  # F4 Batch 15: verdict file gate
  VERDICT_FILE="${PHASE_DIR}/.final-review/verdict.md"
  if [ ! -f "$VERDICT_FILE" ]; then
    echo "⛔ STEP 7.1.5 F4: vg-build-final-reviewer did not write $VERDICT_FILE" >&2
    echo "   Final review must persist verdict to disk; marker requires evidence." >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.final_review_missing_verdict" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -qE "^verdict:\s*FAIL" "$VERDICT_FILE"; then
    echo "⛔ STEP 7.1.5 F4: cumulative final review FAIL" >&2
    cat "$VERDICT_FILE" | head -30 >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "build.final_review_failed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -qE "^verdict:\s*PARTIAL" "$VERDICT_FILE"; then
    echo "⚠ STEP 7.1.5 F4: cumulative final review PARTIAL — gaps logged but proceeding (v4.18.0 advisory)" >&2
  fi

  mkdir -p "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers" 2>/dev/null
  (type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "7_1_5_final_review" "${PHASE_DIR}") || touch "${PHASE_DIR_CANDIDATE:-${PHASE_DIR:-.}}/.step-markers/7_1_5_final_review.done"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step build 7_1_5_final_review 2>/dev/null || true
fi
```

```bash
git commit -m "fix(build): F4 — B4 final review verdict file gate (Batch 15)

Codex audit Finding F4 (CRITICAL): vg-build-final-reviewer Agent spawn
was comment-only in build/close.md STEP 7.1.5. After narrate calls,
marker fired unconditionally. Cumulative cross-task integration review
could be skipped while contract validator passed.

Fix: requires \${PHASE_DIR}/.final-review/verdict.md on disk with
frontmatter 'verdict: PASS|PARTIAL|FAIL'. Missing → BLOCK. FAIL →
BLOCK. PARTIAL → advisory WARN (v4.18.0 — flip to BLOCK in v4.19+
after telemetry). Marker only touched after verdict valid.

Emits build.final_review_missing_verdict / build.final_review_failed
events for telemetry.

Tests: tests/test_f4_b4_final_review_verdict_gate.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Regression sweep + release v4.18.0

Bump VERSION 4.17.2 → 4.18.0. CHANGELOG entry per F3+F4. Tag v4.18.0. Push. Re-sync ~/.vgflow.

End of Batch 15 plan. Estimated 2 hours.
