# Batch 23 — Spec stage coverage validator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect shallow `.spec.ts` files that ignore LIFECYCLE-SPECS declared stages. Real bug (user dogfood): test opens modal then ends — never fills form, never submits, never verifies persistence.

**Root cause:** Codegen subagent reads RCRURDR + 4-layer-verify instruction from `delegation.md` (prose). Generates `.spec.ts`. No validator opens spec file to check body covers declared stages. F1 CODEGEN-MANIFEST gate only checks spec COUNT, not CONTENT.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "spec_stage_coverage or spec_body or shallow_spec or batch_23"`
- Single Co-Authored-By trailer per commit
- Global paths pattern (`${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}`)

---

## Task 1: verify-spec-stage-coverage.py validator

**Files:**
- Create: `scripts/validators/verify-spec-stage-coverage.py`
- Mirror
- Test: `tests/test_batch23_spec_stage_coverage.py`

**Step 1: Failing test**

```python
"""tests/test_batch23_spec_stage_coverage.py — Batch 23 spec stage coverage."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-spec-stage-coverage.py"


def test_validator_exists():
    assert VAL.is_file(), "Batch 23: scripts/validators/verify-spec-stage-coverage.py must ship"


def test_shallow_spec_fails(tmp_path):
    """LIFECYCLE-SPECS declares G-01 stages=[read_before, create, read_after_create].
    Spec only opens modal. Validator MUST fail."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "phase": "07",
        "goals": {
            "G-01": {"stages": [
                {"name": "read_before"},
                {"name": "create"},
                {"name": "read_after_create"},
            ]}
        }
    }), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps({
        "playwright_specs": [
            {"path": "tests/e2e/lifecycle/G-01.create.spec.ts", "goal_id": "G-01"}
        ]
    }), encoding="utf-8")
    # Generate shallow spec — opens modal, asserts visible, end.
    spec_dir = phase_dir.parent.parent.parent / "tests/e2e/lifecycle"
    spec_dir.mkdir(parents=True)
    (spec_dir / "G-01.create.spec.ts").write_text("""
import { test, expect } from '@playwright/test';
test('G-01: open create modal', async ({ page }) => {
  await page.goto('/users');
  await page.click('button:has-text("Add User")');
  await expect(page.getByRole('dialog')).toBeVisible();
});
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(phase_dir.parent.parent.parent)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"Batch 23: shallow spec (modal-open only, no fill/click/submit) MUST fail. "
        f"rc={r.returncode}, out={(r.stdout + r.stderr)[:400]}"
    )
    combined = r.stdout + r.stderr
    assert "G-01" in combined and ("create" in combined.lower() or "fill" in combined.lower() or "stage" in combined.lower()), (
        f"failure must reference G-01 + missing stage. Got: {combined[:300]}"
    )


def test_full_spec_passes(tmp_path):
    """Spec covering all RCRURDR stages must pass."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "phase": "07",
        "goals": {
            "G-02": {"stages": [
                {"name": "read_before"},
                {"name": "create"},
                {"name": "read_after_create"},
            ]}
        }
    }), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps({
        "playwright_specs": [
            {"path": "tests/e2e/lifecycle/G-02.create.spec.ts", "goal_id": "G-02"}
        ]
    }), encoding="utf-8")
    spec_dir = phase_dir.parent.parent.parent / "tests/e2e/lifecycle"
    spec_dir.mkdir(parents=True)
    (spec_dir / "G-02.create.spec.ts").write_text("""
import { test, expect } from '@playwright/test';
test('G-02: create user lifecycle', async ({ page }) => {
  // read_before
  await page.goto('/users');
  await expect(page.getByText('No users yet')).toBeVisible();

  // create
  await page.click('button:has-text("Add User")');
  await page.fill('input[name="email"]', 'new@example.com');
  await page.fill('input[name="name"]', 'New User');
  const res = page.waitForResponse(r => r.url().includes('/api/users') && r.request().method() === 'POST');
  await page.click('button[type="submit"]');
  const response = await res;
  expect(response.status()).toBeLessThan(400);
  await expect(page.getByRole('status')).toContainText('User created');

  // read_after_create
  await page.reload();
  await expect(page.getByText('new@example.com')).toBeVisible();
});
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(phase_dir.parent.parent.parent)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"Batch 23: full RCRURDR spec must pass. rc={r.returncode}, "
        f"out={(r.stdout + r.stderr)[:400]}"
    )


def test_validator_emits_event_on_shallow(tmp_path):
    """Shallow spec detection should emit test_spec.spec_body_shallow event."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "phase": "07",
        "goals": {"G-01": {"stages": [{"name": "create"}]}}
    }), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps({
        "playwright_specs": [{"path": "tests/e2e/lifecycle/G-01.create.spec.ts", "goal_id": "G-01"}]
    }), encoding="utf-8")
    spec_dir = phase_dir.parent.parent.parent / "tests/e2e/lifecycle"
    spec_dir.mkdir(parents=True)
    (spec_dir / "G-01.create.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('G-01', async ({ page }) => { await page.click('btn'); });\n",
        encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(phase_dir.parent.parent.parent),
         "--json"],
        capture_output=True, text=True,
    )
    # JSON mode emits structured output (not just exit code) — must list goal + missing patterns
    if r.stdout.strip():
        try:
            report = json.loads(r.stdout)
            assert "shallow_specs" in report or "missing_patterns" in report or "failures" in report
        except json.JSONDecodeError:
            pass  # accept text output too
