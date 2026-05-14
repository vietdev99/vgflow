# Batch 21 — Test execution plan enforcement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `/vg:test` execution must consume `CODEGEN-MANIFEST.json` + `TEST-EXECUTION-PLAN.json` as authoritative spec list + order. Eliminate glob-based playwright invocation that ignores test-spec lifecycle artifacts.

**Real bug (user dogfood):** "test không chạy theo lộ trình của test-specs đề ra". `regression-security.md:99-101` uses `{phase}-goal-*.spec.ts` glob — runs whatever specs match, in alphabetical order, ignoring test-spec's declared execution order, family routing, fixture DAG, and lifecycle stages.

**Artifacts ignored by test runtime today:**
- `CODEGEN-MANIFEST.json` (authoritative spec list + goal_id mapping)
- `TEST-EXECUTION-PLAN.json` (execution order + family routing)
- `TEST-FIXTURE-DAG.json` (topo order of fixtures)
- `LIFECYCLE-SPECS.json` (per-goal RCRURDR stages — used for verdict only, not run order)

**Tech Stack:** Python + bash.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "test_execution or codegen_manifest or orphan_spec or batch_21"`
- Single Co-Authored-By trailer per commit

---

## Task 1: Test runtime reads CODEGEN-MANIFEST for spec list (no glob)

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (lines 96-101 — playwright invocation)
- Mirror
- Test: `tests/test_batch21_codegen_manifest_consume.py`

**Step 1: Failing test**

```python
"""tests/test_batch21_codegen_manifest_consume.py — Batch 21 manifest consumption."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_test_reads_codegen_manifest():
    body = _read(RS)
    assert "CODEGEN-MANIFEST.json" in body, (
        "Batch 21: test/regression-security.md must read CODEGEN-MANIFEST.json "
        "to get authoritative spec list (not glob)"
    )


def test_no_pure_glob_invocation():
    body = _read(RS)
    # The bare-glob playwright invocation pattern must be guarded by a
    # 'manifest missing' fallback path, not the primary path
    primary_glob_idx = body.find("{phase}-goal-*.spec.ts")
    if primary_glob_idx > 0:
        # Look at surrounding context
        ctx_start = max(0, primary_glob_idx - 1500)
        ctx = body[ctx_start:primary_glob_idx]
        # The glob path must be conditional on CODEGEN-MANIFEST missing
        # i.e. it's a fallback, not the default
        assert ("if [ ! -f" in ctx and "CODEGEN-MANIFEST.json" in ctx) or "manifest" in ctx.lower(), (
            "Batch 21: glob spec list must be a FALLBACK when CODEGEN-MANIFEST.json "
            "missing, not the primary path"
        )


def test_manifest_spec_list_used_for_playwright():
    body = _read(RS)
    # Need a Python extraction step that reads manifest + builds spec list
    # for playwright
    assert ("playwright_specs" in body or "spec_list" in body or "SPEC_LIST=" in body), (
        "Batch 21: must extract spec list from manifest into variable used by "
        "playwright test invocation"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/test/regression-security.md` replace the playwright invocation block (around lines 96-101):

```bash
# Batch 21: read CODEGEN-MANIFEST.json for authoritative spec list.
# Glob is fallback only when manifest missing (legacy phase).
CODEGEN_MANIFEST="${PHASE_DIR}/CODEGEN-MANIFEST.json"
if [ -f "$CODEGEN_MANIFEST" ]; then
  SPEC_LIST=$(${PYTHON_BIN:-python3} -c "
import json
m = json.loads(open('${CODEGEN_MANIFEST}', encoding='utf-8').read())
specs = m.get('playwright_specs', m.get('specs', []))
# Each entry: {'path': '...', 'goal_id': '...', 'family': '...'}
print(' '.join(s['path'] if isinstance(s, dict) else s for s in specs))
" 2>/dev/null)
  if [ -z "$SPEC_LIST" ]; then
    echo "⛔ Batch 21 BLOCK: CODEGEN-MANIFEST.json exists but contains 0 specs" >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test.manifest_empty" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
  echo "▸ Batch 21: running ${SPEC_LIST} from CODEGEN-MANIFEST.json"
  PLAYWRIGHT_TARGETS="$SPEC_LIST"
else
  echo "⚠ Batch 21: CODEGEN-MANIFEST.json missing — falling back to glob (legacy phase)" >&2
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test.manifest_missing_glob_fallback" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
  PLAYWRIGHT_TARGETS="${GENERATED_TESTS_DIR}/${PHASE_NUMBER}-goal-*.spec.ts"
fi

run_on_target "cd ${PROJECT_PATH} && \
  VG_HEADED=${VG_HEADED} VG_SLOW_MO=${SLOW_MO} \
  npx playwright test \
    --config ${GENERATED_TESTS_DIR}/playwright.config.generated.ts \
    ${PLAYWRIGHT_TARGETS}"
```

```bash
git commit -m "fix(test): Batch 21 Task 1 — read CODEGEN-MANIFEST for spec list (no glob)

User dogfood: 'test không chạy theo lộ trình của test-specs đề ra'.
regression-security.md:99-101 used '{phase}-goal-*.spec.ts' glob,
ignoring CODEGEN-MANIFEST.json declared spec list.

Fix: CODEGEN-MANIFEST.json now primary source (Python extracts
playwright_specs[].path list). Glob is fallback only when manifest
missing (legacy phase) — emits test.manifest_missing_glob_fallback
event for telemetry. Empty manifest → BLOCK with test.manifest_empty.

Tests: tests/test_batch21_codegen_manifest_consume.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Test reads TEST-EXECUTION-PLAN for order + family routing

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (extend Task 1 block)
- Mirror
- Test: `tests/test_batch21_execution_plan_order.py`

**Step 1: Failing test**

```python
"""tests/test_batch21_execution_plan_order.py — Batch 21 execution plan order."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_reads_execution_plan_for_order():
    body = RS.read_text(encoding="utf-8")
    # Must read TEST-EXECUTION-PLAN.json for execution_order or order
    assert "TEST-EXECUTION-PLAN.json" in body, (
        "Batch 21: test runtime must read TEST-EXECUTION-PLAN.json"
    )
    # And use it to order specs
    assert ("execution_order" in body or "order" in body and "playwright" in body), (
        "Batch 21: must consume execution_order from TEST-EXECUTION-PLAN.json "
        "(not rely on alphabetical default)"
    )


