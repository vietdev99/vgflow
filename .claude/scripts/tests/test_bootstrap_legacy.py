"""
Tests for v2.5.2.1 Fix 3: bootstrap-legacy-artifacts.py +
verify-no-legacy-manifest-creation.py.

Closes CrossAI round 3 finding: no migration path for Phase 17+ cutover
referencing grandfathered phase 0-16 artifacts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_SCRIPT = REPO_ROOT / ".claude" / "scripts" / \
    "bootstrap-legacy-artifacts.py"
NO_LEGACY_VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-no-legacy-manifest-creation.py"


def _run(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd), env=env,
        encoding="utf-8", errors="replace",
    )


def _make_phase(root: Path, phase_name: str,
                artifacts: dict[str, str]) -> Path:
    phase_dir = root / ".vg" / "phases" / phase_name
    phase_dir.mkdir(parents=True, exist_ok=True)
    for rel_name, content in artifacts.items():
        fp = phase_dir / rel_name
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return phase_dir


# ─── bootstrap-legacy-artifacts.py tests ───────────────────────────────


class TestBootstrap:
    def test_dry_run_reports_orphan_artifacts(self, tmp_path):
        _make_phase(tmp_path, "7.14-test", {
            "PLAN.md": "# plan",
            "API-CONTRACTS.md": "# contracts",
        })
        r = _run(BOOTSTRAP_SCRIPT, [], cwd=tmp_path)
        assert r.returncode == 1  # drift detected
        assert "2 new entries" in r.stdout or "2 artifacts" in r.stdout

    def test_apply_writes_manifest(self, tmp_path):
        _make_phase(tmp_path, "7.14-test", {
            "PLAN.md": "# plan",
            "SUMMARY.md": "# summary",
        })
        r = _run(BOOTSTRAP_SCRIPT, ["--apply"], cwd=tmp_path)
        assert r.returncode == 0
        manifest_file = tmp_path / ".vg" / "runs" / "legacy-bootstrap" / \
                        "evidence-manifest.json"
        assert manifest_file.exists()
        m = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert len(m["entries"]) == 2
        for e in m["entries"]:
            assert e["creator_run_id"] == "legacy-bootstrap"
            assert e["grandfathered"] is True
            assert e["phase"] == "7.14-test"

    def test_idempotent(self, tmp_path):
        _make_phase(tmp_path, "7-test", {"PLAN.md": "# plan"})
        r1 = _run(BOOTSTRAP_SCRIPT, ["--apply"], cwd=tmp_path)
        assert r1.returncode == 0
        # Second run: already cataloged
        r2 = _run(BOOTSTRAP_SCRIPT, [], cwd=tmp_path)
        assert r2.returncode == 0
        assert "0 new entries" in r2.stdout

    def test_phase_filter(self, tmp_path):
        _make_phase(tmp_path, "7.1-a", {"PLAN.md": "x"})
        _make_phase(tmp_path, "7.2-b", {"PLAN.md": "y"})
        r = _run(BOOTSTRAP_SCRIPT, ["--apply", "--phase", "7.1"], cwd=tmp_path)
        assert r.returncode == 0
        m = json.loads((tmp_path / ".vg" / "runs" / "legacy-bootstrap" /
                        "evidence-manifest.json").read_text(encoding="utf-8"))
        assert len(m["entries"]) == 1
        assert m["entries"][0]["phase"] == "7.1-a"

    def test_json_output(self, tmp_path):
        _make_phase(tmp_path, "3-test", {"PLAN.md": "p"})
        r = _run(BOOTSTRAP_SCRIPT, ["--apply", "--json"], cwd=tmp_path)
        data = json.loads(r.stdout)
        assert data["new_manifest_entries"] == 1
        assert data["mode"] == "apply"


# ─── verify-no-legacy-manifest-creation.py tests ──────────────────────


class TestNoLegacyCreation:
    def test_clean_when_all_pre_cutover(self, tmp_path):
        _make_phase(tmp_path, "5-early", {"PLAN.md": "x"})
        # Bootstrap pre-cutover phase
        r = _run(BOOTSTRAP_SCRIPT, ["--apply"], cwd=tmp_path)
        assert r.returncode == 0
        # Validate: cutover 17, phase 5 is below → clean
        r = _run(NO_LEGACY_VALIDATOR,
                 ["--cutover-phase", "17", "--quiet"], cwd=tmp_path)
        assert r.returncode == 0

    def test_blocks_post_cutover_legacy(self, tmp_path):
        _make_phase(tmp_path, "20-future", {"PLAN.md": "x"})
        _run(BOOTSTRAP_SCRIPT, ["--apply"], cwd=tmp_path)
        # Phase 20 > cutover 17 → BLOCK
        r = _run(NO_LEGACY_VALIDATOR,
                 ["--cutover-phase", "17"], cwd=tmp_path)
        assert r.returncode == 1
        assert "20" in r.stdout

    def test_blocks_grandfather_flag_on_other_run(self, tmp_path):
        # Create a non-bootstrap run with grandfathered entry (forge attempt)
        fake_run = tmp_path / ".vg" / "runs" / "some-real-run-uuid"
        fake_run.mkdir(parents=True)
        (fake_run / "evidence-manifest.json").write_text(json.dumps({
            "run_id": "some-real-run-uuid",
            "entries": [{
                "path": "x/y.md",
                "sha256": "abc",
                "creator_run_id": "legacy-bootstrap",
                "grandfathered": True,
                "phase": "18-post-cutover",
            }],
        }), encoding="utf-8")
        r = _run(NO_LEGACY_VALIDATOR,
                 ["--cutover-phase", "17"], cwd=tmp_path)
        assert r.returncode == 1
        assert "grandfathered entry" in r.stdout or "bootstrap" in r.stdout

    def test_unparseable_phase_warns_not_blocks(self, tmp_path):
        # Manifest with a weird phase ref
        legacy = tmp_path / ".vg" / "runs" / "legacy-bootstrap"
        legacy.mkdir(parents=True)
        (legacy / "evidence-manifest.json").write_text(json.dumps({
            "run_id": "legacy-bootstrap",
            "entries": [{
                "path": "weird.md",
                "sha256": "abc",
                "creator_run_id": "legacy-bootstrap",
                "phase": "",  # blank
                "grandfathered": True,
            }],
        }), encoding="utf-8")
        r = _run(NO_LEGACY_VALIDATOR,
                 ["--cutover-phase", "17"], cwd=tmp_path)
        # warn severity only → exit 0
        assert r.returncode == 0

    def test_json_output(self, tmp_path):
        _make_phase(tmp_path, "19-over", {"PLAN.md": "x"})
        _run(BOOTSTRAP_SCRIPT, ["--apply"], cwd=tmp_path)
        r = _run(NO_LEGACY_VALIDATOR,
                 ["--cutover-phase", "17", "--json"], cwd=tmp_path)
        data = json.loads(r.stdout)
        assert data["blocking_count"] >= 1
