"""
Tests for verify-override-debt-sla.py — Phase O of v2.5.2.

Covers:
  - Clean register (all under SLA) → exit 0
  - One entry past SLA → exit 1
  - Malformed markdown (no entries found) → treated as zero breaches (exit 0)
  - JSON output parseable, top_breaches sorted oldest-first
  - Mixed open + resolved entries — only open counted
  - Register with logged_at field (VG __main__.py format) parsed correctly
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-override-debt-sla.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd), env=env, encoding="utf-8", errors="replace",
    )


class TestOverrideDebtSla:
    def test_all_under_sla(self, tmp_path):
        debt = tmp_path / "debt.md"
        debt.write_text(
            "# Override Debt\n\n"
            "- id: OD-001\n"
            "  opened: 2026-04-20\n"
            "  status: open\n"
            "  flag: --skip-foo\n",
            encoding="utf-8",
        )
        r = _run([
            "--debt-file", str(debt),
            "--max-days", "30",
            "--today", "2026-04-24",
            "--json",
        ], tmp_path)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] is True
        assert out["breach_count"] == 0

    def test_entry_past_sla_flagged(self, tmp_path):
        debt = tmp_path / "debt.md"
        debt.write_text(
            "- id: OD-002\n"
            "  opened: 2026-02-01\n"
            "  status: open\n",
            encoding="utf-8",
        )
        r = _run([
            "--debt-file", str(debt),
            "--max-days", "30",
            "--today", "2026-04-24",
            "--json",
        ], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert out["ok"] is False
        assert out["breach_count"] == 1
        assert out["top_breaches"][0]["id"] == "OD-002"

    def test_resolved_entry_ignored(self, tmp_path):
        debt = tmp_path / "debt.md"
        debt.write_text(
            "- id: OD-003\n"
            "  opened: 2026-01-01\n"
            "  status: resolved\n"
            "\n"
            "- id: OD-004\n"
            "  opened: 2026-04-20\n"
            "  status: open\n",
            encoding="utf-8",
        )
        r = _run([
            "--debt-file", str(debt),
            "--max-days", "30",
            "--today", "2026-04-24",
            "--json",
        ], tmp_path)
        out = json.loads(r.stdout)
        assert out["ok"] is True
        assert out["breach_count"] == 0
        assert out["open_entries"] == 1

    def test_missing_file_treated_as_zero_breaches(self, tmp_path):
        missing = tmp_path / "nope.md"
        r = _run(["--debt-file", str(missing), "--json"], tmp_path)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["ok"] is True

    def test_logged_at_format_parsed(self, tmp_path):
        # The __main__.py cmd_override uses logged_at not opened
        debt = tmp_path / "debt.md"
        debt.write_text(
            "\n- id: OD-005\n"
            "  logged_at: 2026-01-15T10:00:00Z\n"
            "  status: active\n"
            "  flag: --allow-bar\n",
            encoding="utf-8",
        )
        r = _run([
            "--debt-file", str(debt),
            "--max-days", "30",
            "--today", "2026-04-24",
            "--json",
        ], tmp_path)
        out = json.loads(r.stdout)
        assert out["breach_count"] == 1
        assert out["top_breaches"][0]["id"] == "OD-005"

    def test_top_breaches_sorted_oldest_first(self, tmp_path):
        debt = tmp_path / "debt.md"
        debt.write_text(
            "- id: OD-A\n  opened: 2026-01-01\n  status: open\n\n"
            "- id: OD-B\n  opened: 2025-06-01\n  status: open\n\n"
            "- id: OD-C\n  opened: 2026-02-15\n  status: open\n",
            encoding="utf-8",
        )
        r = _run([
            "--debt-file", str(debt),
            "--max-days", "30",
            "--today", "2026-04-24",
            "--json",
        ], tmp_path)
        out = json.loads(r.stdout)
        assert out["breach_count"] == 3
        assert out["top_breaches"][0]["id"] == "OD-B"  # oldest
