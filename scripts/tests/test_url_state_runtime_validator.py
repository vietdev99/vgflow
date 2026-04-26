"""
test_url_state_runtime_validator.py — v2.7 Phase A coverage for
verify-url-state-runtime.

Pins:
1. PASS — every declared control has a matching probe entry with the
   declared url_param present in url_params_after.
2. WARN — url-runtime-probe.json artifact missing.
3. WARN — probe artifact present but specific goal absent from probe.
4. WARN — goal probed but a declared control was not exercised.
5. BLOCK — control exercised but url_params_after missing the declared param.
6. WARN-only — --skip-runtime suppresses checks (CI without browser).
7. PASS — goal without interactive_controls.url_sync: true is ignored.
8. ERROR-handled — malformed probe JSON produces BLOCK with parse error.
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
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-url-state-runtime.py"


def _run(repo: Path, phase: str, *extra: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase", phase, *extra],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {
            "verdict": "ERROR", "raw_stdout": proc.stdout,
            "raw_stderr": proc.stderr,
        }
    return proc.returncode, data


def _setup_fake_repo(
    tmp_path: Path,
    *,
    phase: str,
    goals_md: str,
    probe_json: dict | str | None = None,
) -> Path:
    """Mirror validator + helpers + write TEST-GOALS.md (+ optional probe)."""
    scripts_dir = tmp_path / ".claude" / "scripts" / "validators"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts_dir / SCRIPT.name)
    for helper in ("_common.py", "_i18n.py", "_repo_root.py"):
        src = REPO_ROOT / ".claude" / "scripts" / "validators" / helper
        if src.exists():
            shutil.copy(src, scripts_dir / helper)
    narr_src = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
                / "narration-strings.yaml")
    if narr_src.exists():
        narr_dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
        narr_dst.mkdir(parents=True)
        shutil.copy(narr_src, narr_dst / "narration-strings.yaml")

    phase_dir = tmp_path / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True)
    (phase_dir / "TEST-GOALS.md").write_text(goals_md, encoding="utf-8")

    if probe_json is not None:
        probe_path = phase_dir / "url-runtime-probe.json"
        if isinstance(probe_json, str):
            probe_path.write_text(probe_json, encoding="utf-8")
        else:
            probe_path.write_text(json.dumps(probe_json), encoding="utf-8")

    return tmp_path


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    original = os.environ.get("VG_REPO_ROOT")
    yield
    if original is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original


# ---------------------------------------------------------------------------
# Goal + probe fixtures
# ---------------------------------------------------------------------------


GOAL_FULL = """---
id: G-01
title: "Campaigns list"
surface: ui
trigger: "GET /api/campaigns"
interactive_controls:
  url_sync: true
  filters:
    - name: status
      values: [active, paused]
      url_param: status
      assertion: "rows match"
  pagination:
    page_size: 20
    url_param_page: page
    assertion: "page2 differs"
  search:
    url_param: q
    debounce_ms: 300
    assertion: "search syncs"
  sort:
    columns: [created_at]
    url_param_field: sort
    url_param_dir: dir
    assertion: "asc/desc"
---
"""

GOAL_NO_URL_SYNC = """---
id: G-02
title: "Static dashboard"
surface: ui
trigger: "GET /admin/dashboard"
---
"""


def _full_probe() -> dict:
    return {
        "goals": [{
            "goal_id": "G-01",
            "url": "/admin/campaigns",
            "controls": [
                {"kind": "filter", "name": "status",
                 "value": "active",
                 "url_params_after": {"status": "active"}},
                {"kind": "pagination", "name": "page",
                 "value": "2",
                 "url_params_after": {"page": "2"}},
                {"kind": "search", "name": "search",
                 "value": "abc",
                 "url_params_after": {"q": "abc"}},
                {"kind": "sort", "name": "sort",
                 "value": "created_at",
                 "url_params_after": {"sort": "created_at", "dir": "asc"}},
            ],
        }],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pass_all_controls_match(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_FULL, probe_json=_full_probe(),
    )
    rc, data = _run(repo, "14")
    assert rc == 0, data
    assert data["verdict"] == "PASS", data


def test_warn_on_missing_probe_artifact(tmp_path):
    repo = _setup_fake_repo(
        tmp_path, phase="14", goals_md=GOAL_FULL, probe_json=None,
    )
    rc, data = _run(repo, "14")
    assert rc == 0, data
    assert data["verdict"] == "WARN", data
    types = [e["type"] for e in data["evidence"]]
    assert "url_runtime_probe_missing" in types


def test_warn_on_goal_unprobed(tmp_path):
    """Probe artifact exists but G-01 is missing from probe.goals[]."""
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_FULL,
        probe_json={"goals": [{"goal_id": "G-99", "url": "/x", "controls": []}]},
    )
    rc, data = _run(repo, "14")
    assert rc == 0
    assert data["verdict"] == "WARN", data
    assert any(e["type"] == "url_runtime_probe_goal_missing"
               for e in data["evidence"])


def test_warn_on_unprobed_control(tmp_path):
    """G-01 entry exists but pagination control was not exercised."""
    probe = _full_probe()
    probe["goals"][0]["controls"] = [
        c for c in probe["goals"][0]["controls"]
        if c["kind"] != "pagination"
    ]
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_FULL, probe_json=probe,
    )
    rc, data = _run(repo, "14")
    assert rc == 0
    assert data["verdict"] == "WARN", data
    assert any(e["type"] == "url_runtime_control_unprobed"
               for e in data["evidence"])


def test_block_on_param_mismatch(tmp_path):
    """Filter exercised but URL did not carry declared 'status' param."""
    probe = _full_probe()
    # Drift: implementation wrote 'state' instead of 'status'.
    probe["goals"][0]["controls"][0]["url_params_after"] = {"state": "active"}
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_FULL, probe_json=probe,
    )
    rc, data = _run(repo, "14")
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    assert any(e["type"] == "url_runtime_param_missing"
               for e in data["evidence"])


def test_skip_runtime_suppresses_checks(tmp_path):
    """--skip-runtime returns WARN-only even when probe missing."""
    repo = _setup_fake_repo(
        tmp_path, phase="14", goals_md=GOAL_FULL, probe_json=None,
    )
    rc, data = _run(repo, "14", "--skip-runtime")
    assert rc == 0
    assert data["verdict"] == "WARN", data
    assert any(e["type"] == "url_runtime_probe_skipped"
               for e in data["evidence"])


def test_goal_without_url_sync_ignored(tmp_path):
    """Goal lacking interactive_controls.url_sync: true is not checked."""
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_NO_URL_SYNC, probe_json=None,
    )
    rc, data = _run(repo, "14")
    assert rc == 0
    assert data["verdict"] == "PASS", data
    assert data["evidence"] == []


def test_block_on_malformed_probe_json(tmp_path):
    """Malformed probe artifact → BLOCK with parse error evidence."""
    repo = _setup_fake_repo(
        tmp_path, phase="14",
        goals_md=GOAL_FULL,
        probe_json="{ this is not json",
    )
    rc, data = _run(repo, "14")
    assert rc == 1
    assert data["verdict"] == "BLOCK", data
    assert any(e["type"] == "url_runtime_probe_malformed"
               for e in data["evidence"])
