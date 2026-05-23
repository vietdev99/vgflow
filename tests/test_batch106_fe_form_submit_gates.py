"""B106 v4.70.0 — UAT bug root-cause + 2 pre-UAT FE form-submit gates.

User report (2026-05-23): after `/vg:build` + `/vg:test` PASS, UAT step
still finds many runtime FE-BE integration bugs — form submit returns red
error banner, success toast doesn't appear, redirect doesn't happen,
dropdown empty. Operator wants harness to catch these before human UAT.

## Root cause (Explore agents A+B+C, Phase 1)

Pipeline NEVER exercises FE form submit against real backend before UAT:
  - build/close: 10+ static validators, B95 FE-BE shape coherence is
    advisory + static only.
  - test/runtime: curl+jq GET endpoints, no POST.
  - test/smoke+flow: ~3 Playwright spot paths, minimal happy path.
  - test/goal-verifier: spec replay BUT read_after_* stages are GET-only.
  - UAT STEP 5: first time a human submits the form.

Top UAT failure classes (~50% catchable):
  1. Form 4xx/422 silently swallowed (no page.on('response') capture)
  2. Success message/toast missing (codegen ignores mutation_evidence keyword)
  3. Redirect-after-submit broken (no waitForNavigation assertion)

## Gates shipped in B106

**Gate 1 — Network response assertion (per mutation stage):**
`scripts/generate-lifecycle-specs.py:_step()` injects `network_assertion`
metadata for create/update/delete stages. Codegen reads metadata and emits
`page.waitForResponse` + status<400 check + 4xx→error-toast assertion.

**Gate 2 — Success-message + navigation assertion:**
Same `_step()` parses `mutation_evidence` + `success_criteria` for
success/redirect/navigate/toast keywords. When matched, injects
`success_assertion` metadata. Codegen emits `waitForURL` OR
`[role=status]` visibility assertion.

**Validator `verify-fe-form-submit-coverage.py`:**
Scans generated Playwright specs. Each mutation goal with `network_assertion`
metadata MUST have `page.waitForResponse` + (status<400 OR error-toast). Each
with `success_assertion` MUST have success-feedback OR navigation assertion.
Severity warn initially; flips to block after dogfood.

Registered phases [test, accept]. Wired into runtime.md STEP 3.5 + gates.md
new step 3d_fe_form_submit_coverage.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-fe-form-submit-coverage.py"
VALIDATOR_MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-fe-form-submit-coverage.py"
LIFECYCLE_MIRROR = REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"
RUNTIME_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "runtime.md"
GATES_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "gates.md"
CODEGEN_SKILL = REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Generator — _extract_success_signals + Gate 1 + Gate 2 injection
# ---------------------------------------------------------------------------

def test_b106_extract_success_signals_finds_redirect(lc) -> None:
    """`redirected to /detail` keyword → has_signal True + nav URL extracted."""
    out = lc._extract_success_signals(
        "After create, user is redirected to /admin/topups/123"
    )
    assert out["has_signal"] is True
    assert out["expect_navigation_to"] == "/admin/topups/123"


def test_b106_extract_success_signals_finds_toast(lc) -> None:
    """`success toast shown` → has_signal True, no nav."""
    out = lc._extract_success_signals(
        "Success toast shown with confirmation message"
    )
    assert out["has_signal"] is True
    assert out["expect_navigation_to"] is None
    assert any(k in {"success", "toast", "confirmation", "message"} for k in out["keywords_matched"])


def test_b106_extract_success_signals_empty_text(lc) -> None:
    out = lc._extract_success_signals("")
    assert out["has_signal"] is False
    assert out["keywords_matched"] == []
    assert out["expect_navigation_to"] is None


def test_b106_extract_success_signals_no_keyword(lc) -> None:
    """Plain prose without success-feedback keywords → no signal."""
    out = lc._extract_success_signals(
        "The endpoint accepts POST and persists row to DB"
    )
    assert out["has_signal"] is False


def test_b106_build_network_assertion_create_stage(lc) -> None:
    endpoint = {"method": "POST", "path": "/api/v1/admin/topups"}
    out = lc._build_network_assertion("create", endpoint)
    assert out is not None
    assert out["kind"] == "response_capture"
    assert out["endpoint_method"] == "POST"
    assert out["assert_status_lt"] == 400
    assert out["on_4xx_5xx_must_render_error_toast"] is True
    assert "[role=alert]" in out["error_toast_selectors"]


def test_b106_build_network_assertion_skips_read_stage(lc) -> None:
    """`read_after_create` is GET — no form submit, no Gate 1."""
    endpoint = {"method": "GET", "path": "/api/v1/admin/topups/{id}"}
    out = lc._build_network_assertion("read_after_create", endpoint)
    assert out is None


def test_b106_build_network_assertion_skips_when_no_endpoint(lc) -> None:
    """No endpoint bound → can't generate assertion."""
    assert lc._build_network_assertion("create", None) is None


