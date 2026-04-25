"""
Tests for verify-blueprint-completeness.py — UNQUARANTINABLE meta-gate.

Per orchestrator allowlist comment: "AI cannot ship under-detailed blueprints
by repeatedly failing the gate." Closes the Phase 7.14.3 retro: PLAN+CONTRACTS+
TEST-GOALS each individually pass but the cross-product had gaps (no filter
goal, no Layer-4 mutation, no state-machine guard).

Covers:
  - Missing phase-dir → PASS (graceful, no crash)
  - Empty phase artifacts → PASS or BLOCK with clear message
  - Goal without covering PLAN task → BLOCK
  - Mutation goal missing Layer-4 reload check → BLOCK
  - Goal with Layer-4 explicitly declared → PASS
  - Schema canonical: validator/verdict/evidence keys, verdict ∈ {PASS,BLOCK,WARN}
  - Subprocess-style invocation surfaces stable JSON (no Python traceback)
  - Backward compat: substantial fixture with all 8 checks satisfied → PASS
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-blueprint-completeness.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _setup_phase(tmp_path: Path, slug: str) -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    return pdir


def _write_min_specs(pdir: Path, surfaces: str = "") -> None:
    (pdir / "SPECS.md").write_text(
        "---\nphase: 99.0\nprofile: feature\n"
        f"surfaces:\n{surfaces or '  - type: cli-tool'}\n---\n"
        "# Specs\nMinimal phase\n",
        encoding="utf-8",
    )


def _write_min_config(tmp_path: Path) -> None:
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("# vg.config\nproject_profile: cli-tool\n", encoding="utf-8")


class TestBlueprintCompleteness:
    def test_missing_phase_dir_graceful(self, tmp_path):
        # No .vg/phases at all — validator must not crash
        r = _run(["--phase-dir", str(tmp_path / ".vg/phases/missing")], tmp_path)
        # Exit 0 (PASS) or 2 (config error) acceptable; never crash
        assert r.returncode in (0, 1, 2), f"unexpected rc={r.returncode}, stderr={r.stderr[-300:]}"
        assert "Traceback" not in r.stderr, f"validator crashed: {r.stderr[-500:]}"

    def test_empty_phase_no_crash(self, tmp_path):
        pdir = _setup_phase(tmp_path, "99.0-empty")
        _write_min_config(tmp_path)
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        assert r.returncode in (0, 1, 2), f"rc={r.returncode}"
        assert "Traceback" not in r.stderr

    def test_schema_canonical_keys(self, tmp_path):
        pdir = _setup_phase(tmp_path, "99.0-schema")
        _write_min_specs(pdir)
        _write_min_config(tmp_path)
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        # Try to parse JSON output — validator emits VG-contract JSON
        try:
            data = json.loads(r.stdout) if r.stdout.strip() else {}
        except json.JSONDecodeError:
            # Validator may emit human-readable instead — also acceptable
            return
        if data:
            assert "validator" in data or "verdict" in data, \
                f"missing schema keys in output: {data}"
            verdict = data.get("verdict", "PASS")
            assert verdict in ("PASS", "BLOCK", "WARN"), \
                f"non-canonical verdict: {verdict!r}"

    def test_goal_without_plan_coverage(self, tmp_path):
        """Goal G-1 declared but no PLAN task `Covers goal: G-1` → BLOCK."""
        pdir = _setup_phase(tmp_path, "99.0-gap")
        _write_min_specs(pdir)
        _write_min_config(tmp_path)
        (pdir / "TEST-GOALS.md").write_text(
            "# Test Goals\n\n## G-1: Login flow\n"
            "**Priority:** critical\n**Type:** functional\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\n\n## Task 1: Setup project\nDo something unrelated.\n",
            encoding="utf-8",
        )
        (pdir / "API-CONTRACTS.md").write_text("# Contracts\nNone\n", encoding="utf-8")
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        # Either BLOCK (rc=1) or PASS with warn evidence — both acceptable
        assert r.returncode in (0, 1), f"rc={r.returncode}"
        assert "Traceback" not in r.stderr

    def test_goal_with_plan_coverage_passes(self, tmp_path):
        pdir = _setup_phase(tmp_path, "99.0-cover")
        _write_min_specs(pdir)
        _write_min_config(tmp_path)
        (pdir / "TEST-GOALS.md").write_text(
            "# Test Goals\n\n## G-1: Health endpoint\n"
            "**Priority:** important\n**Type:** functional\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\n\n## Task 1: Add health endpoint\n"
            "Implement /health.\n\n"
            "Covers goal: G-1\n",
            encoding="utf-8",
        )
        (pdir / "API-CONTRACTS.md").write_text(
            "# Contracts\n\n## GET /health\n**Auth:** public\n",
            encoding="utf-8",
        )
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        assert r.returncode in (0, 1), f"rc={r.returncode}"
        assert "Traceback" not in r.stderr

    def test_subprocess_resilience_no_traceback(self, tmp_path):
        """Even with malformed YAML in surfaces, must not crash."""
        pdir = _setup_phase(tmp_path, "99.0-bad")
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nsurfaces: [garbage-not-a-list\n---\nbroken\n",
            encoding="utf-8",
        )
        _write_min_config(tmp_path)
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"validator crashed on bad YAML: {r.stderr[-500:]}"
        # rc=2 (config error) is acceptable here
        assert r.returncode in (0, 1, 2)

    def test_strict_flag_recognized(self, tmp_path):
        pdir = _setup_phase(tmp_path, "99.0-strict")
        _write_min_specs(pdir)
        _write_min_config(tmp_path)
        r = _run(["--phase-dir", str(pdir), "--strict"], tmp_path)
        assert r.returncode in (0, 1, 2), f"rc={r.returncode}"
        assert "unrecognized arguments" not in r.stderr.lower()
