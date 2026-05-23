"""B107 v4.70.1 — semantic verify-spec-stage-coverage upgrade.

Codex postmortem (2026-05-23) recommendation #2: pre-B107 the validator
only checked TOKEN PRESENCE — a spec could have `waitForResponse` bound
to an unrelated endpoint, never assert status<400, and still pass. Top
25-35% of UAT bugs (form 4xx swallowed, missing success, broken
redirect) shipped through `/vg:test` PASS.

B107 reads B106's `network_assertion` + `success_assertion` metadata
from each step in LIFECYCLE-SPECS.json and requires the spec to:
  - Bind waitForResponse to the EXPECTED method + endpoint path
  - Have a concrete status<400 assertion (not just bare waitForResponse)
  - For 4xx/5xx branch: error-locator assertion
  - For success_assertion with expect_navigation_to: waitForURL OR
    toHaveURL referencing the declared path pattern
  - For success_assertion without nav: success-locator OR toast assertion
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-spec-stage-coverage.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-spec-stage-coverage.py"


def _run(phase_dir: Path, repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(repo_root),
         "--json"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed(tmp_path: Path, lifecycle: dict, manifest: dict, spec_files: dict) -> tuple[Path, Path]:
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, body in spec_files.items():
        f = repo_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return phase_dir, repo_root


# ---------------------------------------------------------------------------
# Semantic gate — endpoint-bound waitForResponse
# ---------------------------------------------------------------------------

def test_b107_waitForResponse_unbound_to_endpoint_flagged(tmp_path: Path) -> None:
    """Spec has waitForResponse but URL is unrelated to declared endpoint → FAIL."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/admin/topups",
                         "on_4xx_5xx_must_render_error_toast": True,
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "specs/G-001.spec.ts"}]}
    # Spec hits a DIFFERENT endpoint
    spec_body = """
import { test, expect } from '@playwright/test';
test('G-001', async ({ page }) => {
  await page.fill('input', 'x');
  await page.click('button');
  const r = await page.waitForResponse(/\\/api\\/v1\\/unrelated/);
  expect(r.status()).toBeLessThan(400);
  await expect(page.locator('[role=alert]')).toBeVisible();
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"specs/G-001.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    finds = out["failures"][0]["missing_stages"]
    has_endpoint_finding = any(
        "not bound to expected endpoint" in m
        for ms in finds.values() for m in ms
    )
    assert has_endpoint_finding


def test_b107_waitForResponse_bound_to_endpoint_passes(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/admin/topups",
                         "on_4xx_5xx_must_render_error_toast": True,
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "specs/G-001.spec.ts"}]}
    spec_body = """
