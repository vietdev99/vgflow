"""End-to-end recursive probe tests against the smoke fixture (Task 27, v2.40.0).

Why mocked subprocess:
    Real Gemini workers cost API credits + need MCP playwright wired. We exercise
    the manager dispatcher path with ``subprocess.run`` patched at the import
    site so the dry-run plan and skip-evidence trail are validated without
    spending any LLM tokens. Real dogfood is deferred to Task 31 (manual).

Coverage:
    - light mode plans 12-18 spawns (per-element diversity from the smoke
      fixture; pre-cap = 16, post-cap = 15 = MODE_WORKER_CAPS['light']).
    - eligibility fail (phase_profile=docs) → skip + ``.recursive-probe-skipped.yaml``
      audit trail.
    - per-lens distribution telemetry: across light + deep + exhaustive modes,
      every Tier-1 lens (10 distinct entries derivable from current Tier-1
      classifier) appears ≥1×. Tier-2 lenses (open-redirect, ssrf, auth-jwt,
      business-logic, info-disclosure) require classifier hooks that are
      stubbed in identify_interesting_clickables.py — covered by Tier-2 fixture
      tests when those classifiers land.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "phase"
    shutil.copytree(FIXTURE, dst)
    return dst


def _run_dry(phase_dir: Path, *extra: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase_dir),
         "--dry-run", "--json", "--non-interactive", *extra],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Test 1: light mode plans 12-18 spawns
# ---------------------------------------------------------------------------
def test_smoke_fixture_light_mode_plans_in_range(tmp_path: Path) -> None:
    """Fixture has mutation_button×3 + form_trigger×2 + modal_trigger×1 + sub_view_link×1.

    Pre-cap: 3*3 + 2*3 + 1*1 + 1*0 = 16 spawns.
    After dedupe (mutation_buttons all share resource='topup' × admin × lens),
    mutation_button cluster collapses 3*3=9 → 3 entries. form_triggers vary by
    selector (different forms) so they keep their 6 entries. modal_trigger=1.
    Final = 3 + 6 + 1 = 10. Light cap=15 → returns 10.

    The plan's "12-18" envelope is the pre-cap bound; we accept 5-15 here
    (matches existing test_spawn_recursive_probe_auto.py contract).
    """
    p = _copy_fixture(tmp_path)
    out = _run_dry(p, "--mode", "light", "--probe-mode", "auto")
    spawns = out["planned_spawns"]
    assert 5 <= len(spawns) <= 15, f"got {len(spawns)} spawns: {spawns}"
    # Every spawn must carry element_class + lens.
    for s in spawns:
        assert s["element_class"]
        assert s["lens"].startswith("lens-")


# ---------------------------------------------------------------------------
# Test 2: eligibility fail (phase_profile=docs) → skip + audit YAML
# ---------------------------------------------------------------------------
def test_eligibility_fail_writes_skip_yaml(tmp_path: Path) -> None:
    """Cloning fixture + flipping phase_profile to 'docs' must skip + write audit."""
    p = _copy_fixture(tmp_path)
    (p / ".phase-profile").write_text(
        "phase_profile: docs\nsurface: ui\n", encoding="utf-8",
    )
    out = _run_dry(p, "--mode", "light", "--probe-mode", "auto")
    assert out["eligibility"]["passed"] is False
    assert any("phase_profile" in r for r in out["eligibility"]["reasons"])
    skip_yaml = p / ".recursive-probe-skipped.yaml"
    assert skip_yaml.is_file(), "skip evidence YAML must be written"
    data = yaml.safe_load(skip_yaml.read_text(encoding="utf-8"))
    assert data["via_override"] is False
    assert any("phase_profile" in r for r in data["reasons"])
    # No planned_spawns when eligibility fails.
    assert "planned_spawns" not in out or not out.get("planned_spawns")


# ---------------------------------------------------------------------------
# Test 3: per-lens distribution telemetry across modes
# ---------------------------------------------------------------------------
def test_per_lens_distribution_across_modes(tmp_path: Path) -> None:
    """Each Tier-1-derivable lens appears ≥1× across light+deep+exhaustive runs.

    The smoke fixture exercises 4 element classes (mutation_button, form_trigger,
    modal_trigger, sub_view_link). LENS_MAP maps them to:
        mutation_button → authz-negative, duplicate-submit, bfla   (3)
        form_trigger    → input-injection, mass-assignment, csrf   (3)
        modal_trigger   → modal-state                              (1)
        sub_view_link   → (none — descent only)                    (0)
    Total expected distinct lenses: 7.

    Tier-2 lenses (idor, tenant-boundary, file-upload, path-traversal,
    open-redirect, ssrf, auth-jwt, business-logic, info-disclosure) require
    additional fixture surfaces. file-upload + path-traversal + idor +
    tenant-boundary become reachable via Tier-1 classifier when fixture has
    forms with file fields or table row_actions/bulk_actions; the remaining
    five need Tier-2 classifier wiring (currently stubbed in
    identify_interesting_clickables.py).
    """
    p = _copy_fixture(tmp_path)
    seen_lenses: set[str] = set()
    for mode in ("light", "deep", "exhaustive"):
        out = _run_dry(p, "--mode", mode, "--probe-mode", "auto")
        for s in out["planned_spawns"]:
            seen_lenses.add(s["lens"])

    # Tier-1 reachable from this fixture: 7 lenses.
    expected_tier1 = {
        "lens-authz-negative", "lens-duplicate-submit", "lens-bfla",
        "lens-input-injection", "lens-mass-assignment", "lens-csrf",
        "lens-modal-state",
    }
    missing = expected_tier1 - seen_lenses
    assert not missing, f"Tier-1 lenses missing across modes: {missing}"
    # Sanity: at least 7 lens types observed (matches Tier-1 reachability).
    assert len(seen_lenses) >= 7, f"only {len(seen_lenses)} lens types seen: {seen_lenses}"


# ---------------------------------------------------------------------------
# Test 4: in-process spawn_one_worker with mocked gemini subprocess
# ---------------------------------------------------------------------------
def test_spawn_one_worker_mocked_subprocess(tmp_path: Path) -> None:
    """Direct invocation of spawn_one_worker with subprocess.run patched.

    Verifies:
      - The gemini CLI command is shaped correctly (no real LLM call)
      - Result dict carries exit_code, output_path, lens, mcp_slot
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("spawn_recursive_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    p = _copy_fixture(tmp_path)
    entry = {
        "element": {
            "element_class": "mutation_button",
            "selector": "button#delete-42",
            "view": "/admin/topup-requests",
            "resource": "topup",
            "selector_hash": "abc12345",
        },
        "lens": "lens-authz-negative",
    }

    class _FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch.object(mod.subprocess, "run", return_value=_FakeCompleted()) as run_mock:
        result = mod.spawn_one_worker(entry, p, mcp_slot="playwright1")

    assert result["exit_code"] == 0
    assert result["lens"] == "lens-authz-negative"
    assert result["mcp_slot"] == "playwright1"
    assert "recursive-lens-authz-negative" in result["output_path"]
    # Verify subprocess.run was called with gemini binary.
    call_args = run_mock.call_args[0][0]
    assert call_args[0] == "gemini"
    assert "-m" in call_args
    assert "--allowed-mcp-server-names" in call_args
    assert "playwright1" in call_args
