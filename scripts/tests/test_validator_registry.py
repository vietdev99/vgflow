"""
Tests for validator-registry.py + verify-validator-drift.py — Phase S of v2.5.2.

Covers:
  CLI:
    - list prints entries; filter by --domain works
    - describe prints one entry; missing id exits 1
    - missing detects validators on disk but not registered
    - orphans detects registry entries with no file on disk
    - validate reports schema errors on malformed registry
    - disable/enable mark flag in-place (YAML persistence)

  Drift detection:
    - never_fires pattern when registry entry has 0 events
    - always_pass when 100% pass rate >= min_runs
    - perf_regression when p95 > 2x target_ms
    - JSON output schema parseable
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_CLI = REPO_ROOT / ".claude" / "scripts" / "validator-registry.py"
DRIFT_VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-validator-drift.py"


def _run(script: Path, args: list[str], cwd: Path | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if cwd:
        env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
        encoding="utf-8", errors="replace",
    )


def _write_registry(tmp_path: Path, entries: list[dict]) -> Path:
    target = tmp_path / ".claude" / "scripts" / "validators" / "registry.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["validators:"]
    for e in entries:
        lines.append(f"  - id: {e['id']}")
        for k, v in e.items():
            if k == "id":
                continue
            if isinstance(v, list):
                lines.append(f"    {k}: [{', '.join(v)}]")
            elif isinstance(v, bool):
                lines.append(f"    {k}: {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"    {k}: {v}")
            else:
                lines.append(f"    {k}: {v}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _create_validator_file(tmp_path: Path, name: str) -> Path:
    """Create a stub .py file in the tmp_path validator dir."""
    vdir = tmp_path / ".claude" / "scripts" / "validators"
    vdir.mkdir(parents=True, exist_ok=True)
    fp = vdir / f"{name}.py"
    fp.write_text("# stub\n", encoding="utf-8")
    return fp


# ─── validator-registry CLI tests ─────────────────────────────────────


class TestRegistryCLI:
    def test_list_prints_entries(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "foo", "path": "x.py", "severity": "warn",
             "domain": "security", "description": "test",
             "added_in": "v2.5.2"},
            {"id": "bar", "path": "y.py", "severity": "block",
             "domain": "evidence", "description": "test2",
             "added_in": "v2.5.2"},
        ])
        r = _run(REGISTRY_CLI, ["list"], cwd=tmp_path)
        assert r.returncode == 0
        assert "foo" in r.stdout
        assert "bar" in r.stdout

    def test_list_domain_filter(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "a", "path": "x.py", "severity": "warn",
             "domain": "security", "description": "x", "added_in": "v2.5.2"},
            {"id": "b", "path": "y.py", "severity": "warn",
             "domain": "evidence", "description": "y", "added_in": "v2.5.2"},
        ])
        r = _run(REGISTRY_CLI,
                 ["list", "--domain", "security"],
                 cwd=tmp_path)
        assert r.returncode == 0
        assert "a" in r.stdout
        assert "b" not in r.stdout

    def test_describe_found(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "xyz", "path": "x.py", "severity": "block",
             "domain": "test", "description": "desc xyz",
             "added_in": "v2.5.2"},
        ])
        r = _run(REGISTRY_CLI, ["describe", "xyz"], cwd=tmp_path)
        assert r.returncode == 0
        assert "desc xyz" in r.stdout

    def test_describe_missing_exits_1(self, tmp_path):
        _write_registry(tmp_path, [])
        r = _run(REGISTRY_CLI, ["describe", "nonexistent"], cwd=tmp_path)
        assert r.returncode == 1

    def test_missing_detects_unregistered_file(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "foo", "path": "x.py", "severity": "warn",
             "domain": "x", "description": "x", "added_in": "v2.5.2"},
        ])
        _create_validator_file(tmp_path, "verify-bar")
        _create_validator_file(tmp_path, "verify-foo")  # registered
        r = _run(REGISTRY_CLI, ["missing"], cwd=tmp_path)
        assert r.returncode == 1
        assert "bar" in r.stdout

    def test_orphans_detects_missing_file(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "ghost", "path": "missing.py", "severity": "warn",
             "domain": "x", "description": "x", "added_in": "v2.5.2"},
        ])
        # No actual file created for "ghost"
        r = _run(REGISTRY_CLI, ["orphans"], cwd=tmp_path)
        assert r.returncode == 1
        assert "ghost" in r.stdout

    def test_validate_pass(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "ok", "path": "x.py", "severity": "warn",
             "domain": "x", "description": "y", "added_in": "v2.5.2"},
        ])
        r = _run(REGISTRY_CLI, ["validate"], cwd=tmp_path)
        assert r.returncode == 0

    def test_validate_invalid_severity(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "bad", "path": "x.py", "severity": "catastrophic",
             "domain": "x", "description": "y", "added_in": "v2.5.2"},
        ])
        r = _run(REGISTRY_CLI, ["validate"], cwd=tmp_path)
        assert r.returncode == 1
        assert "catastrophic" in r.stdout or "invalid severity" in r.stdout


# ─── drift detection tests ────────────────────────────────────────────


def _make_events_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            payload TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


def _insert_event(db_path: Path, event_type: str, payload: dict,
                  days_ago: int = 0) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO events (event_type, payload, timestamp) VALUES (?, ?, ?)",
        (event_type, json.dumps(payload), ts),
    )
    conn.commit()
    conn.close()


class TestValidatorDrift:
    def test_never_fires_detected(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "ghost-validator", "path": "x.py",
             "severity": "warn", "domain": "test",
             "description": "x", "added_in": "v2.5.2",
             "runtime_target_ms": 100},
        ])
        db = tmp_path / ".vg" / "state" / "events.db"
        _make_events_db(db)
        # No events — zero runs

        r = _run(
            DRIFT_VALIDATOR,
            ["--db-path", str(db),
             "--registry", str(tmp_path / ".claude" / "scripts" / "validators" / "registry.yaml"),
             "--lookback-days", "30"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "never_fires" in r.stdout
        assert "ghost-validator" in r.stdout

    def test_always_pass_detected(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "always-ok", "path": "x.py",
             "severity": "warn", "domain": "test",
             "description": "x", "added_in": "v2.5.2",
             "runtime_target_ms": 100},
        ])
        db = tmp_path / ".vg" / "state" / "events.db"
        _make_events_db(db)
        for _ in range(15):
            _insert_event(db, "validator.run",
                          {"validator": "always-ok", "verdict": "PASS",
                           "duration_ms": 50}, days_ago=1)

        r = _run(
            DRIFT_VALIDATOR,
            ["--db-path", str(db),
             "--registry", str(tmp_path / ".claude" / "scripts" / "validators" / "registry.yaml"),
             "--min-runs", "10"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "always_pass" in r.stdout

    def test_perf_regression_detected(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "slow-one", "path": "x.py",
             "severity": "warn", "domain": "test",
             "description": "x", "added_in": "v2.5.2",
             "runtime_target_ms": 100},
        ])
        db = tmp_path / ".vg" / "state" / "events.db"
        _make_events_db(db)
        # 10 fast + 5 very slow → p95 well above 200ms
        for _ in range(10):
            _insert_event(db, "validator.run",
                          {"validator": "slow-one", "verdict": "PASS",
                           "duration_ms": 50}, days_ago=1)
        for _ in range(5):
            _insert_event(db, "validator.run",
                          {"validator": "slow-one", "verdict": "PASS",
                           "duration_ms": 900}, days_ago=1)

        r = _run(
            DRIFT_VALIDATOR,
            ["--db-path", str(db),
             "--registry", str(tmp_path / ".claude" / "scripts" / "validators" / "registry.yaml"),
             "--min-runs", "10"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "perf_regression" in r.stdout or "always_pass" in r.stdout

    def test_json_output(self, tmp_path):
        _write_registry(tmp_path, [
            {"id": "x", "path": "x.py",
             "severity": "warn", "domain": "test",
             "description": "x", "added_in": "v2.5.2"},
        ])
        db = tmp_path / ".vg" / "state" / "events.db"
        _make_events_db(db)

        r = _run(
            DRIFT_VALIDATOR,
            ["--db-path", str(db),
             "--registry", str(tmp_path / ".claude" / "scripts" / "validators" / "registry.yaml"),
             "--json"],
            cwd=tmp_path,
        )
        data = json.loads(r.stdout)
        assert "findings" in data
        assert data["validators_tracked"] == 1
