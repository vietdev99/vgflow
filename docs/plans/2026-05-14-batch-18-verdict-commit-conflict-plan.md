# Batch 18 — Verdict contract + commit count + reset-queue conflict (F5+F10+F11) Implementation Plan FINAL

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close last 3 audit findings. Final batch closes all 11 NEW Codex bp+build findings.

- **F5 (HIGH)**: Reviewer agents declared READ-ONLY ("MUST NOT modify any files"), output to stdout. But Batch 15 verdict-file gate expects file on disk. CONTRACT MISMATCH.
- **F10 (MEDIUM)**: `waves-overview.md:714` blocks `ACTUAL_COMMITS < EXPECTED` only. Extra commits pass — should be `!=`.
- **F11 (HIGH)**: `build-queue-preflight.sh:55` `--reset-queue` returns 0 BEFORE merge-conflict check (line 102). Build can start on conflicted tree.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "verdict_contract or commit_count or reset_queue or f5 or f10 or f11 or reviewer"`
- Single Co-Authored-By trailer per commit

---

## Task 1: F5 — Reviewer agents write verdict file

**Files:**
- Modify: `.claude/agents/vg-build-final-reviewer/SKILL.md` (add Write tool, instruct to write `.final-review/verdict.md`)
- Modify: `.claude/agents/vg-build-spec-reviewer/SKILL.md` (add Write tool, instruct to write `.spec-review/{task_id}.md`)
- Also `agents/` canonical copies if separate
- Test: `tests/test_f5_reviewer_writes_verdict.py`

**Step 1: Failing test**

```python
"""tests/test_f5_reviewer_writes_verdict.py — F5 reviewer verdict contract."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
FINAL = REPO / ".claude" / "agents" / "vg-build-final-reviewer" / "SKILL.md"
SPEC = REPO / ".claude" / "agents" / "vg-build-spec-reviewer" / "SKILL.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_final_reviewer_allows_write():
    body = _read(FINAL)
    # allowed-tools must include Write
    fm_end = body.find("\n---\n", 4)
    fm = body[:fm_end] if fm_end > 0 else body[:2000]
    assert "Write" in fm, (
        "F5: vg-build-final-reviewer must have Write in allowed-tools so it "
        "can persist verdict to disk (Batch 15 gate expects file on disk)"
    )


def test_final_reviewer_documents_verdict_file_write():
    body = _read(FINAL)
    assert ".final-review/verdict.md" in body, (
        "F5: vg-build-final-reviewer SKILL.md must instruct the agent to "
        "write verdict to ${PHASE_DIR}/.final-review/verdict.md (matches "
        "Batch 15 gate in build/close.md)"
    )


def test_spec_reviewer_allows_write():
    body = _read(SPEC)
    fm_end = body.find("\n---\n", 4)
    fm = body[:fm_end] if fm_end > 0 else body[:2000]
    assert "Write" in fm, "F5: vg-build-spec-reviewer must have Write in allowed-tools"


def test_spec_reviewer_documents_verdict_file_write():
    body = _read(SPEC)
    assert ".spec-review/" in body and "verdict" in body.lower(), (
        "F5: vg-build-spec-reviewer must instruct agent to write verdict to "
        "${PHASE_DIR}/.spec-review/{task_id}.md (matches Batch 15 gate in "
        "build/post-execution-overview.md)"
    )


def test_final_reviewer_strict_rules_no_longer_read_only():
    body = _read(FINAL)
    # The old "READ-ONLY agent. You MUST NOT modify any files" must be removed
    # or qualified. Allow if there's an explicit exception for the verdict file.
    if "READ-ONLY agent" in body or "MUST NOT modify any files" in body:
        # Acceptable if explicitly excepted for verdict file
        assert "except" in body.lower() or "verdict" in body.lower(), (
            "F5: SKILL.md must remove or qualify the 'READ-ONLY / MUST NOT "
            "modify any files' rule — agent now writes verdict file"
        )
```

**Step 2-6:** RED → implement → GREEN → mirror canonical → commit.

In `.claude/agents/vg-build-final-reviewer/SKILL.md`:
1. Add `- Write` to `allowed-tools` list.
2. Replace strict rule "READ-ONLY agent. You MUST NOT modify any files. Use only Read / Bash..." with: "Write-restricted: you may only Write `${phase_dir}/.final-review/verdict.md`. No other file modifications. Use Read / Bash (read-only) / Grep otherwise."
3. Add new step in Job:
   > 7. Write verdict to `${phase_dir}/.final-review/verdict.md` with frontmatter:
   >    ```
   >    ---
   >    verdict: PASS | PARTIAL | FAIL
   >    commit_range: <range>
   >    phase: <number>
   >    ts: <ISO>
   >    ---
   >    <gaps as markdown>
   >    ```
4. Update "Output the verdict text directly to stdout" → "Output the verdict text both to stdout AND to the verdict file."

In `.claude/agents/vg-build-spec-reviewer/SKILL.md`: similar adjustments. Verdict file at `${phase_dir}/.spec-review/{task_id}.md` with frontmatter `task_id: T-XX, verdict: PASS|FAIL, gaps: ...`.

If canonical `agents/` dir exists separately, mirror there too.

```bash
git commit -m "fix(agents): F5 — reviewer agents write verdict file (Batch 18 FINAL)

Codex audit Finding F5 (HIGH): vg-build-final-reviewer + vg-build-spec-
reviewer SKILL.md declared READ-ONLY ('MUST NOT modify any files'),
emit verdict to stdout only. But Batch 15 F3+F4 verdict-file gates in
build/close.md + post-execution-overview.md require verdict files on
disk. Contract mismatch — agent return value unreachable by bash gates.

Fix:
- allowed-tools adds Write.
- Strict rule qualified: Write-restricted to specific verdict file path.
- Job step added: write verdict file with frontmatter (verdict, range,
  phase, ts) + markdown gaps body.
- Stdout verdict retained for orchestrator visibility.

Closes the Batch 15 ↔ agent contract gap. Verdict-file gates now have
their producer.

Tests: tests/test_f5_reviewer_writes_verdict.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F10 — Commit count != not <

**Files:**
- Modify: `commands/vg/_shared/build/waves-overview.md` (line 714 area)
- Mirror
- Test: `tests/test_f10_commit_count_strict.py`

**Step 1: Failing test**

```python
"""tests/test_f10_commit_count_strict.py — F10 commit count strict equality."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
WAVES = REPO / "commands" / "vg" / "_shared" / "build" / "waves-overview.md"


