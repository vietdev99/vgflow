"""
Regression coverage for Issue #120.

Backend-only `/vg:review` full runs legitimately skip browser discovery, but
run-complete still enforces the review contract's root `scan-*.json` glob.
This test locks two invariants:

1. The review contract still requires a root scan artifact unless
   `--skip-discovery` is explicitly used.
2. The pure-backend fast-path in `review.md` emits a synthetic
   `scan-backend-surface-probes.json` artifact so contract validation does not
   false-block backend-only phases.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".claude" / "commands" / "vg" / "review.md").exists():
            return candidate
    raise RuntimeError("repo root not found")


REPO_ROOT = _repo_root()
ORCH_PATH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"


@pytest.fixture(scope="module")
def orchestrator_main():
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_issue120",
        ORCH_PATH,
    )
    assert spec and spec.loader, "orchestrator __main__.py not loadable"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_issue120"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    phase = repo / ".vg" / "phases" / "14-api"
    phase.mkdir(parents=True)
    (repo / ".claude" / "commands" / "vg").mkdir(parents=True)

    for sub in ("scripts/vg-orchestrator", "scripts/validators", "schemas"):
        shutil.copytree(REPO_ROOT / sub, repo / ".claude" / sub, dirs_exist_ok=True)
    shutil.copy2(REVIEW_MD, repo / ".claude" / "commands" / "vg" / "review.md")

    monkeypatch.setenv("VG_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)
    return repo


def test_review_contract_keeps_scan_glob_for_full_runs(orchestrator_main) -> None:
    contract = orchestrator_main.contracts.parse("vg:review")
    assert contract is not None
    must_write = orchestrator_main.contracts.normalize_must_write(
        contract.get("must_write") or []
    )
    scan_entry = next(
        (item for item in must_write if item["path"].endswith("scan-*.json")),
        None,
    )
    assert scan_entry is not None, "review contract lost root scan-*.json evidence gate"
    assert scan_entry["glob_min_count"] == 1
    assert scan_entry["required_unless_flag"] == "--skip-discovery"


def test_review_pure_backend_fastpath_emits_synthetic_scan_artifact() -> None:
    text = REVIEW_MD.read_text(encoding="utf-8")
    assert "scan-backend-surface-probes.json" in text
    assert "backend://surface-probes" in text
    assert "pure_backend_fastpath" in text
    assert "runtime_contract still requires one root scan-*.json artifact" in text
    assert "synthetic backend scan so run-complete does not false-block on must_write" in text


def test_verify_contract_accepts_synthetic_backend_scan(
    sandbox: Path,
    orchestrator_main,
    monkeypatch,
) -> None:
    phase = sandbox / ".vg" / "phases" / "14-api"
    (phase / "SPECS.md").write_text(
        "# SPECS\n\nBackend-only feature verification.\n" + ("x" * 160),
        encoding="utf-8",
    )
    (phase / "TEST-GOALS.md").write_text(
        "## Goal G-01: Create order via API\n"
        "**Surface:** api\n"
        "**Success criteria:** POST /api/orders returns 201.\n",
        encoding="utf-8",
    )
    (phase / "RUNTIME-MAP.json").write_text(
        json.dumps({"views": {}, "goal_sequences": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    (phase / "GOAL-COVERAGE-MATRIX.md").write_text(
        "# Matrix\n\n- backend probe pending\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(orchestrator_main, "_run_validators", lambda *args: [])
    monkeypatch.setattr(orchestrator_main.db, "append_event", lambda **kwargs: None)
    monkeypatch.setattr(orchestrator_main.contracts, "PHASES_DIR", sandbox / ".vg" / "phases")
    projection_event = orchestrator_main._tasklist_projection_event_name("vg:review")
    monkeypatch.setattr(
        orchestrator_main.db,
        "query_events",
        lambda **kwargs: (
            [{"payload_json": "{}"}]
            if kwargs.get("event_type") == projection_event
            else []
        ),
    )

    contract = {
        "must_write": [
            "${PHASE_DIR}/RUNTIME-MAP.json",
            "${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md",
            {
                "path": "${PHASE_DIR}/scan-*.json",
                "glob_min_count": 1,
                "required_unless_flag": "--skip-discovery",
            },
        ],
        "must_touch_markers": [],
        "must_emit_telemetry": [],
        "forbidden_without_override": [],
    }

    ok, violations = orchestrator_main._verify_contract(
        contract, "run-issue120", "vg:review", "14", ""
    )
    assert not ok
    assert any(
        v["type"] == "must_write"
        and any("scan-" in missing["path"] for missing in v["missing"])
        for v in violations
    ), violations

    (phase / "scan-backend-surface-probes.json").write_text(
        json.dumps(
            {
                "view": "backend://surface-probes",
                "surface": "backend",
                "generated_by": "phase4_goal_comparison.pure_backend_fastpath",
                "results": [],
                "forms": [],
                "tables": [],
                "modal_triggers": [],
                "sub_views_discovered": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ok, violations = orchestrator_main._verify_contract(
        contract, "run-issue120", "vg:review", "14", ""
    )
    assert ok, violations
    assert violations == []
