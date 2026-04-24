"""
Tests for evaluate-test-requirements.py — Phase R of v2.5.2.

Validates goal-to-test mapping + assertion density + E2E variant for
critical user-flow goals.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "evaluate-test-requirements.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, cwd=str(cwd), env=env,
        encoding="utf-8", errors="replace",
    )


def _write_goals(path: Path, goals: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "# Test Goals\n\n"
    for g in goals:
        content += f"### {g['id']} — {g['title']}\n"
        content += f"**Priority:** {g['priority']}\n"
        if g.get("ts_id"):
            content += f"**TS:** {g['ts_id']}\n"
        content += f"**Description:** {g.get('description', '')}\n"
        content += f"**Verification:** {g.get('verification', 'automated')}\n\n"
    path.write_text(content, encoding="utf-8")


def _write_foundation(path: Path, runner="vitest", e2e="playwright",
                       coverage=80) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# FOUNDATION

## 7. Testing baseline

**Runner:** {runner}
**E2E framework:** {e2e}
**Coverage threshold:** {coverage}%
**Mock strategy:** minimal fakes + stdlib
"""
    path.write_text(content, encoding="utf-8")


def _write_test(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestEvaluateTestRequirements:
    def test_goal_with_passing_test_ok(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-01", "title": "Login works",
            "priority": "important", "ts_id": "TS-01",
            "description": "happy-path login",
        }])
        _write_test(tmp_path / "apps" / "web" / "test.spec.ts", """
// TS-01 Login works
expect(result).toBe(200);
expect(body.token).toBeTruthy();
""")
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_missing_ts_flagged(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-02", "title": "No TS",
            "priority": "critical",
            "description": "",
        }])
        r = _run(
            ["--phase-dir", ".vg/phases/X"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "G-02" in r.stdout
        assert "no TS" in r.stdout or "marker" in r.stdout.lower()

    def test_ts_not_referenced_by_any_test(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-03", "title": "Dangling TS",
            "priority": "critical", "ts_id": "TS-99",
            "description": "no test yet",
        }])
        r = _run(
            ["--phase-dir", ".vg/phases/X"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "G-03" in r.stdout

    def test_too_few_assertions_flagged(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-04", "title": "Only one assertion",
            "priority": "important", "ts_id": "TS-04",
            "description": "",
        }])
        _write_test(tmp_path / "tests" / "t.py", """
# TS-04 single-assert test
assert result == True
""")
        r = _run(
            ["--phase-dir", ".vg/phases/X",
             "--min-assertions", "3"],
            cwd=tmp_path,
        )
        assert r.returncode == 1

    def test_critical_user_flow_without_e2e_flagged(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-05", "title": "Login flow",
            "priority": "critical", "ts_id": "TS-05",
            "description": "user login flow happy path",
        }])
        # Unit test only — no E2E
        _write_test(tmp_path / "apps" / "web" / "unit.spec.ts", """
// TS-05 login unit test
expect(a).toBe(1);
expect(b).toBe(2);
""")
        r = _run(
            ["--phase-dir", ".vg/phases/X"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "E2E" in r.stdout or "e2e" in r.stdout

    def test_critical_flow_with_e2e_passes(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-06", "title": "Login flow",
            "priority": "critical", "ts_id": "TS-06",
            "description": "user login flow happy path",
        }])
        _write_test(tmp_path / "apps" / "web" / "e2e" / "login.spec.ts", """
// TS-06 login E2E
expect(page).toHaveTitle('Login');
expect(response.status).toBe(200);
""")
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_manual_verification_skipped(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-07", "title": "Manual only",
            "priority": "critical",
            "verification": "manual",
            "description": "",
        }])
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_nice_priority_skipped(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-08", "title": "Nice to have",
            "priority": "nice",
            "description": "not enforced",
        }])
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_warn_only_suppresses_exit1(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-09", "title": "Missing test",
            "priority": "critical", "ts_id": "TS-09",
            "description": "",
        }])
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--warn-only"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_json_output_schema(self, tmp_path):
        _write_foundation(tmp_path / "FOUNDATION.md")
        _write_goals(tmp_path / ".vg" / "phases" / "X" / "TEST-GOALS.md", [{
            "id": "G-10", "title": "ok",
            "priority": "important", "ts_id": "TS-10",
            "description": "",
        }])
        _write_test(tmp_path / "apps" / "test.spec.ts", """
// TS-10
expect(x).toBe(1);
expect(y).toBe(2);
""")
        r = _run(
            ["--phase-dir", ".vg/phases/X", "--json"],
            cwd=tmp_path,
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["goals_evaluated"] == 1
        assert data["gaps_count"] == 0
