"""B111 v4.71.1 — role-swap multi-actor replay coverage.

Pre-B111 codegen ran whole spec as the FIRST actor; role-B-only branches
(admin approval, viewer 403, conditional visibility) never executed →
UAT phase caught the RBAC bugs. B111 generator emits
`role_swap_assertion` metadata for multi-actor goal mutation/interaction
stages. Codegen reads metadata + emits browser.newContext + loginAs(actor)
OR logout+login swap. Validator enforces.
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
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-role-swap-coverage.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def test_b111_single_actor_no_swap(lc) -> None:
    """1 actor → no role-swap needed."""
    actors = [{"id": "admin", "role": "admin", "session": "admin_s"}]
    out = lc._build_role_swap_assertion("create", {}, "admin", actors)
    assert out is None


def test_b111_multi_actor_create_gets_swap(lc) -> None:
    actors = [
        {"id": "user", "role": "user", "session": "user_s"},
        {"id": "approver", "role": "approver", "session": "approver_s"},
    ]
    out = lc._build_role_swap_assertion("create", {}, "user", actors)
    assert out is not None
    assert out["kind"] == "role_swap"
    assert out["active_actor"] == "user"
    assert "approver" in out["actors_in_workflow"]


def test_b111_read_before_stage_no_swap(lc) -> None:
    """`read_before` is fixture-setup level — no swap needed."""
    actors = [{"id": "a"}, {"id": "b"}]
    out = lc._build_role_swap_assertion("read_before", {}, "a", actors)
    assert out is None


def test_b111_step_emits_role_swap_metadata(lc) -> None:
    goal = {
        "id": "G-001",
        "title": "Approve topup",
        "body": "actor_workflow:\n  create: user\n  update: approver\n",
        "mutation_evidence": "Approver clicks approve",
    }
    actors = [
        {"id": "user", "role": "user", "session": "user_s"},
        {"id": "approver", "role": "approver", "session": "approver_s"},
    ]
    step = lc._step("update", goal, "approver", actors=actors)
    assert "role_swap_assertion" in step
    assert step["role_swap_assertion"]["active_actor"] == "approver"
    assert goal["_b111_role_swap_count"] == 1


def test_b111_summary_role_swap_audit(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "phase"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: Approver approves topup created by user\n\n"
        "goal_type: multi-actor\n"
        "actors: user, approver\n"
        "Mutation evidence: user creates, approver approves and is redirected\n"
        "Persistence check: row appears in approved list\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir)
    audit = payload["summary"]["role_swap_coverage_audit"]
    # Multi-actor goal → at least update + create + delete stages emit swap
    assert audit["role_swap_assertion_total"] >= 1
    assert audit["multi_actor_goals_with_swap"] == 1


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


def test_b111_validator_block_no_swap_mechanism(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "update",
                     "role_swap_assertion": {
                         "kind": "role_swap",
                         "active_actor": "approver",
                         "actors_in_workflow": ["user", "approver"],
                     }},
                ]
            }
        }
    }
    spec = """
test('G-001 approve', async ({ page }) => {
  await page.goto('/admin/topups');
  await page.getByRole('button', { name: 'Approve' }).click();
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("no role-swap mechanism" in f for f in finds)


def test_b111_validator_pass_with_loginAs(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "update",
                     "role_swap_assertion": {
                         "active_actor": "approver",
                         "actors_in_workflow": ["user", "approver"],
                     }},
                ]
            }
        }
    }
    spec = """
import { loginAs } from './utils/auth';
test('G-001', async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await loginAs(page, 'approver');
  await page.goto('/admin/topups');
  await loginAs(page, 'user');
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS", json.dumps(out, indent=2)


def test_b111_validator_block_missing_actor(tmp_path: Path) -> None:
    """Spec calls loginAs('user') but not approver → missing-actor finding."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "update",
                     "role_swap_assertion": {
                         "active_actor": "approver",
                         "actors_in_workflow": ["user", "approver"],
                     }},
                ]
            }
        }
    }
    spec = """
import { loginAs } from './utils';
test('G-001', async ({ page }) => {
  await loginAs(page, 'user');
  await page.goto('/topups');
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase, "--severity", "block")
    out = json.loads(proc.stdout)
    finds = out["audits"][0]["findings"]
    assert any("missing:" in f and "approver" in f for f in finds)


def test_b111_validator_logout_login_acceptable(tmp_path: Path) -> None:
    """Single-context logout→login pattern is acceptable swap."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"stage": "update",
                     "role_swap_assertion": {
                         "active_actor": "approver",
                         "actors_in_workflow": ["user", "approver"],
                     }},
                ]
            }
        }
    }
    spec = """
test('G-001', async ({ page }) => {
  await page.goto('/login');
  await page.fill('input[name=email]', process.env.USER_EMAIL);
  await page.click('button[type=submit]');
  await page.click('[data-testid=logout]');
  await page.goto('/login');
  await page.fill('input[name=email]', process.env.APPROVER_EMAIL);
  await page.click('button[type=submit]');
});
"""
    phase = _seed(tmp_path, lifecycle, spec)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    # No loginAs() so missing-actor check skipped; logout+login present
    # so mechanism satisfied → PASS
    assert out["status"] == "PASS", json.dumps(out, indent=2)


def test_b111_validator_skips_single_actor_goals(tmp_path: Path) -> None:
    lifecycle = {"goals": {"G-002": {"steps": [{"stage": "create"}]}}}
    phase = _seed(tmp_path, lifecycle)
    proc = _run(phase)
    out = json.loads(proc.stdout)
    assert out["multi_actor_goals"] == 0


# ---------------------------------------------------------------------------
# Codegen + registry + mirror
# ---------------------------------------------------------------------------

def test_b111_codegen_skill_has_directive() -> None:
    body = (REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md").read_text(encoding="utf-8")
    assert "B111" in body
    assert "role_swap_assertion" in body
    assert "loginAs" in body


def test_b111_registry_entry() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")
    assert "id: role-swap-coverage" in body
    assert "added_in: v4.71.1" in body


def test_b111_lifecycle_mirror() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b


def test_b111_validator_mirror() -> None:
    a = VALIDATOR.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-role-swap-coverage.py").read_bytes()
    assert a == b
