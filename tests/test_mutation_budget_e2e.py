"""Mutation budget E2E (Task 30, v2.40.0).

Generates a synthetic phase with ≥80 mutation_button clickables, runs the
manager in sandbox mode (mutation_budget=50 per env_policy), and verifies
the plan is truncated to 50 entries with the rest dropped on the floor.

Telemetry assertion:
  recursion.mutation_budget_exhausted is the contract counter — emission
  is deferred to v2.41 because spawn_recursive_probe.apply_env_policy
  currently truncates silently. Marked pytest.skip; kept as a regression
  hook.

No real Gemini subprocess: the test runs --dry-run --json and inspects
``planned_spawns`` count.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
SMOKE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


def _build_phase_with_n_mutation_buttons(tmp_path: Path, n: int) -> Path:
    """Clone the smoke fixture and overwrite scan-admin.json with N mutation buttons."""
    dst = tmp_path / "phase"
    shutil.copytree(SMOKE_FIXTURE, dst)
    # Replace scan-admin.json with N mutation buttons (each unique resource so
    # build_plan doesn't dedupe them via the (resource, role, lens) scope key).
    results = []
    for i in range(n):
        results.append({
            "selector": f"button#mutate-{i}",
            "network": [{"method": "DELETE", "path": f"/api/resource{i}/{i}"}],
        })
    (dst / "scan-admin.json").write_text(
        json.dumps({
            "view": "/admin/big-view",
            "results": results,
            "forms": [],
            "modal_triggers": [],
            "sub_views_discovered": [],
        }), encoding="utf-8",
    )
    # Drop conflicting touched_resources so eligibility passes lazily.
    (dst / "SUMMARY.md").write_text(
        "```yaml\ntouched_resources: []\n```\n", encoding="utf-8",
    )
    # CRUD-SURFACES already lists topup_requests; keep it (rule 4 lenient when
    # touched_resources is empty).
    return dst


def _run_dry(phase: Path, *extra: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase),
         "--dry-run", "--json", "--non-interactive", *extra],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Test 1: 80 mutation buttons in sandbox → plan truncates to mutation_budget=50
# ---------------------------------------------------------------------------
def test_80_mutation_buttons_truncate_to_sandbox_budget(tmp_path: Path) -> None:
    phase = _build_phase_with_n_mutation_buttons(tmp_path, 80)
    out = _run_dry(phase, "--mode", "exhaustive", "--target-env", "sandbox")
    spawns = out["planned_spawns"]
    # Sandbox mutation_budget = 50; even though exhaustive cap allows 100,
    # apply_env_policy clips the plan to 50.
    assert len(spawns) == 50, (
        f"expected 50 spawns under sandbox budget, got {len(spawns)}"
    )
    assert out["env_policy"]["mutation_budget"] == 50
    assert out["env_policy"]["env"] == "sandbox"


# ---------------------------------------------------------------------------
# Test 2: prod env → mutation_budget=0 + only safe lenses survive
# ---------------------------------------------------------------------------
def test_prod_env_budget_zero_strips_all_mutation_lenses(tmp_path: Path) -> None:
    """Prod policy allows only lens-info-disclosure + lens-auth-jwt; mutation_button
    fans out to authz-negative + duplicate-submit + bfla — all stripped.
    Expect 0 planned spawns."""
    phase = _build_phase_with_n_mutation_buttons(tmp_path, 80)
    out = _run_dry(
        phase, "--mode", "exhaustive",
        "--target-env", "prod",
        "--i-know-this-is-prod", "test fixture",
    )
    spawns = out["planned_spawns"]
    assert len(spawns) == 0, f"prod must allow zero mutation spawns, got {len(spawns)}"
    assert out["env_policy"]["mutation_budget"] == 0
    assert out["env_policy"]["env"] == "prod"


# ---------------------------------------------------------------------------
# Test 3: local env → unlimited budget keeps the full mode-cap envelope
# ---------------------------------------------------------------------------
def test_local_env_unlimited_budget_keeps_full_plan(tmp_path: Path) -> None:
    """Local policy mutation_budget=-1 (unlimited). 80 buttons × 3 lenses = 240
    pre-cap → exhaustive cap=100 keeps 100. Local policy then keeps all 100."""
    phase = _build_phase_with_n_mutation_buttons(tmp_path, 80)
    out = _run_dry(phase, "--mode", "exhaustive", "--target-env", "local")
    spawns = out["planned_spawns"]
    # exhaustive cap is 100; local doesn't trim further.
    assert len(spawns) == 100, f"expected 100 spawns under local + exhaustive, got {len(spawns)}"
    assert out["env_policy"]["mutation_budget"] == -1


# ---------------------------------------------------------------------------
# Test 4: telemetry recursion.mutation_budget_exhausted — wired v2.41
# ---------------------------------------------------------------------------
def test_mutation_budget_exhausted_telemetry_emitted(tmp_path: Path) -> None:
    """When plan_pre_budget > kept_post_budget, apply_env_policy emits a
    ``recursion.mutation_budget_exhausted`` event. Closes v2.40 backlog #4.
    """
    import importlib
    import os as _os
    import sys as _sys
    _sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import spawn_recursive_probe  # type: ignore
    import _telemetry_helpers  # type: ignore

    telemetry_path = tmp_path / "telemetry.jsonl"
    _os.environ["VG_TELEMETRY_PATH"] = str(telemetry_path)
    importlib.reload(_telemetry_helpers)
    importlib.reload(spawn_recursive_probe)
    try:
        # 80 mutation_button entries → 240 raw lens spawns; light cap 15 takes
        # the first slice. Use exhaustive (cap 100) so we have plenty over the
        # sandbox budget of 50.
        classification = [
            {"element_class": "mutation_button",
             "view": "/admin/big",
             "selector": f"btn-{i}",
             "selector_hash": f"h{i}",
             "resource": f"res{i}",
             "role": "admin"}
            for i in range(80)
        ]
        plan = spawn_recursive_probe.build_plan(classification, "exhaustive",
                                                phase_dir=tmp_path)
        # Sanity: exhaustive cap clipped at 100.
        assert len(plan) == 100
        kept, policy = spawn_recursive_probe.apply_env_policy(
            plan, "sandbox", phase_dir=tmp_path
        )
        assert len(kept) == 50
        events = _telemetry_helpers.read_events(telemetry_path)
        exhausted = [
            e for e in events
            if e["event"] == "recursion.mutation_budget_exhausted"
        ]
        assert len(exhausted) == 1, (
            f"expected 1 mutation_budget_exhausted event, got {len(exhausted)}: {events}"
        )
        payload = exhausted[0]["payload"]
        assert payload["env"] == "sandbox"
        assert payload["mutation_budget"] == 50
        assert payload["plan_size_pre_budget"] == 100
        assert payload["plan_size_post_budget"] == 50
        assert payload["dropped"] == 50
    finally:
        _os.environ.pop("VG_TELEMETRY_PATH", None)


# ---------------------------------------------------------------------------
# Test 5: under budget → NO telemetry event (regression guard)
# ---------------------------------------------------------------------------
def test_mutation_budget_no_event_when_under_budget(tmp_path: Path) -> None:
    """When kept count <= mutation_budget, no event must be emitted."""
    import importlib
    import os as _os
    import sys as _sys
    _sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import spawn_recursive_probe  # type: ignore
    import _telemetry_helpers  # type: ignore

    telemetry_path = tmp_path / "telemetry.jsonl"
    _os.environ["VG_TELEMETRY_PATH"] = str(telemetry_path)
    importlib.reload(_telemetry_helpers)
    importlib.reload(spawn_recursive_probe)
    try:
        classification = [
            {"element_class": "mutation_button",
             "view": "/admin/small",
             "selector": f"btn-{i}",
             "selector_hash": f"h{i}",
             "resource": f"res{i}",
             "role": "admin"}
            for i in range(3)  # 3 buttons × 3 lenses = 9 → under 50
        ]
        plan = spawn_recursive_probe.build_plan(classification, "light",
                                                phase_dir=tmp_path)
        spawn_recursive_probe.apply_env_policy(plan, "sandbox", phase_dir=tmp_path)
        events = _telemetry_helpers.read_events(telemetry_path)
        exhausted = [
            e for e in events
            if e["event"] == "recursion.mutation_budget_exhausted"
        ]
        assert exhausted == [], (
            f"no event expected when under budget, got: {exhausted}"
        )
    finally:
        _os.environ.pop("VG_TELEMETRY_PATH", None)
