from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "reconcile-build-summary.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_reconcile_updates_summary_sections_and_block(tmp_path: Path) -> None:
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)

    (phase_dir / "SUMMARY.md").write_text(textwrap.dedent("""
        # Build Summary - Phase 4.2

        ## Tasks shipped

        - Task 01

        ## Files touched

        - apps/api/routes.ts

        ## Goal coverage

        - G-01 PASS

        ## Deviations

        - None.

        ## Gates failed

        - `webhooks-subscriptions` - UNRESOLVED: stale route gap

        ## Gaps closed

        - None.

        ## Next steps

        - Hand off to review.
    """).strip() + "\n", encoding="utf-8")

    _write_json(
        phase_dir / ".evidence" / "classified" / "in-scope.webhooks-subscriptions.fixed.json",
        {
            "status": "FIXED",
            "iterations": 2,
            "summary": "route added and contract gap closed",
        },
    )
    _write_json(
        phase_dir / ".evidence" / "classified" / "in-scope.billing-migration.fixed.json",
        {
            "status": "UNRESOLVED",
            "iterations": 3,
            "summary": "requires schema migration",
            "repair_packet": {"blocked_by": "migration"},
        },
    )
    (phase_dir / "PRE-TEST-REPORT.md").write_text("# Pre-Test Report\n", encoding="utf-8")

    result = _run("--phase-dir", str(phase_dir), "--now-iso", "2026-05-06T05:00:00Z")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "updated"

    summary = (phase_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## Gates failed" in summary
    assert "`billing-migration` - UNRESOLVED (attempts=3): requires schema migration" in summary
    assert "`webhooks-subscriptions` - FIXED (attempts=2): route added and contract gap closed" in summary
    assert "<!-- VG:POST-BUILD-RECONCILE:START -->" in summary
    assert "Reconciled at: 2026-05-06T05:00:00Z" in summary
    assert "Pre-test artifact: `PRE-TEST-REPORT.md` present" in summary

    second = _run("--phase-dir", str(phase_dir), "--now-iso", "2026-05-06T05:00:00Z")
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "unchanged"

    final_summary = (phase_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert final_summary.count("<!-- VG:POST-BUILD-RECONCILE:START -->") == 1
    assert final_summary.count("<!-- VG:POST-BUILD-RECONCILE:END -->") == 1


def test_reconcile_fails_when_summary_missing(tmp_path: Path) -> None:
    phase_dir = tmp_path / ".vg" / "phases" / "4.2-example"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PRE-TEST-REPORT.md").write_text("# Pre-Test Report\n", encoding="utf-8")

    result = _run("--phase-dir", str(phase_dir))
    assert result.returncode == 1
    assert "summary missing:" in result.stdout
