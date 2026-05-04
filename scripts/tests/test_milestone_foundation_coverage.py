"""R8-G — Tests for `verify-milestone-foundation-coverage.py`.

Coverage:
  - test_passes_all_goals_satisfied        — all goals cited + UAT + runtime
  - test_blocks_unsatisfied_goal           — F-02 not cited anywhere → BLOCK
  - test_warns_partial_no_runtime_evidence — cited + UAT but no RUNTIME-MAP → WARN
  - test_generates_matrix_artifact         — FOUNDATION-COVERAGE-MATRIX.md written
  - test_handles_modern_uat_path           — ${PHASE}-UAT.md (R8-H glob)
  - test_handles_legacy_uat_path           — plain UAT.md (legacy)
  - test_no_foundation_returns_warn        — graceful for early projects
  - test_no_milestone_goals_returns_warn   — milestone section without F-XX ids
  - test_mirror_parity                     — source vs .claude/ mirror byte-equal

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  rc 0 → PASS or WARN
  rc 1 → BLOCK
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-milestone-foundation-coverage.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-milestone-foundation-coverage.py"


# ─── Fixture helpers ──────────────────────────────────────────────────


def _seed_repo(
    tmp_path: Path,
    *,
    foundation: str | None,
    roadmap: str | None = None,
    state_md: str | None = None,
) -> Path:
    """Seed a tmp 'repo' with .vg/ structure.

    Returns the repo root.
    """
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / "phases").mkdir()
    if foundation is not None:
        (vg_dir / "FOUNDATION.md").write_text(foundation, encoding="utf-8")
    if roadmap is not None:
        (vg_dir / "ROADMAP.md").write_text(roadmap, encoding="utf-8")
    if state_md is not None:
        (vg_dir / "STATE.md").write_text(state_md, encoding="utf-8")
    return tmp_path


def _make_phase(
    repo: Path,
    name: str,
    *,
    specs: str | None = None,
    uat_filename: str | None = None,
    uat_verdict: str | None = "ACCEPTED",
    runtime_map: str | None = None,
    runtime_filename: str = "RUNTIME-MAP.json",
) -> Path:
    """Create a phase dir with optional SPECS, UAT, RUNTIME-MAP."""
    phase = repo / ".vg" / "phases" / name
    phase.mkdir()
    if specs is not None:
        (phase / "SPECS.md").write_text(specs, encoding="utf-8")
    if uat_filename:
        text = f"# UAT\n\nVerdict: {uat_verdict or 'PENDING'}\n"
        (phase / uat_filename).write_text(text, encoding="utf-8")
    if runtime_map is not None:
        (phase / runtime_filename).write_text(runtime_map, encoding="utf-8")
    return phase


def _run_validator(
    repo: Path,
    *args: str,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_PLANNING_DIR"] = str(repo / ".vg")
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20,
        env=env, encoding="utf-8", errors="replace",
        cwd=str(repo),
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# Canonical FOUNDATION + ROADMAP fixtures ───────────────────────────────

_FOUNDATION = """# FOUNDATION

## Milestone M1

Goals delivered in this milestone:

- F-01: User authentication and session management
- F-02: Payments processing
- F-03: Reporting dashboard

## Milestone M2

- F-10: Mobile app
"""

_ROADMAP = """# ROADMAP

## M1

- Phase 1 — auth foundation
- Phase 2 — payments
- Phase 4.1 — auth follow-up
- Phase 5.2 — reporting

## M2

