"""v2.65.0 A8 — RUNTIME-MAP must_write provenance enforcement.

Closes the regression-risk gap raised in plan task A8: the contract
parser at `scripts/vg-orchestrator/contracts.py:482-485` reads the
`must_be_created_in_run` and `check_provenance` flags off `must_write`
entries, but it was unverified whether those flags are actually
*enforced* at run-complete.

This suite locks two layers:

1. **Parsing layer** — `contracts.normalize_must_write` preserves the
   two flags with correct defaults (False) and explicit overrides.
2. **Enforcement layer** — `_verify_artifact_run_binding` (called from
   `_verify_contract` for every must_write entry that has
   `must_be_created_in_run: true`) rejects:
     - missing evidence-manifest.json for the current run,
     - manifest entry from a different run (cross-run reuse),
     - sha256 drift (artifact mutated after emit),
     - provenance drift (source_inputs hash mismatch).
3. **Skill-MD declaration layer** — `commands/vg/review.md` declares
   the two flags on the artifacts that need cross-run trust
   (`RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`,
   `api-docs-check.txt`, `api-contract-precheck.txt`).

If review.md ever drops a flag, or if a refactor of `__main__.py`
silently severs the call from `_verify_contract` to
`_verify_artifact_run_binding`, this suite fails loudly.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
ORCH_DIR = REPO_ROOT / "scripts" / "vg-orchestrator"


def _init_git_repo(path: Path) -> None:
    """_verify_artifact_run_binding uses `git rev-parse --show-toplevel`
    to anchor the manifest lookup. Tests must run inside a real git
    repo to exercise the function; tmp_path alone is not a git repo.
    """
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=path, check=True, capture_output=True,
    )


# ─── Module loader ────────────────────────────────────────────────────────


def _load_orch_main():
    """Load scripts/vg-orchestrator/__main__.py as a module.

    The orchestrator module pulls sibling files (db, contracts, state,
    evidence, _repo_root) via top-level `import db`, so we must put
    its directory on sys.path FIRST.
    """
    if str(ORCH_DIR) not in sys.path:
        sys.path.insert(0, str(ORCH_DIR))
    spec = importlib.util.spec_from_file_location(
        "_vg_orch_main_under_test", ORCH_DIR / "__main__.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_contracts():
    if str(ORCH_DIR) not in sys.path:
        sys.path.insert(0, str(ORCH_DIR))
    import contracts  # type: ignore
    return contracts


# ─── Helpers ──────────────────────────────────────────────────────────────


def _sha256_normalized(path: Path) -> str:
    """Match _verify_artifact_run_binding's CRLF→LF normalization."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _write_manifest(repo_root: Path, run_id: str, entries: list[dict]) -> Path:
    manifest_path = repo_root / ".vg" / "runs" / run_id / "evidence-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"version": 1, "entries": entries}, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _write_artifact(path: Path, content: str = "stub-artifact-content\n") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _sha256_normalized(path)


