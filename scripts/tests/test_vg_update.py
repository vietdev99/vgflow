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
    preflight_scan,
)

_HAS_GIT = shutil.which("git") is not None
REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_MD = REPO_ROOT / "commands" / "vg" / "update.md"


def test_update_command_syncs_codex_without_vgflow_sync_sh():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert "Syncing Codex mirror from updated release assets" in text
    assert 'CODEX_SOURCE="${NEW_ANCESTOR}"' in text
    assert '${REPO_ROOT}/.codex/skills' in text
    assert '$HOME/.codex/skills' in text
    assert "verify-codex-mirror-equivalence.py" in text
    assert 'rm -rf "${REPO_ROOT}/.codex/skills/${skill}"' in text
    assert 'rm -rf "$HOME/.codex/skills/${skill}"' in text
    assert "vgflow/sync.sh not present" not in text


def test_update_command_keeps_codex_assets_out_of_claude_tree():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert "codex-skills/*|gemini-skills/*|templates/codex/*|templates/codex-agents/*)" in text
    assert "commands/*|skills/*|scripts/*|schemas/*|templates/vg/*)" in text
    assert "commands/*|skills/*|scripts/*|templates/*|codex-skills/*" not in text


def test_update_command_merges_all_known_file_types():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert 'done < <(find "$EXTRACTED" -type f)' in text
    assert '-name "*.md" -o -name "*.py"' not in text


def test_update_command_repairs_enforcement_hooks():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert '<step name="7b_repair_hooks">' in text
    assert "vg-hooks-install.py" in text
    assert "vg-hooks-selftest.py" in text
    assert "UserPromptSubmit" in text
    assert "PostToolUse" in text
    assert ".vg/events.db" in text


def test_update_command_repairs_playwright_mcp_workers():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert '<step name="8b_repair_playwright_mcp">' in text
    assert "verify-playwright-mcp-config.py" in text
    assert "--repair --lock-source" in text
    assert "playwright1" in text
    assert "playwright5" in text
    assert "Claude + Codex" in text


def test_update_command_repairs_graphify_tooling():
    text = UPDATE_MD.read_text(encoding="utf-8")
    assert '<step name="8c_ensure_graphify">' in text
    assert "ensure-graphify.py" in text
    assert '--target "$REPO_ROOT" --repair' in text
    assert "graphifyy[mcp]" in text


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


# ---- Issue #42: pre-flight integrity scan -----------------------------------

def _make_preflight_fixture(tmp_path):
    """Build a synthetic upstream + install + ancestor tree.

    Returns (extracted_root, install_root, ancestor_root) Paths.
    Ancestor dir is created EMPTY by default — caller drops files in
    selectively to simulate "ancestor present for some files, missing for
    others" scenarios.
    """
    extracted = tmp_path / "extracted"
    install = tmp_path / "install"
    ancestor = tmp_path / "ancestor"
    for d in (extracted, install, ancestor):
        d.mkdir(parents=True, exist_ok=True)
    return extracted, install, ancestor


def test_preflight_no_local_install_dir_returns_zeros(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "scripts").mkdir()
    (extracted / "scripts" / "foo.py").write_text("upstream", encoding="utf-8")
    # install dir empty — every file is "new"
    res = preflight_scan(extracted, install, ancestor)
    assert res["force_upstream_count"] == 0
    assert res["totals"]["new"] == 1
    assert res["force_upstream_files"] == []


def test_preflight_clean_match_no_risk(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "scripts").mkdir()
    (install / "scripts").mkdir()
    (extracted / "scripts" / "foo.py").write_text("same", encoding="utf-8")
    (install / "scripts" / "foo.py").write_text("same", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["force_upstream_count"] == 0
    assert res["totals"]["clean"] == 1


def test_preflight_ancestor_missing_local_diverges_flags_at_risk(tmp_path):
    """The smoking-gun case from issue #42: ancestor missing AND local
    differs from upstream → file will be silently force-upstreamed."""
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "scripts").mkdir()
    (install / "scripts").mkdir()
    (extracted / "scripts" / "verify-claim.py").write_text("upstream-fix\n", encoding="utf-8")
    (install / "scripts" / "verify-claim.py").write_text("local-stale\n", encoding="utf-8")
    # ancestor dir exists but does NOT contain scripts/verify-claim.py
    res = preflight_scan(extracted, install, ancestor)
    assert res["force_upstream_count"] == 1
    assert res["force_upstream_files"] == ["scripts/verify-claim.py"]


