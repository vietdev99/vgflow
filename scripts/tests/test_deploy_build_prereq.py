from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deploy_build_prereq_accepts_durable_evidence() -> None:
    text = (REPO_ROOT / "commands" / "vg" / "deploy.md").read_text(encoding="utf-8")

    assert "PIPELINE-STATE when present" in text
    assert ".step-markers\" / \"build\" / \"12_run_complete.done" in text
    assert "SUMMARY.md" in text
    assert "PRE-TEST-REPORT.md" in text
    assert "BUILD-LOG" in text
    assert "evidence-complete" in text


def test_deploy_shared_overview_checks_namespaced_marker() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "deploy" / "overview.md"
    ).read_text(encoding="utf-8")

    assert ".step-markers/build/12_run_complete.done" in text
    assert "BUILD_DONE_MARKER" in text
