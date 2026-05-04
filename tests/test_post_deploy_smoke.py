"""Post-deploy smoke + PRE-TEST-REPORT writer."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRITER = REPO / "scripts" / "validators" / "write-pre-test-report.py"


def test_writer_renders_pretty_report(tmp_path: Path) -> None:
    t12_report = tmp_path / "t12.json"
    t12_report.write_text(json.dumps({
        "phase": "test-1.0",
        "started_at": "2026-05-03T10:00:00Z",
        "tier_1": {
            "typecheck":      {"status": "PASS", "duration_ms": 1200},
            "lint":           {"status": "PASS", "duration_ms": 800},
            "debug_leftover": {"status": "PASS", "evidence": [], "duration_ms": 50},
        },
        "tier_2": {"status": "PASS", "runner": "vitest", "duration_ms": 8400},
        "completed_at": "2026-05-03T10:00:11Z",
    }), encoding="utf-8")

    deploy_report = tmp_path / "deploy.json"
    deploy_report.write_text(json.dumps({
        "decision": "sandbox",
        "deployed": True,
        "deploy_url": "https://sandbox.example.com",
        "deploy_duration_ms": 45000,
        "smoke_health_check": {"status": "PASS", "endpoint": "/health", "code": 200},
        "smoke_test_run": {"status": "PASS", "spec_count": 5, "duration_ms": 6000},
    }), encoding="utf-8")

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(WRITER),
        "--phase", "test-1.0",
        "--t12-report", str(t12_report),
        "--deploy-report", str(deploy_report),
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    md = out.read_text(encoding="utf-8")
    assert "# Pre-Test Report — test-1.0" in md
    assert "## Tier 1 — Static checks" in md
    assert "## Tier 2 — Local tests" in md
    assert "## Deploy + post-deploy smoke" in md
    assert "vitest" in md
    assert "https://sandbox.example.com" in md


def test_writer_handles_no_deploy(tmp_path: Path) -> None:
    t12_report = tmp_path / "t12.json"
    t12_report.write_text(json.dumps({
        "phase": "test-1.0",
        "started_at": "2026-05-03T10:00:00Z",
        "tier_1": {"typecheck": {"status": "PASS", "duration_ms": 0},
                   "lint": {"status": "SKIPPED", "reason": "no tool", "duration_ms": 0},
                   "debug_leftover": {"status": "PASS", "evidence": [], "duration_ms": 0}},
        "tier_2": {"status": "SKIPPED", "reason": "no tests"},
        "completed_at": "2026-05-03T10:00:01Z",
    }), encoding="utf-8")

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(WRITER),
        "--phase", "test-1.0",
        "--t12-report", str(t12_report),
        "--no-deploy",
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    md = out.read_text(encoding="utf-8")
    assert "Deploy: SKIPPED" in md
