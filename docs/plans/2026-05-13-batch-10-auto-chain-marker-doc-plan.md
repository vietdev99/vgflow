# Batch 10 — Auto-chain + marker integrity + LIFECYCLE.md doc (Findings 1+2+3+10) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 4 high+medium severity scale-readiness findings from `docs/plans/2026-05-13-flow-chain-audit.md`.

- **F1 (HIGH)**: Only review→build emits `next_command`. Extend to ALL 5 other phase closes so `--auto-chain` works end-to-end.
- **F2 (HIGH)**: `LIFECYCLE.md:60` lists `TEST-RESULTS.json` but actual artifact is `SANDBOX-TEST.md`. Doc drift.
- **F3 (HIGH)**: Only test/close uses `verify_all_markers_strict_runid`. Blueprint/build/accept still use `-f .done` checks. Propagate strict marker check.
- **F10 (MEDIUM)**: `LIFECYCLE.md` stale post-Batch 1-9. Update to reference step-ledger, strict markers, CrossAI, evidence-manifest.

**Tech Stack:** Python embed + bash.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "next_command or lifecycle or marker or strict or auto_chain or f1 or f2 or f3 or f10"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: F1 — next_command emit on 5 phase closes

**Files:**
- Modify: 
  - `commands/vg/_shared/scope/close.md`
  - `commands/vg/_shared/blueprint/close.md`
  - `commands/vg/test-spec.md`
  - `commands/vg/_shared/test/close.md`
  - `commands/vg/_shared/specs/write-and-commit.md`
- Mirrors for each
- Test: `tests/test_f1_next_command_emit.py`

**Step 1: Failing test**

```python
"""tests/test_f1_next_command_emit.py — F1 auto-chain next_command on all closes."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

CASES = [
    ("commands/vg/_shared/specs/write-and-commit.md", "/vg:scope"),
    ("commands/vg/_shared/scope/close.md", "/vg:blueprint"),
    ("commands/vg/_shared/blueprint/close.md", "/vg:build"),
    ("commands/vg/test-spec.md", "/vg:review"),
    ("commands/vg/_shared/test/close.md", "/vg:accept"),
]


def test_each_close_writes_next_command_to_pipeline_state():
    """Each phase close must write state['next_command'] = '/vg:NEXT {phase}'
    to PIPELINE-STATE.json so --auto-chain readers can pick it up."""
    failures = []
    for rel, expected_cmd in CASES:
        path = REPO / rel
        body = path.read_text(encoding="utf-8")
        if 'next_command' not in body:
            failures.append(f"{rel}: missing next_command write")
            continue
        if expected_cmd not in body:
            failures.append(f"{rel}: expected '{expected_cmd}' next-command target")
    assert not failures, "F1 next_command missing:\n  " + "\n  ".join(failures)


def test_review_close_pattern_remains_intact():
    """Review close (existing emit) must still write next_command — no regression."""
    body = (REPO / "commands/vg/_shared/review/close.md").read_text(encoding="utf-8")
    assert "next_command" in body, "F1: existing review next_command pattern must remain"
```

**Step 2: Run** → likely 1 fail listing 5 missing emits.

**Step 3: Implement**

For each close file, locate the PIPELINE-STATE update block (search for `PIPELINE-STATE.json` or `pipeline_step =`). Insert a `state["next_command"] = "/vg:NEXT_PHASE {PHASE_NUMBER}"` assignment alongside existing state writes.

Example for `commands/vg/_shared/scope/close.md`:
```python
# Inside PIPELINE-STATE block, add:
state["next_command"] = f"/vg:blueprint {phase}"
state["next_command_emitted_at"] = datetime.utcnow().isoformat() + "Z"
```

For test-spec.md, find the closing PIPELINE-STATE write near the `Next: /vg:review` echo (line ~545 area).

For test/close.md, find the §8.3.2 PIPELINE-STATE update (line ~458 area). Verdict-dependent: emit `next_command=/vg:accept` only when verdict in PASSED/GAPS_FOUND; emit `next_command=/vg:review --resume` when FAILED.

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/_shared/specs/write-and-commit.md \
        commands/vg/_shared/scope/close.md \
        commands/vg/_shared/blueprint/close.md \
        commands/vg/test-spec.md \
        commands/vg/_shared/test/close.md \
        .claude/commands/vg/_shared/specs/write-and-commit.md \
        .claude/commands/vg/_shared/scope/close.md \
        .claude/commands/vg/_shared/blueprint/close.md \
        .claude/commands/vg/test-spec.md \
        .claude/commands/vg/_shared/test/close.md \
        tests/test_f1_next_command_emit.py
git commit -m "feat(auto-chain): F1 — next_command emit on all phase closes (Batch 10)

