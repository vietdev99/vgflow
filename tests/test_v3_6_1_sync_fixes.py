"""sync.sh must stay global-only.

Older sync.sh versions copied VG workflow files into project-local .claude and
.codex trees, then tried to dedupe Codex skills after the fact. Global-only
VGFlow must do the opposite: refresh global surfaces and prune project copies.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "sync.sh"


def _read_sync() -> str:
    return SYNC.read_text(encoding="utf-8")


def test_sync_global_only_invokes_dispatcher_install_global():
    body = _read_sync()
    assert "VGFlow sync: global-only mode" in body
    assert 'bin/vg-cli-dispatcher.sh" install --global' in body
    assert "refresh global hooks" in body
    assert "prune current project" in body


def test_sync_has_no_legacy_project_copy_pipeline():
    body = _read_sync()
    assert "sync_tree()" not in body
    assert "compare()" not in body
    assert "prune_duplicate_codex_skills()" not in body
    assert 'chmod +x "$TARGET_ROOT/.claude/scripts/hooks/' not in body
    assert "settings.local.json VG hooks pruned" not in body


def test_sync_deprecated_flags_are_noops():
    body = _read_sync()
    for flag in ("--no-global", "--global-codex", "--no-source"):
        assert flag in body
    assert "global deploy is mandatory" in body
    assert "SKIP_GLOBAL" not in body


def test_sync_check_detects_global_and_project_drift():
    body = _read_sync()
    assert "check_global_surface()" in body
    assert "collect_project_local_vg_surfaces()" in body
    assert "STALE project-local VG surfaces" in body
    assert "MISSING global Claude hooks" in body
    assert "MISSING global Codex hooks" in body


def test_sync_does_not_prune_source_repo_by_default():
    body = _read_sync()
    assert "is_source_repo_target()" in body
    assert "VGFlow source repo detected as cwd" in body
    assert "mktemp -d" in body
    assert "project cleanup skipped unless DEV_ROOT is set" in body


def test_lifecycle_md_uses_single_quote_for_embedded_phrase():
    """Source LIFECYCLE.md must not have unescaped quotes in description."""
    src = (REPO_ROOT / "commands" / "vg" / "LIFECYCLE.md").read_text(encoding="utf-8")
    m = re.search(r"^description:\s*(.+)$", src, re.M)
    assert m, "description line not found"
    desc = m.group(1)
    assert '"' not in desc.replace('\\"', ""), (
        f'LIFECYCLE.md description has unescaped ": {desc}'
    )


def test_generator_escapes_double_quote_in_description():
    body = (REPO_ROOT / "scripts" / "generate-codex-skills.sh").read_text(encoding="utf-8")
    assert "description_yaml" in body
    assert 'description//\\\\' in body and 'description_yaml//\\"' in body, (
        'generator must escape both backslash and " before YAML emission'
    )
