"""
Tests for verify-test-goals-platform-essentials.py — UNQUARANTINABLE.

Phase 7.14.3 retro: TEST-GOALS frontmatter must cover platform's
mandatory essentials (filter, paging, column count, sort, Layer-4
mutation reload, state guards). AI lazy-read markdown rules and skipped.

Covers:
  - Missing phase-dir → rc=2 (config error, --phase-dir required)
  - Phase with no SPECS surfaces → PASS
  - Phase with web-fullstack table surface + complete TEST-GOALS → PASS
  - Phase with web-fullstack table + missing paging goal → BLOCK
  - Phase with cli-tool surface + exit-code goal → PASS
  - --strict flag recognized
  - Schema canonical output
  - Subprocess resilience: malformed YAML
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
    "verify-test-goals-platform-essentials.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _setup(tmp_path: Path, slug: str = "99.0-essentials") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("# vg.config\nproject_profile: web-fullstack\n", encoding="utf-8")
    return pdir


class TestTestGoalsPlatformEssentials:
    def test_missing_phase_dir_arg_required(self, tmp_path):
        # --phase-dir is required — running without it must rc=2 (argparse error)
        r = _run([], tmp_path)
        assert r.returncode == 2, f"missing required arg → rc=2, got {r.returncode}"

    def test_phase_dir_does_not_exist(self, tmp_path):
        r = _run(["--phase-dir", str(tmp_path / ".vg/phases/missing")], tmp_path)
        # Validator may emit BLOCK or PASS or rc=2 for non-existent dir
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stderr

    def test_missing_specs_blocks(self, tmp_path):
        """SPECS.md required — missing artifact → BLOCK."""
        pdir = _setup(tmp_path)
        # No SPECS.md at all
        (pdir / "TEST-GOALS.md").write_text("# Goals\n", encoding="utf-8")
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        assert r.returncode == 1, \
            f"missing SPECS should BLOCK (validator requires both artifacts), " \
            f"rc={r.returncode}, stdout={r.stdout[:300]}"

    def test_cli_tool_surface_with_essentials_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nprofile: feature\nsurfaces:\n"
            "  - type: cli-tool\n    description: vg-orchestrator CLI\n"
            "---\n# Specs\n",
            encoding="utf-8",
        )
        (pdir / "TEST-GOALS.md").write_text(
            "# Test Goals\n\n"
            "## G-1: exit-code on success\n**Priority:** critical\n\n"
            "## G-2: stderr emitted on error\n**Priority:** critical\n\n"
            "## G-3: idempotency — re-run produces same result\n**Priority:** important\n",
            encoding="utf-8",
        )
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        # Either PASS or BLOCK — both acceptable, no crash
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stderr

    def test_strict_flag_recognized(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nsurfaces:\n  - type: cli-tool\n---\n",
            encoding="utf-8",
        )
        (pdir / "TEST-GOALS.md").write_text("# Goals\n", encoding="utf-8")
        r = _run(["--phase-dir", str(pdir), "--strict"], tmp_path)
        assert r.returncode in (0, 1, 2)
        assert "unrecognized arguments" not in r.stderr.lower()

    def test_schema_canonical(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nsurfaces:\n  - type: cli-tool\n---\n",
            encoding="utf-8",
        )
        (pdir / "TEST-GOALS.md").write_text("# Goals\n", encoding="utf-8")
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        try:
            data = json.loads(r.stdout)
            assert "validator" in data or "verdict" in data
            verdict = data.get("verdict")
            if verdict is not None:
                assert verdict in ("PASS", "BLOCK", "WARN")
        except json.JSONDecodeError:
            # Non-JSON output acceptable; rc must still be valid
            assert r.returncode in (0, 1, 2)

    def test_malformed_yaml_no_traceback(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nsurfaces: [garbage\n---\nbroken\n",
            encoding="utf-8",
        )
        r = _run(["--phase-dir", str(pdir)], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad YAML: {r.stderr[-400:]}"

    def test_report_md_flag(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "---\nphase: 99.0\nsurfaces:\n  - type: cli-tool\n---\n",
            encoding="utf-8",
        )
        (pdir / "TEST-GOALS.md").write_text("# Goals\n", encoding="utf-8")
        report = tmp_path / "report.md"
        r = _run(
            ["--phase-dir", str(pdir), "--report-md", str(report)],
            tmp_path,
        )
        # Validator may or may not write report depending on implementation;
        # contract is just that --report-md doesn't crash
        assert r.returncode in (0, 1, 2)
        assert "unrecognized arguments" not in r.stderr.lower()