def test_preflight_ancestor_present_for_diverged_file_not_at_risk(tmp_path):
    """Ancestor present + content diverges → 3-way merge handles it →
    not at risk for silent overwrite."""
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    for sub in ("scripts", ):
        (extracted / sub).mkdir()
        (install / sub).mkdir()
        (ancestor / sub).mkdir()
    (extracted / "scripts" / "foo.py").write_text("upstream", encoding="utf-8")
    (install / "scripts" / "foo.py").write_text("local", encoding="utf-8")
    (ancestor / "scripts" / "foo.py").write_text("ancestor", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["force_upstream_count"] == 0


def test_preflight_skips_meta_files(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    for name in ("VERSION", "CHANGELOG.md", "README.md", "LICENSE"):
        (extracted / name).write_text("upstream", encoding="utf-8")
        (install / name).write_text("local", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["totals"]["skipped"] == 4
    assert res["force_upstream_count"] == 0


def test_preflight_skips_codex_skills(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "codex-skills" / "vg-build").mkdir(parents=True)
    (extracted / "codex-skills" / "vg-build" / "SKILL.md").write_text("up", encoding="utf-8")
    (install / "codex-skills" / "vg-build").mkdir(parents=True)
    (install / "codex-skills" / "vg-build" / "SKILL.md").write_text("loc", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["totals"]["skipped"] == 1
    assert res["force_upstream_count"] == 0


def test_preflight_only_install_prefixes_count(tmp_path):
    """Files outside commands/skills/scripts/schemas/templates/vg are skipped."""
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "random-tool").mkdir()
    (extracted / "random-tool" / "x.py").write_text("up", encoding="utf-8")
    (install / "random-tool").mkdir()
    (install / "random-tool" / "x.py").write_text("loc", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["totals"]["skipped"] == 1
    assert res["force_upstream_count"] == 0


def test_preflight_at_risk_files_sorted_alphabetically(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "scripts").mkdir()
    (install / "scripts").mkdir()
    for name in ("zebra.py", "alpha.py", "middle.py"):
        (extracted / "scripts" / name).write_text("up", encoding="utf-8")
        (install / "scripts" / name).write_text("loc", encoding="utf-8")
    res = preflight_scan(extracted, install, ancestor)
    assert res["force_upstream_files"] == [
        "scripts/alpha.py", "scripts/middle.py", "scripts/zebra.py",
    ]


def test_preflight_extracted_root_missing_returns_error_field(tmp_path):
    extracted = tmp_path / "does-not-exist"
    install = tmp_path / "install"; install.mkdir()
    ancestor = tmp_path / "ancestor"
    res = preflight_scan(extracted, install, ancestor)
    assert "error" in res
    assert res["force_upstream_count"] == 0


def test_preflight_ancestor_present_field_reflects_dir_state(tmp_path):
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    res_present = preflight_scan(extracted, install, ancestor)
    assert res_present["ancestor_present"] is True
    res_missing = preflight_scan(extracted, install, tmp_path / "nope")
    assert res_missing["ancestor_present"] is False


def test_preflight_real_world_scenario_issue_42(tmp_path):
    """End-to-end scenario from issue #42 — upgrading from v2.12.7 to v2.28.0
    with ancestor stash for v2.12.7 missing entirely. Expected: ALL diverged
    files in scripts/ flagged as at-risk."""
    extracted, install, ancestor = _make_preflight_fixture(tmp_path)
    (extracted / "scripts").mkdir()
    (install / "scripts").mkdir()
    # 14 files that drifted between v2.12.7 and v2.28.0 in PrintwayV3 case
    drifted = [
        "vg-verify-claim.py", "vg-step-tracker.py", "vg-wired-check.py",
        "vg-typecheck-hook.py", "vg-entry-hook.py", "vg-build-crossai-loop.py",
        "generate-pentest-checklist.py", "distribution-check.py",
        "build-uat-narrative.py", "bootstrap-test-runner.py",
    ]
    for name in drifted:
        (extracted / "scripts" / name).write_text("v2.28.0\n", encoding="utf-8")
        (install / "scripts" / name).write_text("v2.12.7\n", encoding="utf-8")

    # Ancestor stash for v2.12.7 is missing entirely (the smoking gun)
    res = preflight_scan(extracted, install, ancestor)  # ancestor exists but EMPTY
    assert res["ancestor_present"] is True  # dir exists
    assert res["force_upstream_count"] == len(drifted)
    # Order is sorted; user can audit specific files
    assert res["force_upstream_files"][0] == "scripts/bootstrap-test-runner.py"