def test_b106_build_success_assertion_create_with_redirect(lc) -> None:
    goal = {
        "title": "Create topup approval",
        "mutation_evidence": "User redirected to /admin/topups list after submit",
        "success_criteria": "Confirmation toast visible",
    }
    out = lc._build_success_assertion("create", goal)
    assert out is not None
    assert out["kind"] == "post_submit_feedback"
    assert out["expect_navigation_to"] == "/admin/topups"
    assert "[role=status]" in out["success_selectors"]


def test_b106_build_success_assertion_no_signal_skips(lc) -> None:
    """Goal with no success keyword → no metadata injection."""
    goal = {
        "title": "Create resource",
        "mutation_evidence": "POST endpoint stores row",
        "success_criteria": "",
    }
    out = lc._build_success_assertion("create", goal)
    assert out is None


def test_b106_step_injects_network_assertion(lc) -> None:
    """End-to-end: _step() for create stage produces network_assertion key."""
    goal = {
        "id": "G-001",
        "title": "Create topup",
        "primary_endpoints": [{"method": "POST", "path": "/api/v1/admin/topups"}],
        "mutation_evidence": "Topup created; success message shown",
    }
    step = lc._step("create", goal, "admin", contracts=[
        {"method": "POST", "path": "/api/v1/admin/topups"},
    ])
    assert "network_assertion" in step
    assert step["network_assertion"]["endpoint_method"] == "POST"
    assert "success_assertion" in step
    # Goal-level counters tagged
    assert goal["_b106_network_assertion_count"] == 1
    assert goal["_b106_success_assertion_count"] == 1


def test_b106_step_skips_assertions_on_read_stage(lc) -> None:
    """read_after_create stage is GET — no network/success metadata."""
    goal = {
        "id": "G-001",
        "title": "Create topup",
        "primary_endpoints": [{"method": "GET", "path": "/api/v1/admin/topups/{id}"}],
        "mutation_evidence": "redirected to success page",
    }
    step = lc._step("read_after_create", goal, "admin", contracts=[
        {"method": "GET", "path": "/api/v1/admin/topups/{id}"},
    ])
    assert "network_assertion" not in step
    assert "success_assertion" not in step


