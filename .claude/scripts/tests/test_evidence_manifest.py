"""
Tests for emit-evidence-manifest.py + verify-artifact-freshness.py
— Phase K of v2.5.2 hardening.

Covers:
  - Manifest emit writes valid JSON with run_id + sha256 + created_at
  - Freshness passes when artifact unmodified
  - Freshness fails with HASH_MISMATCH when artifact mutated after emit
  - Freshness fails with NO_ENTRY when manifest lacks path
  - Freshness fails with RUN_ID_MISMATCH when entry from different run
  - Freshness fails with MANIFEST_MISSING when no emit ever called
  - Freshness fails with ARTIFACT_MISSING when file deleted
  - Multiple emits for same path → last-write-wins (dedupe)
  - Source inputs tracked + provenance drift detected via --check-provenance
  - Line ending normalization (CRLF/LF hash to same value)
  - --run-id override works (standalone usage without current-run.json)
  - --json output parseable for orchestrator consumption
  - Phase/env variable expansion (${PHASE_DIR}, ${PHASE_NUMBER})
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EMITTER = REPO_ROOT / ".claude" / "scripts" / "emit-evidence-manifest.py"
VERIFIER = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-artifact-freshness.py"


def _run(script: Path, args: list[str], env_overrides: dict | None = None,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd) if cwd else None, env=env,
        encoding="utf-8", errors="replace",
    )


def _setup_run(tmp_path: Path, run_id: str = "test-run-abc123") -> tuple[Path, str]:
    """Init git repo + fake current-run.json."""
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=False)
    current_run = tmp_path / ".vg" / "current-run.json"
    current_run.parent.mkdir(parents=True, exist_ok=True)
    current_run.write_text(json.dumps({
        "run_id": run_id,
        "command": "vg:test",
        "phase": "99",
    }), encoding="utf-8")
    return tmp_path, run_id


# ─── Emitter tests ─────────────────────────────────────────────────────

class TestEmitter:
    def test_emit_writes_valid_manifest(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        artifact = root / "test.md"
        artifact.write_text("hello world\n", encoding="utf-8")

        r = _run(EMITTER, ["--path", "test.md"], cwd=root)
        assert r.returncode == 0, f"emit failed: {r.stderr}"

        manifest = root / ".vg" / "runs" / run_id / "evidence-manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["run_id"] == run_id
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["path"] == "test.md"
        assert entry["creator_run_id"] == run_id
        assert entry["sha256"] == hashlib.sha256(b"hello world\n").hexdigest()

    def test_emit_expands_phase_dir(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        phase_dir_rel = ".vg/phases/99-test"
        (root / phase_dir_rel).mkdir(parents=True)
        (root / phase_dir_rel / "SUMMARY.md").write_text("content")

        r = _run(EMITTER, ["--path", "${PHASE_DIR}/SUMMARY.md"],
                 env_overrides={"PHASE_DIR": phase_dir_rel,
                                "PHASE_NUMBER": "99"},
                 cwd=root)
        assert r.returncode == 0, r.stderr
        manifest = json.loads(
            (root / ".vg" / "runs" / run_id / "evidence-manifest.json")
            .read_text(encoding="utf-8")
        )
        entry = manifest["entries"][0]
        assert entry["path"] == f"{phase_dir_rel}/SUMMARY.md"

    def test_emit_dedupe_last_write_wins(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("v1")

        _run(EMITTER, ["--path", "x.md"], cwd=root)
        # Mutate + re-emit
        (root / "x.md").write_text("v2-changed")
        r = _run(EMITTER, ["--path", "x.md"], cwd=root)
        assert r.returncode == 0

        manifest = json.loads(
            (root / ".vg" / "runs" / run_id / "evidence-manifest.json")
            .read_text(encoding="utf-8")
        )
        # Only 1 entry — latest overwrites older
        entries_for_x = [e for e in manifest["entries"] if e["path"] == "x.md"]
        assert len(entries_for_x) == 1
        assert entries_for_x[0]["sha256"] == hashlib.sha256(b"v2-changed").hexdigest()

    def test_emit_tracks_source_inputs(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "src1.md").write_text("input1")
        (root / "src2.md").write_text("input2")
        (root / "output.md").write_text("derived")

        r = _run(EMITTER, ["--path", "output.md",
                           "--source-inputs", "src1.md,src2.md"],
                 cwd=root)
        assert r.returncode == 0
        manifest = json.loads(
            (root / ".vg" / "runs" / run_id / "evidence-manifest.json")
            .read_text(encoding="utf-8")
        )
        entry = manifest["entries"][0]
        assert len(entry["source_inputs"]) == 2
        assert entry["source_inputs"][0]["path"] == "src1.md"
        assert entry["source_inputs"][0]["sha256"] == \
            hashlib.sha256(b"input1").hexdigest()

    def test_emit_fails_on_missing_artifact(self, tmp_path):
        root, _ = _setup_run(tmp_path)
        r = _run(EMITTER, ["--path", "nonexistent.md"], cwd=root)
        assert r.returncode == 1
        assert "Cannot read artifact" in r.stderr

    def test_emit_fails_without_run_id(self, tmp_path):
        # No current-run.json, no --run-id
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=False)
        (tmp_path / "test.md").write_text("x")
        r = _run(EMITTER, ["--path", "test.md"], cwd=tmp_path)
        assert r.returncode == 2
        assert "run_id" in r.stderr.lower()

    def test_emit_explicit_run_id_override(self, tmp_path):
        """--run-id works even without current-run.json."""
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=False)
        (tmp_path / "test.md").write_text("x")
        r = _run(EMITTER, ["--path", "test.md", "--run-id", "explicit-uuid"],
                 cwd=tmp_path)
        assert r.returncode == 0
        manifest = tmp_path / ".vg" / "runs" / "explicit-uuid" / \
            "evidence-manifest.json"
        assert manifest.exists()


# ─── Freshness verifier tests ──────────────────────────────────────────

class TestFreshness:
    def test_fresh_artifact_passes(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("pristine")
        _run(EMITTER, ["--path", "x.md"], cwd=root)

        r = _run(VERIFIER, ["--path", "x.md", "--quiet"], cwd=root)
        assert r.returncode == 0

    def test_hash_mismatch_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("original")
        _run(EMITTER, ["--path", "x.md"], cwd=root)
        # Mutate after emit
        (root / "x.md").write_text("tampered")

        r = _run(VERIFIER, ["--path", "x.md"], cwd=root)
        assert r.returncode == 1
        assert "HASH_MISMATCH" in r.stdout

    def test_no_entry_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "a.md").write_text("a")
        (root / "b.md").write_text("b")
        _run(EMITTER, ["--path", "a.md"], cwd=root)
        # b.md on disk but not in manifest

        r = _run(VERIFIER, ["--path", "b.md"], cwd=root)
        assert r.returncode == 1
        assert "NO_ENTRY" in r.stdout

    def test_run_id_mismatch_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("x")
        # Emit with run_id A
        _run(EMITTER, ["--path", "x.md", "--run-id", "run-A"], cwd=root)
        # Verify with run_id B
        r = _run(VERIFIER, ["--path", "x.md", "--run-id", "run-B"], cwd=root)
        assert r.returncode == 1
        assert "MANIFEST_MISSING" in r.stdout or "RUN_ID_MISMATCH" in r.stdout

    def test_manifest_missing_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("x")
        # Never call emit

        r = _run(VERIFIER, ["--path", "x.md"], cwd=root)
        assert r.returncode == 1
        assert "MANIFEST_MISSING" in r.stdout

    def test_artifact_missing_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("x")
        _run(EMITTER, ["--path", "x.md"], cwd=root)
        # Delete after emit
        (root / "x.md").unlink()

        r = _run(VERIFIER, ["--path", "x.md"], cwd=root)
        assert r.returncode == 1
        assert "ARTIFACT_MISSING" in r.stdout

    def test_multiple_paths_checked(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "a.md").write_text("a")
        (root / "b.md").write_text("b")
        _run(EMITTER, ["--path", "a.md"], cwd=root)
        _run(EMITTER, ["--path", "b.md"], cwd=root)

        r = _run(VERIFIER, ["--paths", "a.md,b.md", "--quiet"], cwd=root)
        assert r.returncode == 0

    def test_crlf_vs_lf_not_drift(self, tmp_path):
        """Content with CRLF vs LF line endings hash to same value."""
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("line1\nline2\n", encoding="utf-8")
        _run(EMITTER, ["--path", "x.md"], cwd=root)
        # Rewrite with CRLF
        (root / "x.md").write_bytes(b"line1\r\nline2\r\n")

        r = _run(VERIFIER, ["--path", "x.md", "--quiet"], cwd=root)
        assert r.returncode == 0  # normalized hash matches

    def test_json_output_parseable(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "x.md").write_text("x")
        _run(EMITTER, ["--path", "x.md"], cwd=root)

        r = _run(VERIFIER, ["--path", "x.md", "--json"], cwd=root)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["run_id"] == run_id
        assert data["checked"] == 1
        assert data["failures"] == 0
        assert len(data["results"]) == 1


# ─── Provenance tests ─────────────────────────────────────────────────

class TestProvenance:
    def test_provenance_intact_passes(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "src.md").write_text("input")
        (root / "out.md").write_text("output")
        _run(EMITTER, ["--path", "out.md",
                       "--source-inputs", "src.md"], cwd=root)

        r = _run(VERIFIER, ["--path", "out.md",
                            "--check-provenance", "--quiet"], cwd=root)
        assert r.returncode == 0

    def test_provenance_drift_detected(self, tmp_path):
        root, run_id = _setup_run(tmp_path)
        (root / "src.md").write_text("input-v1")
        (root / "out.md").write_text("derived-from-v1")
        _run(EMITTER, ["--path", "out.md",
                       "--source-inputs", "src.md"], cwd=root)
        # Mutate upstream src AFTER artifact produced
        (root / "src.md").write_text("input-v2-CHANGED")

        r = _run(VERIFIER, ["--path", "out.md", "--check-provenance"], cwd=root)
        assert r.returncode == 1
        assert "PROVENANCE_DRIFT" in r.stdout
