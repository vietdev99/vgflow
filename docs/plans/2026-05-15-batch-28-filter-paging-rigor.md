# Batch 28 — Filter/Paging validator wired (F14 root cause) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** User dogfood (PrintwayV3): "test-specs khá nghiêm trọng, không gen đủ các test specs về filter, paging". Audit confirms F14 is root cause — D-16 14-filter/18-paging rigor pack exists but never enforced.

- **F14 (CRITICAL):** `scripts/validators/verify-filter-test-coverage.py` exists with full D-16 matrix logic (14 filter + 18 paging cases per control) but is NEVER bash-invoked. Only mentioned in `commands/vg/_shared/test/codegen/delegation.md:216` and `agents/vg-test-codegen/SKILL.md:147` as prose ("Validate with..."). No exit-on-fail gate. Codegen subagent receives prose instruction "render rigor pack via matrix module" but no validator catches incomplete rendering. Filter/paging rigor pack is unenforced.

**Scope deferrals (separate batches):**
- F13 (enrich-test-goals.py auto-detect filters from scan): scan-*.json schema doesn't currently emit `filters[]` (only forms/tables/tabs per `skills/vg-haiku-scanner/SKILL.md:343-404`). Adding scanner-side filter widget detection requires SKILL.md prompt update + downstream parser — defer to Batch 29.
- F15 (codegen-auto-goals.py spec_kind tag): nice-to-have, doesn't block dogfood. Defer.

**Working directory:** `main`. Commit+push direct.

---

## Conventions

- Caveman commits (single Co-Authored-By trailer per commit)
- Mirror byte-identical `commands/` → `.claude/commands/`, `scripts/` → `.claude/scripts/`, `agents/` → `.claude/agents/`
- Test sweep: `python -m pytest tests/ -q --tb=short -k "batch_28 or filter_test_coverage or enrich_filter"`
- Global paths pattern

---

## ~~Task 1: F13 — DEFERRED to Batch 29~~

(F13 requires scanner schema change. Defer.)

## Task 1 (was Task 2): F14 — wire verify-filter-test-coverage.py bash invoke

(See Task "F14" below — this is now the primary task.)

---

## ~~OLD Task 1: F13~~ (kept for Batch 29 reference)

**Files:**
- Modify: `scripts/enrich-test-goals.py` (`classify_elements` + new `_emit_filter_stubs` helper)
- Mirror to `.claude/scripts/enrich-test-goals.py`
- Test: `tests/test_batch28_enrich_filter_stubs.py`

**Step 1: Failing test**

```python
"""tests/test_batch28_enrich_filter_stubs.py — F13 filter auto-emit."""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENRICH = REPO / "scripts" / "enrich-test-goals.py"


def _load():
    spec = importlib.util.spec_from_file_location("enrich", ENRICH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scan_select_emits_filter_stub():
    """Scan with a <select>/<combobox> element near a table → emit G-AUTO-*-filter-* stub."""
    mod = _load()
    scan = {
        "view": "/admin/orders",
        "results": [],
        "forms": [],
        "tables": [{"row_count": 10, "actions_per_row": []}],
        "tabs": [],
        "filters": [
            {"name": "Status", "kind": "select", "ref": "f-status",
             "options": ["all", "pending", "shipped"]},
            {"name": "Customer", "kind": "text", "ref": "f-customer"},
        ],
    }
    stubs = mod.classify_elements("/admin/orders", scan, {}, [])
    filter_ids = [s["id"] for s in stubs if "-filter-" in s["id"]]
    assert "G-AUTO-admin-orders-filter-status" in filter_ids, (
        f"F13: scan.filters[name=Status] must yield filter stub. Got: {filter_ids}"
    )
    assert "G-AUTO-admin-orders-filter-customer" in filter_ids


def test_filter_stub_has_rigor_marker():
    """Filter stub frontmatter must include interactive_controls.filters[] declaration
    so /vg:test codegen knows to invoke filter-test-matrix.mjs rigor pack."""
    mod = _load()
    scan = {
        "view": "/orders",
        "results": [],
        "forms": [],
        "tables": [{"row_count": 5}],
        "filters": [{"name": "Status", "kind": "select", "options": ["a", "b"]}],
    }
    stubs = mod.classify_elements("/orders", scan, {}, [])
    fs = next(s for s in stubs if "-filter-status" in s["id"])
    # Stub must declare interactive_controls so verify-filter-test-coverage finds it
    assert "interactive_controls" in fs, (
        "F13: filter stub must carry interactive_controls.filters[] so codegen "
        "knows to run rigor pack (14 cases per filter)"
    )
    ic = fs["interactive_controls"]
    assert "filters" in ic and isinstance(ic["filters"], list)
    assert any(f.get("name") == "Status" for f in ic["filters"])


def test_paging_stub_has_rigor_marker():
    """Existing paging stub must also carry interactive_controls.pagination=true."""
    mod = _load()
    scan = {
        "view": "/orders",
        "results": [],
        "forms": [],
        "tables": [{"row_count": 50}],
    }
    stubs = mod.classify_elements("/orders", scan, {}, [])
    ps = next(s for s in stubs if "-table-paging" in s["id"])
    assert "interactive_controls" in ps, (
        "F13: paging stub must declare interactive_controls.pagination so "
        "downstream verify-filter-test-coverage finds it (18-case rigor pack)"
    )
    assert ps["interactive_controls"].get("pagination") is True


def test_declared_filter_skipped_via_declared_set():
    """If blueprint already declared filter:Status, don't emit duplicate auto-stub."""
    mod = _load()
    scan = {
        "view": "/orders",
        "results": [], "forms": [], "tables": [{"row_count": 5}],
        "filters": [{"name": "Status", "kind": "select"}],
    }
    declared = ["filter:Status"]
    stubs = mod.classify_elements("/orders", scan, {}, declared)
    assert not any("-filter-status" in s["id"] for s in stubs), (
        "F13: declared filters in TEST-GOALS.md must dedupe — no G-AUTO-*-filter-* "
        "for same name"
    )
```

