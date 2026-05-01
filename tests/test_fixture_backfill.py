"""Tests for scripts/fixture-backfill.py — RFC v9 PR-A.5 migration tool."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fixture-backfill.py"


def _run(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _phase_with_runtime(tmp_path: Path, name: str, runtime: dict) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / name
    phase_dir.mkdir(parents=True)
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps(runtime, indent=2), encoding="utf-8",
    )
    return phase_dir


def _mutation_seq_with_body() -> dict:
    return {
        "G-10": {
            "title": "Approve tier2 topup",
            "steps": [{
                "do": "click",
                "target": "Submit topup",
                "network": [{
                    "method": "POST",
                    "endpoint": "/api/topup/approve",
                    "status": 200,
                    "body": {"id": "p7", "approver_note": "ok"},
                }],
            }],
        },
    }


def test_high_confidence_when_body_captured(tmp_path):
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", {
        "goal_sequences": _mutation_seq_with_body(),
    })
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0, result.stderr
    fixture = phase_dir / "FIXTURES" / "G-10.yaml"
    assert fixture.exists()
    content = fixture.read_text()
    assert "confidence: HIGH" in content
    assert "approver_note: ok" in content
    assert "method: POST" in content
    assert "/api/topup/approve" in content


def test_medium_confidence_when_body_missing(tmp_path):
    runtime = {
        "goal_sequences": {
            "G-10": {
                "title": "Approve",
                "steps": [{
                    "do": "click",
                    "target": "Submit",
                    "network": [{
                        "method": "POST",
                        "endpoint": "/api/x",
                        "status": 200,
                    }],
                }],
            },
        },
    }
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", runtime)
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0, result.stderr
    content = (phase_dir / "FIXTURES" / "G-10.yaml").read_text()
    assert "confidence: MEDIUM" in content
    # Body skeleton with TODO sentinel
    assert "TODO" in content


def test_skips_non_mutation_goals(tmp_path):
    runtime = {
        "goal_sequences": {
            "G-read": {
                "title": "Read only",
                "steps": [{
                    "do": "click",
                    "target": "Open detail",
                    "network": [{"method": "GET", "endpoint": "/x", "status": 200}],
                }],
            },
        },
    }
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", runtime)
    result = _run(tmp_path, "--phase", "1.0", "--dry-run")
    assert result.returncode == 0
    assert "No mutation goals" in result.stdout


def test_dry_run_does_not_write(tmp_path):
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", {
        "goal_sequences": _mutation_seq_with_body(),
    })
    result = _run(tmp_path, "--phase", "1.0", "--dry-run")
    assert result.returncode == 0
    assert not (phase_dir / "FIXTURES").exists()


def test_only_filter_targets_specific_goals(tmp_path):
    runtime = {
        "goal_sequences": {
            "G-10": _mutation_seq_with_body()["G-10"],
            "G-11": {
                "title": "Other",
                "steps": [{
                    "do": "click",
                    "target": "Save merchant",
                    "network": [{"method": "PUT", "endpoint": "/api/m",
                                  "status": 200, "body": {"x": 1}}],
                }],
            },
        },
    }
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", runtime)
    result = _run(tmp_path, "--phase", "1.0", "--apply", "--only", "G-11")
    assert result.returncode == 0
    assert (phase_dir / "FIXTURES" / "G-11.yaml").exists()
    assert not (phase_dir / "FIXTURES" / "G-10.yaml").exists()


def test_existing_yaml_not_clobbered(tmp_path):
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", {
        "goal_sequences": _mutation_seq_with_body(),
    })
    fixtures = phase_dir / "FIXTURES"
    fixtures.mkdir()
    (fixtures / "G-10.yaml").write_text("# user-authored content — keep me\n",
                                           encoding="utf-8")
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0
    # Original file unchanged
    assert "# user-authored content — keep me\n" == (
        (fixtures / "G-10.yaml").read_text()
    )
    # Backfill goes to .backfill-draft
    assert (fixtures / "G-10.yaml.backfill-draft").exists()


def test_writes_backfill_report(tmp_path):
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", {
        "goal_sequences": _mutation_seq_with_body(),
    })
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0
    report = phase_dir / "FIXTURES" / ".backfill-report.json"
    data = json.loads(report.read_text())
    assert data["phase"] == "1.0"
    assert len(data["goals"]) == 1
    assert data["goals"][0]["goal_id"] == "G-10"
    assert data["goals"][0]["confidence"] == "HIGH"


def test_post_step_has_idempotency_key(tmp_path):
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", {
        "goal_sequences": _mutation_seq_with_body(),
    })
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    content = (phase_dir / "FIXTURES" / "G-10.yaml").read_text()
    assert "idempotency_key:" in content


def test_phase_not_found_returns_nonzero(tmp_path):
    (tmp_path / ".vg" / "phases").mkdir(parents=True)
    result = _run(tmp_path, "--phase", "99.99", "--dry-run")
    assert result.returncode != 0


def test_dry_run_or_apply_required(tmp_path):
    result = _run(tmp_path, "--phase", "1.0")
    assert result.returncode != 0


def test_path_traversal_goal_id_rejected(tmp_path):
    """Codex-R4-HIGH-3: RUNTIME-MAP is untrusted. goal_id with path
    traversal must be rejected, not used as filename."""
    runtime = {
        "goal_sequences": {
            "../../etc/passwd": _mutation_seq_with_body()["G-10"],
            "G-10": _mutation_seq_with_body()["G-10"],  # legit one for control
        },
    }
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", runtime)
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0
    # Only the legit G-10 should be backfilled
    assert (phase_dir / "FIXTURES" / "G-10.yaml").exists()
    # No file written outside FIXTURES dir
    assert not (tmp_path / ".." / ".." / "etc" / "passwd.yaml").exists()
    # Stderr should mention skipping
    assert "path-traversal" in result.stderr or "invalid goal_id" in result.stderr


def test_invalid_goal_id_format_rejected(tmp_path):
    """goal_id not matching G-XX pattern rejected."""
    runtime = {
        "goal_sequences": {
            "not-a-goal": _mutation_seq_with_body()["G-10"],
            "G_underscore": _mutation_seq_with_body()["G-10"],
            "G-10": _mutation_seq_with_body()["G-10"],
        },
    }
    phase_dir = _phase_with_runtime(tmp_path, "01.0-foo", runtime)
    result = _run(tmp_path, "--phase", "1.0", "--apply")
    assert result.returncode == 0
    fixtures = list((phase_dir / "FIXTURES").iterdir()) if (phase_dir / "FIXTURES").exists() else []
    fixture_names = {f.name for f in fixtures}
    assert "G-10.yaml" in fixture_names
    assert "not-a-goal.yaml" not in fixture_names
    assert "G_underscore.yaml" not in fixture_names
