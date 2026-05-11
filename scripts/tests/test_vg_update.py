"""Unit tests for vg_update.py helper."""
import argparse
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import vg_update
from vg_update import (
    compare_versions,
    verify_sha256,
    three_way_merge,
    MergeResult,
    PatchesManifest,
)

_HAS_GIT = shutil.which("git") is not None
REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_MD = REPO_ROOT / "commands" / "vg" / "update.md"
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "preflight.md"


def test_update_command_declares_global_only_contract():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert "Global-only" in text
    assert "`~/.vgflow`/global npm package" in text
    assert "`~/.claude/settings.json`" in text
    assert "`~/.codex/skills`" in text
    assert "Project-local VG-owned `.claude/` and `.codex/` files are pruned" in text


def test_update_preflight_coerces_marker_to_global():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert 'INSTALL_TARGET="global"' in text
    assert "MARKER_TARGET" in text
    assert "coercing to global-only" in text
    assert "project-local 3-way merge path is retained only as dead compatibility text" in text


def test_update_preflight_delegates_to_dispatcher_first():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert 'DISPATCHER=""' in text
    assert '"${VG_HOME:-}/bin/vg-cli-dispatcher.sh"' in text
    assert '"${HOME}/.vgflow/bin/vg-cli-dispatcher.sh"' in text
    assert "Delegating to global dispatcher" in text
    assert 'VG_HOME="$(dirname "$(dirname "$DISPATCHER")")" bash "$DISPATCHER" update' in text


def test_update_preflight_bootstraps_npm_into_home_vgflow():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "npm install -g vgflow@latest" in text
    assert 'NPM_ROOT="$(npm root -g' in text
    assert 'NPM_VGFLOW="${NPM_ROOT%/}/vgflow"' in text
    assert "Delegating to npm-installed dispatcher so ~/.vgflow is canonicalized" in text
    assert 'VG_HOME="$NPM_VGFLOW" bash "${NPM_VGFLOW}/bin/vg-cli-dispatcher.sh" update' in text


def test_update_preflight_refreshes_global_codex():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "${HOME_VGFLOW}/codex-skills" in text
    assert "${HOME}/.codex/skills" in text
    assert "${HOME}/.codex/agents" in text
    assert "codex-hooks-install.py" in text
    assert "${HOME}/.codex" in text
    assert "global Codex refreshed" in text
    assert "vgflow-orchestrator" in text


def test_update_preflight_prunes_project_local_vg_files():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    helper = (REPO_ROOT / "scripts" / "vg_uninstall.py").read_text(encoding="utf-8")
    assert "vg_uninstall.py" in text
    assert "Cleaning stale project-local VG files" in text
    assert ".claude/commands/vg" in helper
    assert ".claude/scripts" in helper
    assert ".codex/config.template.toml" in helper
    assert "CODEX_SKILL_PREFIXES" in helper
    assert ".vgflow-uninstall-backup" in helper


def test_update_preflight_writes_global_marker():
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert 'mkdir -p "${REPO_ROOT}/.vg"' in text
    assert 'printf \'%s\\n\' "global" > "${REPO_ROOT}/.vg/.install-target"' in text
    assert ".global-vgflow-version" in text


# ---- Task C1: compare_versions -----------------------------------------------

def test_compare_equal():
    assert compare_versions("1.2.3", "1.2.3") == 0


def test_compare_less():
    assert compare_versions("1.2.3", "1.2.4") < 0
    assert compare_versions("1.2.3", "1.3.0") < 0
    assert compare_versions("1.2.3", "2.0.0") < 0


def test_compare_greater():
    assert compare_versions("1.2.4", "1.2.3") > 0
    assert compare_versions("2.0.0", "1.99.99") > 0


def test_compare_zero_baseline():
    assert compare_versions("0.0.0", "1.0.0") < 0


def test_compare_invalid_returns_lt():
    # Unparseable fallback: treat local as "behind" so update is offered
    assert compare_versions("unknown", "1.0.0") < 0


# ---- Task C2: verify_sha256 --------------------------------------------------