**Step 2: Implementation**

In `scripts/enrich-test-goals.py`, modify `classify_elements`. After the existing `tabs` loop, add filter-classification block. Also patch existing paging stub to include `interactive_controls.pagination`. Code insert:

```python
    # F13 Batch 28: auto-emit filter rigor-pack stubs from scan-detected widgets.
    # Scan output may include `filters` array (haiku-scanner T6.x) with
    # {name, kind, options?, ref?}. Each becomes a G-AUTO-*-filter-* goal with
    # interactive_controls.filters[] declaration so /vg:test codegen's
    # filter-test-matrix.mjs renders the 14-case rigor pack and
    # verify-filter-test-coverage.py finds it.
    for fw in scan.get("filters") or []:
        if not isinstance(fw, dict):
            continue
        fname = (fw.get("name") or "").strip()
        if not fname:
            continue
        fkey = name_slug(fname)
        # Dedup against blueprint-declared filters (from TEST-GOALS.md frontmatter).
        if f"filter:{fname}" in declared_set:
            continue
        stubs.append({
            "id": f"G-AUTO-{vslug}-filter-{fkey}",
            "title": f"Filter '{fname}' on {view} — D-16 rigor pack (cardinality + boundary + URL sync + edge)",
            "priority": "important",
            "surface": "ui",
            "source": "review.runtime_discovery",
            "evidence": {
                "view": view,
                "filter_name": fname,
                "filter_kind": fw.get("kind"),
                "filter_ref": fw.get("ref"),
                "option_count": len(fw.get("options") or []),
            },
            "interactive_controls": {
                "filters": [{
                    "name": fname,
                    "kind": fw.get("kind") or "text",
                    "options": fw.get("options") or [],
                }],
                "url_sync": True,
            },
            "trigger": f"Apply filter '{fname}' on {view}",
            "main_steps": [
                {"S1": f"User on {view} as authenticated role"},
                {"S2": f"Open filter '{fname}' control"},
                {"S3": "Select non-default value → list updates"},
                {"S4": "URL reflects filter param; refresh persists state"},
                {"S5": "Clear filter → list returns to default; URL param removed"},
            ],
            "alternate_flows": [
                {"name": "empty_result", "trigger": "filter to value with 0 matches",
                 "expected": "empty state shown, no errors"},
                {"name": "filter_sort_pagination",
                 "trigger": "apply filter while paginated/sorted",
                 "expected": "page resets to 1, sort preserved"},
                {"name": "xss_sanitize", "trigger": "filter value contains <script>",
                 "expected": "sanitized, no script exec, no API error"},
            ],
        })

    # F13 Batch 28: patch existing paging stub at table-iteration above by
    # backfilling interactive_controls.pagination=true so codegen routes
    # through rigor pack instead of single-case URL persist test.
    for s in stubs:
        if s["id"].endswith("-table-paging") and "interactive_controls" not in s:
            s["interactive_controls"] = {"pagination": True, "url_sync": True}
```

Also update `render_markdown` so frontmatter emits `interactive_controls:` block:

```python
        if stub.get("interactive_controls"):
            lines.append("interactive_controls:")
            ic = stub["interactive_controls"]
            if ic.get("filters"):
                lines.append("  filters:")
                for f in ic["filters"]:
                    lines.append(f"    - name: \"{f.get('name','')}\"")
                    if f.get("kind"):
                        lines.append(f"      kind: \"{f['kind']}\"")
                    if f.get("options"):
                        lines.append(f"      options: {json.dumps(f['options'])}")
            if ic.get("pagination"):
                lines.append("  pagination: true")
            if ic.get("url_sync"):
                lines.append("  url_sync: true")
```

