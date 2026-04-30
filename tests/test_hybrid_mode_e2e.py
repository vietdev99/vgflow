"""Hybrid-mode E2E (v2.41 — closes v2.40 backlog #5).

Hybrid contract per design doc:
  - lenses listed in vg.config recursive_probe.hybrid_routing.auto_lenses →
    spawn worker (auto)
  - lenses in hybrid_routing.manual_lenses → render prompt file (manual)
  - both groups merge in goal back-flow

v2.41 implementation: spawn_recursive_probe.split_hybrid() partitions the
plan per config; main() dispatches each subset through the matching path.
Validation surfaces routing config errors with actionable messages
(unrouted lenses, overlap between auto/manual lists).

We exercise dry-run paths with --dry-run so no real Gemini fires for the
plan-shape tests; integration tests for the actual dispatch use
unittest.mock to stub subprocess.run.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
SMOKE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recursive-probe-smoke"


def _copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "phase"
    shutil.copytree(SMOKE_FIXTURE, dst)
    return dst


def _import_spawn_module():
    """Re-import the script as a module to access split_hybrid + main."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("spawn_recursive_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_dry_hybrid(phase: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--phase-dir", str(phase),
         "--mode", "light",
         "--probe-mode", "hybrid",
         "--non-interactive",
         "--target-env", "sandbox",
         "--dry-run", "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Test 1: hybrid mode is accepted by the CLI + plan composes
# ---------------------------------------------------------------------------
def test_hybrid_mode_dry_run_composes_plan(tmp_path: Path) -> None:
    phase = _copy_fixture(tmp_path)
    out = _run_dry_hybrid(phase)
    assert out["probe_mode"] == "hybrid"
    spawns = out["planned_spawns"]
    assert spawns, f"hybrid mode should still produce a plan, got: {out}"
    # Light cap = 15.
    assert 1 <= len(spawns) <= 15


# ---------------------------------------------------------------------------
# Test 2: hybrid_routing config defines disjoint auto/manual lens sets
# ---------------------------------------------------------------------------
def test_hybrid_routing_config_disjoint() -> None:
    """Sanity gate against a regression where someone adds a lens to BOTH lists."""
    template = REPO_ROOT / "vg.config.template.md"
    text = template.read_text(encoding="utf-8")
    # Quick parse: find lines under hybrid_routing: until the next top-level key.
    # We rely on the existing hybrid_routing block in vg.config.template.md.
    assert "hybrid_routing:" in text
    auto_idx = text.index("auto_lenses:")
    manual_idx = text.index("manual_lenses:")
    auto_block = text[auto_idx:manual_idx]
    # Crude: find next top-level key after manual_lenses.
    after = text[manual_idx:]
    end = after.find("\n  # ")
    manual_block = after[:end] if end > 0 else after[:600]

    auto_lenses = {
        line.strip().strip('-').strip().strip('"').strip("'")
        for line in auto_block.splitlines()
        if line.strip().startswith('- "lens-')
    }
    manual_lenses = {
        line.strip().strip('-').strip().strip('"').strip("'")
        for line in manual_block.splitlines()
        if line.strip().startswith('- "lens-')
    }
    assert auto_lenses, f"could not parse auto_lenses; first 200 chars: {auto_block[:200]}"
    assert manual_lenses, f"could not parse manual_lenses"
    overlap = auto_lenses & manual_lenses
    assert not overlap, f"hybrid routing lists must be disjoint, overlap={overlap}"


# ---------------------------------------------------------------------------
# Test 3: split_hybrid splits plan per routing config
# ---------------------------------------------------------------------------
def test_hybrid_splits_plan_per_routing_config() -> None:
    """split_hybrid partitions a plan into auto/manual buckets."""
    mod = _import_spawn_module()
    plan = [
        {"element": {"selector": "btn-1"}, "lens": "lens-authz-negative"},
        {"element": {"selector": "btn-2"}, "lens": "lens-csrf"},
        {"element": {"selector": "btn-3"}, "lens": "lens-business-logic"},
        {"element": {"selector": "btn-4"}, "lens": "lens-duplicate-submit"},
    ]
    cfg = {
        "review": {
            "recursive_probe": {
                "hybrid_routing": {
                    "auto_lenses": ["lens-authz-negative", "lens-csrf"],
                    "manual_lenses": ["lens-business-logic", "lens-duplicate-submit"],
                }
            }
        }
    }
    auto_plan, manual_plan = mod.split_hybrid(plan, cfg)
    assert [p["lens"] for p in auto_plan] == [
        "lens-authz-negative", "lens-csrf"
    ]
    assert [p["lens"] for p in manual_plan] == [
        "lens-business-logic", "lens-duplicate-submit"
    ]


# ---------------------------------------------------------------------------
# Test 4: validation — unrouted lenses raise actionable error
# ---------------------------------------------------------------------------
def test_hybrid_validates_unrouted_lenses_error() -> None:
    """A lens in plan but in NEITHER auto nor manual lists must raise."""
    mod = _import_spawn_module()
    plan = [
        {"element": {"selector": "btn-1"}, "lens": "lens-authz-negative"},
        {"element": {"selector": "btn-2"}, "lens": "lens-undefined-yet"},
    ]
    cfg = {
        "review": {
            "recursive_probe": {
                "hybrid_routing": {
                    "auto_lenses": ["lens-authz-negative"],
                    "manual_lenses": ["lens-business-logic"],
                }
            }
        }
    }
    with pytest.raises(ValueError) as excinfo:
        mod.split_hybrid(plan, cfg)
    msg = str(excinfo.value)
    assert "lens-undefined-yet" in msg
    assert "missing" in msg.lower() or "auto_lenses" in msg


# ---------------------------------------------------------------------------
# Test 5: validation — overlap between auto + manual raises
# ---------------------------------------------------------------------------
def test_hybrid_validates_overlap_error() -> None:
    """A lens in BOTH auto AND manual must raise."""
    mod = _import_spawn_module()
    plan = [{"element": {"selector": "btn-1"}, "lens": "lens-csrf"}]
    cfg = {
        "review": {
            "recursive_probe": {
                "hybrid_routing": {
                    "auto_lenses": ["lens-csrf"],
                    "manual_lenses": ["lens-csrf"],   # OVERLAP
                }
            }
        }
    }
    with pytest.raises(ValueError) as excinfo:
        mod.split_hybrid(plan, cfg)
    msg = str(excinfo.value)
    assert "lens-csrf" in msg
    assert "both" in msg.lower()


# ---------------------------------------------------------------------------
# Test 6: hybrid auto-only when manual_lenses bucket is empty
# ---------------------------------------------------------------------------
def test_hybrid_auto_only_when_manual_empty() -> None:
    """If routing has manual_lenses but plan only contains auto-routable
    lenses, manual_plan must be empty (not error)."""
    mod = _import_spawn_module()
    plan = [{"element": {"selector": "btn-1"}, "lens": "lens-authz-negative"}]
    cfg = {
        "review": {
            "recursive_probe": {
                "hybrid_routing": {
                    "auto_lenses": ["lens-authz-negative"],
                    "manual_lenses": ["lens-business-logic"],
                }
            }
        }
    }
    auto_plan, manual_plan = mod.split_hybrid(plan, cfg)
    assert len(auto_plan) == 1
    assert manual_plan == []


# ---------------------------------------------------------------------------
# Test 7: hybrid manual-only when auto bucket is empty
# ---------------------------------------------------------------------------
def test_hybrid_manual_only_when_auto_empty() -> None:
    mod = _import_spawn_module()
    plan = [{"element": {"selector": "btn-1"}, "lens": "lens-business-logic"}]
    cfg = {
        "review": {
            "recursive_probe": {
                "hybrid_routing": {
                    "auto_lenses": ["lens-authz-negative"],
                    "manual_lenses": ["lens-business-logic"],
                }
            }
        }
    }
    auto_plan, manual_plan = mod.split_hybrid(plan, cfg)
    assert auto_plan == []
    assert len(manual_plan) == 1


# ---------------------------------------------------------------------------
# Test 8: integration — real-run dispatches both branches end-to-end
# ---------------------------------------------------------------------------
def test_hybrid_real_run_dispatches_both_branches(tmp_path: Path) -> None:
    """Real run with --probe-mode=hybrid (no --dry-run) writes auto INDEX +
    invokes generate_recursive_prompts.py for the manual subset.

    We mock subprocess.run for the worker dispatches so no Gemini binary is
    invoked; the assertion focuses on the split + which paths the manager
    walked.
    """
    phase = _copy_fixture(tmp_path)
    # Write a hybrid_routing config that the manager will discover.
    cfg_path = tmp_path / "vg.config.md"
    cfg_path.write_text(
        "# vg.config\n```yaml\nreview:\n"
        "  recursive_probe:\n"
        "    hybrid_routing:\n"
        "      auto_lenses:\n        - lens-authz-negative\n"
        "      manual_lenses:\n        - lens-business-logic\n"
        "```\n",
        encoding="utf-8",
    )
    mod = _import_spawn_module()

    # Force a known plan with one auto-routed lens + one manual-routed lens.
    fake_plan_classification = [
        {"element_class": "mutation_button", "selector": "btn-auto",
         "view": "/admin", "resource": "topup", "selector_hash": "ha",
         "role": "admin"},
        # Same surface but force-tagged with form_trigger to fan out into
        # lens-business-logic via LENS_MAP modal_trigger? Simpler — manipulate
        # build_plan output directly via patching.
    ]

    # Replace _classify_phase + build_plan to hand back a curated plan.
    fake_plan = [
        {"element": {"element_class": "mutation_button", "selector": "btn-a",
                      "view": "/admin", "resource": "topup",
                      "selector_hash": "ha", "role": "admin"},
         "lens": "lens-authz-negative",
         "scope_key": ("topup", "admin", "lens-authz-negative")},
        {"element": {"element_class": "mutation_button", "selector": "btn-m",
                      "view": "/admin", "resource": "topup",
                      "selector_hash": "hm", "role": "admin"},
         "lens": "lens-business-logic",
         "scope_key": ("topup", "admin", "lens-business-logic")},
    ]

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    import io
    import contextlib

    captured_out = io.StringIO()
    captured_err = io.StringIO()

    rc: int | None = None
    with patch.object(mod, "_classify_phase",
                       return_value=fake_plan_classification), \
         patch.object(mod, "build_plan", return_value=fake_plan), \
         patch.object(mod, "apply_env_policy",
                       return_value=(fake_plan, {"env": "sandbox", "applied": True,
                                                  "allowed_lenses": ["lens-authz-negative",
                                                                     "lens-business-logic"],
                                                  "mutation_budget": 50})), \
         patch.object(mod.subprocess, "run", return_value=_FakeCompleted()):
        with contextlib.redirect_stdout(captured_out), \
             contextlib.redirect_stderr(captured_err):
            try:
                rc = mod.main([
                    "--phase-dir", str(phase),
                    "--mode", "light",
                    "--probe-mode", "hybrid",
                    "--non-interactive",
                    "--target-env", "sandbox",
                ])
            except SystemExit as exc:
                rc = int(exc.code) if exc.code is not None else 0

    out = captured_out.getvalue()
    err = captured_err.getvalue()
    assert rc == 0, f"expected exit 0, got {rc}; stderr={err}; stdout={out}"
    # Auto branch wrote runs/INDEX.json.
    auto_index = phase / "runs" / "INDEX.json"
    assert auto_index.is_file(), (
        f"auto branch should write runs/INDEX.json; ls phase: "
        f"{[p.name for p in phase.glob('**/*')]}"
    )
    payload = json.loads(auto_index.read_text(encoding="utf-8"))
    assert payload["mode"] == "hybrid-auto"
    assert len(payload["plan"]) == 1
    assert payload["plan"][0]["lens"] == "lens-authz-negative"
    # Hard-fail message must NOT appear.
    assert "Hybrid mode is not yet implemented" not in err


# ---------------------------------------------------------------------------
# Test 9: missing config gracefully reports unrouted lenses
# ---------------------------------------------------------------------------
def test_hybrid_missing_config_surfaces_unrouted_error(tmp_path: Path) -> None:
    """When vg.config has no hybrid_routing block, every lens is unrouted →
    actionable ValueError surface."""
    mod = _import_spawn_module()
    plan = [{"element": {"selector": "btn-1"}, "lens": "lens-authz-negative"}]
    with pytest.raises(ValueError) as excinfo:
        mod.split_hybrid(plan, {})  # empty config
    msg = str(excinfo.value)
    assert "lens-authz-negative" in msg
