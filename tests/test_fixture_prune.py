"""Tests for scripts/fixture-prune.py — RFC v9 PR-F."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fixture-prune.py"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )


def _phase(tmp_path: Path, name: str, cache: dict, goals_md: str = "") -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / name
    phase_dir.mkdir(parents=True)
    (phase_dir / "FIXTURES-CACHE.json").write_text(
        json.dumps(cache, indent=2), encoding="utf-8",
    )
    if goals_md:
        (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    return phase_dir


def _expired_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(timespec="seconds")


def _fresh_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat(timespec="seconds")


def test_dry_run_does_not_mutate(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {
            "G-1": {"lease": {"owner_session": "s", "expires_at": _expired_iso(),
                              "consume_semantics": "destructive"}},
        },
    }, goals_md="## Goal G-1: x\n")
    result = _run(tmp_path, "--phase", "1.0", "--dry-run")
    assert result.returncode == 0, result.stderr
    after = json.loads((phase_dir / "FIXTURES-CACHE.json").read_text())
    assert "lease" in after["entries"]["G-1"]


def test_apply_reaps_expired_leases(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {
            "G-1": {"lease": {"owner_session": "s", "expires_at": _expired_iso(),
                              "consume_semantics": "destructive"}},
            "G-2": {"lease": {"owner_session": "s", "expires_at": _fresh_iso(),
                              "consume_semantics": "destructive"}},
        },
    }, goals_md="## Goal G-1: x\n## Goal G-2: y\n")
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0, result.stderr
    after = json.loads((phase_dir / "FIXTURES-CACHE.json").read_text())
    assert "lease" not in after["entries"]["G-1"]  # expired → reaped
    assert "lease" in after["entries"]["G-2"]  # fresh → kept


def test_apply_reaps_orphans(tmp_path):
    """Cache has G-orphan but TEST-GOALS only declares G-keep."""
    phase_dir = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {
            "G-keep": {"captured": {"x": 1}},
            "G-orphan": {"captured": {"y": 2}},
        },
    }, goals_md="## Goal G-keep: keep me\n")
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0, result.stderr
    after = json.loads((phase_dir / "FIXTURES-CACHE.json").read_text())
    assert "G-orphan" not in after["entries"]
    assert "G-keep" in after["entries"]


def test_skip_orphans_only_reaps_leases(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {
            "G-orphan": {"lease": {"owner_session": "s",
                                    "expires_at": _expired_iso(),
                                    "consume_semantics": "destructive"}},
        },
    }, goals_md="")  # no TEST-GOALS → orphan
    result = _run(tmp_path, "--phase", "1.0", "--apply", "--skip-orphans")
    assert result.returncode == 0
    # Lease reaped; entry kept
    after = json.loads((phase_dir / "FIXTURES-CACHE.json").read_text())
    assert "G-orphan" in after["entries"]
    assert "lease" not in after["entries"]["G-orphan"]


def test_skip_leases_only_reaps_orphans(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {
            "G-orphan": {"lease": {"owner_session": "s",
                                    "expires_at": _expired_iso(),
                                    "consume_semantics": "destructive"}},
        },
    }, goals_md="## Goal G-keep: keep me\n")
    result = _run(tmp_path, "--phase", "1.0", "--apply", "--skip-leases")
    assert result.returncode == 0
    after = json.loads((phase_dir / "FIXTURES-CACHE.json").read_text())
    assert "G-orphan" not in after["entries"]


def test_all_phases_processes_each(tmp_path):
    p1 = _phase(tmp_path, "01.0-x", {
        "schema_version": "1.0",
        "entries": {"G-1": {"captured": {}}},
    }, goals_md="")
    p2 = _phase(tmp_path, "02.0-y", {
        "schema_version": "1.0",
        "entries": {"G-2": {"captured": {}}},
    }, goals_md="## Goal G-2: y\n")
    result = _run(tmp_path, "--all-phases", "--apply")
    assert result.returncode == 0
    after_p1 = json.loads((p1 / "FIXTURES-CACHE.json").read_text())
    after_p2 = json.loads((p2 / "FIXTURES-CACHE.json").read_text())
    # Phase 1 has no TEST-GOALS → no orphan list available, so entries kept.
    # Phase 2 has G-2 declared, so G-2 is kept.
    assert "G-2" in after_p2["entries"]


def test_phase_or_all_required(tmp_path):
    result = _run(tmp_path, "--apply")
    assert result.returncode != 0


def test_skip_both_rejected(tmp_path):
    result = _run(tmp_path, "--phase", "1.0", "--apply",
                  "--skip-leases", "--skip-orphans")
    assert result.returncode != 0


def test_dry_run_or_apply_required(tmp_path):
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode != 0