def test_sha256_match(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello")
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    assert verify_sha256(
        f,
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    ) is True


def test_sha256_mismatch(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello")
    assert verify_sha256(
        f,
        "0000000000000000000000000000000000000000000000000000000000000000",
    ) is False


def test_sha256_missing_file(tmp_path):
    assert verify_sha256(tmp_path / "nope.txt", "abc") is False


# ---- Task C3: three_way_merge ------------------------------------------------

@pytest.mark.skipif(not _HAS_GIT, reason="git CLI not available")
def test_merge_clean(tmp_path):
    """upstream change, user untouched -> clean apply"""
    ancestor = tmp_path / "ancestor.md"; ancestor.write_text("line1\nline2\nline3\n")
    current = tmp_path / "current.md"; current.write_text("line1\nline2\nline3\n")
    upstream = tmp_path / "upstream.md"; upstream.write_text("line1\nline2 UPDATED\nline3\n")
    result = three_way_merge(ancestor, current, upstream)
    assert isinstance(result, MergeResult)
    assert result.status == "clean"
    assert "line2 UPDATED" in result.content


@pytest.mark.skipif(not _HAS_GIT, reason="git CLI not available")
def test_merge_no_upstream_change(tmp_path):
    """upstream == ancestor -> keep user's version"""
    ancestor = tmp_path / "ancestor.md"; ancestor.write_text("v1\n")
    current = tmp_path / "current.md"; current.write_text("v1 USER\n")
    upstream = tmp_path / "upstream.md"; upstream.write_text("v1\n")
    result = three_way_merge(ancestor, current, upstream)
    assert result.status == "clean"
    assert result.content == "v1 USER\n"


@pytest.mark.skipif(not _HAS_GIT, reason="git CLI not available")
def test_merge_conflict(tmp_path):
    """both user + upstream changed same line -> conflict markers"""
    ancestor = tmp_path / "ancestor.md"; ancestor.write_text("config: A\n")
    current = tmp_path / "current.md"; current.write_text("config: USER_EDIT\n")
    upstream = tmp_path / "upstream.md"; upstream.write_text("config: UPSTREAM_EDIT\n")
    result = three_way_merge(ancestor, current, upstream)
    assert result.status == "conflict"
    assert "<<<<<<<" in result.content
    assert ">>>>>>>" in result.content
    assert "USER_EDIT" in result.content
    assert "UPSTREAM_EDIT" in result.content


def test_merge_missing_ancestor_fallback(tmp_path):
    """no ancestor -> upstream wins, with distinct status for caller logging"""
    current = tmp_path / "current.md"; current.write_text("user\n")
    upstream = tmp_path / "upstream.md"; upstream.write_text("upstream\n")
    result = three_way_merge(tmp_path / "missing.md", current, upstream)
    assert result.status == "force-upstream"
    assert result.content == "upstream\n"


def test_cmd_merge_writes_bytes_not_text(tmp_path, monkeypatch):
    """Windows path must not reintroduce CRLF via text-mode write_text()."""
    output = tmp_path / "merged.md"

    monkeypatch.setattr(
        vg_update,
        "three_way_merge",
        lambda *_args, **_kwargs: MergeResult("clean", "line1\nline2\n"),
    )

    def _fail_write_text(self, *args, **kwargs):
        raise AssertionError("cmd_merge must not use write_text()")

    monkeypatch.setattr(Path, "write_text", _fail_write_text)

    rc = vg_update.cmd_merge(
        argparse.Namespace(
            ancestor="ancestor.md",
            current="current.md",
            upstream="upstream.md",
            output=str(output),
        )
    )

    assert rc == 0
    assert output.read_bytes() == b"line1\nline2\n"


# ---- Task C4: PatchesManifest ------------------------------------------------

def test_manifest_empty(tmp_path):
    m = PatchesManifest(tmp_path / "manifest.json")
    assert m.list() == []


def test_manifest_add_and_list(tmp_path):
    m = PatchesManifest(tmp_path / "manifest.json")
    m.add("commands/vg/build.md", "conflict")
    m.add("skills/api-contract/SKILL.md", "conflict")
    entries = m.list()
    assert len(entries) == 2
    assert any(e["path"] == "commands/vg/build.md" for e in entries)


def test_manifest_persist_across_instances(tmp_path):
    p = tmp_path / "manifest.json"
    m1 = PatchesManifest(p)
    m1.add("a.md", "conflict")
    m2 = PatchesManifest(p)
    assert len(m2.list()) == 1


def test_manifest_remove(tmp_path):
    m = PatchesManifest(tmp_path / "manifest.json")
    m.add("a.md", "conflict")
    m.add("b.md", "conflict")
    m.remove("a.md")
    entries = m.list()
    assert len(entries) == 1
    assert entries[0]["path"] == "b.md"


def test_manifest_save_does_not_leave_tmp_files(tmp_path):
    """Atomic save should not leave .tmp artefacts after multiple operations."""
    m = PatchesManifest(tmp_path / "manifest.json")
    m.add("a.md", "conflict")
    m.remove("a.md")
    m.add("b.md", "conflict")
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], "Unexpected tmp files remain: {}".format(leftovers)