```

**Step 2: Run** → 4 fail.

**Step 3: Implement**

Create `scripts/validators/verify-spec-stage-coverage.py`:

```python
#!/usr/bin/env python3
"""verify-spec-stage-coverage.py — Batch 23

Opens each spec file listed in CODEGEN-MANIFEST.json, checks body contains
stage-specific patterns matching LIFECYCLE-SPECS.json declared stages per
goal.

Stages and required regex patterns (per RCRURDR + 4-layer verify):

  read_before:       page.goto OR page.reload (navigation before mutation)
  create:            page.fill (form input) + page.click (submit) + waitForResponse
  read_after_create: page.reload OR navigate + expect(...).toBeVisible (new entity)
  update:            page.fill (second time) + page.click (save)
  read_after_update: page.reload + expect(persisted_value)
  delete:            page.click (delete) + waitForResponse(DELETE method)
  read_after_delete: expect(...).not.toBeVisible (entity gone)

Plus 4-layer verify (for every mutation stage):
  L1 toast:        expect(...).toContainText(...)
  L2 API 2xx:      waitForResponse + status < 400
  L3 persistence:  page.reload + assertion
  L4 console:      window.__consoleErrors check (advisory, not blocking)

Missing required pattern per declared stage → BLOCK with file:line context.

Exit codes:
  0 — all specs cover declared stages
  1 — at least one shallow spec found
  2 — config error (missing files, malformed JSON)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Stage → list of required regex patterns. Each pattern (compiled, IGNORECASE)
# is checked against the spec file body. Missing pattern = stage not covered.
STAGE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "read_before": [
        ("navigation", r"page\.goto\("),
    ],
    "create": [
        ("form_fill", r"page\.fill\("),
        ("submit_click", r"page\.click\(['\"](?:button|.*type=['\"]submit)|getByRole\(['\"]button"),
        ("api_response", r"waitForResponse\("),
    ],
    "read_after_create": [
        ("post_create_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "update": [
        ("update_fill", r"page\.fill\("),
        ("update_save", r"page\.click\("),
        ("update_response", r"waitForResponse\("),
    ],
    "read_after_update": [
        ("persist_reload", r"page\.reload\(\)|page\.goto\("),
        ("persist_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "delete": [
        ("delete_click", r"page\.click\("),
        ("delete_response", r"waitForResponse\("),
    ],
    "read_after_delete": [
        ("not_visible", r"not\.toBeVisible\(\)|toBeHidden\(\)|toHaveCount\(0\)"),
    ],
}


def _check_spec(spec_path: Path, required_stages: list[str]) -> dict:
    """Returns dict with stage → list[missing_pattern_names]."""
    if not spec_path.is_file():
        return {"_error": f"spec file not found: {spec_path}"}
    body = spec_path.read_text(encoding="utf-8", errors="replace")
    missing: dict[str, list[str]] = {}
    for stage in required_stages:
        patterns = STAGE_PATTERNS.get(stage, [])
        if not patterns:
            continue
        miss = []
        for name, regex in patterns:
            if not re.search(regex, body, re.IGNORECASE):
                miss.append(name)
        if miss:
            missing[stage] = miss
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path("."),
                    help="Repo root for resolving spec relative paths")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ls_path = args.phase_dir / "LIFECYCLE-SPECS.json"
    cm_path = args.phase_dir / "CODEGEN-MANIFEST.json"
    if not ls_path.is_file():
        print(f"⛔ LIFECYCLE-SPECS.json missing at {ls_path}", file=sys.stderr)
        return 2
    if not cm_path.is_file():
        print(f"⛔ CODEGEN-MANIFEST.json missing at {cm_path}", file=sys.stderr)
        return 2

    try:
        ls = json.loads(ls_path.read_text(encoding="utf-8"))
        cm = json.loads(cm_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ JSON parse error: {e}", file=sys.stderr)
        return 2

    # Map goal_id → list of stage names
    goal_stages: dict[str, list[str]] = {}
    for gid, gdata in ls.get("goals", {}).items():
        stages = gdata.get("stages", [])
        names = [s.get("name", s) if isinstance(s, dict) else s for s in stages]
        goal_stages[gid] = names

    # Map goal_id → spec path
    goal_spec: dict[str, str] = {}
    for s in cm.get("playwright_specs", cm.get("specs", [])):
        if isinstance(s, dict):
            goal_spec[s.get("goal_id", "")] = s.get("path", "")
        # bare string entries have no goal binding — skip

    shallow_findings = []
    for gid, stages in goal_stages.items():
        spec_rel = goal_spec.get(gid)
        if not spec_rel:
            continue  # no spec for this goal (MANUAL/INFRA_PENDING?)
        spec_abs = args.repo_root / spec_rel
        result = _check_spec(spec_abs, stages)
        if "_error" in result:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "error": result["_error"]
            })
            continue
        if result:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "missing_stages": result
            })

    if args.json:
        print(json.dumps({
            "phase_dir": str(args.phase_dir),
            "total_goals": len(goal_stages),
            "shallow_specs": len(shallow_findings),
            "failures": shallow_findings,
        }, indent=2))
    else:
        if shallow_findings:
            print(f"⛔ Batch 23: {len(shallow_findings)} shallow spec(s) detected:", file=sys.stderr)
            for f in shallow_findings:
                print(f"  - {f['goal_id']} ({f['spec']}):", file=sys.stderr)
                if "error" in f:
                    print(f"      ERROR: {f['error']}", file=sys.stderr)
                else:
                    for stage, missing in f["missing_stages"].items():
                        print(f"      stage '{stage}' missing: {', '.join(missing)}", file=sys.stderr)
        else:
            print(f"✓ Batch 23: {len(goal_stages)} goals — all specs cover declared stages")

    return 1 if shallow_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4-6:** pass + mirror + commit.

```bash
git commit -m "feat(test-spec): Batch 23 Task 1 — verify-spec-stage-coverage.py validator

User dogfood bug: 'test bật form modal, bật xong là xong, không hề test
nhập form, save form'. LIFECYCLE-SPECS.json declares full RCRURDR
stages, codegen instruction lists 4-layer verify, but codegen subagent
silently produces shallow .spec.ts. F1 CODEGEN-MANIFEST gate checks
SPEC COUNT not BODY.

New validator opens each spec file listed in manifest, regex-checks
body covers per-stage patterns:
- read_before: page.goto
- create: page.fill + page.click(submit) + waitForResponse
- read_after_create: toBeVisible / toContainText
- update/delete/read_after_*: analogous patterns
Missing pattern per declared stage → exit 1 with file:line context.

JSON mode emits structured failures for telemetry.

Tests: tests/test_batch23_spec_stage_coverage.py (4 tests).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire validator into test-spec post-codegen + test preflight

**Files:**
- Modify: `commands/vg/test-spec.md` (after F1 manifest gate, before run-complete)
- Modify: `commands/vg/_shared/test/preflight.md` (early gate before runtime)
- Mirrors
- Test: `tests/test_batch23_validator_wired.py`

**Step 1: Failing test**

```python
"""tests/test_batch23_validator_wired.py — Batch 23 wiring."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_test_spec_invokes_stage_coverage():
    body = (REPO / "commands/vg/test-spec.md").read_text(encoding="utf-8")
    assert "verify-spec-stage-coverage" in body, (
        "Batch 23: test-spec.md must invoke verify-spec-stage-coverage.py "
        "after codegen (post-F1-gate, pre-run-complete)"
    )


