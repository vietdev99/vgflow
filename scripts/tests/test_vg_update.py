"""Unit tests for vg_update.py helper."""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from vg_update import (
    compare_versions,
    verify_sha256,
    three_way_merge,
    MergeResult,
    PatchesManifest,
)

_HAS_GIT = shutil.which("git") is not None


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
    """no ancestor -> conservative: keep user, report as conflict"""
    current = tmp_path / "current.md"; current.write_text("user\n")
    upstream = tmp_path / "upstream.md"; upstream.write_text("upstream\n")
    result = three_way_merge(tmp_path / "missing.md", current, upstream)
    assert result.status == "conflict"
    assert "user" in result.content


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