def test_family_routing_applied():
    body = RS.read_text(encoding="utf-8")
    # If TEST-EXECUTION-PLAN.json has family field per spec, must apply
    # --project=<family> to playwright invocation OR document family-aware run
    assert ("family" in body and "playwright" in body), (
        "Batch 21: family field from execution-plan must affect playwright "
        "invocation (e.g. --project=<family> or runner selection)"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Extend the Task 1 block — when `CODEGEN_MANIFEST` exists, also load `TEST-EXECUTION-PLAN.json` and reorder specs:

```bash
# Batch 21 Task 2: TEST-EXECUTION-PLAN.json for order + family routing
EXEC_PLAN="${PHASE_DIR}/TEST-EXECUTION-PLAN.json"
if [ -f "$EXEC_PLAN" ] && [ -f "$CODEGEN_MANIFEST" ]; then
  # Reorder SPEC_LIST per execution_order array
  SPEC_LIST=$(${PYTHON_BIN:-python3} -c "
import json
plan = json.loads(open('${EXEC_PLAN}', encoding='utf-8').read())
manifest = json.loads(open('${CODEGEN_MANIFEST}', encoding='utf-8').read())
specs = manifest.get('playwright_specs', manifest.get('specs', []))
by_goal = {(s.get('goal_id') if isinstance(s, dict) else s): (s['path'] if isinstance(s, dict) else s) for s in specs}
# execution_order: list of goal_ids in run order
order = plan.get('execution_order', [])
ordered = []
for gid in order:
    p = by_goal.get(gid)
    if p:
        ordered.append(p)
# Append any manifest spec NOT in execution_order (defensive)
remaining = [p for s in specs for p in [s['path'] if isinstance(s, dict) else s] if p not in ordered]
ordered.extend(remaining)
print(' '.join(ordered))
" 2>/dev/null)
  if [ -n "$SPEC_LIST" ]; then
    echo "▸ Batch 21: reordered specs per TEST-EXECUTION-PLAN.execution_order"
    PLAYWRIGHT_TARGETS="$SPEC_LIST"
  fi

  # Family routing: pick playwright project per family if multi-family declared
  FAMILY=$(${PYTHON_BIN:-python3} -c "
import json
plan = json.loads(open('${EXEC_PLAN}', encoding='utf-8').read())
print(plan.get('family', plan.get('default_family', '')))
" 2>/dev/null)
  PROJECT_FLAG=""
  if [ -n "$FAMILY" ] && [ "$FAMILY" != "web" ] && [ "$FAMILY" != "mixed" ]; then
    PROJECT_FLAG="--project=${FAMILY}"
    echo "▸ Batch 21: family=${FAMILY} → adding ${PROJECT_FLAG} to playwright"
  fi
fi
```

Then in `npx playwright test` invocation append `${PROJECT_FLAG}`.

```bash
git commit -m "fix(test): Batch 21 Task 2 — TEST-EXECUTION-PLAN order + family routing

Test runtime now reads TEST-EXECUTION-PLAN.json execution_order array
and reorders spec list to match. Specs not in execution_order appended
defensively (no orphan drop). Family field (mobile, backend, cli,
library) adds --project=<family> to playwright invocation.

Closes 'test runs in alphabetical playwright default' gap. Spec
dependencies declared in execution_order now honored.

Tests: tests/test_batch21_execution_plan_order.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Pre-run gate — every manifest spec must exist on disk

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (before playwright invocation)
- Mirror
- Test: `tests/test_batch21_prerun_existence_gate.py`

**Step 1: Failing test**

```python
"""tests/test_batch21_prerun_existence_gate.py — Batch 21 pre-run gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_prerun_existence_check():
    body = RS.read_text(encoding="utf-8")
    # Must verify each manifest spec file exists before playwright runs
    assert ("spec_missing" in body or "missing.*spec" in body or "[ ! -f" in body and "MISSING" in body.upper()), (
        "Batch 21: pre-run gate must check each manifest spec exists on disk; "
        "missing spec → BLOCK"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Insert before playwright invocation, AFTER SPEC_LIST built:

```bash
# Batch 21 Task 3: pre-run existence gate — every manifest spec must exist on disk
if [ -f "$CODEGEN_MANIFEST" ] && [ -n "${SPEC_LIST:-}" ]; then
  MISSING_SPECS=""
  for spec_rel in $SPEC_LIST; do
    spec_abs="${PROJECT_PATH}/${spec_rel}"
    [ -f "$spec_abs" ] || MISSING_SPECS="${MISSING_SPECS} ${spec_rel}"
  done
  if [ -n "$MISSING_SPECS" ]; then
    echo "⛔ Batch 21 BLOCK: CODEGEN-MANIFEST.json references missing spec file(s):" >&2
    echo "  ${MISSING_SPECS}" >&2
    echo "   Re-run /vg:test-spec ${PHASE_NUMBER} to regenerate." >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test.manifest_spec_missing" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing\":\"${MISSING_SPECS}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

```bash
git commit -m "fix(test): Batch 21 Task 3 — pre-run existence gate for manifest specs

Before playwright invocation, validate each spec listed in
CODEGEN-MANIFEST.json exists on disk. Missing spec → exit 1 + emit
test.manifest_spec_missing. Closes 'codegen claims spec X exists but
file deleted/never written' drift.

Tests: tests/test_batch21_prerun_existence_gate.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Post-run gate — orphan spec detection

**Files:**
- Modify: `commands/vg/_shared/test/regression-security.md` (after playwright invocation)
- Mirror
- Test: `tests/test_batch21_orphan_spec_detection.py`

**Step 1: Failing test**

```python
"""tests/test_batch21_orphan_spec_detection.py — Batch 21 orphan spec detection."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_orphan_spec_event_emitted():
    body = RS.read_text(encoding="utf-8")
    # Must emit test.orphan_spec_executed event when specs ran that aren't in manifest
    assert ("test.orphan_spec" in body or "orphan_spec" in body), (
        "Batch 21: post-run gate must emit test.orphan_spec_executed when "
        "specs executed that aren't in CODEGEN-MANIFEST.json"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Insert after playwright invocation finishes:

```bash
# Batch 21 Task 4: post-run orphan spec detection.
# playwright-results.json lists specs that ran. Compare to CODEGEN-MANIFEST list.
# Orphan = ran but not in manifest. May indicate stale specs from prior phase.
if [ -f "$CODEGEN_MANIFEST" ] && [ -f "$RESULTS_JSON" ]; then
  ORPHANS=$(${PYTHON_BIN:-python3} -c "
import json
m = json.loads(open('${CODEGEN_MANIFEST}', encoding='utf-8').read())
manifest_paths = set()
for s in m.get('playwright_specs', m.get('specs', [])):
    manifest_paths.add(s['path'] if isinstance(s, dict) else s)
results = json.loads(open('${RESULTS_JSON}', encoding='utf-8').read())
ran_paths = set()
for suite in results.get('suites', []):
    for spec in suite.get('specs', []):
        ran_paths.add(spec.get('file', ''))
    # Recurse if nested
    for nested in suite.get('suites', []):
        for spec in nested.get('specs', []):
            ran_paths.add(spec.get('file', ''))
orphans = ran_paths - manifest_paths
print(','.join(sorted(orphans)) if orphans else '')
" 2>/dev/null)
  if [ -n "$ORPHANS" ]; then
    echo "⚠ Batch 21: orphan specs executed (not in CODEGEN-MANIFEST.json): ${ORPHANS}" >&2
    "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "test.orphan_spec_executed" \
      --payload "{\"phase\":\"${PHASE_NUMBER}\",\"orphans\":\"${ORPHANS}\"}" >/dev/null 2>&1 || true
    echo "   These specs may be stale from prior runs. Clean ${GENERATED_TESTS_DIR}/ or regenerate." >&2
  fi
fi
```

```bash
git commit -m "fix(test): Batch 21 Task 4 — post-run orphan spec detection

After playwright finishes, parse playwright-results.json suites[].specs[].
Compute set diff vs CODEGEN-MANIFEST.json paths. Orphan specs (executed
but not in manifest) emit test.orphan_spec_executed event with file list.

Advisory at v4.23.0 (WARN). Will flip to BLOCK in v4.24+ after
telemetry — gives users time to clean stale specs.

Tests: tests/test_batch21_orphan_spec_detection.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Release v4.23.0

Bump VERSION 4.22.1 → 4.23.0. CHANGELOG entry. Tag v4.23.0. Push. Re-sync ~/.vgflow. Codex mirror verify; regen if drift.

End of Batch 21 plan. Estimated 2-3 hours.