**Step 3: Mirror to `.claude/scripts/enrich-test-goals.py`. Commit:**

```bash
git add scripts/enrich-test-goals.py .claude/scripts/enrich-test-goals.py tests/test_batch28_enrich_filter_stubs.py
git commit -m "fix(test-spec): F13 Batch 28 — enrich-test-goals auto-emits filter rigor stubs (CRITICAL)

User dogfood PrintwayV3: 'test-specs khá nghiêm trọng, không gen đủ
các test specs về filter, paging'. Audit confirms scripts/enrich-test-goals.py
classify_elements only emitted 1 paging stub per table (line 275-294)
and NO filter stubs — scan.filters[] data ignored.

Fix: add filter-widget classification loop. Each scan.filters[] entry
(name, kind, options) yields G-AUTO-{view}-filter-{slug} stub with
interactive_controls.filters[] frontmatter so /vg:test codegen's
filter-test-matrix.mjs renders D-16 14-case rigor pack and downstream
verify-filter-test-coverage.py finds the control.

Also backfill existing G-AUTO-*-table-paging with
interactive_controls.pagination=true so paging goals get 18-case rigor
pack instead of single URL-persist test.

Dedup vs TEST-GOALS.md declared filters (declared_set 'filter:Name')
preserved — no double-emit.

Tests: tests/test_batch28_enrich_filter_stubs.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push
```

---

## Task 2: F14 — wire verify-filter-test-coverage.py bash invoke (HARD GATE)

**Files:**
- Modify: `commands/vg/_shared/test/codegen/overview.md` (add bash invoke after codegen-auto-goals)
- Mirror to `.claude/commands/...`
- Test: `tests/test_batch28_filter_validator_wired.py`

**Step 1: Failing test**

```python
"""tests/test_batch28_filter_validator_wired.py — F14 bash invoke gate."""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODEGEN_OVERVIEW = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "overview.md"
CODEGEN_DEL = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


def test_overview_invokes_filter_coverage_validator():
    """codegen/overview.md must bash-invoke verify-filter-test-coverage.py
    (not just mention in prose)."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8") if CODEGEN_OVERVIEW.exists() else ""
    # If overview.md doesn't exist, fallback to delegation.md
    if not body or "verify-filter-test-coverage" not in body:
        body = CODEGEN_DEL.read_text(encoding="utf-8")

    # Must have an actual bash invocation pattern, NOT just "Validate with"
    has_bash_invoke = (
        "verify-filter-test-coverage.py --phase" in body
        and any(marker in body for marker in [
            "${PYTHON_BIN:-python3}",
            "python3 ",
            'FILTER_RC=$?',
            "if [ $FILTER_RC",
        ])
    )
    assert has_bash_invoke, (
        "F14 Batch 28: codegen overview/delegation must actually bash-invoke "
        "verify-filter-test-coverage.py with rc capture. Currently only prose: "
        "'Validate with verify-filter-test-coverage.py --phase ${PHASE_NUMBER}'."
    )


def test_filter_validator_exit_on_fail_or_block_emit():
    """Validator non-zero rc must either exit-on-fail OR emit
    test.filter_coverage_failed event so step-status-ledger records FAIL."""
    body = CODEGEN_OVERVIEW.read_text(encoding="utf-8") if CODEGEN_OVERVIEW.exists() else ""
    if not body or "verify-filter-test-coverage" not in body:
        body = CODEGEN_DEL.read_text(encoding="utf-8")
    assert (
        "test.filter_coverage_failed" in body
        or "FILTER_COVERAGE_STATUS=\"FAIL\"" in body
        or "FILTER_COVERAGE_STATUS=FAIL" in body
    ), (
        "F14: filter validator FAIL must emit event or set status FAIL "
        "(currently silent — rigor pack shortfall passes through)"
    )
```

**Step 2: Implementation**

Inspect `commands/vg/_shared/test/codegen/overview.md` to find the right insertion point (after `codegen-auto-goals.py` invoke, before next step). Add this block:

