"""
Phase B.4+B.6 skill file integration (2026-04-23).

Validates:
  B.4 — accept.md step 6b_security_baseline wired correctly
  B.4 — test.md step 5f_security_audit Tier 0 loop includes v2.5 validators
  B.6 — test.md step 5h_security_dynamic wired correctly

These are regression guards: if someone edits the skill files and
accidentally removes the wiring, tests catch it immediately.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_MD   = REPO_ROOT / ".claude" / "commands" / "vg" / "test.md"
ACCEPT_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "accept.md"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def step_6b_body() -> str:
    text = ACCEPT_MD.read_text(encoding="utf-8")
    m = re.search(
        r'<step name="6b_security_baseline">(.*?)</step>',
        text, re.DOTALL,
    )
    assert m, "accept.md: <step name=\"6b_security_baseline\"> not found"
    return m.group(1)


@pytest.fixture(scope="module")
def step_5f_body() -> str:
    text = TEST_MD.read_text(encoding="utf-8")
    # 5f ends before 5f_mobile or 5g — use lookahead on next step
    m = re.search(
        r'<step name="5f_security_audit">(.*?)(?=<step name=)',
        text, re.DOTALL,
    )
    assert m, "test.md: <step name=\"5f_security_audit\"> not found"
    return m.group(1)


@pytest.fixture(scope="module")
def step_5h_body() -> str:
    text = TEST_MD.read_text(encoding="utf-8")
    m = re.search(
        r'<step name="5h_security_dynamic"[^>]*>(.*?)</step>',
        text, re.DOTALL,
    )
    assert m, "test.md: <step name=\"5h_security_dynamic\"> not found"
    return m.group(1)


# ─── B.4: accept.md 6b_security_baseline ──────────────────────────────────

class TestAccept6bSecurityBaseline:
    def test_step_exists(self, step_6b_body):
        """Step 6b_security_baseline must exist in accept.md."""
        assert len(step_6b_body) > 50

    def test_invokes_verify_security_baseline(self, step_6b_body):
        assert "verify-security-baseline.py" in step_6b_body, (
            "6b does not invoke verify-security-baseline.py"
        )

    def test_uses_scope_all(self, step_6b_body):
        """--scope all ensures project-wide check (not per-phase only)."""
        assert "--scope all" in step_6b_body

    def test_passes_phase_number(self, step_6b_body):
        assert "--phase" in step_6b_body and "PHASE_NUMBER" in step_6b_body

    def test_checks_exit_code(self, step_6b_body):
        """Must branch on BASELINE_RC to decide block vs pass."""
        assert "BASELINE_RC" in step_6b_body
        assert "$BASELINE_RC" in step_6b_body or "${BASELINE_RC}" in step_6b_body

    def test_hard_block_on_failure(self, step_6b_body):
        """Non-zero exit without override flag → exit 1 (hard block)."""
        assert "exit 1" in step_6b_body

    def test_allow_baseline_drift_override(self, step_6b_body):
        """--allow-baseline-drift override must be wired."""
        assert "--allow-baseline-drift" in step_6b_body

    def test_override_logs_debt(self, step_6b_body):
        """Override must log to override-debt register."""
        assert "log_override_debt" in step_6b_body

    def test_step_marker_written(self, step_6b_body):
        """Step marker required for gate integrity verification."""
        assert "6b_security_baseline.done" in step_6b_body

    def test_positioned_before_write_uat(self):
        """6b must appear before 6_write_uat_md in accept.md."""
        text = ACCEPT_MD.read_text(encoding="utf-8")
        pos_6b  = text.find('name="6b_security_baseline"')
        pos_uat = text.find('name="6_write_uat_md"')
        assert pos_6b != -1
        assert pos_uat != -1
        assert pos_6b < pos_uat, (
            "6b_security_baseline must come BEFORE 6_write_uat_md"
        )

    def test_validator_script_exists(self):
        p = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-security-baseline.py"
        assert p.exists(), f"verify-security-baseline.py missing: {p}"


# ─── B.4: test.md 5f Tier 0 loop includes new validators ──────────────────

class TestTest5fTier0Loop:
    def test_verify_goal_security_in_tier0(self, step_5f_body):
        assert "verify-goal-security" in step_5f_body, (
            "5f Tier 0 loop missing verify-goal-security (B.1)"
        )

    def test_verify_goal_perf_in_tier0(self, step_5f_body):
        assert "verify-goal-perf" in step_5f_body, (
            "5f Tier 0 loop missing verify-goal-perf (B.2)"
        )

    def test_verify_security_baseline_in_tier0(self, step_5f_body):
        assert "verify-security-baseline" in step_5f_body, (
            "5f Tier 0 loop missing verify-security-baseline (B.3)"
        )

    def test_v25_validators_scripts_exist(self):
        for name in (
            "verify-goal-security.py",
            "verify-goal-perf.py",
            "verify-security-baseline.py",
        ):
            p = REPO_ROOT / ".claude" / "scripts" / "validators" / name
            assert p.exists(), f"validator script missing on disk: {name}"


# ─── B.6: test.md 5h_security_dynamic ────────────────────────────────────

class TestTest5hSecurityDynamic:
    def test_step_exists(self, step_5h_body):
        assert len(step_5h_body) > 100

    def test_profile_web_only(self):
        """5h must carry profile attribute to skip non-web phases."""
        text = TEST_MD.read_text(encoding="utf-8")
        m = re.search(r'<step name="5h_security_dynamic"[^>]*profile="([^"]+)"', text)
        assert m, "5h_security_dynamic missing profile attribute"
        assert "web" in m.group(1), f"profile should include 'web': {m.group(1)}"

    def test_invokes_dast_runner(self, step_5h_body):
        assert "dast-runner.sh" in step_5h_body, (
            "5h does not invoke dast-runner.sh"
        )

    def test_invokes_dast_scan_report(self, step_5h_body):
        assert "dast-scan-report.py" in step_5h_body, (
            "5h does not invoke dast-scan-report.py"
        )

    def test_passes_risk_profile(self, step_5h_body):
        """--risk-profile must be passed to dast-scan-report.py."""
        assert "--risk-profile" in step_5h_body
        assert "RISK_PROFILE" in step_5h_body

    def test_checks_runner_rc(self, step_5h_body):
        """RUNNER_RC exit code 2 = no tool → warn not block."""
        assert "RUNNER_RC" in step_5h_body
        assert "exit 2" in step_5h_body or "RUNNER_RC" in step_5h_body

    def test_checks_report_rc(self, step_5h_body):
        """REPORT_RC must gate block/override."""
        assert "REPORT_RC" in step_5h_body

    def test_hard_block_on_critical_findings(self, step_5h_body):
        assert "exit 1" in step_5h_body

    def test_skip_dast_override_wired(self, step_5h_body):
        assert "--skip-dast" in step_5h_body

    def test_allow_dast_findings_override_wired(self, step_5h_body):
        assert "--allow-dast-findings" in step_5h_body

    def test_both_overrides_log_debt(self, step_5h_body):
        assert "log_override_debt" in step_5h_body

    def test_step_marker_written(self, step_5h_body):
        assert "5h_security_dynamic.done" in step_5h_body

    def test_scan_url_resolution(self, step_5h_body):
        """Must resolve SANDBOX_URL or fallback to LOCAL_API_URL."""
        assert "SANDBOX_URL" in step_5h_body
        assert "LOCAL_API_URL" in step_5h_body

    def test_positioned_before_write_report(self):
        """5h must appear before write_report step."""
        text = TEST_MD.read_text(encoding="utf-8")
        pos_5h   = text.find('name="5h_security_dynamic"')
        pos_wr   = text.find('name="write_report"')
        assert pos_5h != -1
        assert pos_wr != -1
        assert pos_5h < pos_wr, (
            "5h_security_dynamic must come BEFORE write_report"
        )

    def test_dast_runner_script_exists(self):
        p = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "dast-runner.sh"
        assert p.exists(), f"dast-runner.sh missing: {p}"

    def test_dast_scan_report_validator_exists(self):
        p = REPO_ROOT / ".claude" / "scripts" / "validators" / "dast-scan-report.py"
        assert p.exists(), f"dast-scan-report.py missing: {p}"
