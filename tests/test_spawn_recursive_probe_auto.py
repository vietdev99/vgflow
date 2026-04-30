"""Auto-mode worker-dispatch tests for spawn_recursive_probe.py (Task 19).

We assert against the dry-run plan only — never spawning a real Gemini worker.
The Task 27 smoke fixture covers actual subprocess invocation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


def _copy_fixture_phase(tmp_path: Path) -> Path:
    """Clone the recursive-probe-smoke fixture into ``tmp_path/phase``."""
    import shutil
    dst = tmp_path / "phase"
    shutil.copytree(FIXTURE, dst)
    return dst


def _run(phase_dir: Path, *extra: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase_dir),
         "--dry-run", "--json", *extra],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Plan composition
# ---------------------------------------------------------------------------
def test_auto_mode_dry_run_lists_planned_spawns(tmp_path: Path) -> None:
    p = _copy_fixture_phase(tmp_path)
    out = _run(p, "--mode", "light", "--probe-mode", "auto")
    assert "planned_spawns" in out
    spawns = out["planned_spawns"]
    # Fixture has 3 mutation_buttons + 2 form_triggers + 1 modal_trigger + 1 sub_view_link.
    # mutation_button → 3 lenses, form_trigger → 3 lenses, modal_trigger → 1 lens,
    # sub_view_link → 0 lenses. Pre-cap = 3*3 + 2*3 + 1*1 + 0 = 16. Light cap = 15.
    assert 5 <= len(spawns) <= 15
    # Every spawn carries element_class + lens.
    for s in spawns:
        assert "element_class" in s and "lens" in s
        assert s["lens"].startswith("lens-")


def test_mode_caps_enforced(tmp_path: Path) -> None:
    """Light cap ≤ deep cap ≤ exhaustive cap."""
    p = _copy_fixture_phase(tmp_path)
    light = len(_run(p, "--mode", "light", "--probe-mode", "auto")["planned_spawns"])
    deep = len(_run(p, "--mode", "deep", "--probe-mode", "auto")["planned_spawns"])
    exh = len(_run(p, "--mode", "exhaustive", "--probe-mode", "auto")["planned_spawns"])
    assert light <= deep <= exh


# ---------------------------------------------------------------------------
# LENS_MAP unit-style tests against the in-process module
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def probe_module():
    """Import the script as a module so we can call build_plan / LENS_MAP directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "spawn_recursive_probe", SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_lens_map_assigns_correct_lenses_per_element_class(probe_module) -> None:
    """Spec table from design doc — verify exact lens mapping."""
    lm = probe_module.LENS_MAP
    assert lm["mutation_button"] == [
        "lens-authz-negative", "lens-duplicate-submit", "lens-bfla",
    ]
    assert lm["form_trigger"] == [
        "lens-input-injection", "lens-mass-assignment", "lens-csrf",
    ]
    assert lm["row_action"] == ["lens-idor", "lens-tenant-boundary"]
    assert lm["bulk_action"] == ["lens-duplicate-submit", "lens-bfla"]
    assert lm["modal_trigger"] == ["lens-modal-state"]
    assert lm["file_upload"] == [
        "lens-file-upload", "lens-input-injection", "lens-path-traversal",
    ]
    assert lm["redirect_url_param"] == ["lens-open-redirect"]
    assert lm["url_fetch_param"] == ["lens-ssrf"]
    assert lm["auth_endpoint"] == ["lens-auth-jwt", "lens-csrf"]
    assert lm["payment_or_workflow"] == [
        "lens-business-logic", "lens-duplicate-submit",
    ]
    assert lm["error_response"] == ["lens-info-disclosure"]
    assert lm["path_param"] == ["lens-path-traversal"]
    # tab + sub_view_link have no lens (descent only).
    assert lm["tab"] == []
    assert lm["sub_view_link"] == []


def test_build_plan_dedupes_same_resource_role_lens(probe_module) -> None:
    """Guard #7: two clickables on same resource × role × lens collapse to one."""
    classification = [
        {"element_class": "mutation_button", "selector": "btn-1",
         "view": "/admin", "resource": "topup", "role": "admin"},
        {"element_class": "mutation_button", "selector": "btn-2",
         "view": "/admin", "resource": "topup", "role": "admin"},  # dup scope
    ]
    plan = probe_module.build_plan(classification, mode="exhaustive")
    # mutation_button has 3 lenses → 3 entries (NOT 6) after dedupe.
    assert len(plan) == 3
    lenses = sorted(p["lens"] for p in plan)
    assert lenses == sorted([
        "lens-authz-negative", "lens-duplicate-submit", "lens-bfla",
    ])


def test_build_plan_respects_mode_cap(probe_module) -> None:
    """light mode must clip to MODE_WORKER_CAPS['light'] = 15."""
    # Synthesize 30 unique mutation_buttons so plan would be 90 pre-cap.
    classification = [
        {"element_class": "mutation_button", "selector": f"btn-{i}",
         "view": "/admin", "resource": f"res-{i}", "role": "admin"}
        for i in range(30)
    ]
    plan = probe_module.build_plan(classification, mode="light")
    assert len(plan) == 15  # MODE_WORKER_CAPS['light']
    plan_deep = probe_module.build_plan(classification, mode="deep")
    assert len(plan_deep) == 40  # MODE_WORKER_CAPS['deep']
