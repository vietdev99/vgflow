"""Tests for scripts/migrate-legacy-provenance.py.

RFC v9 D10 migration tool — tags pre-v9 mutation steps lacking
`evidence` with `provenance_status: legacy_pre_provenance` so the
provenance validator skips them while still allowing future re-scans
to record real scanner-source evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate-legacy-provenance.py"


def _run(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _phase(tmp_path: Path, name: str, runtime: dict) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / name
    phase_dir.mkdir(parents=True)
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps(runtime, indent=2), encoding="utf-8",
    )
    return phase_dir


def _mutation_step(evidence: dict | None = None,
                   already_tagged: bool = False) -> dict:
    step = {
        "do": "click",
        "target": "Submit topup",
        "network": [{"method": "POST", "endpoint": "/api/topup", "status": 200}],
    }
    if evidence is not None:
        step["evidence"] = evidence
    if already_tagged:
        step["provenance_status"] = "legacy_pre_provenance"
    return step


def test_dry_run_reports_without_writing(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step()]}}
    })
    result = _run(tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "newly-tagged=  1" in result.stdout
    # File NOT modified
    rt = json.loads((phase_dir / "RUNTIME-MAP.json").read_text())
    assert "provenance_status" not in rt["goal_sequences"]["G-01"]["steps"][0]


def test_apply_tags_legacy_steps(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step()]}}
    })
    result = _run(tmp_path, "--apply", "--no-backup")
    assert result.returncode == 0, result.stderr
    rt = json.loads((phase_dir / "RUNTIME-MAP.json").read_text())
    step = rt["goal_sequences"]["G-01"]["steps"][0]
    assert step["provenance_status"] == "legacy_pre_provenance"
    assert "provenance_migrated_at" in step


def test_apply_writes_backup_by_default(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step()]}}
    })
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0
    bak = phase_dir / "RUNTIME-MAP.json.bak"
    assert bak.exists()
    # Backup is the ORIGINAL (no provenance_status tag)
    bak_data = json.loads(bak.read_text())
    assert "provenance_status" not in bak_data["goal_sequences"]["G-01"]["steps"][0]


def test_skips_steps_with_existing_evidence(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step(
            evidence={"source": "scanner", "scanner_run_id": "haiku-1"}
        )]}}
    })
    result = _run(tmp_path, "--apply", "--no-backup")
    assert result.returncode == 0
    rt = json.loads((phase_dir / "RUNTIME-MAP.json").read_text())
    step = rt["goal_sequences"]["G-01"]["steps"][0]
    # Untouched
    assert "provenance_status" not in step
    assert "evidence" in step


def test_skips_already_tagged_legacy(tmp_path):
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step(already_tagged=True)]}}
    })
    result = _run(tmp_path, "--apply", "--no-backup")
    assert result.returncode == 0
    assert "already-legacy=  1" in result.stdout
    assert "newly-tagged=  0" in result.stdout


def test_skips_steps_without_2xx_network(tmp_path):
    """No claim-of-success → no evidence required → no migration tag."""
    step = {
        "do": "click",
        "target": "Submit topup",
        "network": [{"method": "POST", "endpoint": "/api/topup", "status": 422}],
    }
    phase_dir = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [step]}}
    })
    result = _run(tmp_path, "--apply", "--no-backup")
    assert result.returncode == 0
    rt = json.loads((phase_dir / "RUNTIME-MAP.json").read_text())
    assert "provenance_status" not in rt["goal_sequences"]["G-01"]["steps"][0]


def test_phase_filter_targets_single_phase(tmp_path):
    p1 = _phase(tmp_path, "01.0-foo", {
        "goal_sequences": {"G-01": {"steps": [_mutation_step()]}}
    })
    p2 = _phase(tmp_path, "02.0-bar", {
        "goal_sequences": {"G-02": {"steps": [_mutation_step()]}}
    })
    result = _run(tmp_path, "--phase", "1.0", "--apply", "--no-backup")
    assert result.returncode == 0, result.stderr
    rt1 = json.loads((p1 / "RUNTIME-MAP.json").read_text())
    rt2 = json.loads((p2 / "RUNTIME-MAP.json").read_text())
    assert "provenance_status" in rt1["goal_sequences"]["G-01"]["steps"][0]
    assert "provenance_status" not in rt2["goal_sequences"]["G-02"]["steps"][0]


def test_requires_dry_run_or_apply(tmp_path):
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "must specify" in result.stderr.lower() or "must specify" in result.stdout.lower()


def test_dry_run_and_apply_mutually_exclusive(tmp_path):
    result = _run(tmp_path, "--dry-run", "--apply")
    assert result.returncode != 0
