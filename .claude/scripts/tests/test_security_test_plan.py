"""
Phase D v2.5 (2026-04-23) — verify-security-test-plan.py tests.

8 test cases covering:
1. Complete valid STP → PASS
2. Missing file + phase < cutover → skip (rc=0)
3. Missing file + phase >= 14 → BLOCK
4. Invalid risk_profile value → BLOCK
5. Critical risk + DAST=None → BLOCK
6. FOUNDATION mentions GDPR + STP §6 says "none" → WARN
7. §5 empty when approach != "none" → BLOCK
8. All enums valid + consistent with FOUNDATION → PASS
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (
    REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-security-test-plan.py"
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _copy_narration(tmp_path: Path) -> None:
    """Copy narration YAML files so _i18n.t() resolves keys properly."""
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"), encoding="utf-8")


def _setup(
    tmp_path: Path,
    stp_md: str | None = None,
    foundation_md: str | None = None,
    phase_dir: bool = True,
) -> Path:
    """Scaffold tmp repo with optional STP file, FOUNDATION, and phase dir."""
    _copy_narration(tmp_path)
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir(parents=True, exist_ok=True)

    if stp_md is not None:
        (vg_dir / "SECURITY-TEST-PLAN.md").write_text(stp_md, encoding="utf-8")

    if foundation_md is not None:
        (vg_dir / "FOUNDATION.md").write_text(foundation_md, encoding="utf-8")

    if phase_dir:
        (vg_dir / "phases" / "09-test").mkdir(parents=True, exist_ok=True)

    return tmp_path


def _run(repo: Path, phase: str = "9") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", phase],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON in stdout:\n{stdout}")


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

VALID_STP = """\
# Security Test Plan — TestProject

Generated: 2026-04-23T00:00:00Z
FOUNDATION §9 reference: .vg/FOUNDATION.md
Last updated: 2026-04-23T00:00:00Z

---

## 1. Risk Classification

**Risk profile:** `moderate`

**Justification:**
Internal tool with external users; processes user PII but no payment data.

**Implications:**
- DAST severity: High finding = WARN
- Pen-test frequency: quarterly
- Incident response SLA: moderate=24hr

---

## 2. DAST (Dynamic Application Security Testing)

**Tool:** `ZAP`
**Payload profile:** `owasp-top10-2021`
**Scan timeout:** `300`
**Scan frequency:** every `/vg:test` step 5h

---

## 3. Static Analysis (SAST)

Beyond VG's built-in validators (verify-goal-security / verify-security-baseline):
- `Semgrep` for `TypeScript` — detects injection, path traversal, crypto misuse
- Check frequency: on-commit via pre-commit

---

## 4. Pen-Test Strategy

**Approach:** `internal-team-quarterly`
**Scope:** All API endpoints + SSP Admin + Publisher dashboards
**Vendor contact:** N/A — internal team
**Last test date:** pending milestone M1 completion
**Next scheduled:** Q3 2026

---

## 5. Bug Bounty (if applicable)

**Platform:** `none`
**Scope:** N/A — no public bug bounty program
**Out of scope:** DoS, staff accounts, 3rd-party dependencies
**Reward tier:**
- Critical: N/A
- High: N/A
- Medium: N/A
- Low: N/A
**Disclosure timeline:** 90 days standard

---

## 6. Compliance Framework Mapping

**Framework:** `GDPR`

**Control list:**
- Art. 25 (Data protection by design) → verify-authz-declared + FOUNDATION §9.5 PII handling
- Art. 32 (Security of processing) → verify-security-baseline + TLS 1.3 enforcement
- Art. 33 (Breach notification) → Incident Response §7 SLA 72hr notification

---

## 7. Incident Response

**IR team contact:** security@vollx.com / Slack #security-oncall
**Escalation path:** L1 (on-call engineer) → L2 (tech lead) → CTO within 4hrs
**Public disclosure policy:** 30-day after fix
**Post-mortem SLA:** 5 business days after incident closure

---

## 8. Acceptable Residual Risk

**Threshold:** `severity-based`

Examples:
- Critical severity: 0 days acceptable — must block ship
- High severity: 7 days acceptable with compensating control
- Medium severity: 30 days acceptable with scheduled fix
- Low severity: 90 days acceptable backlog

**Debt register integration:** security debt appended to `.vg/override-debt/register.jsonl` via `/vg:override-resolve`
"""

VALID_FOUNDATION_WITH_GDPR = """\
# FOUNDATION

## 9. Architecture & Security

### 9.5 Security Model

Authentication: JWT + session cookies (SameSite=Strict).
Data sensitivity: user PII stored — GDPR compliance required.
Audit log events: login, logout, data export, admin actions.
"""

VALID_FOUNDATION_NO_GDPR = """\
# FOUNDATION

## 9. Architecture & Security

### 9.5 Security Model

Authentication: JWT + session cookies.
No special compliance framework required.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Test Cases
# ──────────────────────────────────────────────────────────────────────────────

