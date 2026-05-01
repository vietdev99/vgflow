"""Tests for verify-codegen-fixture-ref.py — Codex-HIGH-3 regression guard."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-codegen-fixture-ref.py"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        env={"VG_REPO_ROOT": str(repo), "PATH": "/usr/bin:/bin",
             "PYTHONPATH": str(REPO_ROOT / "scripts")},
        capture_output=True, text=True, timeout=30,
    )


def _make_phase(tmp_path: Path, entries: dict) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "01.0-x"
    phase_dir.mkdir(parents=True)
    (phase_dir / "FIXTURES-CACHE.json").write_text(
        json.dumps({"schema_version": "1.0", "entries": entries}, indent=2),
        encoding="utf-8",
    )
    return phase_dir


def _spec(tests_dir: Path, name: str, body: str) -> Path:
    tests_dir.mkdir(parents=True, exist_ok=True)
    spec = tests_dir / name
    spec.write_text(body, encoding="utf-8")
    return spec


def test_passes_when_spec_references_fixture(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    _spec(e2e, "1.0-G-10.spec.ts",
          "test('x', async () => { console.log(FIXTURE.id); });\n")
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e")
    assert result.returncode == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["verdict"] in ("PASS", "WARN")


def test_blocks_when_spec_does_not_reference_fixture(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    _spec(e2e, "1.0-G-10.spec.ts",
          "test('x', async () => { await page.goto('/hardcoded'); });\n")
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e")
    assert result.returncode == 1, result.stdout
    out = json.loads(result.stdout)
    types = [e["type"] for e in out["evidence"]]
    assert "fixture_ref_missing" in types


def test_blocks_when_spec_missing_for_captured_goal(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    e2e.mkdir(parents=True)
    # No spec file for G-10 at all
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e")
    assert result.returncode == 1
    out = json.loads(result.stdout)
    types = [e["type"] for e in out["evidence"]]
    assert "spec_missing_for_captured_goal" in types


def test_skip_goal_without_captured_store(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"lease": {"owner_session": "x"}},  # no captured
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    e2e.mkdir(parents=True)
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    types = [e["type"] for e in out["evidence"]]
    assert "no_captured_goals" in types


def test_warn_severity_does_not_block(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    _spec(e2e, "1.0-G-10.spec.ts", "test('x', async () => {});\n")
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e",
                   "--severity", "warn")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    types = [e["type"] for e in out["evidence"]]
    assert "severity_downgraded" in types


def test_allow_no_fixture_ref_override(tmp_path):
    _make_phase(tmp_path, {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "apps" / "web" / "e2e"
    _spec(e2e, "1.0-G-10.spec.ts", "test('x', async () => {});\n")
    result = _run(tmp_path, "--phase", "1.0", "--tests-dir", "apps/web/e2e",
                   "--allow-no-fixture-ref")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    types = [e["type"] for e in out["evidence"]]
    assert "override_accepted" in types
