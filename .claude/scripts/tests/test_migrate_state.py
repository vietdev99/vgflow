"""
test_migrate_state.py — Tier A coverage for /vg:migrate-state drift detector.

Pins:
1. Idempotency: re-applying on a sync'd phase produces no marker writes,
   no new OD entry.
2. Drift detection: a phase with artifact evidence + missing markers is
   identified; a phase without evidence is skipped.
3. Apply mode: backfilled markers carry the documented schema string and
   live under .step-markers/{cmd}/{step}.done.
4. Dry-run: would-create actions reported but no files written.
5. OD entry format: appended to .vg/OVERRIDE-DEBT.md with required fields.
6. CLI exit codes: 0 = no-drift / applied, 1 = drift-detected (scan/dry-run).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "migrate-state.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the COPY of migrate-state.py inside cwd so its REPO_ROOT
    (Path(__file__).parents[2]) resolves to the test fixture, not the host
    repo. The fixture pre-copies the script via _setup_fake_repo.
    """
    fake_script = cwd / ".claude" / "scripts" / "migrate-state.py"
    return subprocess.run(
        [sys.executable, str(fake_script)] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30,
    )


def _setup_fake_repo(tmp_path: Path, *, with_drift: bool = True) -> Path:
    """Create a minimal repo layout with one phase that has artifact evidence
    (PLAN.md, REVIEW-FEEDBACK.md, SANDBOX-TEST.md) but no markers.
    """
    # Mirror skill files so script's REPO_ROOT detection finds steps.
    (tmp_path / ".claude" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / ".claude" / "scripts" / "migrate-state.py")

    cmd_dir = tmp_path / ".claude" / "commands" / "vg"
    cmd_dir.mkdir(parents=True)
    # Minimal skill stubs declaring 2 steps each
    (cmd_dir / "blueprint.md").write_text(
        '<step name="2a_plan">\n<step name="3_complete">\n', encoding="utf-8"
    )
    (cmd_dir / "review.md").write_text(
        '<step name="phase1_code_scan">\n<step name="phase4_goal_comparison">\n',
        encoding="utf-8",
    )
    (cmd_dir / "test.md").write_text(
        '<step name="5a_deploy">\n<step name="write_report">\n', encoding="utf-8"
    )
    # Phase with full artifacts + zero markers (drift case)
    phase = tmp_path / ".vg" / "phases" / "9.0-test"
    phase.mkdir(parents=True)
    if with_drift:
        (phase / "PLAN.md").write_text("# plan", encoding="utf-8")
        (phase / "API-CONTRACTS.md").write_text("# contracts", encoding="utf-8")
        (phase / "TEST-GOALS.md").write_text("# goals", encoding="utf-8")
        (phase / "REVIEW-FEEDBACK.md").write_text("# review", encoding="utf-8")
        (phase / "SANDBOX-TEST.md").write_text("# test", encoding="utf-8")
    # OVERRIDE-DEBT.md skeleton
    od = tmp_path / ".vg" / "OVERRIDE-DEBT.md"
    od.write_text("# VG Override Debt Register\n\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scan_detects_drift(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    r = _run(["--scan", "--json"], repo)
    assert r.returncode == 1, "drift present → expect exit 1 in scan mode"
    data = json.loads(r.stdout)
    phase = data["scan"][0]
    assert phase["phase"] == "9.0-test"
    assert phase["totals"]["missing_markers"] == 6, (
        "blueprint(2) + review(2) + test(2) = 6 markers expected missing"
    )


def test_scan_skips_command_without_artifacts(tmp_path):
    repo = _setup_fake_repo(tmp_path, with_drift=False)
    r = _run(["--scan", "--json"], repo)
    # No artifact files = "command never ran" → no drift counted
    data = json.loads(r.stdout)
    assert data["scan"][0]["totals"]["missing_markers"] == 0
    assert r.returncode == 0


def test_apply_creates_markers_with_schema(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    r = _run(["9.0-test"], repo)
    assert r.returncode == 0
    phase = repo / ".vg" / "phases" / "9.0-test"
    bp_marker = phase / ".step-markers" / "blueprint" / "2a_plan.done"
    assert bp_marker.exists(), "blueprint marker should be created"
    body = bp_marker.read_text(encoding="utf-8")
    assert body.startswith("migration-backfill|9.0-test|blueprint/2a_plan|")
    assert body.rstrip().endswith("skill-version-drift")


def test_apply_logs_single_od_entry(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    _run(["9.0-test"], repo)
    od_text = (repo / ".vg" / "OVERRIDE-DEBT.md").read_text(encoding="utf-8")
    od_ids = re.findall(r"^- id: (OD-\d+)", od_text, re.MULTILINE)
    assert len(od_ids) == 1, f"expected exactly 1 OD entry, got: {od_ids}"
    # Required schema fields present
    assert "flag: skill-version-drift-marker-backfill" in od_text
    assert 'phase: "9.0-test"' in od_text
    assert "command: vg:migrate-state" in od_text


def test_apply_idempotent(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    _run(["9.0-test"], repo)  # first apply
    od1 = (repo / ".vg" / "OVERRIDE-DEBT.md").read_text(encoding="utf-8")
    r = _run(["9.0-test"], repo)  # second apply
    od2 = (repo / ".vg" / "OVERRIDE-DEBT.md").read_text(encoding="utf-8")
    assert "no drift (already in sync)" in r.stdout
    assert od1 == od2, "idempotent re-run must not append a new OD entry"


def test_dry_run_writes_nothing(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    r = _run(["9.0-test", "--dry-run"], repo)
    assert r.returncode == 0
    assert "Would backfill" in r.stdout
    phase = repo / ".vg" / "phases" / "9.0-test"
    assert not (phase / ".step-markers").exists(), (
        "dry-run must not create marker dir"
    )
    od = (repo / ".vg" / "OVERRIDE-DEBT.md").read_text(encoding="utf-8")
    assert "OD-" not in od, "dry-run must not append OD entry"


def test_apply_all_only_touches_drifted_phases(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    # Add a clean phase (no artifacts, no drift)
    (repo / ".vg" / "phases" / "9.1-clean").mkdir()
    r = _run(["--apply-all", "--json"], repo)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    phase_ids = {a["phase"] for a in data["applied"]}
    assert phase_ids == {"9.0-test"}, (
        f"only drifted phase should appear in applied list: {phase_ids}"
    )


def test_phase_shorthand_resolution(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    # Rename to shorthand-style: "9.0-something-long"
    src = repo / ".vg" / "phases" / "9.0-test"
    long_name = repo / ".vg" / "phases" / "9.0-some-long-suffix"
    src.rename(long_name)
    r = _run(["9.0", "--dry-run"], repo)
    assert r.returncode == 0, r.stderr
    assert "9.0-some-long-suffix" in r.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
