"""
Tests for verify-artifact-freshness.py — Phase K v2.5.2.

Closes "stale artifact satisfies gate" loophole — verifies file was
CREATED BY THE CURRENT RUN via .vg/runs/{run_id}/evidence-manifest.json.

Covers:
  - Required arg missing → rc=2 (config error)
  - Artifact missing on disk → rc=1, verdict=BLOCK, ARTIFACT_MISSING
  - Manifest missing → rc=1, MANIFEST_MISSING
  - Manifest entry missing for path → NO_ENTRY
  - Run-id mismatch → RUN_ID_MISMATCH
  - Hash mismatch (file mutated post-emit) → HASH_MISMATCH
  - Happy path: fresh artifact, manifest match → rc=0, verdict=PASS
  - Verdict schema canonical (--json: top-level PASS|BLOCK)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-artifact-freshness.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    env["REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _sha256(text: str) -> str:
    data = text.encode("utf-8").replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _write_artifact(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _write_manifest(tmp_path: Path, run_id: str, entries: list[dict]) -> None:
    mdir = tmp_path / ".vg" / "runs" / run_id
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "evidence-manifest.json").write_text(
        json.dumps({"entries": entries}),
        encoding="utf-8",
    )


class TestArtifactFreshness:
    def test_no_required_arg_rc2(self, tmp_path):
        # No --path or --paths; argparse exits 2
        r = _run(["--run-id", "abc"], tmp_path)
        assert r.returncode == 2

    def test_artifact_missing_blocks(self, tmp_path):
        run_id = "run-001"
        _write_manifest(tmp_path, run_id, [])
        r = _run(["--run-id", run_id, "--path", "missing.md", "--json"], tmp_path)
        assert r.returncode == 1, f"missing artifact → rc=1, got {r.returncode}"
        data = json.loads(r.stdout)
        assert data.get("verdict") == "BLOCK"
        assert data["failures"] == 1
        assert data["results"][0]["verdict"] == "ARTIFACT_MISSING"

    def test_manifest_missing_blocks(self, tmp_path):
        run_id = "run-002"
        _write_artifact(tmp_path, "out/file.md", "hello\n")
        # No manifest written
        r = _run(["--run-id", run_id, "--path", "out/file.md", "--json"], tmp_path)
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "MANIFEST_MISSING"

    def test_no_entry_blocks(self, tmp_path):
        run_id = "run-003"
        _write_artifact(tmp_path, "out/file.md", "hello\n")
        _write_manifest(tmp_path, run_id, [
            {"path": "out/other.md", "creator_run_id": run_id,
             "sha256": "x", "created_at": "now"},
        ])
        r = _run(["--run-id", run_id, "--path", "out/file.md", "--json"], tmp_path)
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "NO_ENTRY"

    def test_run_id_mismatch_blocks(self, tmp_path):
        current_run = "run-current"
        prior_run = "run-prior"
        content = "fresh\n"
        _write_artifact(tmp_path, "out/file.md", content)
        _write_manifest(tmp_path, current_run, [
            {"path": "out/file.md", "creator_run_id": prior_run,
             "sha256": _sha256(content), "created_at": "earlier"},
        ])
        r = _run(["--run-id", current_run,
                  "--path", "out/file.md", "--json"], tmp_path)
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "RUN_ID_MISMATCH"

    def test_hash_mismatch_blocks(self, tmp_path):
        run_id = "run-005"
        _write_artifact(tmp_path, "out/file.md", "actual content\n")
        _write_manifest(tmp_path, run_id, [
            {"path": "out/file.md", "creator_run_id": run_id,
             "sha256": _sha256("different content\n"),
             "created_at": "earlier"},
        ])
        r = _run(["--run-id", run_id, "--path", "out/file.md", "--json"], tmp_path)
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "HASH_MISMATCH"

    def test_happy_path_passes(self, tmp_path):
        run_id = "run-happy"
        content = "production-ready\n"
        _write_artifact(tmp_path, "out/file.md", content)
        _write_manifest(tmp_path, run_id, [
            {"path": "out/file.md", "creator_run_id": run_id,
             "sha256": _sha256(content), "created_at": "now"},
        ])
        r = _run(["--run-id", run_id, "--path", "out/file.md", "--json"], tmp_path)
        assert r.returncode == 0, \
            f"happy path → rc=0, got {r.returncode}, stdout={r.stdout[:300]}"
        data = json.loads(r.stdout)
        assert data["verdict"] == "PASS"
        assert data["failures"] == 0

    def test_verdict_schema_canonical(self, tmp_path):
        """--json output emits top-level verdict ∈ {PASS, BLOCK}."""
        run_id = "run-schema"
        _write_manifest(tmp_path, run_id, [])
        r = _run(["--run-id", run_id, "--path", "x.md", "--json"], tmp_path)
        data = json.loads(r.stdout)
        assert "validator" in data
        assert data.get("verdict") in {"BLOCK", "PASS"}, \
            f"verdict drift: {data.get('verdict')!r}"
        # No FAIL/OK leakage at top level
        assert data["verdict"] not in {"FAIL", "OK"}