- Phase 7 — mobile shell
"""


# ─── Behavioral tests ─────────────────────────────────────────────────


def test_passes_all_goals_satisfied(tmp_path):
    """All milestone goals cited + UAT ACCEPTED + runtime evidence → PASS."""
    repo = _seed_repo(tmp_path, foundation=_FOUNDATION, roadmap=_ROADMAP)
    _make_phase(
        repo, "1-auth",
        specs="# SPECS\n\nDelivers F-01 user auth.\n",
        uat_filename="1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"], "routes": ["/login"]}),
    )
    _make_phase(
        repo, "4.1-auth-follow",
        specs="# SPECS\n\nExtends F-01 with 2FA.\n",
        uat_filename="4.1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    _make_phase(
        repo, "2-payments",
        specs="# SPECS\n\nF-02 payments engine.\n",
        uat_filename="2-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-02"]}),
    )
    _make_phase(
        repo, "5.2-reports",
        specs="# SPECS\n\nF-03 reporting.\n",
        uat_filename="5.2-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-03"]}),
    )

    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, (
        f"Expected rc=0 (PASS), got {proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "PASS", out


def test_blocks_unsatisfied_goal(tmp_path):
    """F-02 cited by no phase → BLOCK rc=1."""
    repo = _seed_repo(tmp_path, foundation=_FOUNDATION, roadmap=_ROADMAP)
    # Only F-01 cited
    _make_phase(
        repo, "1-auth",
        specs="# SPECS\n\nF-01 only.\n",
        uat_filename="1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )

    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 1, (
        f"Expected rc=1 (BLOCK), got {proc.returncode}\n"
        f"stdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK", out
    types = {e.get("type") for e in out["evidence"]}
    assert "foundation_goal_unsatisfied" in types, types
    # F-02 and F-03 should both surface as unsatisfied
    msgs = " ".join(e.get("message", "") for e in out["evidence"])
    assert "F-02" in msgs, msgs
    assert "F-03" in msgs, msgs


def test_warns_partial_no_runtime_evidence(tmp_path):
    """Phase cites + UAT ACCEPTED but no RUNTIME-MAP → PARTIAL → WARN (rc=0)."""
    repo = _seed_repo(tmp_path, foundation=_FOUNDATION, roadmap=_ROADMAP)
    # All three goals cited + accepted, but reporting has no runtime evidence
    _make_phase(
        repo, "1-auth",
        specs="# SPECS\n\nF-01.\n",
        uat_filename="1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    _make_phase(
        repo, "2-payments",
        specs="# SPECS\n\nF-02.\n",
        uat_filename="2-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-02"]}),
    )
    _make_phase(
        repo, "5.2-reports",
        specs="# SPECS\n\nF-03 reporting.\n",
        uat_filename="5.2-UAT.md", uat_verdict="ACCEPTED",
        # No runtime_map → PARTIAL
    )

    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, (
        f"Expected rc=0 (WARN), got {proc.returncode}\n"
        f"stdout={proc.stdout}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "foundation_goal_partial" in types, types


def test_generates_matrix_artifact(tmp_path):
    """Validator writes .vg/milestones/{M}/FOUNDATION-COVERAGE-MATRIX.md."""
    repo = _seed_repo(tmp_path, foundation=_FOUNDATION, roadmap=_ROADMAP)
    _make_phase(
        repo, "1-auth",
        specs="F-01 cited",
        uat_filename="1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    proc = _run_validator(repo, "--milestone", "M1")
    # rc may be 1 (BLOCK because F-02/F-03 unsatisfied) — that's fine; we
    # only care that the artifact landed regardless of verdict.
    assert proc.returncode in (0, 1), proc.stdout

    matrix = repo / ".vg" / "milestones" / "M1" / "FOUNDATION-COVERAGE-MATRIX.md"
    assert matrix.is_file(), f"Matrix not written: {matrix}"
    text = matrix.read_text(encoding="utf-8")
    assert "Foundation Coverage Matrix" in text
    assert "M1" in text
    assert "F-01" in text
    assert "F-02" in text
    assert "F-03" in text
    # Header should include the goal/desc/citing/verdicts/runtime/status columns
    assert "Phases citing" in text
    assert "Status" in text


def test_handles_modern_uat_path(tmp_path):
    """${PHASE}-UAT.md (e.g. 4.1-UAT.md) recognized as ACCEPTED (R8-H glob)."""
    foundation = """## M1

- F-01: Auth
"""
    repo = _seed_repo(tmp_path, foundation=foundation)
    _make_phase(
        repo, "4.1-auth",
        specs="cites F-01",
        uat_filename="4.1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "PASS", out


def test_handles_legacy_uat_path(tmp_path):
    """Plain UAT.md (legacy phases) still counts as ACCEPTED."""
    foundation = """## M1

- F-01: Auth
"""
    repo = _seed_repo(tmp_path, foundation=foundation)
    _make_phase(
        repo, "1-legacy",
        specs="cites F-01",
        uat_filename="UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "PASS", out


def test_no_foundation_returns_warn(tmp_path):
    """No FOUNDATION.md → graceful WARN (advisory) rc=0."""
    repo = _seed_repo(tmp_path, foundation=None)
    # No FOUNDATION at all — should not crash
    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "foundation_missing" in types, types


def test_no_milestone_goals_returns_warn(tmp_path):
    """FOUNDATION.md exists but milestone section has no F-XX ids → WARN."""
    foundation = """# FOUNDATION

## Milestone M1

Some narrative without any goal ids.
"""
    repo = _seed_repo(tmp_path, foundation=foundation)
    proc = _run_validator(repo, "--milestone", "M1")
    assert proc.returncode == 0, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "WARN", out
    types = {e.get("type") for e in out["evidence"]}
    assert "milestone_goals_not_extracted" in types, types


def test_auto_detect_milestone_from_state(tmp_path):
    """Without --milestone, validator reads current_milestone from STATE.md."""
    state_md = "current_milestone: M1\n"
    foundation = """## Milestone M1

- F-01: Auth
"""
    repo = _seed_repo(tmp_path, foundation=foundation, state_md=state_md)
    _make_phase(
        repo, "1-a",
        specs="F-01",
        uat_filename="1-UAT.md", uat_verdict="ACCEPTED",
        runtime_map=json.dumps({"goals": ["F-01"]}),
    )
    proc = _run_validator(repo)  # no --milestone
    assert proc.returncode == 0, proc.stdout
    out = _parse_output(proc)
    assert out["verdict"] == "PASS", out


# ─── Mirror parity ────────────────────────────────────────────────────


def test_mirror_parity():
    """Source and .claude/ mirror must stay byte-identical."""
    assert MIRROR.is_file(), f"Mirror missing: {MIRROR}"
    src_bytes = VALIDATOR.read_bytes()
    mirror_bytes = MIRROR.read_bytes()
    assert src_bytes == mirror_bytes, (
        f"Mirror drift between {VALIDATOR} and {MIRROR}"
    )