def test_commit_count_blocks_both_directions():
    body = WAVES.read_text(encoding="utf-8")
    # Find the audit block
    idx = body.find("EXPECTED_COMMITS")
    assert idx > 0
    block = body[idx:idx + 2000]
    # Old behavior: `[ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]` (< only)
    # New behavior: != check OR both -lt + -gt
    has_strict_eq = (
        "ACTUAL_COMMITS\" != \"$EXPECTED_COMMITS" in block or
        "ACTUAL_COMMITS != EXPECTED_COMMITS" in block or
        ("-lt" in block and "-gt" in block) or
        "-ne" in block
    )
    assert has_strict_eq, (
        "F10: commit count audit must reject ACTUAL != EXPECTED (both "
        "directions). Old code blocked only ACTUAL < EXPECTED; extra "
        "commits passed audit silently."
    )


def test_extra_commits_message_present():
    body = WAVES.read_text(encoding="utf-8")
    # Should mention extra commit case
    assert ("extra" in body.lower() or "more than" in body.lower() or "exceed" in body.lower()) and "commit" in body.lower(), (
        "F10: error message must distinguish missing vs extra commits "
        "so operator knows which case fired"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/build/waves-overview.md` around line 714, change:

```bash
if [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]; then
  echo "⛔ COMMIT MISMATCH: wave ${N} expected ${EXPECTED_COMMITS} commits, got ${ACTUAL_COMMITS}"
  ...
fi
```

To:

```bash
if [ "$ACTUAL_COMMITS" -ne "$EXPECTED_COMMITS" ]; then
  if [ "$ACTUAL_COMMITS" -lt "$EXPECTED_COMMITS" ]; then
    echo "⛔ F10 COMMIT MISMATCH: wave ${N} expected ${EXPECTED_COMMITS}, got ${ACTUAL_COMMITS} (missing)"
  else
    echo "⛔ F10 COMMIT MISMATCH: wave ${N} expected ${EXPECTED_COMMITS}, got ${ACTUAL_COMMITS} (extra commits — task over-committed)"
  fi
  # Existing diagnostic blocks ...
fi
```

```bash
git commit -m "fix(build): F10 — commit count strict equality, not less-than (Batch 18)

Codex audit Finding F10 (MEDIUM): waves-overview.md:714 blocked
ACTUAL_COMMITS < EXPECTED only. Extra commits from over-committing
tasks passed audit silently. Rule is 'exactly 1 commit per task' but
gate enforced only ≤1.

Fix: -ne (not equal) check. Branched message distinguishes missing vs
extra so operator knows which task over-committed.

Tests: tests/test_f10_commit_count_strict.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: F11 — reset-queue runs conflict check first

**Files:**
- Modify: `commands/vg/_shared/lib/build-queue-preflight.sh` (lines 43-57 reset-queue branch)
- Mirror
- Test: `tests/test_f11_reset_queue_conflict_gate.py`

**Step 1: Failing test**

```python
"""tests/test_f11_reset_queue_conflict_gate.py — F11 reset-queue still checks conflicts."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
PRE = REPO / "commands" / "vg" / "_shared" / "lib" / "build-queue-preflight.sh"


def test_conflict_check_runs_even_under_reset_queue():
    body = PRE.read_text(encoding="utf-8")
    # The reset-queue branch must NOT short-circuit before conflict check.
    # Look for conflict check happening either: (a) before reset short-circuit,
    # (b) inside the reset branch before return 0, or
    # (c) reset branch removed and check moved earlier
    reset_idx = body.find('"$reset_queue" = "true"')
    assert reset_idx > 0
    reset_block = body[reset_idx:reset_idx + 1200]
    # Either no `return 0` in reset block (means flow continues to check),
    # OR conflict check happens INSIDE reset block before return
    if "return 0" in reset_block:
        # Must have diff-filter=U check BEFORE the return 0
        ret_idx = reset_block.find("return 0")
        before_return = reset_block[:ret_idx]
        assert ("diff-filter=U" in before_return or "merge conflict" in before_return.lower()), (
            "F11: --reset-queue short-circuit (return 0) must NOT happen "
            "before merge-conflict check. Build cannot start on conflicted "
            "working tree even with --reset-queue."
        )


def test_conflict_check_blocks_under_reset_queue():
    body = PRE.read_text(encoding="utf-8")
    # Confirm a hard block path exists for conflicts under reset_queue
    assert "diff-filter=U" in body
    # The conflict block must contain an error message
    conflict_idx = body.find("diff-filter=U")
    block = body[max(0, conflict_idx - 200):conflict_idx + 500]
    assert ("⛔" in block or "BLOCK" in block.upper() or "blockers" in block), (
        "F11: conflict path must still BLOCK (not silently continue)"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/lib/build-queue-preflight.sh`, restructure the reset-queue branch (lines 44-57). Move the conflict check (currently lines 102-111) to fire BEFORE the reset short-circuit. Pattern:

```bash
vg_build_queue_preflight() {
  local reset_queue="${1:-false}"
  local phase_arg="${2:-<phase>}"
  local blockers=()

  # F11 Batch 18: conflict check ALWAYS runs first, even under --reset-queue.
  # Build cannot start on conflicted working tree regardless of reset.
  local conflicts
  conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null)
  if [ -n "$conflicts" ]; then
    echo "⛔ Unresolved merge conflicts (cannot build on conflicted working tree):"
    echo "$conflicts" | head -5 | sed 's/^/     /'
    echo ""
    echo "   Fix: resolve via your merge tool, then re-run /vg:build ${phase_arg}"
    echo "   --reset-queue does NOT bypass conflict check (intentional)."
    return 1
  fi

  # --- 1. --reset-queue: wipe state + unstage leftovers ---
  if [ "$reset_queue" = "true" ]; then
    ... (existing reset logic unchanged) ...
    return 0
  fi

  # --- 2/3/4 unchanged but drop conflict block since it ran above ---
  ...
}
```

```bash
git commit -m "fix(build-queue): F11 — conflict check before --reset-queue short-circuit (Batch 18)

Codex audit Finding F11 (HIGH): build-queue-preflight.sh:55 returned 0
from --reset-queue branch BEFORE the merge-conflict check at line 102.
Operator passing --reset-queue on a conflicted working tree had the
queue wiped + unstaged but conflicts remained — build proceeded.

Fix: move merge-conflict check to TOP of vg_build_queue_preflight, BEFORE
the reset short-circuit. --reset-queue no longer bypasses conflict gate.
Error message explicitly states this intentional behavior.

Tests: tests/test_f11_reset_queue_conflict_gate.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Release v4.21.0 — FINAL audit batch

Bump VERSION 4.20.0 → 4.21.0. CHANGELOG entry per F5+F10+F11 PLUS final summary noting all 11 Codex bp+build findings closed across Batches 15/16/17/18 (v4.18.0-v4.21.0). Tag v4.21.0. Push. Re-sync ~/.vgflow.

End of Batch 18 plan. Estimated 2 hours.
