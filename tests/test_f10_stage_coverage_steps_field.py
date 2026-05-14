"""tests/test_f10_stage_coverage_steps_field.py — F10 Batch 27

Codex audit Finding F10 (CRITICAL): verify-spec-stage-coverage.py (Batch 23)
read field `stages[]` but generate-lifecycle-specs.py emits `steps[]`. Each
step dict has both `name` and `stage` fields. Validator's `stages.get` returned
`[]` → no stages required → shallow specs PASSED.

This test reproduces the canonical LIFECYCLE-SPECS.json shape and verifies
the validator catches shallow spec body.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-spec-stage-coverage.py"


def test_validator_reads_steps_field_not_stages(tmp_path):
    """Reproduce canonical LIFECYCLE-SPECS.json shape (steps[].stage)
    and confirm shallow spec body fails validation."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    # Canonical lifecycle shape from generate-lifecycle-specs.py:693+
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "phase": "07",
        "goals": {
            "G-01": {
                "actors": [{"role": "user"}],
                "fixture_dag": [],
                "preconditions": [],
                "steps": [
                    {"name": "read_before", "stage": "read_before", "actor": "user", "action": "..."},
                    {"name": "create", "stage": "create", "actor": "user", "action": "..."},
                    {"name": "read_after_create", "stage": "read_after_create", "actor": "user", "action": "..."},
                ],
            }
        }
    }), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps({
        "playwright_specs": [
            {"path": "tests/e2e/lifecycle/G-01.create.spec.ts", "goal_id": "G-01"}
        ]
    }), encoding="utf-8")
    # Shallow spec — modal open only, no fill/click/submit
    spec_dir = phase_dir.parent.parent.parent / "tests" / "e2e" / "lifecycle"
    spec_dir.mkdir(parents=True)
    (spec_dir / "G-01.create.spec.ts").write_text("""
import { test, expect } from '@playwright/test';
test('shallow', async ({ page }) => {
  await page.click('button:has-text("Add")');
  await expect(page.getByRole('dialog')).toBeVisible();
});
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(phase_dir.parent.parent.parent)],
        capture_output=True, text=True,
    )
    # F10 fix: validator must now read steps[].stage and detect missing
    # create/read_after_create patterns in shallow spec → exit 1
    assert r.returncode != 0, (
        f"F10 FIX VERIFY: validator MUST detect shallow spec when LIFECYCLE "
        f"emits steps[] (NOT stages[]). rc={r.returncode}, "
        f"out={(r.stdout + r.stderr)[:400]}"
    )
    combined = r.stdout + r.stderr
    assert "G-01" in combined and ("create" in combined.lower() or "stage" in combined.lower() or "fill" in combined.lower()), (
        f"failure must name G-01 + missing stage info. Got: {combined[:400]}"
    )


def test_validator_passes_legacy_stages_field(tmp_path):
    """Legacy phases may use stages[]; validator should still work."""
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "phase": "07",
        "goals": {
            "G-02": {
                "stages": [{"name": "create"}]  # legacy shape
            }
        }
    }), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps({
        "playwright_specs": [
            {"path": "tests/e2e/lifecycle/G-02.create.spec.ts", "goal_id": "G-02"}
        ]
    }), encoding="utf-8")
    spec_dir = phase_dir.parent.parent.parent / "tests" / "e2e" / "lifecycle"
    spec_dir.mkdir(parents=True)
    (spec_dir / "G-02.create.spec.ts").write_text(
        "import { test } from '@playwright/test';\n"
        "test('shallow', async ({ page }) => { await page.click('btn'); });\n",
        encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(phase_dir.parent.parent.parent)],
        capture_output=True, text=True,
    )
    # Legacy stages[] format with shallow spec — should still detect missing create patterns
    assert r.returncode != 0, "Legacy stages[] format should still trigger detection"