Flow-chain audit Finding 1 (HIGH): only review→build wired next_command for
auto-chain consumption. specs/scope/blueprint/test-spec/test closes echoed
'Next: /vg:X' to stdout but never wrote the JSON field. In --auto-chain or
CI runs, the pipeline stalled at every boundary except review→build.

Fix: each phase close now writes state['next_command'] = '/vg:NEXT {phase}'
to PIPELINE-STATE.json. test/close verdict-dependent (PASSED/GAPS_FOUND →
/vg:accept; FAILED → /vg:review --resume).

Now --auto-chain works end-to-end across all 6 phase boundaries:
  specs → scope → blueprint → build → test-spec → review → test → accept

Tests: tests/test_f1_next_command_emit.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F3 — Strict marker check propagated to blueprint/build/accept

**Files:**
- Modify:
  - `commands/vg/_shared/blueprint/close.md` (R7 block at line ~127-165)
  - `commands/vg/_shared/build/close.md` (run-complete step around 12_run_complete area)
  - `commands/vg/_shared/accept/cleanup/overview.md` (marker gate at ~117-118)
- Mirrors
- Test: `tests/test_f3_strict_markers_all_closes.py`

**Step 1: Failing test**

```python
"""tests/test_f3_strict_markers_all_closes.py — F3 strict markers propagate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

CLOSES = [
    "commands/vg/_shared/blueprint/close.md",
    "commands/vg/_shared/build/close.md",
    "commands/vg/_shared/accept/cleanup/overview.md",
    "commands/vg/_shared/test/close.md",  # already done in Batch 9 — must stay
]


def test_all_phase_closes_use_strict_marker_check():
    failures = []
    for rel in CLOSES:
        body = (REPO / rel).read_text(encoding="utf-8")
        if "verify_all_markers_strict_runid" not in body and "verify_marker" not in body:
            failures.append(f"{rel}: missing strict marker verification call")
    assert not failures, "F3 strict marker missing:\n  " + "\n  ".join(failures)


def test_blueprint_close_no_bare_file_exists_check_on_markers():
    body = (REPO / "commands/vg/_shared/blueprint/close.md").read_text(encoding="utf-8")
    # The bare `[ ! -f "${PHASE_DIR}/.step-markers/${step}.done" ]` pattern
    # should be removed in favor of strict-runid verification.
    # Tolerate the pattern if it's wrapped by verify_marker fallback.
    if 'verify_all_markers_strict_runid' in body or 'verify_marker' in body:
        return  # acceptable — strict path present
    assert False, "F3: blueprint/close.md must replace bare -f check with verify_marker"
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Pattern for each close (similar to test/close.md from Batch 9):

```bash
# F3 Batch 10: strict marker check
MARKER_LIB="${VG_COMMAND_ROOT:-${VG_HOME:-$HOME/.vgflow}/commands/vg/_shared}/lib/marker-schema.sh"
[ -f "$MARKER_LIB" ] || MARKER_LIB="commands/vg/_shared/lib/marker-schema.sh"
[ -f "$MARKER_LIB" ] || MARKER_LIB=".claude/commands/vg/_shared/lib/marker-schema.sh"
if [ -f "$MARKER_LIB" ]; then
  source "$MARKER_LIB"
  export VG_MARKER_STRICT=1
  if ! verify_all_markers_strict_runid "${PHASE_DIR}" "${PHASE_NUMBER}" "${VG_RUN_ID:-}"; then
    echo "⛔ Marker integrity gate failed — empty/stale/forged markers detected" >&2
    echo "   Set VG_MARKER_STRICT=0 to bypass (UNSAFE — only for migration)." >&2
    exit 1
  fi
fi
```

Insert at appropriate position in each close file (before existing R7 / cleanup / verify-complete blocks).

```bash
git commit -m "fix(marker-integrity): F3 — strict marker check on blueprint/build/accept (Batch 10)

Flow-chain audit Finding 3 (HIGH): Batch 9 wired verify_all_markers_strict_runid
into test/close.md only. Blueprint, build, accept/cleanup still used
bare '-f .step-markers/X.done' file-existence checks. In multi-run/resume
scenarios at scale, stale markers from prior runs satisfied the gate
silently.

Fix: same strict-runid pattern propagated to blueprint/close.md (R7 block),
build/close.md (12_run_complete), accept/cleanup/overview.md (marker gate).
All 4 phase closes (blueprint, build, test, accept) now reject empty/stale/
forged markers and require run_id match.

Bypass via VG_MARKER_STRICT=0 only for explicit migration.

Tests: tests/test_f3_strict_markers_all_closes.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: F2+F10 — LIFECYCLE.md doc refresh

