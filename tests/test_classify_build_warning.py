"""Evidence-based classifier — assigns 4-tier severity per Codex review (2026-05-03)."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
CLASSIFIER = REPO / "scripts" / "classify-build-warning.py"


def _make_phase(tmp: Path) -> Path:
    pd = tmp / "phase"
    (pd / "PLAN").mkdir(parents=True)
    (pd / "API-CONTRACTS").mkdir()
    (pd / "TEST-GOALS").mkdir()
    (pd / "PLAN" / "task-39.md").write_text("# task-39\nFile: apps/api/src/billing/invoices.ts\n", encoding="utf-8")
    (pd / "API-CONTRACTS" / "post-api-invoices.md").write_text(
        "**Method:** POST\n**Path:** /api/invoices\n", encoding="utf-8",
    )
    (pd / "TEST-GOALS" / "G-04.md").write_text("# G-04: Invoice CRUD\n", encoding="utf-8")
    return pd


def test_warning_referencing_phase_task_classifies_in_scope(tmp_path: Path) -> None:
    pd = _make_phase(tmp_path)
    warning = {
        "warning_id": "w1",
        "severity": "BLOCK",
        "category": "spec_drift",
        "phase": "4.1",
        "evidence_refs": [{"file": "apps/api/src/billing/invoices.ts", "task_id": "task-39"}],
        "summary": "task-39 returned 202 instead of 201",
        "detected_by": "verify-spec-drift.py",
        "detected_at": "2026-05-03T10:00:00Z",
    }
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "--phase-dir", str(pd), "--warning", json.dumps(warning)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["classification"] == "IN_SCOPE"
    assert out["confidence"] >= 0.8
    assert "task-39" in out["evidence_refs_matched"]


def test_warning_unrelated_to_phase_classifies_forward_dep(tmp_path: Path) -> None:
    pd = _make_phase(tmp_path)
    warning = {
        "warning_id": "w2",
        "severity": "ADVISORY",
        "category": "perf_budget",
        "phase": "4.1",
        "evidence_refs": [{"file": "apps/web/src/pages/UnrelatedPage.tsx"}],
        "summary": "bundle size budget exceeded in unrelated route",
        "detected_by": "perf-check.py",
        "detected_at": "2026-05-03T10:00:00Z",
    }
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "--phase-dir", str(pd), "--warning", json.dumps(warning)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["classification"] in {"FORWARD_DEP", "NEEDS_TRIAGE"}


def test_ambiguous_warning_classifies_needs_triage(tmp_path: Path) -> None:
    pd = _make_phase(tmp_path)
    warning = {
        "warning_id": "w3",
        "severity": "TRIAGE_REQUIRED",
        "category": "other",
        "phase": "4.1",
        "evidence_refs": [{"file": "apps/api/src/shared/error-handler.ts"}],
        "summary": "error handler may need refactor (cross-cutting)",
        "detected_by": "ad-hoc",
        "detected_at": "2026-05-03T10:00:00Z",
    }
    result = subprocess.run(
        ["python3", str(CLASSIFIER), "--phase-dir", str(pd), "--warning", json.dumps(warning)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["classification"] == "NEEDS_TRIAGE"
