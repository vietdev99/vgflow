"""tests/test_f1_f2_complete_milestone_hook.py — F1+F2 milestone hook + audit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
CM = REPO / "commands" / "vg" / "complete-milestone.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_complete_milestone_calls_run_start():
    body = _read(CM)
    assert "vg-orchestrator run-start" in body or "run_start" in body, (
        "F2: complete-milestone must call vg-orchestrator run-start so Stop "
        "hook sees an active run and can verify contract"
    )


def test_complete_milestone_has_must_touch_markers():
    body = _read(CM)
    assert "must_touch_markers" in body, (
        "F2: complete-milestone frontmatter runtime_contract must declare "
        "must_touch_markers for each step so Stop hook enforces completion"
    )
    # At minimum expect security_audit marker
    assert "security_audit" in body or "2_gate_check" in body, (
        "F2: must_touch_markers list must include the security audit + gate steps"
    )


def test_security_audit_actually_invokes():
    body = _read(CM)
    sec_block_idx = body.find("security_audit")
    if sec_block_idx < 0:
        sec_block_idx = body.find("/vg:security-audit-milestone")
    assert sec_block_idx > 0
    # Look for actual invocation: subprocess.run, or shell command, or SlashCommand directive
    block = body[sec_block_idx:sec_block_idx + 2000]
    assert ("subprocess" in block or
            "generate-strix-advisory" in block or
            "SlashCommand: /vg:security-audit" in block or
            "scripts/run-security-audit.sh" in block), (
        "F1: security audit must actually invoke (subprocess/script/SlashCommand), "
        "not just print 'Run: /vg:security-audit-milestone'"
    )
