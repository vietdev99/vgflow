"""tests/test_mcp_validator_windows_cmd.py — v4.31.1 hotfix

User dogfood bug: "sau mỗi lần /vg:update là claude lại mất MCP Playwright,
graphify". Root cause:
1. verify-playwright-mcp-config.py:126 read ~/.claude/settings.json (wrong
   file). Claude Code reads ~/.claude.json (top-level).
2. _valid_entry rejected Windows-style cmd wrapper (command='cmd',
   args=['/c', 'npx', ...]) as invalid → --repair overwrote with bare
   'npx' which doesn't spawn on Windows → MCP fails to start.
3. _valid_profile_entry rejected custom user-data-dir paths → also
   triggered overwrite.

This test suite verifies the v4.31.1 fix handles both Unix + Windows
forms + custom profile paths without clobbering working configs.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-playwright-mcp-config.py"


def _load():
    spec = importlib.util.spec_from_file_location("mcpval", VAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_validator_reads_claude_dot_json_not_settings():
    """check_claude must read ~/.claude.json (canonical) before ~/.claude/settings.json."""
    body = VAL.read_text(encoding="utf-8")
    assert "home / \".claude.json\"" in body or 'home / ".claude.json"' in body, (
        "v4.31.1 hotfix: validator must check ~/.claude.json (canonical mcpServers location). "
        "Old code wrote to ~/.claude/settings.json which Claude Code doesn't read."
    )


def test_windows_cmd_entry_accepted():
    """command='cmd' + args=['/c', 'npx', ...] is valid on Windows."""
    mod = _load()
    entry = {
        "command": "cmd",
        "args": ["/c", "npx", "@playwright/mcp@latest", "--user-data-dir", "C:/Users/LIONEL~1/AppData/Local/Temp/playwright-mcp-1"],
    }
    assert mod._valid_entry(entry), (
        "v4.31.1: Windows-cmd-wrapped entry must be accepted (was rejected → "
        "--repair overwrote with bare npx which fails on Windows)"
    )


def test_unix_npx_entry_still_accepted():
    """Backward compat — Unix npx entries still valid."""
    mod = _load()
    entry = {
        "command": "npx",
        "args": ["@playwright/mcp@latest", "--no-headless", "--user-data-dir", "/home/u/.claude/playwright-profile-1"],
    }
    assert mod._valid_entry(entry)


def test_custom_profile_dir_not_overwritten_for_windows_cmd():
    """Windows-cmd entry with non-default profile path must NOT trigger repair."""
    mod = _load()
    entry = {
        "command": "cmd",
        "args": ["/c", "npx", "@playwright/mcp@latest", "--user-data-dir", "C:/CustomPath/profile-1"],
    }
    expected_profile = Path("C:/Users/x/.claude/playwright-profile-1")
    assert mod._valid_profile_entry(entry, expected_profile, allow_custom=False), (
        "v4.31.1: Windows-cmd entries with custom user-data-dir must be treated "
        "as valid (implicit allow_custom). Otherwise --repair clobbers working "
        "Windows config."
    )


def test_invalid_entry_no_mcp_package_still_rejected():
    """Don't over-relax — entries missing MCP_PACKAGE still invalid."""
    mod = _load()
    entry = {
        "command": "npx",
        "args": ["--user-data-dir", "/some/path"],  # no @playwright/mcp@latest
    }
    assert not mod._valid_entry(entry), "Entry without MCP_PACKAGE must be rejected"


def test_invalid_random_command_rejected():
    """Random command string still invalid."""
    mod = _load()
    entry = {"command": "bash", "args": ["@playwright/mcp@latest"]}
    assert not mod._valid_entry(entry)