def test_b106_summary_aggregates_coverage_audit(lc, tmp_path: Path) -> None:
    """Phase summary surfaces network + success coverage counts."""
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: Create topup\n\n"
        "goal_type: mutation\n"
        "Mutation evidence: POST /api/v1/admin/topups returns 201. "
        "Success toast shown, user redirected to /admin/topups\n"
        "Persistence check: Row appears in list via GET /api/v1/admin/topups\n",
        encoding="utf-8",
    )
    # API-CONTRACTS so _bind_endpoint can resolve via slug filter
    (pdir / "API-CONTRACTS.md").write_text(
        "## POST /api/v1/admin/topups\n\n"
        "## GET /api/v1/admin/topups\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir)
    audit = payload["summary"]["form_submit_coverage_audit"]
    # Mutation goal → 3 stages (create + update + delete) each get network_assertion
    assert audit["network_assertion_total"] >= 1
    assert audit["success_assertion_total"] >= 1
    assert audit["mutation_goals_with_network_check"] == 1
    assert audit["mutation_goals_with_success_check"] == 1


# ---------------------------------------------------------------------------
# Validator — coverage scan
# ---------------------------------------------------------------------------

def _run_validator(phase_dir: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed_phase(tmp_path: Path, lifecycle_specs: dict, spec_content: str = "") -> Path:
    phase_dir = tmp_path / "08.2-test"
    phase_dir.mkdir()
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps(lifecycle_specs), encoding="utf-8"
    )
    if spec_content:
        (phase_dir / "playwright-specs").mkdir()
        (phase_dir / "playwright-specs" / "G-001.spec.ts").write_text(
            spec_content, encoding="utf-8"
        )
    return phase_dir


def test_b106_validator_pass_when_spec_has_network_capture(tmp_path: Path) -> None:
    """Spec has page.waitForResponse + status<400 + error toast assertion → PASS."""
    lifecycle = {
        "specs": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {"kind": "response_capture",
                                            "endpoint_method": "POST",
                                            "endpoint_path": "/api/v1/admin/topups"}},
                ]
            }
        }
    }
    spec = """
import { test, expect } from '@playwright/test';
test('G-001 create topup', async ({ page }) => {
  const respPromise = page.waitForResponse(r => r.url().includes('/api/v1/admin/topups'));
  await page.getByRole('button', { name: 'Submit' }).click();
  const resp = await respPromise;
  if (resp.status() >= 400) {
    await expect(page.locator('[role=alert]')).toBeVisible();
  }
  expect(resp.status()).toBeLessThan(400);
});
"""
    phase_dir = _seed_phase(tmp_path, lifecycle, spec)
    proc = _run_validator(phase_dir)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["total_findings"] == 0


def test_b106_validator_block_when_spec_missing_network_capture(tmp_path: Path) -> None:
    """Spec has button click but NO page.waitForResponse → BLOCK."""
    lifecycle = {
        "specs": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {"kind": "response_capture",
                                            "endpoint_method": "POST",
                                            "endpoint_path": "/api/v1/admin/topups"}},
                ]
            }
        }
    }
    spec_no_capture = """
import { test, expect } from '@playwright/test';
test('G-001 create topup', async ({ page }) => {
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.locator('.thing')).toBeVisible();
});
"""
    phase_dir = _seed_phase(tmp_path, lifecycle, spec_no_capture)
    proc = _run_validator(phase_dir, "--severity", "block")
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    findings = out["audits"][0]["findings"]
    assert any("network capture" in f for f in findings)


def test_b106_validator_block_when_navigation_missing(tmp_path: Path) -> None:
    """success_assertion expects navigation but spec has no waitForURL → BLOCK."""
    lifecycle = {
        "specs": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {"endpoint_method": "POST",
                                            "endpoint_path": "/api/v1/admin/topups"},
                     "success_assertion": {"expect_navigation_to": "/admin/topups"}},
                ]
            }
        }
    }
    spec_no_nav = """
import { test, expect } from '@playwright/test';
test('G-001 create topup', async ({ page }) => {
  const resp = await page.waitForResponse(r => r.url().includes('/api/v1/admin/topups'));
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(resp.status()).toBeLessThan(400);
});
"""
    phase_dir = _seed_phase(tmp_path, lifecycle, spec_no_nav)
    proc = _run_validator(phase_dir, "--severity", "block")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    findings = out["audits"][0]["findings"]
    assert any("redirect" in f.lower() or "waitForURL" in f for f in findings)


def test_b106_validator_skips_goals_without_metadata(tmp_path: Path) -> None:
    """Goals without B106 metadata (read-only / legacy) are ignored."""
    lifecycle = {
        "specs": {
            "G-002": {
                "steps": [
                    {"name": "render_initial", "stage": "render_initial"},  # no B106 meta
                ]
            }
        }
    }
    phase_dir = _seed_phase(tmp_path, lifecycle, "")
    proc = _run_validator(phase_dir)
    out = json.loads(proc.stdout)
    assert out["mutation_goals_audited"] == 0
    assert out["status"] == "PASS"