@pytest.fixture
def git_tmp_path(tmp_path, monkeypatch):
    """tmp_path with `git init` + cwd switched in. Required because
    _verify_artifact_run_binding anchors paths via `git rev-parse
    --show-toplevel`."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ─── Layer 1: parsing ─────────────────────────────────────────────────────


class TestContractParsing:
    """contracts.normalize_must_write must round-trip both flags."""

    def test_default_flags_false(self):
        contracts = _load_contracts()
        out = contracts.normalize_must_write([{"path": "X.json"}])
        assert out[0]["must_be_created_in_run"] is False
        assert out[0]["check_provenance"] is False

    def test_explicit_must_be_created_in_run_true(self):
        contracts = _load_contracts()
        out = contracts.normalize_must_write(
            [{"path": "X.json", "must_be_created_in_run": True}]
        )
        assert out[0]["must_be_created_in_run"] is True
        assert out[0]["check_provenance"] is False

    def test_explicit_check_provenance_true(self):
        contracts = _load_contracts()
        out = contracts.normalize_must_write(
            [{"path": "X.json", "check_provenance": True}]
        )
        assert out[0]["check_provenance"] is True
        assert out[0]["must_be_created_in_run"] is False

    def test_both_flags_true_preserved(self):
        contracts = _load_contracts()
        out = contracts.normalize_must_write([{
            "path": "X.json",
            "must_be_created_in_run": True,
            "check_provenance": True,
        }])
        assert out[0]["must_be_created_in_run"] is True
        assert out[0]["check_provenance"] is True

    def test_string_form_defaults(self):
        """Bare string entry -> flags default False (back-compat)."""
        contracts = _load_contracts()
        out = contracts.normalize_must_write(["X.json"])
        assert out[0]["must_be_created_in_run"] is False
        assert out[0]["check_provenance"] is False


# ─── Layer 2: enforcement on _verify_artifact_run_binding ─────────────────


class TestArtifactRunBindingEnforcement:
    """The actual function called from _verify_contract for every
    must_write entry whose `must_be_created_in_run: true`. Without this
    layer the flag would be a no-op.
    """

    def test_missing_manifest_rejected(self, git_tmp_path):
        run_id = "run-no-manifest"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        _write_artifact(artifact, '{"phase":"test"}\n')
        # No manifest written → enforcement must reject.

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, False)
        assert result["ok"] is False
        assert "evidence-manifest.json missing" in result["reason"]

    def test_no_manifest_entry_rejected(self, git_tmp_path):
        run_id = "run-empty-manifest"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        _write_artifact(artifact)
        _write_manifest(git_tmp_path, run_id, entries=[])  # manifest exists but empty

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, False)
        assert result["ok"] is False
        assert "no manifest entry" in result["reason"]

    def test_creator_run_id_mismatch_rejected(self, git_tmp_path):
        """Stale artifact emitted by a prior run must fail freshness."""
        current_run = "run-current"
        prior_run = "run-prior-stale"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        sha = _write_artifact(artifact)
        _write_manifest(git_tmp_path, current_run, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": prior_run,  # ← cross-run reuse
            "sha256": sha,
        }])

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, current_run, False)
        assert result["ok"] is False
        assert "creator_run_id" in result["reason"]
        assert "stale" in result["reason"]

    def test_sha256_drift_after_emit_rejected(self, git_tmp_path):
        """File mutated after manifest emit must fail."""
        run_id = "run-mutated"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        _write_artifact(artifact, "original-content\n")
        # Manifest records a different sha (simulating post-emit mutation):
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": run_id,
            "sha256": "a" * 64,  # bogus, won't match real bytes
        }])

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, False)
        assert result["ok"] is False
        assert "mutated" in result["reason"]

    def test_valid_binding_passes(self, git_tmp_path):
        run_id = "run-valid"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        sha = _write_artifact(artifact)
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": run_id,
            "sha256": sha,
        }])

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, False)
        assert result["ok"] is True
        assert result["reason"] is None

    def test_check_provenance_drift_rejected(self, git_tmp_path):
        """When check_provenance=True, mutated source_inputs must reject."""
        run_id = "run-provenance-drift"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        sha = _write_artifact(artifact)
        # Source input file with KNOWN content + correct hash recorded:
        src = git_tmp_path / "phase-test" / "SPECS.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("original-spec\n", encoding="utf-8")
        original_src_sha = _sha256_normalized(src)
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": run_id,
            "sha256": sha,
            "source_inputs": [{
                "path": "phase-test/SPECS.md",
                "sha256": original_src_sha,
            }],
        }])
        # Now mutate the source AFTER manifest emit:
        src.write_text("mutated-spec-after-emit\n", encoding="utf-8")

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, True)
        assert result["ok"] is False
        assert "provenance drift" in result["reason"]

    def test_check_provenance_intact_passes(self, git_tmp_path):
        run_id = "run-provenance-ok"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        sha = _write_artifact(artifact)
        src = git_tmp_path / "phase-test" / "SPECS.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("intact-spec\n", encoding="utf-8")
        src_sha = _sha256_normalized(src)
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": run_id,
            "sha256": sha,
            "source_inputs": [{
                "path": "phase-test/SPECS.md",
                "sha256": src_sha,
            }],
        }])

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, True)
        assert result["ok"] is True

    def test_check_provenance_false_skips_source_check(self, git_tmp_path):
        """check_provenance=False must not reject on source drift."""
        run_id = "run-skip-provenance"
        artifact = git_tmp_path / "phase-test" / "RUNTIME-MAP.json"
        sha = _write_artifact(artifact)
        src = git_tmp_path / "phase-test" / "SPECS.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("v1\n", encoding="utf-8")
        v1_sha = _sha256_normalized(src)
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": "phase-test/RUNTIME-MAP.json",
            "creator_run_id": run_id,
            "sha256": sha,
            "source_inputs": [{
                "path": "phase-test/SPECS.md",
                "sha256": v1_sha,
            }],
        }])
        # Drift the source — but enforcement called with check_provenance=False:
        src.write_text("v2-drifted\n", encoding="utf-8")

        m = _load_orch_main()
        result = m._verify_artifact_run_binding(artifact, run_id, False)
        assert result["ok"] is True


# ─── Layer 3: skill-MD declaration ────────────────────────────────────────


class TestReviewSkillContractDeclaration:
    """commands/vg/review.md must declare must_be_created_in_run +
    check_provenance on the artifacts that need cross-run trust.

    v2.65.0 A8 follow-up: RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md
    were previously declared with only profile_aware + content_min_bytes,
    so a stale RUNTIME-MAP from a prior run could satisfy the gate
    (state-shortcut bug). They now carry the same provenance flags as
    api-docs-check.txt and api-contract-precheck.txt.
    """

    @pytest.fixture
    def must_write(self):
        contracts = _load_contracts()
        contract = contracts.parse("vg:review")
        assert contract is not None, "vg:review skill MD has no runtime_contract"
        return contracts.normalize_must_write(contract.get("must_write", []))

    def _entry_for(self, must_write, suffix):
        for item in must_write:
            if item["path"].endswith(suffix):
                return item
        return None

    def test_runtime_map_declared(self, must_write):
        entry = self._entry_for(must_write, "RUNTIME-MAP.json")
        assert entry is not None, (
            "RUNTIME-MAP.json missing from review.md must_write"
        )

    def test_runtime_map_has_provenance_flags(self, must_write):
        """v2.65.0 A8 follow-up — RUNTIME-MAP.json is the canonical
        review output. A stale RUNTIME-MAP from a prior session must
        not satisfy the gate; the file must be (a) created in the
        current run AND (b) traceable to its source inputs.
        """
        entry = self._entry_for(must_write, "RUNTIME-MAP.json")
        assert entry is not None, "RUNTIME-MAP.json missing from must_write"
        assert entry["must_be_created_in_run"] is True, (
            "RUNTIME-MAP.json must declare must_be_created_in_run: true "
            "to prevent stale runtime-map reuse across review runs "
            "(v2.65.0 A8 follow-up — state-shortcut bug fix)"
        )
        assert entry["check_provenance"] is True, (
            "RUNTIME-MAP.json must declare check_provenance: true"
        )

    def test_goal_coverage_matrix_has_provenance_flags(self, must_write):
        """v2.65.0 A8 follow-up — GOAL-COVERAGE-MATRIX.md is the
        per-run goal verdict. Reusing a prior run's matrix would
        silently shortcut goal coverage validation.
        """
        entry = self._entry_for(must_write, "GOAL-COVERAGE-MATRIX.md")
        assert entry is not None, (
            "GOAL-COVERAGE-MATRIX.md missing from must_write"
        )
        assert entry["must_be_created_in_run"] is True, (
            "GOAL-COVERAGE-MATRIX.md must declare must_be_created_in_run: true"
        )
        assert entry["check_provenance"] is True, (
            "GOAL-COVERAGE-MATRIX.md must declare check_provenance: true"
        )

    def test_api_docs_check_has_both_flags(self, must_write):
        """API discovery report must be created in current run + check provenance."""
        entry = self._entry_for(must_write, "api-docs-check.txt")
        assert entry is not None, "api-docs-check.txt missing from must_write"
        assert entry["must_be_created_in_run"] is True, (
            "api-docs-check.txt must declare must_be_created_in_run: true "
            "to prevent stale Codex probe reuse across review runs"
        )
        assert entry["check_provenance"] is True, (
            "api-docs-check.txt must declare check_provenance: true"
        )

    def test_api_contract_precheck_has_both_flags(self, must_write):
        entry = self._entry_for(must_write, "api-contract-precheck.txt")
        assert entry is not None, (
            "api-contract-precheck.txt missing from must_write"
        )
        assert entry["must_be_created_in_run"] is True
        assert entry["check_provenance"] is True


# ─── Layer 4: integration — _verify_contract reaches binding check ────────


class TestVerifyContractIntegration:
    """End-to-end: a synthetic contract with must_be_created_in_run on
    a present-but-stale file must trigger a missing_files violation
    via _verify_contract → _verify_artifact_run_binding.

    Skipped if database / db.append_event has side-effects that need a
    full repo-init; the unit-level tests above already pin enforcement.
    """

    def test_stale_artifact_appears_in_missing_files(self, git_tmp_path):
        run_id = "run-stale-integration"
        prior = "run-prior-integration"

        # Build .vg layout: active runs + manifest with WRONG creator
        artifact_rel = "phases/test/RUNTIME-MAP.json"
        artifact = git_tmp_path / artifact_rel
        sha = _write_artifact(artifact, "x" * 200)
        _write_manifest(git_tmp_path, run_id, entries=[{
            "path": artifact_rel,
            "creator_run_id": prior,
            "sha256": sha,
        }])

        m = _load_orch_main()
        binding = m._verify_artifact_run_binding(artifact, run_id, False)
        assert binding["ok"] is False
        # Reason carries the orchestrator-level diagnostic prefix used
        # in __main__.py:4438 → "[artifact-run-binding] ..."
        assert "creator_run_id" in binding["reason"]
        assert "stale" in binding["reason"]
