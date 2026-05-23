"""B109 v4.71.2 — visual fidelity gate.

Closes UAT design-vs-impl bug class. Pre-B109 design refs declared in
TEST-GOALS but codegen ignored them; specs never compared rendered UI
to baseline. Layout drift, padding crush, color rendering, font load
failure all caught only at UAT step.

Generator emits `visual_assertion` metadata for render-bearing stages
when goal has `design_ref` / `design_refs` / `design` field. Codegen
emits `await expect(page).toHaveScreenshot('<name>.png', { ... })`.
Validator enforces.
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
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-visual-fidelity-coverage.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def test_b109_extract_inline_design_refs(lc) -> None:
    goal = {"body": "## Goal\n\ndesign_refs: [topup-list.png, topup-detail.png]\n"}
    refs = lc._extract_design_refs(goal)
    assert refs == ["topup-list.png", "topup-detail.png"]


def test_b109_extract_single_design_ref(lc) -> None:
    goal = {"body": "design_ref: figma-frame-42\n"}
    refs = lc._extract_design_refs(goal)
    assert refs == ["figma-frame-42"]


def test_b109_extract_no_design_field(lc) -> None:
    assert lc._extract_design_refs({"body": "## Goal\n\nfoo: bar\n"}) == []


def test_b109_render_initial_with_design_ref_gets_visual(lc) -> None:
    goal = {"id": "G-001", "body": "design_ref: topup-list.png\n"}
    out = lc._build_visual_assertion("render_initial", goal)
    assert out is not None
    assert out["kind"] == "playwright_screenshot"
    assert out["max_diff_pixel_ratio"] == 0.02
    assert out["animation_strategy"] == "disable"
    assert out["fullPage"] is True


def test_b109_create_stage_no_visual(lc) -> None:
    """Mutation stages (create/update/delete) — no visual assertion."""
    goal = {"id": "G-001", "body": "design_ref: topup.png\n"}
    out = lc._build_visual_assertion("create", goal)
    assert out is None


def test_b109_no_design_ref_no_visual(lc) -> None:
    out = lc._build_visual_assertion("render_initial", {"body": ""})
    assert out is None


def test_b109_waiver_skips_visual(lc) -> None:
    goal = {
        "body": "design_ref: topup.png\n",
        "visual_fidelity_waiver": "true",
    }
    out = lc._build_visual_assertion("render_initial", goal)
    assert out is None


def test_b109_step_emits_visual_metadata(lc) -> None:
    goal = {
        "id": "G-001",
        "title": "Show topup list",
        "body": "design_refs: [topup-list.png]\n",
    }
    step = lc._step("render_initial", goal, "admin")
    assert "visual_assertion" in step
    assert step["visual_assertion"]["snapshot_name"] == "G-001-render_initial"
    assert goal["_b109_visual_assertion_count"] == 1


def test_b109_summary_visual_audit(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "phase"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: List topups\n\n"
        "goal_class: readonly\n"
        "design_ref: topup-list.png\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir, include_readonly=True)
    audit = payload["summary"]["visual_coverage_audit"]
    assert audit["visual_assertion_total"] >= 1
    assert audit["goals_with_design_ref"] == 1


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


def test_b109_validator_block_no_screenshot(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "render_initial",
                     "visual_assertion": {"kind": "playwright_screenshot",
                                           "snapshot_name": "G-001-render"}},
                ]
            }
        }
    }
    spec = """
test('G-001', async ({ page }) => {
  await page.goto('/topups');
  await expect(page.locator('h1')).toBeVisible();
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("toHaveScreenshot" in f for f in finds)


def test_b109_validator_pass_with_full_screenshot(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "render_initial",
                     "visual_assertion": {"snapshot_name": "G-001-render"}},
                ]
            }
        }
    }
    spec = """
test('G-001', async ({ page }) => {
  await page.goto('/topups');
  await expect(page).toHaveScreenshot('G-001-render.png', {
    maxDiffPixelRatio: 0.02,
    threshold: 0.2,
    animations: 'disabled',
  });
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS", json.dumps(out, indent=2)


def test_b109_validator_missing_threshold(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "render_initial",
                     "visual_assertion": {"snapshot_name": "G-001"}},
                ]
            }
        }
    }
    spec = """
test('G-001', async ({ page }) => {
  await page.goto('/topups');
  await expect(page).toHaveScreenshot('G-001.png');
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("threshold" in f.lower() or "maxDiff" in f for f in finds)


def test_b109_validator_skips_goals_without_metadata(tmp_path: Path) -> None:
    lifecycle = {"goals": {"G-002": {"steps": [{"stage": "render_initial"}]}}}
    phase = _seed(tmp_path, lifecycle)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["goals_with_design_ref"] == 0


def test_b109_validator_warn_severity_zero_exit(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "render_initial",
                     "visual_assertion": {"snapshot_name": "G-001"}},
                ]
            }
        }
    }
    phase = _seed(tmp_path, lifecycle, "// no screenshot")
    proc = _run(phase, "--severity", "warn")
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Codegen + registry + mirror
# ---------------------------------------------------------------------------

def test_b109_codegen_skill_has_directive() -> None:
    body = (REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md").read_text(encoding="utf-8")
    assert "B109" in body
    assert "visual_assertion" in body
    assert "toHaveScreenshot" in body


def test_b109_registry_entry() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")
    assert "id: visual-fidelity-coverage" in body
    assert "added_in: v4.71.2" in body


def test_b109_lifecycle_mirror() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b


def test_b109_validator_mirror() -> None:
    a = VALIDATOR.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-visual-fidelity-coverage.py").read_bytes()
    assert a == b