def test_test_preflight_invokes_stage_coverage():
    body = (REPO / "commands/vg/_shared/test/preflight.md").read_text(encoding="utf-8")
    assert "verify-spec-stage-coverage" in body, (
        "Batch 23: test/preflight.md must invoke verify-spec-stage-coverage.py "
        "before playwright runtime"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/test-spec.md` after CODEGEN-MANIFEST gate (post F1) BEFORE run-complete:

```bash
# Batch 23: spec body coverage gate — catch shallow specs.
STAGE_COV_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-spec-stage-coverage.py"
[ -f "$STAGE_COV_VAL" ] || STAGE_COV_VAL="${REPO_ROOT:-.}/scripts/validators/verify-spec-stage-coverage.py"
if [ -f "$STAGE_COV_VAL" ]; then
  if ! "${PYTHON_BIN:-python3}" "$STAGE_COV_VAL" \
       --phase-dir "${PHASE_DIR}" \
       --repo-root "${REPO_ROOT:-.}"; then
    echo "⛔ Batch 23 BLOCK: shallow spec(s) detected — codegen produced specs missing stage coverage" >&2
    "${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
      "test_spec.spec_body_shallow" --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true
    exit 1
  fi
fi
```

Same block in `commands/vg/_shared/test/preflight.md` early step (after lifecycle-specs JSON check) — make test BLOCK before playwright runs shallow specs.

```bash
git commit -m "fix(test-spec+test): Batch 23 Task 2 — wire spec-stage-coverage validator

Two enforcement points:
1. /vg:test-spec post-codegen: after F1 CODEGEN-MANIFEST gate, before
   run-complete. Catches shallow specs at codegen time.
2. /vg:test preflight: early gate before playwright runtime. Catches
   shallow specs from prior codegen runs (defense-in-depth).

Both emit test_spec.spec_body_shallow event on BLOCK.

Tests: tests/test_batch23_validator_wired.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Release v4.26.0

Bump VERSION 4.25.0 → 4.26.0. CHANGELOG entry. Tag v4.26.0. Push. Re-sync ~/.vgflow. Codex mirror verify; regen if drift.

End of Batch 23. Estimated 3 hours.
