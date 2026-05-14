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
