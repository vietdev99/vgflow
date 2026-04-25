"""
Tests for verify-no-legacy-manifest-creation.py — UNQUARANTINABLE.

Per orchestrator allowlist: "letting AI fail 3x to disable would let it
re-introduce the grandfather exemption to itself." This validator BLOCKS
phases > cutover from forging `creator_run_id: legacy-bootstrap` markers.

Covers:
  - No manifest at all → PASS (nothing to check)
  - Empty entries list → PASS
  - Phase ≤ cutover with legacy entry → PASS (grandfathered)
  - Phase > cutover with legacy entry → BLOCK (forge attempt)
  - Phase 7.14 vs cutover 17 → PASS (7.14 < 17)
  - Phase 18 vs cutover 17 → BLOCK
  - Non-bootstrap run with grandfathered=true flag → BLOCK
  - --json flag emits structured output
  - Unparseable manifest → rc=2 (config error)
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
    "verify-no-legacy-manifest-creation.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    bootstrap_dir = tmp_path / ".vg" / "runs" / "legacy-bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    manifest = bootstrap_dir / "evidence-manifest.json"
    manifest.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return manifest


class TestNoLegacyManifestCreation:
    def test_no_manifest_passes(self, tmp_path):
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}, stderr={r.stderr}"

    def test_empty_entries_passes(self, tmp_path):
        _write_manifest(tmp_path, [])
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 0

    def test_pre_cutover_phase_grandfathered(self, tmp_path):
        _write_manifest(tmp_path, [
            {"path": ".vg/old/foo.json", "phase": "7.14", "creator_run_id": "legacy-bootstrap"},
        ])
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 0, f"7.14 < 17 should PASS, got rc={r.returncode}, stdout={r.stdout}"

    def test_post_cutover_phase_blocks(self, tmp_path):
        _write_manifest(tmp_path, [
            {"path": ".vg/new/forged.json", "phase": "18.0", "creator_run_id": "legacy-bootstrap"},
        ])
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 1, \
            f"18.0 > 17 should BLOCK, got rc={r.returncode}, stdout={r.stdout}"
        assert "18" in r.stdout or "18" in r.stderr

    def test_decimal_phase_boundary(self, tmp_path):
        # cutover=17 means 17.5 should still PASS (≤ 17 fails as 17.5 > 17 → BLOCK)
        # Actually per code: phase_num > cutover → block. So 17.5 > 17 → block.
        _write_manifest(tmp_path, [
            {"path": ".vg/x.json", "phase": "17.5-foo", "creator_run_id": "legacy-bootstrap"},
        ])
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 1, "17.5 > 17 should BLOCK"

    def test_json_output_structured(self, tmp_path):
        _write_manifest(tmp_path, [
            {"path": ".vg/forge.json", "phase": "20.0"},
        ])
        r = _run(["--cutover-phase", "17", "--json"], tmp_path)
        # Validator emits its own JSON shape (not _common Output schema)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"--json should emit parseable JSON, got: {r.stdout[:200]}")
        assert "violations" in data, f"missing violations key: {data}"
        assert "blocking_count" in data
        assert "cutover_phase" in data

    def test_grandfather_drift_in_other_run_blocks(self, tmp_path):
        # Non-bootstrap run emitting grandfathered=true → BLOCK
        other_run = tmp_path / ".vg" / "runs" / "abc12345"
        other_run.mkdir(parents=True)
        (other_run / "evidence-manifest.json").write_text(
            json.dumps({"entries": [
                {"path": "apps/api/foo.ts", "grandfathered": True, "phase": "20.0"},
            ]}), encoding="utf-8",
        )
        # Also need legacy-bootstrap manifest absent / empty so only drift fires
        r = _run(["--cutover-phase", "17"], tmp_path)
        assert r.returncode == 1, \
            f"non-bootstrap run with grandfathered=true should BLOCK, rc={r.returncode}, stdout={r.stdout}"

    def test_unparseable_manifest_returns_config_error(self, tmp_path):
        bootstrap_dir = tmp_path / ".vg" / "runs" / "legacy-bootstrap"
        bootstrap_dir.mkdir(parents=True)
        (bootstrap_dir / "evidence-manifest.json").write_text("{not json", encoding="utf-8")
        r = _run([], tmp_path)
        assert r.returncode == 2, f"unparseable manifest should rc=2, got rc={r.returncode}"
