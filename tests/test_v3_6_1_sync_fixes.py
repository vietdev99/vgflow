"""v3.6.1 — sync.sh fixes for chmod + Codex skill dedupe.

Bugs fixed:
1. chmod +x on .claude/scripts/hooks/*.sh was nested under
   `if [ -d agents ]` — left hooks non-executable on installs without
   custom agents/, causing macOS Stop hook `Permission denied` errors.
2. Codex picker showed every vg-* skill twice when both ~/.codex/skills/
   AND <project>/.codex/skills/ were populated (sync.sh deployed both
   when --global-codex flag was used previously).

Tests:
- chmod block in sync.sh runs unconditionally (outside agents check)
- prune_duplicate_codex_skills function exists with marker-aware logic
- Step 4b (dedupe) wired into main flow
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "sync.sh"


def _read_sync() -> str:
    return SYNC.read_text(encoding="utf-8")


def test_chmod_hooks_unconditional():
    body = _read_sync()
    # Find the chmod hook block
    m = re.search(
        r'if \[ "\$MODE_CHECK" = "false" \]; then\s*\n'
        r'\s*chmod \+x "\$TARGET_ROOT/\.claude/scripts/hooks/"\*\.sh',
        body,
    )
    assert m, "chmod +x .claude/scripts/hooks/*.sh must run when MODE_CHECK=false"
    # Verify it's NOT nested under agents existence (look at preceding 30 lines)
    chmod_pos = body.find('chmod +x "$TARGET_ROOT/.claude/scripts/hooks/"*.sh')
    assert chmod_pos > 0
    preceding = body[max(0, chmod_pos - 600):chmod_pos]
    # The IMMEDIATELY-preceding `if` must be MODE_CHECK, not agents.
    last_if = preceding.rfind("if [")
    assert last_if >= 0
    last_if_line = preceding[last_if:last_if + 80]
    assert "MODE_CHECK" in last_if_line, (
        f"chmod hooks block must be guarded by MODE_CHECK, found: {last_if_line!r}"
    )


def test_chmod_includes_python_hooks():
    body = _read_sync()
    assert 'chmod +x "$TARGET_ROOT/.claude/scripts/hooks/"*.py' in body, (
        "v3.6.1 must also chmod +x *.py hook files (vg-run-bash-hook.py etc)"
    )


def test_prune_function_exists():
    body = _read_sync()
    assert "prune_duplicate_codex_skills()" in body, (
        "sync.sh must declare prune_duplicate_codex_skills function"
    )
    assert "install-target" in body
    assert "HOME/.codex" in body


def test_prune_step_wired_into_main():
    body = _read_sync()
    assert "4b. Dedupe Codex skills" in body
    # Function called at top-level
    assert re.search(r'^prune_duplicate_codex_skills "\$TARGET_ROOT"', body, re.M), (
        "prune_duplicate_codex_skills must be invoked from main script body"
    )


def test_prune_respects_install_target_marker():
    """When marker says project, prune global; when global/unset, prune project."""
    body = _read_sync()
    # Find function body
    m = re.search(r'prune_duplicate_codex_skills\(\) \{(.+?)^\}', body, re.M | re.S)
    assert m, "function body parse failed"
    fn = m.group(1)
    # Both branches present
    assert 'project)' in fn, "project branch missing"
    assert 'global|"")' in fn or 'global)' in fn, "global branch missing"
    # Reads marker from .vg/.install-target
    assert ".vg/.install-target" in fn


def test_lifecycle_md_uses_single_quote_for_embedded_phrase():
    """Source LIFECYCLE.md must not have unescaped `"X"` inside the description."""
    src = (REPO_ROOT / "commands" / "vg" / "LIFECYCLE.md").read_text(encoding="utf-8")
    m = re.search(r"^description:\s*(.+)$", src, re.M)
    assert m, "description line not found"
    desc = m.group(1)
    # Description is unquoted plain scalar; must not contain `"` (Codex CLI
    # rejects when generator wraps unescaped value into "..." YAML scalar)
    # OR may contain only escaped variants. We use single-quoted phrase here.
    # Acceptable forms: 'X', \"X\", or no quoted phrase at all.
    assert '"' not in desc.replace("\\\"", ""), (
        f"LIFECYCLE.md description has unescaped `\"`: {desc}"
    )


def test_generator_escapes_double_quote_in_description():
    body = (REPO_ROOT / "scripts" / "generate-codex-skills.sh").read_text(encoding="utf-8")
    assert "description_yaml" in body
    # Escape pattern present
    assert 'description//\\\\' in body and 'description_yaml//\\"' in body, (
        "generator must do bash parameter-expansion escape for both \\ and \" before YAML emission"
    )
