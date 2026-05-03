"""
Tests for verify-executor-context-scope.py — Phase R of v2.5.2.

Covers behavioral check: prompt text decision IDs vs declared <context-refs>.
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
    "verify-executor-context-scope.py"

# Load prompt_capture via importlib (dashes in path)
import importlib.util as _ilu
_MOD_PATH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "prompt_capture.py"
_spec = _ilu.spec_from_file_location("prompt_capture_r", _MOD_PATH)
_mod = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
capture_prompt = _mod.capture_prompt


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if cwd:
        env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
        encoding="utf-8", errors="replace",
    )


def _write_plan(path: Path, tasks: list[dict]) -> None:
    content = "# PLAN\n\n"
    for t in tasks:
        refs = ",".join(t.get("context_refs", []))
        content += f'<task id="{t["id"]}">\n'
        content += f'  <title>{t.get("title","")}</title>\n'
        content += f'  <context-refs>{refs}</context-refs>\n'
        content += f'</task>\n\n'
    path.write_text(content, encoding="utf-8")


class TestExecutorContextScope:
    def test_prompt_matches_declared_passes(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["D-01", "D-03"],
        }])
        capture_prompt(
            run_id="r1", task_seq=4, agent_type="x",
            prompt_text="task body — follow decisions D-01 and D-03 only",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r1", "--plan-file", "PLAN.md", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_extra_ids_in_prompt_fails_as_leak(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["D-01"],
        }])
        capture_prompt(
            run_id="r2", task_seq=4, agent_type="x",
            prompt_text="task body — references D-01, D-02, D-05",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r2", "--plan-file", "PLAN.md"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "leak" in r.stdout.lower() or "extra_in_prompt" in r.stdout

    def test_declared_but_absent_fails(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["D-01", "D-09"],
        }])
        # Prompt has only D-01, missing D-09
        capture_prompt(
            run_id="r3", task_seq=4, agent_type="x",
            prompt_text="task body cites D-01 only",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r3", "--plan-file", "PLAN.md"],
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "D-09" in r.stdout

    def test_allow_leak_demotes_to_warn(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["D-01"],
        }])
        capture_prompt(
            run_id="r4", task_seq=4, agent_type="x",
            prompt_text="task body with extra D-01 D-02 D-03",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r4", "--plan-file", "PLAN.md", "--allow-leak",
             "--quiet"],
            cwd=tmp_path,
        )
        # --allow-leak means leak=ok, but still check absent. None absent here.
        assert r.returncode == 0

    def test_phased_decision_id_recognized(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["P7.14.D-02"],
        }])
        capture_prompt(
            run_id="r5", task_seq=4, agent_type="x",
            prompt_text="task body — per decision P7.14.D-02 do X",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r5", "--plan-file", "PLAN.md", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_missing_plan_file_exits_2(self, tmp_path):
        r = _run(
            ["--run-id", "r6", "--plan-file", "nonexistent.md"],
            cwd=tmp_path,
        )
        assert r.returncode == 2

    def test_no_tasks_benign_pass(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        plan.write_text("# PLAN (no tasks)\n", encoding="utf-8")
        r = _run(
            ["--run-id", "r7", "--plan-file", "PLAN.md", "--quiet"],
            cwd=tmp_path,
        )
        assert r.returncode == 0

    def test_json_output(self, tmp_path):
        plan = tmp_path / "PLAN.md"
        _write_plan(plan, [{
            "id": "7-04", "context_refs": ["D-01"],
        }])
        capture_prompt(
            run_id="r8", task_seq=4, agent_type="x",
            prompt_text="body with D-01",
            repo_root=tmp_path,
        )
        r = _run(
            ["--run-id", "r8", "--plan-file", "PLAN.md", "--json"],
            cwd=tmp_path,
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["tasks_checked"] == 1
        assert data["leaks"] == []
