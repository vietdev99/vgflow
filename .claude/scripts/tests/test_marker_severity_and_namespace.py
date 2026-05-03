"""
OHOK-9 (d) — marker severity/waiver + D-XX namespace dual-accept.

Gap 1: Runtime contract markers incomplete.
Fix: `must_touch_markers` entries may set severity="warn" or
required_unless_flag="--skip-X". Warn missing emits
contract.marker_warn event (not violation). Waived markers emit
contract.marker_waived and skip check entirely.

Gap 2: D-XX namespace mismatch.
Fix: already handled by validators (context-structure +
commit-attribution) — both accept `D-XX` AND `P{N}.D-XX`. Lock with
regression tests so future refactor doesn't silently tighten either.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "vg-orchestrator"))
sys.path.insert(0, str(Path(__file__).parent.parent / "validators"))

import contracts  # type: ignore  # noqa: E402

from conftest import assert_expected_block  # noqa: E402


ORCH = Path(__file__).resolve().parents[1] / "vg-orchestrator"
PYTHON = sys.executable


# ═══════════════════════════ Gap 1 tests ═══════════════════════════

def test_normalize_markers_string_defaults_to_block():
    out = contracts.normalize_markers(["step1", "step2"])
    assert out[0]["severity"] == "block"
    assert out[0]["required_unless_flag"] is None
    assert out[1]["severity"] == "block"


def test_normalize_markers_dict_severity_warn():
    out = contracts.normalize_markers([
        {"name": "crossai_review", "severity": "warn"},
        {"name": "validation_step", "severity": "warn",
         "required_unless_flag": "--skip-validation"},
    ])
    assert out[0]["severity"] == "warn"
    assert out[0]["required_unless_flag"] is None
    assert out[1]["severity"] == "warn"
    assert out[1]["required_unless_flag"] == "--skip-validation"


def test_normalize_markers_mixed_strings_and_dicts():
    """Must tolerate heterogeneous lists — existing contracts stay valid."""
    out = contracts.normalize_markers([
        "legacy_step",
        {"name": "new_step", "severity": "warn"},
    ])
    assert len(out) == 2
    assert out[0]["name"] == "legacy_step"
    assert out[0]["severity"] == "block"
    assert out[1]["severity"] == "warn"


# ═══════════════════════════ Gap 2 tests ═══════════════════════════

def _run_context_validator(repo: Path) -> subprocess.CompletedProcess:
    """Run context-structure.py with VG_REPO_ROOT scoped to sandbox repo."""
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    validator = (Path(__file__).parent.parent / "validators"
                 / "context-structure.py")
    return subprocess.run(
        [PYTHON, str(validator), "--phase", "88"],
        capture_output=True, text=True, env=env, timeout=10,
    )


def _write_context(repo: Path, phase_slug: str, body: str) -> None:
    phase_dir = repo / ".vg" / "phases" / phase_slug
    phase_dir.mkdir(parents=True, exist_ok=True)
    # Ensure ≥500 bytes so context-structure doesn't fail on size
    padding = "\n" + ("x" * 500)
    (phase_dir / "CONTEXT.md").write_text(body + padding, encoding="utf-8")


def test_context_structure_accepts_bare_D_format(tmp_path):
    """`### D-15: ...` satisfies decision header check (legacy format)."""
    _write_context(
        tmp_path, "88-legacy",
        "# CONTEXT\n\n"
        "### D-01: First decision\n**Endpoints:** /x\n\n"
        "### D-02: Second decision\n**Test Scenarios:** TS-01\n",
    )
    r = _run_context_validator(tmp_path)
    assert r.returncode == 0, (
        f"bare D-XX rejected: rc={r.returncode}\nstderr={r.stderr}\nstdout={r.stdout}"
    )


def test_context_structure_accepts_namespaced_P_D_format(tmp_path):
    """`### P88.D-15: ...` satisfies decision header check (new format)."""
    _write_context(
        tmp_path, "88-namespaced",
        "# CONTEXT\n\n"
        "### P88.D-01: First decision\n**Endpoints:** /x\n\n"
        "### P88.D-02: Second decision\n**Test Scenarios:** TS-01\n",
    )
    r = _run_context_validator(tmp_path)
    assert r.returncode == 0, (
        f"namespaced rejected: rc={r.returncode}\nstderr={r.stderr}\nstdout={r.stdout}"
    )


def test_context_structure_accepts_mixed_format(tmp_path):
    """Mixed bare + namespaced in same CONTEXT.md both count."""
    _write_context(
        tmp_path, "88-mixed",
        "# CONTEXT\n\n"
        "### D-01: Bare format\n**Endpoints:** /x\n\n"
        "### P88.D-02: Namespaced format\n**Test Scenarios:** TS-01\n",
    )
    r = _run_context_validator(tmp_path)
    assert r.returncode == 0, (
        f"mixed format rejected: rc={r.returncode}\nstderr={r.stderr}\nstdout={r.stdout}"
    )


# ═══════════════ End-to-end: severity=warn doesn't block ═══════════════

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolated sandbox with warn-severity marker in scope contract."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".vg" / "phases" / "77-warn-test").mkdir(parents=True)
    (repo / ".claude" / "commands" / "vg").mkdir(parents=True)

    src_root = Path(__file__).resolve().parents[2]
    for sub in ("scripts/vg-orchestrator", "scripts/validators", "schemas"):
        shutil.copytree(src_root / sub, repo / ".claude" / sub,
                        dirs_exist_ok=True)

    # Minimal scope skill-MD with warn-severity marker/telemetry + one waivable
    skill = repo / ".claude" / "commands" / "vg" / "scope.md"
    skill.write_text(textwrap.dedent("""\
        ---
        name: vg:scope
        runtime_contract:
          must_write:
            - "${PHASE_DIR}/CONTEXT.md"
            - "${PHASE_DIR}/DISCUSSION-LOG.md"
          must_touch_markers:
            - "0_parse_and_validate"
            - name: "crossai_review"
              severity: "warn"
            - name: "optional_reflection"
              severity: "warn"
              required_unless_flag: "--skip-reflection"
          must_emit_telemetry:
            - event_type: "scope.completed"
            - event_type: "scope.optional_branch"
              severity: "warn"
        ---

        # Test scope with warn + waivable markers
        """), encoding="utf-8")

    (repo / ".vg" / "phases" / "77-warn-test" / "SPECS.md").write_text(
        "# SPECS\n\nFeature phase test " + ("x" * 120), encoding="utf-8",
    )

    monkeypatch.setenv("VG_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(contracts, "PHASES_DIR", repo / ".vg" / "phases")
    return repo


def orch(sandbox, *args):
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(sandbox)
    return subprocess.run(
        [PYTHON, str(ORCH), *args],
        cwd=str(sandbox),
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_warn_marker_missing_does_not_block(sandbox):
    """Missing warn-severity marker → run PASSES with WARN event logged."""
    r = orch(sandbox, "run-start", "vg:scope", "77")
    assert r.returncode == 0, f"run-start failed: {r.stderr}"

    phase_dir = sandbox / ".vg" / "phases" / "77-warn-test"
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n### P77.D-01: Test decision\n\n"
        "**Endpoints:** GET /api/x\n\n"
        "**Test Scenarios:** TS-01\n\n"
        + ("x" * 600), encoding="utf-8",
    )
    (phase_dir / "DISCUSSION-LOG.md").write_text("log\n" + ("x" * 600),
                                                 encoding="utf-8")
    # Only mark the block-severity marker — leave warn + waivable missing
    orch(sandbox, "mark-step", "scope", "0_parse_and_validate")
    orch(sandbox, "emit-event", "scope.completed")

    r = orch(sandbox, "run-complete")
    # Waivable marker not waived (flag not present) → becomes warn-missing
    # AND warn-severity-marker missing → both should be warn, not block.
    assert r.returncode == 0, (
        f"warn markers blocked run! rc={r.returncode}\n"
        f"stderr={r.stderr}\nstdout={r.stdout}"
    )

    # Verify contract.marker_warn and contract.telemetry_warn events emitted
    db_path = sandbox / ".vg" / "events.db"
    assert db_path.exists(), "events.db missing"
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT event_type, payload_json FROM events "
            "WHERE event_type = 'contract.marker_warn'"
        ).fetchall()
        telemetry_rows = conn.execute(
            "SELECT event_type, payload_json FROM events "
            "WHERE event_type = 'contract.telemetry_warn'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 1, (
        f"Expected >=1 contract.marker_warn event, got {len(rows)}"
    )
    assert len(telemetry_rows) >= 1, (
        f"Expected >=1 contract.telemetry_warn event, got {len(telemetry_rows)}"
    )


def test_waivable_marker_skipped_when_flag_present(sandbox):
    """required_unless_flag=--skip-reflection → marker check waived when flag in args."""
    r = orch(sandbox, "run-start", "vg:scope", "77", "--skip-reflection")
    assert r.returncode == 0, f"run-start failed: {r.stderr}"

    phase_dir = sandbox / ".vg" / "phases" / "77-warn-test"
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n### P77.D-01: Test decision\n\n"
        "**Endpoints:** GET /api/x\n\n"
        "**Test Scenarios:** TS-01\n\n"
        + ("x" * 600), encoding="utf-8",
    )
    (phase_dir / "DISCUSSION-LOG.md").write_text("log\n" + ("x" * 600),
                                                 encoding="utf-8")
    orch(sandbox, "mark-step", "scope", "0_parse_and_validate")
    orch(sandbox, "emit-event", "scope.completed")

    r = orch(sandbox, "run-complete")
    assert r.returncode == 0, (
        f"waivable flag didn't waive marker! rc={r.returncode}\n"
        f"stderr={r.stderr}"
    )

    # Verify contract.marker_waived emitted for `optional_reflection`
    db_path = sandbox / ".vg" / "events.db"
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE event_type = 'contract.marker_waived'"
        ).fetchall()
    finally:
        conn.close()
    assert any(
        json.loads(r[0]).get("marker") == "optional_reflection"
        for r in rows
    ), f"Expected optional_reflection marker waived, got events: {rows}"


def test_block_marker_still_blocks(sandbox):
    """String-form marker (severity=block default) still blocks when missing."""
    r = orch(sandbox, "run-start", "vg:scope", "77")
    assert r.returncode == 0

    phase_dir = sandbox / ".vg" / "phases" / "77-warn-test"
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n### P77.D-01: Test decision\n\n"
        "**Endpoints:** GET /api/x\n\n"
        "**Test Scenarios:** TS-01\n\n"
        + ("x" * 600), encoding="utf-8",
    )
    (phase_dir / "DISCUSSION-LOG.md").write_text("log\n" + ("x" * 600),
                                                 encoding="utf-8")
    # Skip the block marker 0_parse_and_validate → should BLOCK
    orch(sandbox, "emit-event", "scope.completed")

    r = orch(sandbox, "run-complete")
    assert_expected_block(
        r,
        "block-severity marker missing must still BLOCK even when warn/waived peers exist",
    )
