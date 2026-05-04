"""
Phase B.5 v2.5 (2026-04-23) — dast-scan-report.py tests.

Validates DAST JSON report parsing + severity routing by project risk profile.
Covers ZAP baseline format + Nuclei json-export format + degenerate cases
(missing file, malformed JSON, all-Low findings).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "dast-scan-report.py"


def _setup(tmp_path: Path, report_data: object | None,
           write: bool = True) -> Path:
    """Write report JSON to tmp + copy narration yaml; return report path."""
    # Copy narration tables so _i18n resolves keys (graceful even if absent).
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")

    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True, exist_ok=True)
    report_path = phase_dir / "dast-report.json"
    if write and report_data is not None:
        if isinstance(report_data, str):
            report_path.write_text(report_data, encoding="utf-8")
        else:
            report_path.write_text(json.dumps(report_data), encoding="utf-8")
    return report_path


def _run(repo: Path, report_path: Path,
         risk_profile: str = "moderate") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--phase", "9",
         "--report", str(report_path),
         "--risk-profile", risk_profile],
        cwd=repo, capture_output=True, text=True, timeout=20, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON in stdout:\n{stdout}")


# ─── Fixtures ──────────────────────────────────────────────────────────

ZAP_EMPTY = {
    "@programName": "ZAP",
    "site": [{
        "@name": "https://sandbox.example.com",
        "alerts": [],
    }],
}

def _zap_with_alerts(alerts: list[dict]) -> dict:
    return {
        "@programName": "ZAP",
        "site": [{
            "@name": "https://sandbox.example.com",
            "alerts": alerts,
        }],
    }

ZAP_HIGH = _zap_with_alerts([{
    "alert": "SQL Injection",
    "riskdesc": "High (Medium)",
    "cweid": "89",
    "desc": "SQL injection in login form",
    "instances": [{"uri": "https://sandbox.example.com/login"}],
}])

ZAP_MEDIUM = _zap_with_alerts([{
    "alert": "Missing CSP header",
    "riskdesc": "Medium",
    "cweid": "693",
    "desc": "No Content-Security-Policy header",
    "instances": [{"uri": "https://sandbox.example.com/"}],
}])

ZAP_ALL_LOW = _zap_with_alerts([
    {"alert": f"Info disclosure {i}", "riskdesc": "Low",
     "cweid": "200", "desc": "Minor leak",
     "instances": [{"uri": f"https://sandbox.example.com/p{i}"}]}
    for i in range(3)
])

NUCLEI_CRITICAL = [{
    "template-id": "CVE-2024-12345",
    "info": {
        "name": "Remote code execution",
        "severity": "critical",
        "description": "RCE via unauth endpoint",
        "classification": {"cwe-id": ["cwe-78"]},
    },
    "matched-at": "https://sandbox.example.com/admin",
    "host": "sandbox.example.com",
}]


# ─── Tests ─────────────────────────────────────────────────────────────

def test_zap_zero_findings_pass(tmp_path):
    rp = _setup(tmp_path, ZAP_EMPTY)
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"
    assert out["evidence"] == []


def test_zap_high_risk_critical_blocks(tmp_path):
    rp = _setup(tmp_path, ZAP_HIGH)
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "dast_critical_high_findings"
               for e in out["evidence"])


def test_zap_high_risk_moderate_warns(tmp_path):
    rp = _setup(tmp_path, ZAP_HIGH)
    r = _run(tmp_path, rp, risk_profile="moderate")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "dast_medium_findings_advisory"
               for e in out["evidence"])


def test_zap_medium_risk_critical_warns(tmp_path):
    rp = _setup(tmp_path, ZAP_MEDIUM)
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    # Medium alone never blocks — should be WARN even on critical profile.
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "dast_medium_findings_advisory"
               for e in out["evidence"])


def test_nuclei_critical_risk_critical_blocks(tmp_path):
    rp = _setup(tmp_path, NUCLEI_CRITICAL)
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "dast_critical_high_findings"
               for e in out["evidence"])


def test_malformed_json_warns(tmp_path):
    rp = _setup(tmp_path, "{this is not: valid JSON,,,")
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "dast_report_unparseable"
               for e in out["evidence"])


def test_missing_report_file_skips(tmp_path):
    # Don't write report file at all
    rp = _setup(tmp_path, None, write=False)
    assert not rp.exists()
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "dast_scan_skipped"
               for e in out["evidence"])


def test_all_low_severity_risk_critical_pass(tmp_path):
    rp = _setup(tmp_path, ZAP_ALL_LOW)
    r = _run(tmp_path, rp, risk_profile="critical")
    out = _parse(r.stdout)
    # Low findings alone never block or warn.
    assert r.returncode == 0
    assert out["verdict"] == "PASS"
    assert out["evidence"] == []
