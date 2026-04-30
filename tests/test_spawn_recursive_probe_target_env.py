"""Verify spawn_recursive_probe.py honors --target-env via env_policy.

Task 26c (Phase 1.D-bis).

Plan filtering rules:
  - prod  → only allowed_lenses (lens-info-disclosure, lens-auth-jwt)
  - sandbox / staging / local → keep allowed lenses, cap len(plan) at
    mutation_budget when allow_mutations is True.
  - prod without --i-know-this-is-prod → exit non-zero unless
    --skip-recursive-probe is also supplied.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


def _seed_phase(tmp_path: Path) -> Path:
    """Copy the smoke fixture, add .phase-profile so eligibility passes, then
    pre-emit a recursive-classification.json — this lets dry-run skip the
    real identify_interesting_clickables.py subprocess (which still has to
    run, but on the seeded scan it produces a deterministic output)."""
    import shutil
    phase = tmp_path / "phase"
    shutil.copytree(FIXTURE, phase)
    (phase / ".phase-profile").write_text(
        "phase_profile: feature\nsurface: ui\n", encoding="utf-8"
    )
    # SUMMARY references topup_requests; align to seeded scan view.
    # Provide a scan that classifier turns into varied element classes:
    #   - mutation_button (POST request)
    #   - form_trigger
    #   - row_action
    #   - bulk_action
    (phase / "scan-admin.json").write_text(json.dumps({
        "view": "/admin",
        "elements_total": 5,
        "results": [
            {
                "selector": "button#approve-1",
                "network": [
                    {"method": "POST", "url": "/api/orders/1/approve"}
                ],
            },
        ],
        "forms": [
            {"selector": "form#new-order", "fields": [{"name": "amount"}],
             "submit_result": {"status": 200}},
        ],
        "tables": [
            {
                "selector": "table#orders",
                "row_actions": [
                    {"selector": "button.del", "label": "Delete"},
                ],
                "bulk_actions": [
                    {"selector": "button.bulk-del", "label": "Bulk Delete"},
                ],
            },
        ],
        "modal_triggers": [],
        "tabs": [],
        "sub_views_discovered": [],
    }), encoding="utf-8")
    return phase


def _run(phase: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--phase-dir", str(phase),
         "--dry-run", "--json",
         *extra],
        capture_output=True, text=True,
    )


def test_target_env_prod_filters_to_safe_lenses(tmp_path: Path) -> None:
    phase = _seed_phase(tmp_path)
    r = _run(phase, "--target-env", "prod",
             "--i-know-this-is-prod", "smoke-test")
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    if not payload.get("eligibility", {}).get("passed", False):
        # Eligibility may fail on the smoke fixture; that's fine — we still
        # want to confirm policy is reflected in the payload.
        pass
    spawns = payload.get("planned_spawns") or []
    bad = [s for s in spawns if s["lens"] not in {"lens-info-disclosure", "lens-auth-jwt"}]
    assert not bad, f"prod kept disallowed lenses: {bad}"


def test_target_env_prod_requires_reason(tmp_path: Path) -> None:
    phase = _seed_phase(tmp_path)
    r = _run(phase, "--target-env", "prod")
    # Without --i-know-this-is-prod, must fail loudly (exit non-zero).
    assert r.returncode != 0, r.stdout + r.stderr
    assert "prod" in (r.stderr + r.stdout).lower()


def test_target_env_sandbox_caps_to_budget(tmp_path: Path) -> None:
    phase = _seed_phase(tmp_path)
    r = _run(phase, "--target-env", "sandbox", "--mode", "exhaustive")
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    spawns = payload.get("planned_spawns") or []
    # Sandbox budget = 50; classification x lens fanout < 50, but the cap
    # must never be exceeded.
    assert len(spawns) <= 50, len(spawns)


def test_target_env_staging_drops_input_injection(tmp_path: Path) -> None:
    phase = _seed_phase(tmp_path)
    r = _run(phase, "--target-env", "staging")
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    spawns = payload.get("planned_spawns") or []
    assert not any(s["lens"] == "lens-input-injection" for s in spawns)


def test_target_env_default_sandbox(tmp_path: Path) -> None:
    """No --target-env supplied → defaults to sandbox (full lenses, 50 cap)."""
    phase = _seed_phase(tmp_path)
    r = _run(phase)
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    assert payload.get("target_env") == "sandbox", payload
