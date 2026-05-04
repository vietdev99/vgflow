"""Tests for VG Claude hook installer wiring."""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "vg-hooks-install.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("vg_hooks_install", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _commands(settings: dict) -> list[str]:
    out: list[str] = []
    for matchers in settings.get("hooks", {}).values():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                out.append(hook.get("command", ""))
    return out


def test_hook_entry_installs_all_runtime_hooks():
    mod = _load_installer()
    updated, changelog = mod.merge_hooks({}, mod.HOOK_ENTRY)

    commands = "\n".join(_commands(updated))
    assert "vg-entry-hook.py" in commands
    assert "vg-verify-claim.py" in commands
    assert "vg-edit-warn.py" in commands
    assert "vg-step-tracker.py" in commands

    hooks = updated["hooks"]
    assert "UserPromptSubmit" in hooks
    assert "Stop" in hooks
    post_tool = hooks["PostToolUse"]
    assert any(m.get("matcher") == "Bash" for m in post_tool)
    assert any(m.get("matcher") == "Edit|Write|MultiEdit|NotebookEdit" for m in post_tool)
    assert any("vg-step-tracker" in line for line in changelog)


def test_hook_install_is_idempotent_for_step_tracker():
    mod = _load_installer()
    first, _ = mod.merge_hooks({}, mod.HOOK_ENTRY)
    second, changelog = mod.merge_hooks(first, mod.HOOK_ENTRY)

    commands = [cmd for cmd in _commands(second) if "vg-step-tracker.py" in cmd]
    assert len(commands) == 1
    assert any("already installed" in line and "vg-step-tracker" in line for line in changelog)
