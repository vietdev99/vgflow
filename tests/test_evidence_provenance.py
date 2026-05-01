"""Tests for verify-evidence-provenance.py (RFC v9 D10).

Closes wave-3.2.2 trust hole: structured provenance is mandatory on all
mutation steps that claim success (action + 2xx network), so executor
agents cannot fabricate evidence to flip matrix status.

Covers:
- evidence missing → BLOCK (default) / informational (--allow-legacy)
- evidence.source missing / invalid
- artifact_hash absent / wrong format
- captured_at / schema_version absent / unsupported version
- scanner without scanner_run_id
- diagnostic_l2 without layer2_proposal_id
- non-mutation step ignored
- mutation step without 2xx ignored (no claim of success)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-evidence-provenance.py"


def _run(repo_root: Path, phase: str, *flags: str) -> tuple[int, dict]:
    cmd = [sys.executable, str(VALIDATOR), "--phase", phase, *flags]
    proc = subprocess.run(
        cmd,
        env={"VG_REPO_ROOT": str(repo_root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"verdict": "PARSE_ERROR", "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, out


def _make_phase(tmp_path: Path, sequences: dict) -> tuple[Path, Path]:
    phases_dir = tmp_path / ".vg" / "phases"
    phase_dir = phases_dir / "99.9-prov"
    phase_dir.mkdir(parents=True)
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps({"goal_sequences": sequences}, indent=2),
        encoding="utf-8",
    )
    return tmp_path, phase_dir


def _mutation_step(evidence: dict | None = None, with_2xx: bool = True) -> dict:
    step = {"do": "click", "target": "Submit topup"}
    if with_2xx:
        step["network"] = [{"method": "POST", "endpoint": "/api/topup", "status": 200}]
    if evidence is not None:
        step["evidence"] = evidence
    return step


# ─── BLOCK cases ──────────────────────────────────────────────────────────


def test_missing_evidence_blocks_in_default_mode(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step(None)]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1, out
    assert out["verdict"] == "BLOCK"
    types = [e["type"] for e in out.get("evidence", [])]
    assert "evidence_missing" in types


def test_invalid_source_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({"source": "ai_hallucination"})]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "evidence_source_invalid" in types


def test_artifact_hash_wrong_format_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "scanner",
            "scanner_run_id": "haiku-1",
            "artifact_hash": "md5:0123abc",  # wrong algorithm
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "artifact_hash_format" in types


def test_schema_version_major_mismatch_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "scanner",
            "scanner_run_id": "haiku-1",
            "artifact_hash": "sha256:xyz",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "2.0",  # major bump unsupported
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "schema_version_unsupported" in types


def test_scanner_source_without_run_id_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "scanner",
            # NO scanner_run_id
            "artifact_hash": "sha256:xyz",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "scanner_run_id_missing" in types


def test_diagnostic_l2_without_proposal_id_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "diagnostic_l2",
            "artifact_hash": "sha256:abc",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
            # NO layer2_proposal_id
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "layer2_proposal_id_missing" in types


def test_missing_required_subfields_blocks(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({"source": "manual"})]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 1
    types = [e["type"] for e in out.get("evidence", [])]
    assert "artifact_hash_missing" in types
    assert "captured_at_missing" in types
    assert "schema_version_missing" in types


# ─── PASS cases ──────────────────────────────────────────────────────────


def test_complete_scanner_evidence_passes(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "scanner",
            "scanner_run_id": "haiku-r-1",
            "artifact_hash": "sha256:cafebabe1234",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 0, out
    assert out["verdict"] in ("PASS", "WARN")


def test_complete_diagnostic_l2_evidence_passes(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "diagnostic_l2",
            "layer2_proposal_id": "l2-prop-7e9",
            "artifact_hash": "sha256:cafe",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.1",  # minor bump OK
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 0


def test_executor_with_full_metadata_passes_validator(tmp_path):
    """The provenance validator only checks structure, not whether source
    is trustworthy enough for matrix promotion. matrix-staleness D10 is the
    second gate that rejects executor for promotion. This validator passes
    structurally-complete executor evidence — that is intentional."""
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({
            "source": "executor",
            "artifact_hash": "sha256:e",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        })]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 0


# ─── Skip cases ──────────────────────────────────────────────────────────


def test_non_mutation_step_skipped(tmp_path):
    """GET-only step (no submit verb, no 2xx mutation) → no evidence required."""
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [{
            "do": "click",
            "target": "Open detail panel",  # not submit/approve/etc.
            "network": [{"method": "GET", "endpoint": "/api/x", "status": 200}],
        }]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 0


def test_mutation_step_without_2xx_skipped(tmp_path):
    """Submit attempted but 4xx — claim-of-success not made → no evidence required."""
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [{
            "do": "click",
            "target": "Submit topup",
            "network": [{"method": "POST", "endpoint": "/api/topup", "status": 422}],
        }]},
    })
    rc, out = _run(repo, "99.9")
    assert rc == 0


# ─── --allow-legacy migration grace ─────────────────────────────────────


def test_allow_legacy_skips_missing_evidence(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step(None)]},  # no evidence
    })
    rc, out = _run(repo, "99.9", "--allow-legacy")
    assert rc == 0
    # Summary should still report
    types = [e["type"] for e in out.get("evidence", [])]
    assert "provenance_summary" in types


def test_warn_severity_downgrades_block(tmp_path):
    repo, _ = _make_phase(tmp_path, {
        "G-01": {"steps": [_mutation_step({"source": "manual"})]},  # incomplete
    })
    rc, out = _run(repo, "99.9", "--severity", "warn")
    # warn mode → not BLOCK; rc=0
    assert rc == 0
    assert out["verdict"] in ("WARN", "PASS")
    types = [e["type"] for e in out.get("evidence", [])]
    assert "severity_downgraded" in types