```bash
# F14 Batch 28: wire D-16 filter/paging rigor pack validator. Previously
# only prose suggestion at delegation.md:216 — no bash invoke. 14-case
# filter + 18-case paging matrix went unenforced. User PrintwayV3 dogfood:
# "filter gần như không được tạo, không được test".
set +e
"${PYTHON_BIN:-python3}" \
  "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-filter-test-coverage.py" \
  --phase "${PHASE_NUMBER}" \
  --tests-glob "${GENERATED_TESTS_DIR#./}/**/*.spec.ts" \
  > "${VG_TMP}/filter-coverage.json" 2> "${VG_TMP}/filter-coverage.err"
FILTER_RC=$?
set -e

if [ "$FILTER_RC" -ne 0 ]; then
  FILTER_COVERAGE_STATUS="FAIL"
  FILTER_COVERAGE_REASON=$(cat "${VG_TMP}/filter-coverage.json" 2>/dev/null \
    | "${PYTHON_BIN:-python3}" -c "import json,sys; d=json.load(sys.stdin); print('; '.join(e['message'] for e in d.get('evidence',[])[:3]))" 2>/dev/null \
    || echo "validator rc=${FILTER_RC}")
  echo "⛔ F14: filter/paging rigor pack shortfall — ${FILTER_COVERAGE_REASON}" >&2
  "${PYTHON_BIN:-python3}" \
    "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
    "test.filter_coverage_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"rc\":${FILTER_RC},\"reason\":$(printf '%s' "$FILTER_COVERAGE_REASON" | "${PYTHON_BIN:-python3}" -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}" \
    >/dev/null 2>&1 || true
  # Honor --allow-filter-shortfall for legacy phases that haven't migrated
  # to interactive_controls frontmatter
  if [[ "${ARGUMENTS:-}" =~ --allow-filter-shortfall ]]; then
    echo "⚠ --allow-filter-shortfall — proceeding past D-16 matrix shortfall (legacy phase)" >&2
  else
    exit 1
  fi
else
  FILTER_COVERAGE_STATUS="PASS"
fi
```

**Step 3: Mirror + commit:**

```bash
git add commands/vg/_shared/test/codegen/overview.md .claude/commands/vg/_shared/test/codegen/overview.md tests/test_batch28_filter_validator_wired.py
git commit -m "fix(test): F14 Batch 28 — wire verify-filter-test-coverage.py bash invoke (CRITICAL)

User dogfood PrintwayV3: 'filter gần như không được tạo, không được test'.
Audit: scripts/validators/verify-filter-test-coverage.py exists with full
D-16 matrix logic (14 filter + 18 paging cases per control) but is NEVER
bash-invoked. Only mentioned at delegation.md:216 + agents SKILL prose
('Validate with...'). Rigor pack was dead code.

Fix: codegen/overview.md bash block after codegen-auto-goals.py invokes
validator with rc capture. On non-zero:
- FILTER_COVERAGE_STATUS=FAIL
- Emit test.filter_coverage_failed event with reason
- exit 1 unless --allow-filter-shortfall arg passed (legacy escape)

Test count shortfall now blocks /vg:test progression instead of passing
through silently. Downstream verdict computation sees real status.

Tests: tests/test_batch28_filter_validator_wired.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push
```

---

## Task 3: F15 — codegen-auto-goals.py tags spec_kind in frontmatter

**Files:**
- Modify: `scripts/codegen-auto-goals.py` (verify exists; add `spec_kind` field)
- Mirror to `.claude/scripts/`
- Test: `tests/test_batch28_spec_kind_tag.py`

**Step 1: Verify `codegen-auto-goals.py` exists. If not, create stub or skip — defer to Batch 29.**

```bash
test -f scripts/codegen-auto-goals.py && echo "exists" || echo "DEFER"
```

If exists → add `spec_kind: filter|paging|action|mutation|form` to generated `.spec.ts` header comment. If not exists → defer F15 to Batch 29 (separate concern from F13+F14 critical).

**Failing test only if file exists:**

```python
"""tests/test_batch28_spec_kind_tag.py — F15 spec_kind tagging."""
from __future__ import annotations
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "codegen-auto-goals.py"

@pytest.mark.skipif(not GEN.exists(), reason="codegen-auto-goals.py absent — deferred")
def test_spec_kind_for_filter_goal():
    body = GEN.read_text(encoding="utf-8")
    assert "spec_kind" in body, (
        "F15 Batch 28: codegen-auto-goals.py must tag generated specs with "
        "spec_kind: filter|paging|... so verify-filter-test-coverage can "
        "count by kind without re-parsing block names"
    )
```

Commit only if non-deferred:

```bash
git commit -m "feat(test): F15 Batch 28 — codegen-auto-goals tags spec_kind

Generated .spec.ts files now carry spec_kind: filter|paging|action|mutation|form
in header comment + frontmatter. Downstream verify-filter-test-coverage
counts by kind without slug heuristics. Reduces false-positive shortfalls
when filter slug overlaps action slug.

Tests: tests/test_batch28_spec_kind_tag.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Release v4.32.0

```bash
# Bump VERSION 4.31.2 → 4.32.0
# Update CHANGELOG with v4.32.0 section listing F13+F14+F15 hardenings
# Tag v4.32.0, push tags
# Re-sync ~/.vgflow via vg:update
# Verify codex mirror parity (run scripts/regen-codex-skills.sh if drift)
```

End of Batch 28. Estimated 2-3 hours.