def test_complete_valid_stp_passes(tmp_path):
    """Test 1: Complete valid SECURITY-TEST-PLAN.md → PASS."""
    repo = _setup(tmp_path, stp_md=VALID_STP, foundation_md=VALID_FOUNDATION_WITH_GDPR)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_missing_file_before_cutover_skips(tmp_path):
    """Test 2: Missing file + phase < 14 → skip (rc=0, no evidence)."""
    repo = _setup(tmp_path, stp_md=None)  # no STP file
    r = _run(repo, phase="9")
    assert r.returncode == 0
    out = _parse(r.stdout)
    assert out["verdict"] == "PASS"
    assert out["evidence"] == []


def test_missing_file_at_cutover_blocks(tmp_path):
    """Test 3: Missing file + phase >= 14 → BLOCK."""
    repo = _setup(tmp_path, stp_md=None)
    # Create a phase 14 dir so find_phase_dir can resolve it
    (tmp_path / ".vg" / "phases" / "14-per-domain-auth").mkdir(parents=True, exist_ok=True)
    r = _run(repo, phase="14")
    assert r.returncode == 1
    out = _parse(r.stdout)
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "stp_missing" for e in out["evidence"])


def test_invalid_risk_profile_blocks(tmp_path):
    """Test 4: Invalid risk_profile value (e.g. 'super-critical') → BLOCK."""
    bad_stp = VALID_STP.replace(
        "**Risk profile:** `moderate`",
        "**Risk profile:** `super-critical`",
    )
    repo = _setup(tmp_path, stp_md=bad_stp)
    r = _run(repo)
    assert r.returncode == 1
    out = _parse(r.stdout)
    assert out["verdict"] == "BLOCK"
    assert any(
        e["type"] == "stp_schema_invalid" and "§1" in e.get("message", "")
        for e in out["evidence"]
    )


def test_critical_risk_dast_none_blocks(tmp_path):
    """Test 5: Critical risk + DAST=None → BLOCK (severity mismatch)."""
    critical_no_dast = VALID_STP.replace(
        "**Risk profile:** `moderate`",
        "**Risk profile:** `critical`",
    ).replace(
        "**Tool:** `ZAP`",
        "**Tool:** `None`",
    )
    repo = _setup(tmp_path, stp_md=critical_no_dast)
    r = _run(repo)
    assert r.returncode == 1
    out = _parse(r.stdout)
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "stp_critical_dast_none" for e in out["evidence"])


def test_foundation_gdpr_stp_none_warns(tmp_path):
    """Test 6: FOUNDATION §9.5 mentions GDPR + STP §6 says 'none' → WARN."""
    stp_no_gdpr = VALID_STP.replace(
        "**Framework:** `GDPR`",
        "**Framework:** `none`",
    )
    # Remove control list bullet so §6 schema doesn't also BLOCK on "none+bullets"
    # (framework=none + bullets is fine; none + no bullets is fine too)
    repo = _setup(
        tmp_path,
        stp_md=stp_no_gdpr,
        foundation_md=VALID_FOUNDATION_WITH_GDPR,
    )
    r = _run(repo)
    out = _parse(r.stdout)
    # Should not BLOCK but should WARN
    assert r.returncode == 0
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "stp_consistency_mismatch" for e in out["evidence"])


def test_section5_empty_when_approach_is_bug_bounty_blocks(tmp_path):
    """Test 7: §5 empty platform+scope when approach='bug-bounty-continuous' → BLOCK."""
    bb_stp = VALID_STP.replace(
        "**Approach:** `internal-team-quarterly`",
        "**Approach:** `bug-bounty-continuous`",
    ).replace(
        "**Platform:** `none`",
        "**Platform:** `{HackerOne|Bugcrowd|self-hosted|none}`",
    ).replace(
        "**Scope:** N/A — no public bug bounty program",
        "**Scope:** {in-scope assets}",
    )
    repo = _setup(tmp_path, stp_md=bb_stp)
    r = _run(repo)
    assert r.returncode == 1
    out = _parse(r.stdout)
    assert out["verdict"] == "BLOCK"
    assert any(
        e["type"] == "stp_schema_invalid" and "§5" in e.get("message", "")
        for e in out["evidence"]
    )


def test_all_enums_valid_with_foundation_passes(tmp_path):
    """Test 8: All enums valid + consistent GDPR in both STP §6 and FOUNDATION → PASS."""
    repo = _setup(
        tmp_path,
        stp_md=VALID_STP,
        foundation_md=VALID_FOUNDATION_WITH_GDPR,
    )
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"
    # No consistency mismatch warnings
    assert not any(e["type"] == "stp_consistency_mismatch" for e in out["evidence"])


def test_registered_in_blueprint_accept_and_unquarantinable():
    """Orchestrator must list verify-security-test-plan in blueprint, accept, UNQUARANTINABLE."""
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main_stp",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main_stp"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "verify-security-test-plan" in mod.COMMAND_VALIDATORS.get("vg:blueprint", [])
    assert "verify-security-test-plan" in mod.COMMAND_VALIDATORS.get("vg:accept", [])
    assert "verify-security-test-plan" in mod.UNQUARANTINABLE