def test_b106_validator_accepts_canonical_goals_root(tmp_path: Path) -> None:
    """B106.1 (Codex postmortem): canonical generator emits payload under
    `goals` key (not `specs`). Validator MUST read both — pre-Codex-feedback
    only checked `specs` → silent zero-audit on every real phase."""
    lifecycle = {
        "goals": {  # canonical root key
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {"endpoint_method": "POST",
                                            "endpoint_path": "/api/v1/admin/topups"}},
                ]
            }
        }
    }
    phase_dir = _seed_phase(tmp_path, lifecycle, "")
    proc = _run_validator(phase_dir)
    out = json.loads(proc.stdout)
    assert out["mutation_goals_audited"] == 1, (
        "Validator must read `goals` key (canonical) — currently reads only `specs`"
    )


def test_b106_validator_flags_zero_audit_when_mutation_goals_present(tmp_path: Path) -> None:
    """B106.1 hardening (Codex): if phase has mutation goals declared but
    audit count = 0, flag as harness bug (likely B106 regen needed or root
    mismatch) — not silent PASS."""
    lifecycle = {
        "goals": {
            "G-001": {
                "goal_class": "mutation",
                "goal_type": "mutation",
                "steps": [
                    # No network_assertion — would be the pre-B106 state OR
                    # B106 metadata stripped/regen-missing
                    {"name": "create", "stage": "create"},
                ],
            }
        }
    }
    phase_dir = _seed_phase(tmp_path, lifecycle, "")
    proc = _run_validator(phase_dir, "--severity", "block")
    out = json.loads(proc.stdout)
    assert out["zero_audit_with_mutation_goals"] is True
    assert "zero_audit_diagnostic" in out
    assert proc.returncode == 1


def test_b106_validator_warn_severity_exits_zero(tmp_path: Path) -> None:
    lifecycle = {
        "specs": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {"endpoint_method": "POST",
                                            "endpoint_path": "/api/v1/admin/topups"}},
                ]
            }
        }
    }
    phase_dir = _seed_phase(tmp_path, lifecycle, "")
    proc = _run_validator(phase_dir, "--severity", "warn")
    assert proc.returncode == 0  # warn mode: never fails


# ---------------------------------------------------------------------------
# Registry + wiring + skill instructions
# ---------------------------------------------------------------------------

def test_b106_registry_entry_present() -> None:
    body = REGISTRY.read_text(encoding="utf-8")
    assert "id: fe-form-submit-coverage" in body
    idx = body.index("id: fe-form-submit-coverage")
    region = body[idx:idx + 1000]
    assert "severity: warn" in region
    assert "added_in: v4.70.0" in region
    assert "[test, accept]" in region


def test_b106_runtime_md_has_step_35() -> None:
    body = RUNTIME_MD.read_text(encoding="utf-8")
    assert "STEP 3.5" in body
    assert "verify-fe-form-submit-coverage.py" in body
    assert "B106" in body


def test_b106_gates_md_has_step_3d() -> None:
    body = GATES_MD.read_text(encoding="utf-8")
    assert "3d_fe_form_submit_coverage" in body
    assert "verify-fe-form-submit-coverage.py" in body
    assert "B106" in body


def test_b106_codegen_skill_has_directive() -> None:
    body = CODEGEN_SKILL.read_text(encoding="utf-8")
    assert "B106" in body
    assert "network_assertion" in body
    assert "success_assertion" in body
    assert "waitForURL" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b106_lifecycle_mirror_parity() -> None:
    assert LIFECYCLE.read_bytes() == LIFECYCLE_MIRROR.read_bytes()


def test_b106_validator_mirror_parity() -> None:
    assert VALIDATOR.read_bytes() == VALIDATOR_MIRROR.read_bytes()


def test_b106_registry_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"
    assert REGISTRY.read_bytes() == mirror.read_bytes()


def test_b106_runtime_md_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "runtime.md"
    assert RUNTIME_MD.read_bytes() == mirror.read_bytes()


def test_b106_gates_md_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "accept" / "gates.md"
    assert GATES_MD.read_bytes() == mirror.read_bytes()


def test_b106_codegen_skill_mirror_parity() -> None:
    mirror = REPO_ROOT / ".claude" / "agents" / "vg-test-codegen" / "SKILL.md"
    assert CODEGEN_SKILL.read_bytes() == mirror.read_bytes()
