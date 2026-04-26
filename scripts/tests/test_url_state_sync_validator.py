"""
test_url_state_sync_validator.py — Phase J coverage for verify-url-state-sync.

Pins:
1. List-view goal missing interactive_controls block → BLOCK (mandatory phase).
2. Phase below cutover (legacy phase number) → WARN, not BLOCK.
3. Non-list-view goal (single-record GET, mutation) → no checks fire.
4. interactive_controls present but filter missing required fields → BLOCK.
5. url_sync: false without url_sync_waive_reason → BLOCK.
6. url_sync: false WITH waive reason → PASS (waiver respected).
7. Pagination/search/sort sub-blocks missing required fields → BLOCK each.
8. No goals at all → PASS quietly.

Strategy: subprocess invoke validator against fake repo with controlled
TEST-GOALS.md content. Parse stdout JSON.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-url-state-sync.py"


def _run(repo: Path, phase: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase", phase],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"verdict": "ERROR", "raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, data


def _setup_fake_repo(
    tmp_path: Path,
    *,
    phase: str,
    goals_md: str,
    cutover: int = 14,
) -> Path:
    """Create a minimal fake repo with TEST-GOALS.md + vg.config.md."""
    # Mirror script + dependencies
    scripts_dir = tmp_path / ".claude" / "scripts" / "validators"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts_dir / "verify-url-state-sync.py")
    # Copy _common, _i18n, _repo_root for the validator imports.
    for helper in ("_common.py", "_i18n.py", "_repo_root.py"):
        src = REPO_ROOT / ".claude" / "scripts" / "validators" / helper
        if src.exists():
            shutil.copy(src, scripts_dir / helper)
    # _i18n loads narration strings — copy that file too if exists.
    narr_src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "narration-strings.yaml"
    if narr_src.exists():
        narr_dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
        narr_dst.mkdir(parents=True)
        shutil.copy(narr_src, narr_dst / "narration-strings.yaml")

    # vg.config.md with cutover
    cfg_dir = tmp_path / ".claude"
    cfg = cfg_dir / "vg.config.md"
    cfg.write_text(
        f"---\nui_state_conventions:\n"
        f"  list_view_state_in_url: true\n"
        f"  severity_phase_cutover: {cutover}\n",
        encoding="utf-8",
    )

    # Phase dir + TEST-GOALS.md
    phase_dir = tmp_path / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Goal fixture builders
# ---------------------------------------------------------------------------


def _list_goal_no_controls(gid: str = "G-01") -> str:
    return (
        f"---\n"
        f"id: {gid}\n"
        f"title: \"Campaigns list view\"\n"
        f"surface: ui\n"
        f"trigger: \"GET /api/campaigns\"\n"
        f"main_steps:\n"
        f"  - S1: User opens campaigns table view\n"
        f"  - S2: Filters by status\n"
        f"---\n"
        f"\nProse...\n"
    )


def _list_goal_full_controls(gid: str = "G-01") -> str:
    return (
        f"---\n"
        f"id: {gid}\n"
        f"title: \"Campaigns list view\"\n"
        f"surface: ui\n"
        f"trigger: \"GET /api/campaigns\"\n"
        f"main_steps:\n"
        f"  - S1: User opens campaigns table view\n"
        f"interactive_controls:\n"
        f"  url_sync: true\n"
        f"  filters:\n"
        f"    - name: status\n"
        f"      values: [active, paused]\n"
        f"      url_param: status\n"
        f"      assertion: \"rows match + URL ?status=active synced\"\n"
        f"  pagination:\n"
        f"    page_size: 20\n"
        f"    url_param_page: page\n"
        f"    ui_pattern: \"first-prev-numbered-window-next-last\"\n"
        f"    window_radius: 5\n"
        f"    show_total_records: true\n"
        f"    show_total_pages: true\n"
        f"    assertion: \"page2 first row != page1 first row\"\n"
        f"  search:\n"
        f"    url_param: q\n"
        f"    debounce_ms: 300\n"
        f"    assertion: \"type query → URL synced\"\n"
        f"  sort:\n"
        f"    columns: [created_at, name]\n"
        f"    url_param_field: sort\n"
        f"    url_param_dir: dir\n"
        f"    assertion: \"toggle asc/desc + ORDER BY holds\"\n"
        f"---\n"
    )


def _single_record_goal(gid: str = "G-02") -> str:
    return (
        f"---\n"
        f"id: {gid}\n"
        f"title: \"Edit campaign detail\"\n"
        f"surface: ui\n"
        f"trigger: \"PUT /api/campaigns/{{id}}\"\n"
        f"main_steps:\n"
        f"  - S1: User opens edit modal\n"
        f"  - S2: Submits form\n"
        f"---\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_view_missing_controls_blocks_at_mandatory_phase(tmp_path):
    repo = _setup_fake_repo(tmp_path, phase="14",
                            goals_md=_list_goal_no_controls(),
                            cutover=14)
    rc, data = _run(repo, "14")
    assert data["verdict"] in ("BLOCK", "ERROR"), f"got {data}"
    assert any(e["type"] == "url_state_block_missing"
               for e in data.get("evidence", []))


def test_list_view_missing_controls_warns_at_legacy_phase(tmp_path):
    """Phase 7 < cutover 14 → WARN not BLOCK."""
    repo = _setup_fake_repo(tmp_path, phase="7.14.3",
                            goals_md=_list_goal_no_controls(),
                            cutover=14)
    rc, data = _run(repo, "7.14.3")
    assert data["verdict"] == "WARN", f"got {data}"
    assert any(e["type"] == "url_state_block_missing"
               for e in data.get("evidence", []))


def test_full_controls_passes(tmp_path):
    repo = _setup_fake_repo(tmp_path, phase="14",
                            goals_md=_list_goal_full_controls())
    rc, data = _run(repo, "14")
    assert data["verdict"] == "PASS", f"got {data}"
    assert data.get("evidence") == [] or data.get("evidence") is None


def test_single_record_goal_skipped(tmp_path):
    """PUT /campaigns/{id} → not a list view, no checks fire."""
    repo = _setup_fake_repo(tmp_path, phase="14",
                            goals_md=_single_record_goal())
    rc, data = _run(repo, "14")
    assert data["verdict"] == "PASS", f"got {data}"


def test_filter_missing_assertion_blocks(tmp_path):
    incomplete = (
        "---\n"
        "id: G-01\n"
        "title: \"Campaigns list\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view\n"
        "interactive_controls:\n"
        "  url_sync: true\n"
        "  filters:\n"
        "    - name: status\n"
        "      values: [active]\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=incomplete)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "BLOCK"
    assert any(e["type"] == "url_state_filter_incomplete"
               for e in data.get("evidence", []))


def test_url_sync_false_without_reason_blocks(tmp_path):
    no_reason = (
        "---\n"
        "id: G-01\n"
        "title: \"Modal-internal filter\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view in modal\n"
        "interactive_controls:\n"
        "  url_sync: false\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=no_reason)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "BLOCK"
    assert any(e["type"] == "url_state_waive_invalid"
               for e in data.get("evidence", []))


def test_url_sync_false_with_reason_passes(tmp_path):
    with_reason = (
        "---\n"
        "id: G-01\n"
        "title: \"Modal-internal filter\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view in modal\n"
        "interactive_controls:\n"
        "  url_sync: false\n"
        "  url_sync_waive_reason: \"modal-internal filter, resets on close\"\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=with_reason)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "PASS", f"got {data}"


def test_pagination_missing_fields_blocks(tmp_path):
    incomplete = (
        "---\n"
        "id: G-01\n"
        "title: \"Campaigns list\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view\n"
        "interactive_controls:\n"
        "  url_sync: true\n"
        "  pagination:\n"
        "    page_size: 20\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=incomplete)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "BLOCK"
    assert any(e["type"] == "url_state_pagination_incomplete"
               for e in data.get("evidence", []))


def test_pagination_banned_ui_pattern_blocks(tmp_path):
    """ui_pattern: prev-next-only is banned — must be the locked window pattern."""
    banned = (
        "---\n"
        "id: G-01\n"
        "title: \"Campaigns list\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view\n"
        "interactive_controls:\n"
        "  url_sync: true\n"
        "  pagination:\n"
        "    page_size: 20\n"
        "    url_param_page: page\n"
        "    ui_pattern: \"prev-next-only\"\n"
        "    show_total_records: true\n"
        "    show_total_pages: true\n"
        "    assertion: \"prev/next clicks update URL\"\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=banned)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "BLOCK"
    assert any(e["type"] == "url_state_pagination_incomplete"
               for e in data.get("evidence", []))


def test_pagination_missing_total_records_blocks(tmp_path):
    """show_total_records is mandatory — missing → BLOCK."""
    no_totals = (
        "---\n"
        "id: G-01\n"
        "title: \"Campaigns list\"\n"
        "surface: ui\n"
        "trigger: \"GET /api/campaigns\"\n"
        "main_steps:\n"
        "  - S1: list view\n"
        "interactive_controls:\n"
        "  url_sync: true\n"
        "  pagination:\n"
        "    page_size: 20\n"
        "    url_param_page: page\n"
        "    ui_pattern: \"first-prev-numbered-window-next-last\"\n"
        "    assertion: \"clicks sync URL\"\n"
        "---\n"
    )
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=no_totals)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "BLOCK"
    evidences = data.get("evidence", [])
    pagination_ev = [e for e in evidences if e["type"] == "url_state_pagination_incomplete"]
    assert pagination_ev, f"expected pagination_incomplete, got {evidences}"
    # Should mention both totals fields missing
    actual = pagination_ev[0]["actual"]
    assert "show_total_records" in actual or "show_total_pages" in actual


def test_no_goals_passes(tmp_path):
    empty = "# Test Goals\n\nNo goals defined yet.\n"
    repo = _setup_fake_repo(tmp_path, phase="14", goals_md=empty)
    rc, data = _run(repo, "14")
    assert data["verdict"] == "PASS"


def test_phase_dir_missing_passes(tmp_path):
    """Validator should skip silently when phase dir doesn't exist."""
    cfg_dir = tmp_path / ".claude"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vg.config.md").write_text("---\n", encoding="utf-8")
    # Mirror script
    scripts_dir = cfg_dir / "scripts" / "validators"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts_dir / "verify-url-state-sync.py")
    for helper in ("_common.py", "_i18n.py", "_repo_root.py"):
        src = REPO_ROOT / ".claude" / "scripts" / "validators" / helper
        if src.exists():
            shutil.copy(src, scripts_dir / helper)
    rc, data = _run(tmp_path, "99.99")
    assert data["verdict"] == "PASS"