import { test, expect } from '@playwright/test';
test('G-001', async ({ page }) => {
  await page.goto('/admin/topups/new');
  await page.fill('input', 'x');
  const r = await page.waitForResponse(r => r.url().includes('/api/v1/admin/topups'));
  await page.click('button');
  expect(r.status()).toBeLessThan(400);
  await expect(page.locator('[role=alert]')).toBeVisible();
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"specs/G-001.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    # PASS — should be no failures
    assert out["shallow_specs"] == 0, json.dumps(out, indent=2)


def test_b107_missing_status_assertion_flagged(tmp_path: Path) -> None:
    """Has bound waitForResponse but never asserts status<400 → FAIL."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/topups",
                         "on_4xx_5xx_must_render_error_toast": True,
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "s.spec.ts"}]}
    spec_body = """
import { test, expect } from '@playwright/test';
test('G-001', async ({ page }) => {
  await page.goto('/admin/topups');
  await page.fill('input', 'x');
  const r = await page.waitForResponse(/\\/api\\/v1\\/topups/);
  await page.click('button');
  await expect(page.locator('[role=alert]')).toBeVisible();
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    finds = out["failures"][0]["missing_stages"]
    assert any(
        "status<400" in m
        for ms in finds.values() for m in ms
    )


def test_b107_missing_error_locator_flagged(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/topups",
                         "on_4xx_5xx_must_render_error_toast": True,
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "s.spec.ts"}]}
    spec_body = """
import { test, expect } from '@playwright/test';
test('G-001', async ({ page }) => {
  await page.goto('/admin/topups');
  await page.fill('input', 'x');
  const r = await page.waitForResponse(/\\/api\\/v1\\/topups/);
  await page.click('button');
  expect(r.status()).toBeLessThan(400);
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    finds = out["failures"][0]["missing_stages"]
    assert any("error-locator" in m for ms in finds.values() for m in ms)


# ---------------------------------------------------------------------------
# Semantic gate — success_assertion + navigation
# ---------------------------------------------------------------------------

def test_b107_navigation_assertion_missing_when_declared(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/topups",
                     },
                     "success_assertion": {
                         "expect_navigation_to": "/admin/topups/details",
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "s.spec.ts"}]}
    spec_body = """
test('G-001', async ({ page }) => {
  await page.fill('x','y');
  const r = await page.waitForResponse(/\\/api\\/v1\\/topups/);
  await page.click('button');
  expect(r.status()).toBeLessThan(400);
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    finds = out["failures"][0]["missing_stages"]
    assert any(
        "waitForURL" in m or "toHaveURL" in m
        for ms in finds.values() for m in ms
    )


def test_b107_navigation_assertion_present_passes(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/topups",
                         "on_4xx_5xx_must_render_error_toast": True,
                     },
                     "success_assertion": {
                         "expect_navigation_to": "/admin/topups/details",
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "s.spec.ts"}]}
    spec_body = """
test('G-001', async ({ page }) => {
  await page.fill('x','y');
  const r = await page.waitForResponse(r => r.url().includes('/api/v1/topups'));
  await page.click('button');
  expect(r.status()).toBeLessThan(400);
  await page.waitForURL(/\\/admin\\/topups\\/details/);
  await expect(page.locator('[role=alert]')).toBeVisible();
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert out["shallow_specs"] == 0, json.dumps(out, indent=2)


def test_b107_success_locator_missing_when_no_nav(tmp_path: Path) -> None:
    """success_assertion without nav → require success locator."""
    lifecycle = {
        "goals": {
            "G-001": {
                "steps": [
                    {"name": "create", "stage": "create",
                     "network_assertion": {
                         "endpoint_method": "POST",
                         "endpoint_path": "/api/v1/topups",
                     },
                     "success_assertion": {
                         "expect_navigation_to": None,
                     }},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-001", "path": "s.spec.ts"}]}
    spec_body = """
test('G-001', async ({ page }) => {
  await page.fill('x','y');
  const r = await page.waitForResponse(/\\/api\\/v1\\/topups/);
  await page.click('button');
  expect(r.status()).toBeLessThan(400);
});
"""
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    finds = out["failures"][0]["missing_stages"]
    assert any("success-locator" in m for ms in finds.values() for m in ms)


# ---------------------------------------------------------------------------
# Steps without B106 metadata are not flagged by semantic gate
# ---------------------------------------------------------------------------

def test_b107_no_b106_metadata_no_semantic_block(tmp_path: Path) -> None:
    """Pure read goal (no network_assertion / success_assertion) → semantic
    layer should not produce findings on top of the shallow check."""
    lifecycle = {
        "goals": {
            "G-002": {
                "steps": [
                    {"name": "read_before", "stage": "read_before"},
                ]
            }
        }
    }
    manifest = {"playwright_specs": [{"goal_id": "G-002", "path": "s.spec.ts"}]}
    # No goto → shallow check still fails. The semantic layer should not
    # contribute extra findings.
    spec_body = "test('G-002', async ({page}) => { /* nothing */ });"
    phase, repo = _seed(tmp_path, lifecycle, manifest, {"s.spec.ts": spec_body})
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    # Shallow finds the missing read_before nav. No `__semantic` keys allowed.
    keys = list(out["failures"][0]["missing_stages"].keys()) if out["failures"] else []
    assert not any("__semantic" in k for k in keys)


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b107_validator_mirror_parity() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()
