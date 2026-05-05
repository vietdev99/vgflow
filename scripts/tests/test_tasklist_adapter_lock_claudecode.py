"""HOTFIX 2026-05-05 (session 2) — `vg-orchestrator tasklist-projected`
must lock adapter to "claude" when CLAUDECODE=1 env is set.

Bug: PV3 blueprint 4.3 session — AI rationalized switching `--adapter
fallback` with the false claim "TodoWrite không có trong session này".
Truth: Claude Code unconditionally sets `CLAUDECODE=1` and ships the
TodoWrite tool. Switching adapter bypasses the PostToolUse evidence gate
that HOTFIX session 1 (2026-05-05 morning) installed.

Fix: orchestrator detects CLAUDECODE=1 → rejects --adapter fallback/codex
with rc=2 + actionable error pointing to the rationalization pattern.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"


def _fn_body() -> str:
    src = ORCH.read_text()
    m = re.search(
        r"def cmd_tasklist_projected.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, "cmd_tasklist_projected not found"
    return m.group(0)


def test_source_detects_claudecode_env():
    """Source must check os.environ for CLAUDECODE=1."""
    body = _fn_body()
    assert 'os.environ.get("CLAUDECODE")' in body, (
        "Must read CLAUDECODE env to detect Claude Code runtime"
    )
    assert '"1"' in body, "Must compare CLAUDECODE to '1'"


def test_source_rejects_fallback_under_claudecode():
    """Under CLAUDECODE=1, fallback/codex adapter must return rc=2."""
    body = _fn_body()
    # The lock branch must mention all three: claude_code session, fallback, codex
    assert "is_claude_code_session" in body
    assert '"codex"' in body and '"fallback"' in body
    # Lock branch returns 2
    lock_idx = body.find("Adapter lock:")
    assert lock_idx > 0, "Adapter lock error message missing"
    # Find the next 'return' after the lock message
    return_after_lock = body[lock_idx:].find("return 2")
    assert return_after_lock > 0, "Lock branch must return 2"


def test_source_documents_rationalization_pattern():
    """Source must reference the PV3 blueprint 4.3 rationalization for
    future maintainers — this is the exact bug class to defend against."""
    body = _fn_body()
    assert "blueprint 4.3" in body or "rationalization" in body.lower(), (
        "Source must document the rationalization context"
    )
    assert "TodoWrite" in body, "Must reference TodoWrite availability"


def test_codex_session_unaffected():
    """When CLAUDECODE is unset (Codex CLI session), fallback/codex must
    still be allowed. Lock is gated on CLAUDECODE=1 only."""
    body = _fn_body()
    # The conditional must be `is_claude_code_session AND adapter in (...)`
    # — so when is_claude_code_session is False, lock skips
    assert (
        "if is_claude_code_session and args.adapter in" in body
    ), "Lock must AND CLAUDECODE check with adapter check (not just adapter)"


def test_mirror_parity():
    """Source + .claude/ mirror byte-identical."""
    mirror = REPO_ROOT / ".claude/scripts/vg-orchestrator/__main__.py"
    assert mirror.is_file()
    assert ORCH.read_bytes() == mirror.read_bytes(), "Mirror drift"