**Files:**
- Modify: `commands/vg/LIFECYCLE.md`
- Mirror: `.claude/commands/vg/LIFECYCLE.md`
- Test: `tests/test_f2_f10_lifecycle_doc_freshness.py`

**Step 1: Failing test**

```python
"""tests/test_f2_f10_lifecycle_doc_freshness.py — F2 + F10 LIFECYCLE doc."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO / "commands" / "vg" / "LIFECYCLE.md"


def test_lifecycle_test_artifact_is_sandbox_test_md():
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "SANDBOX-TEST.md" in body, (
        "F2: LIFECYCLE.md must reference SANDBOX-TEST.md as the test phase output "
        "(the actual artifact written by test/close.md)"
    )
    # The stale TEST-RESULTS.json reference must be either removed or annotated
    # as deprecated. Tolerate if it's in a deprecation note.
    if "TEST-RESULTS.json" in body:
        # Must be in a context that marks it as deprecated/historical
        idx = body.index("TEST-RESULTS.json")
        ctx = body[max(0, idx-200):idx+200]
        assert "deprecated" in ctx.lower() or "historical" in ctx.lower() or "renamed" in ctx.lower(), (
            f"F2: LIFECYCLE.md still references TEST-RESULTS.json without "
            f"marking it deprecated. Context: ...{ctx[150:250]}..."
        )


def test_lifecycle_documents_batch_artifacts():
    body = LIFECYCLE.read_text(encoding="utf-8")
    # F10: must reference key artifacts introduced in Batches 1-9 + H13
    required = [
        ".test-step-status.json",       # Batch 9 C5 ledger
        "LIFECYCLE-SPECS.json",          # Batch 1
        "DEEP-TEST-SPECS.md",            # test-spec lane
        "evidence-manifest",             # Issue #175 provenance
        "TEST-FAILURE-REPORT.md",        # H13 v4.12.0
    ]
    missing = [r for r in required if r not in body]
    assert not missing, (
        f"F10: LIFECYCLE.md must document Batch 1-9 + H13 artifacts. "
        f"Missing references: {missing}"
    )


def test_lifecycle_documents_strict_marker_gate():
    body = LIFECYCLE.read_text(encoding="utf-8")
    assert "verify_all_markers_strict_runid" in body or "run_id" in body or "strict marker" in body.lower(), (
        "F10: LIFECYCLE.md must document the strict marker gate introduced in "
        "Batch 9 (C9 verdict integrity)"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Update LIFECYCLE.md:
- Replace `TEST-RESULTS.json` with `SANDBOX-TEST.md` on line 60. Add frontmatter description.
- Add a "Pipeline Artifacts Reference (v4.12.0)" section listing: PIPELINE-STATE.json, .test-step-status.json, LIFECYCLE-SPECS.json, DEEP-TEST-SPECS.md, GOAL-COVERAGE-MATRIX.json, SANDBOX-TEST.md, REVIEW.md, .verdict-computed.json, evidence-manifest.json, TEST-FAILURE-REPORT.md, REFLECTION.md, MATRIX-INTENT.json, url-runtime-status.json, CODEGEN-BINDING-REPORT.json, CODEX-FIX-FAILURES.json, .amend-invalidation.json (planned).
- Add a "Strict Marker Gate (v4.3.0+)" section documenting that all phase closes invoke `verify_all_markers_strict_runid` with run_id match.
- Add a "Auto-chain (v5.0+)" section noting next_command is written by all phase closes for `--auto-chain` consumers.

```bash
git commit -m "docs(lifecycle): F2 + F10 — refresh LIFECYCLE.md post Batches 1-12 (Batch 10)

Flow-chain audit Findings 2 (HIGH) + 10 (MEDIUM): LIFECYCLE.md was stale
since pre-Batch-1. Listed TEST-RESULTS.json as test phase output (actual:
SANDBOX-TEST.md); did not mention any artifact introduced in Batches 1-9
or H13.

Fix:
- Line 60: test phase artifact corrected from TEST-RESULTS.json to
  SANDBOX-TEST.md with YAML frontmatter schema documented.
- New 'Pipeline Artifacts Reference' section: lists every JSON/MD
  artifact produced by the pipeline (16 total) with phase origin.
- New 'Strict Marker Gate' section: documents Batch 9 marker-runid pattern.
- New 'Auto-chain' section: documents F1 next_command emit (Batch 10).

Onboarding-critical doc for any 50+ phase project consumer.

Tests: tests/test_f2_f10_lifecycle_doc_freshness.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Regression sweep + release v4.13.0

Bump VERSION 4.12.0 → 4.13.0. CHANGELOG entry per 4 findings. Tag v4.13.0. Push. Re-sync ~/.vgflow for modified files.

End of Batch 10 plan. Estimated 3 hours.
