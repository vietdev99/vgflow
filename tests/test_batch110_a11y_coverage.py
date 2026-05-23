"""B110 v4.71.0 — a11y axe-core injection.

Closes UAT a11y bug class (missing ARIA, low color contrast, broken
keyboard nav, form-label binding). Generator emits `a11y_assertion`
metadata per render-bearing stage. Codegen emits `new AxeBuilder({page})
.analyze()` + critical+serious violations assertion. Validator
`verify-a11y-coverage.py` blocks when spec lacks axe import / scan /
assertion.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-a11y-coverage.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def test_b110_render_initial_gets_a11y(lc) -> None:
    out = lc._build_a11y_assertion("render_initial", {"title": "x"})
    assert out is not None
    assert out["kind"] == "axe_core_scan"
    assert "critical" in out["block_levels"]
    assert "serious" in out["block_levels"]


def test_b110_create_stage_no_a11y(lc) -> None:
    """Mutation-only stages (create/update/delete) don't render new UI →
    no a11y assertion. They follow up with read_after_* which does."""
    out = lc._build_a11y_assertion("create", {"title": "x"})
    assert out is None


def test_b110_waiver_skips_a11y(lc) -> None:
    out = lc._build_a11y_assertion("render_initial", {"a11y_waiver": "true"})
    assert out is None


def test_b110_read_after_create_has_a11y(lc) -> None:
    out = lc._build_a11y_assertion("read_after_create", {"title": "x"})
    assert out is not None


def test_b110_step_emits_a11y_metadata(lc) -> None:
    goal = {"id": "G-001", "title": "List topups", "body": ""}
    step = lc._step("render_initial", goal, "admin")
    assert "a11y_assertion" in step
    assert goal["_b110_a11y_assertion_count"] == 1


def test_b110_summary_a11y_audit(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "phase"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: List topups\n\ngoal_class: readonly\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir, include_readonly=True)
    audit = payload["summary"]["a11y_coverage_audit"]
    assert audit["a11y_assertion_total"] >= 1
    assert audit["goals_with_a11y_check"] == 1


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def _run(phase_dir: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed(tmp_path: Path, lifecycle: dict, spec_body: str = "") -> Path:
    phase = tmp_path / "phase"
    phase.mkdir()
    (phase / "LIFECYCLE-SPECS.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    if spec_body:
        (phase / "playwright-specs").mkdir()
        (phase / "playwright-specs" / "G-001.spec.ts").write_text(spec_body, encoding="utf-8")
    return phase


def test_b110_validator_block_missing_axe_import(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "render_initial", "stage": "render_initial",
                     "a11y_assertion": {"kind": "axe_core_scan",
                                         "block_levels": ["critical", "serious"]}},
                ]
            }
        }
    }
    spec = """
test('G-001 List topups', async ({ page }) => {
  await page.goto('/topups');
  await expect(page.locator('h1')).toBeVisible();
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("axe-core import" in f for f in finds)


def test_b110_validator_pass_with_full_axe(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "render_initial", "stage": "render_initial",
                     "a11y_assertion": {"kind": "axe_core_scan",
                                         "block_levels": ["critical", "serious"]}},
                ]
            }
        }
    }
    spec = """
import { AxeBuilder } from '@axe-core/playwright';
test('G-001 List topups', async ({ page }) => {
  await page.goto('/topups');
  const results = await new AxeBuilder({ page }).analyze();
  const critical = results.violations.filter(v => v.impact === 'critical');
  expect(critical).toEqual([]);
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS", json.dumps(out, indent=2)


def test_b110_validator_block_missing_assertion(tmp_path: Path) -> None:
    """Has axe import + scan but never asserts on violations."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "render_initial", "stage": "render_initial",
                     "a11y_assertion": {"kind": "axe_core_scan"}},
                ]
            }
        }
    }
    spec = """
import { AxeBuilder } from '@axe-core/playwright';
test('G-001', async ({ page }) => {
  const r = await new AxeBuilder({ page }).analyze();
  console.log(r.violations);  // never asserted!
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("no assertion on violations" in f for f in finds)


def test_b110_validator_skips_goals_without_metadata(tmp_path: Path) -> None:
    lifecycle = {"goals": {"G-002": {"steps": [{"stage": "read_before"}]}}}
    phase = _seed(tmp_path, lifecycle)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["goals_with_a11y"] == 0
    assert out["status"] == "PASS"


def test_b110_validator_warn_severity_zero_exit(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "render_initial",
                     "a11y_assertion": {"kind": "axe_core_scan"}},
                ]
            }
        }
    }
    phase = _seed(tmp_path, lifecycle, "// no axe")
    proc = _run(phase, "--severity", "warn")
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Codegen + registry
# ---------------------------------------------------------------------------

def test_b110_codegen_skill_has_a11y_directive() -> None:
    body = (REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md").read_text(encoding="utf-8")
    assert "B110" in body
    assert "AxeBuilder" in body
    assert "a11y_assertion" in body


def test_b110_registry_entry() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")
    assert "id: a11y-coverage" in body
    idx = body.index("id: a11y-coverage")
    assert "added_in: v4.71.0" in body[idx:idx + 800]


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b110_lifecycle_mirror() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b


def test_b110_validator_mirror() -> None:
    a = VALIDATOR.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-a11y-coverage.py").read_bytes()
    assert a == b


def test_b110_registry_mirror() -> None:
    a = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml").read_bytes()
    assert a == b


def test_b110_codegen_skill_mirror() -> None:
    a = (REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md").read_bytes()
    b = (REPO_ROOT / ".claude" / "agents" / "vg-test-codegen" / "SKILL.md").read_bytes()
    assert a == b
