"""
B11.1 — not-scanned-replay.py tests.

Enforces defense-in-depth for the hard rule "NOT_SCANNED không được
defer sang /vg:test". If review exits with intermediate-status goals,
test gate blocks with actionable per-goal detail.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "not-scanned-replay.py"


def _setup(tmp_path: Path, matrix_content: str | None = None) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    if matrix_content is not None:
        (phase_dir / "GOAL-COVERAGE-MATRIX.md").write_text(
            matrix_content, encoding="utf-8",
        )
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=repo, capture_output=True, text=True, timeout=15, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line.strip())
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

MATRIX_ALL_READY = """
# GOAL-COVERAGE-MATRIX

| Goal | Description | Priority | Status | Start view | Sequence ref |
|------|-------------|----------|--------|------------|--------------|
| G-01 | User login | critical | READY | /login | #seq-1 |
| G-02 | Dashboard render | important | READY | /dashboard | #seq-2 |
"""

MATRIX_WITH_NOT_SCANNED = """
| Goal | Description | Priority | Status | Start view | Sequence ref |
|------|-------------|----------|--------|------------|--------------|
| G-01 | Create campaign | critical | READY | /campaigns | #seq-1 |
| G-02 | Edit profile | important | NOT_SCANNED | /settings/profile | - |
| G-03 | Delete account | critical | NOT_SCANNED | /settings/danger | - |
"""

MATRIX_WITH_FAILED = """
| Goal | Description | Priority | Status | Start view | Sequence ref |
|------|-------------|----------|--------|------------|--------------|
| G-01 | Submit report | critical | FAILED | /reports/new | - |
"""

MATRIX_MIXED = """
| Goal | Description | Priority | Status | Start view | Sequence ref |
|------|-------------|----------|--------|------------|--------------|
| G-01 | Ready goal | critical | READY | /x | #seq-1 |
| G-02 | Not scanned | important | NOT_SCANNED | /y | - |
| G-03 | Failed goal | nice | FAILED | /z | - |
| G-04 | Unreachable | critical | UNREACHABLE | - | - |
"""


def test_all_ready_passes(tmp_path):
    repo = _setup(tmp_path, MATRIX_ALL_READY)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_not_scanned_blocks(tmp_path):
    repo = _setup(tmp_path, MATRIX_WITH_NOT_SCANNED)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    msg = json.dumps(out["evidence"])
    assert "G-02" in msg and "G-03" in msg
    assert "settings/profile" in msg


def test_failed_blocks(tmp_path):
    repo = _setup(tmp_path, MATRIX_WITH_FAILED)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "G-01" in json.dumps(out["evidence"])


def test_mixed_blocks_only_intermediate(tmp_path):
    """UNREACHABLE is a valid terminal status — not counted."""
    repo = _setup(tmp_path, MATRIX_MIXED)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    ev = out["evidence"][0]
    assert "G-02" in ev["actual"]  # NOT_SCANNED surfaced
    assert "G-03" in ev["actual"]  # FAILED surfaced
    assert "G-04" not in ev["actual"]  # UNREACHABLE not surfaced
    assert "G-01" not in ev["actual"]  # READY not surfaced


def test_no_matrix_skips(tmp_path):
    """No matrix → goal-coverage validator handles that; this one skips."""
    repo = _setup(tmp_path, matrix_content=None)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_start_view_surfaced(tmp_path):
    """start_view column must appear in evidence for user to act on."""
    repo = _setup(tmp_path, MATRIX_WITH_NOT_SCANNED)
    r = _run(repo)
    out = _parse(r.stdout)
    ev = out["evidence"][0]
    assert "start_view=/settings/profile" in ev["actual"]


def test_registered_in_test_dispatcher():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "not-scanned-replay" in mod.COMMAND_VALIDATORS.get("vg:test", [])
