"""
Tests for prompt_capture.py + verify-bootstrap-carryforward + verify-learn-promotion
— Phase P of v2.5.2.

Covers:
  prompt_capture module:
    - capture_prompt writes file + manifest entry
    - read_prompt roundtrip with hash integrity check
    - verify_prompt_integrity detects tampered file
    - sweep_old_runs cleans old runs only
    - list_prompts returns sorted by task_seq
    - retry overwrites previous task_seq entry

  verify-bootstrap-carryforward:
    - active critical rule present in all prompts → PASS
    - active critical rule missing from 1 prompt → FAIL (coverage < 1.0)
    - rule in "draft" state (not approved) → not enforced → PASS
    - --severity filter respects severity

  verify-learn-promotion:
    - recent Tier-A promotion propagated to post-promotion run → PASS
    - recent promotion NOT in subsequent run → FAIL
    - no recent promotions → PASS benign
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / ".claude" / "scripts"
VALIDATORS_DIR = SCRIPTS_DIR / "validators"

# Load prompt_capture.py via importlib since its parent dir has a dash
# (`vg-orchestrator`) which blocks normal `from X import Y` syntax.
import importlib.util as _ilu

_MOD_PATH = SCRIPTS_DIR / "vg-orchestrator" / "prompt_capture.py"
_spec = _ilu.spec_from_file_location("prompt_capture", _MOD_PATH)
_mod = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
capture_prompt = _mod.capture_prompt
read_prompt = _mod.read_prompt
verify_prompt_integrity = _mod.verify_prompt_integrity
sweep_old_runs = _mod.sweep_old_runs
list_prompts = _mod.list_prompts


def _run(script: Path, args: list[str], cwd: Path | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if cwd:
        env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
        encoding="utf-8", errors="replace",
    )


# ─── prompt_capture module tests ─────────────────────────────────────


class TestPromptCaptureModule:
    def test_capture_writes_file_and_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entry = capture_prompt(
            run_id="run-abc",
            task_seq=1,
            agent_type="general-purpose",
            prompt_text="Hello world task text.",
            context_refs=["D-01"],
            repo_root=tmp_path,
        )
        assert entry["task_seq"] == 1
        assert entry["sha256"]

        prompt_dir = tmp_path / ".vg" / "runs" / "run-abc" / "executor-prompts"
        assert (prompt_dir / "task-001.prompt.txt").exists()
        assert (prompt_dir / "manifest.json").exists()

    def test_read_prompt_roundtrip(self, tmp_path):
        prompt_text = "Some detailed instruction body here."
        capture_prompt(
            run_id="run-x", task_seq=7, agent_type="explore",
            prompt_text=prompt_text, repo_root=tmp_path,
        )
        result = read_prompt("run-x", 7, repo_root=tmp_path)
        assert result is not None
        text, meta = result
        assert text == prompt_text
        assert meta["agent_type"] == "explore"

    def test_integrity_detects_tamper(self, tmp_path):
        capture_prompt(
            run_id="run-t", task_seq=1, agent_type="x",
            prompt_text="original", repo_root=tmp_path,
        )
        # Tamper
        fpath = tmp_path / ".vg" / "runs" / "run-t" / "executor-prompts" / "task-001.prompt.txt"
        fpath.write_text("MODIFIED after capture", encoding="utf-8")

        report = verify_prompt_integrity("run-t", repo_root=tmp_path)
        assert report["verified"] == 0
        assert len(report["drift"]) == 1
        assert report["drift"][0]["task_seq"] == 1

    def test_retry_overwrites_same_seq(self, tmp_path):
        capture_prompt(
            run_id="run-r", task_seq=3, agent_type="x",
            prompt_text="first", repo_root=tmp_path,
        )
        capture_prompt(
            run_id="run-r", task_seq=3, agent_type="y",
            prompt_text="second", repo_root=tmp_path,
        )
        prompts = list_prompts("run-r", repo_root=tmp_path)
        assert len(prompts) == 1
        assert prompts[0]["agent_type"] == "y"

    def test_list_prompts_sorted(self, tmp_path):
        for seq in [5, 2, 8, 1]:
            capture_prompt(
                run_id="run-s", task_seq=seq, agent_type="x",
                prompt_text=f"task {seq}", repo_root=tmp_path,
            )
        prompts = list_prompts("run-s", repo_root=tmp_path)
        assert [p["task_seq"] for p in prompts] == [1, 2, 5, 8]

    def test_sweep_old_runs(self, tmp_path):
        capture_prompt(
            run_id="old-run", task_seq=1, agent_type="x",
            prompt_text="x", repo_root=tmp_path,
        )
        capture_prompt(
            run_id="new-run", task_seq=1, agent_type="x",
            prompt_text="y", repo_root=tmp_path,
        )
        # Backdate old-run's prompt-dir mtime
        old_dir = tmp_path / ".vg" / "runs" / "old-run" / "executor-prompts"
        past = time.time() - (40 * 86400)
        os.utime(old_dir, (past, past))

        result = sweep_old_runs(retention_days=30, repo_root=tmp_path)
        assert "old-run" in result["swept"]
        assert "new-run" in result["kept"]
        assert not old_dir.exists()


# ─── verify-bootstrap-carryforward tests ─────────────────────────────


BOOTSTRAP_VALIDATOR = VALIDATORS_DIR / "verify-bootstrap-carryforward.py"


def _write_rules(path: Path, rules: list[dict]) -> None:
    content = ""
    for r in rules:
        content += f"## {r['id']} — {r['title']}\n"
        content += f"**State:** {r['state']}\n"
        content += f"**Severity:** {r['severity']}\n"
        content += f"**Rule:** {r['rule_text']}\n\n"
    path.write_text(content, encoding="utf-8")


class TestBootstrapCarryforward:
    def _make_run(self, tmp_path: Path, run_id: str, prompts: list[str]):
        for seq, text in enumerate(prompts, start=1):
            capture_prompt(
                run_id=run_id, task_seq=seq, agent_type="x",
                prompt_text=text, repo_root=tmp_path,
            )

    def test_rule_in_all_prompts_passes(self, tmp_path):
        rule_text = "always use parameterized queries to prevent SQL injection"
        _write_rules(tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"
                     if (tmp_path / ".vg" / "bootstrap").is_dir()
                     else self._mkdir_and_return(
                         tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"),
                     [{"id": "L-001", "title": "SQL safety",
                       "state": "approved", "severity": "critical",
                       "rule_text": rule_text}])

        self._make_run(tmp_path, "run-A", [
            f"task 1 body\n{rule_text}\nmore text",
            f"task 2 body\n{rule_text}\nmore text",
        ])

        r = _run(BOOTSTRAP_VALIDATOR, ["--run-id", "run-A", "--quiet"], cwd=tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_rule_missing_from_prompt_fails(self, tmp_path):
        rule_text = "always use parameterized queries to prevent SQL injection attack vectors"
        rules_path = tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        _write_rules(rules_path, [{
            "id": "L-001", "title": "SQL safety",
            "state": "approved", "severity": "critical",
            "rule_text": rule_text,
        }])

        # 1 prompt has rule, 1 doesn't
        self._make_run(tmp_path, "run-B", [
            f"task 1 body\n{rule_text}\nmore text",
            "task 2 body with no rule injected",
        ])

        r = _run(BOOTSTRAP_VALIDATOR, ["--run-id", "run-B"], cwd=tmp_path)
        assert r.returncode == 1
        assert "L-001" in r.stdout

    def test_draft_rule_not_enforced(self, tmp_path):
        rule_text = "draft rule not yet approved for injection"
        rules_path = tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        _write_rules(rules_path, [{
            "id": "L-009", "title": "Draft",
            "state": "draft", "severity": "critical",
            "rule_text": rule_text,
        }])
        self._make_run(tmp_path, "run-C", ["any content"])
        r = _run(BOOTSTRAP_VALIDATOR, ["--run-id", "run-C", "--quiet"], cwd=tmp_path)
        assert r.returncode == 0

    def test_severity_filter(self, tmp_path):
        rules_path = tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        _write_rules(rules_path, [
            {"id": "L-100", "title": "crit",
             "state": "approved", "severity": "critical",
             "rule_text": "critical-rule-unique-anchor-text-12345"},
            {"id": "L-101", "title": "nice",
             "state": "approved", "severity": "nice",
             "rule_text": "nice-rule-different-anchor-text-67890"},
        ])
        # Only critical-rule present; nice-rule missing
        self._make_run(tmp_path, "run-D", [
            "task with critical-rule-unique-anchor-text-12345 injected"
        ])

        # Severity=critical → pass (all critical rules present)
        r = _run(BOOTSTRAP_VALIDATOR,
                 ["--run-id", "run-D", "--severity", "critical", "--quiet"],
                 cwd=tmp_path)
        assert r.returncode == 0

        # Severity=all → fail (nice rule missing)
        r = _run(BOOTSTRAP_VALIDATOR,
                 ["--run-id", "run-D", "--severity", "all"],
                 cwd=tmp_path)
        assert r.returncode == 1
        assert "L-101" in r.stdout

    def _mkdir_and_return(self, p: Path) -> Path:
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


# ─── verify-learn-promotion tests ────────────────────────────────────


PROMOTION_VALIDATOR = VALIDATORS_DIR / "verify-learn-promotion.py"


def _write_candidates(path: Path, records: list[dict]) -> None:
    content = ""
    for r in records:
        content += f"## {r['id']} — {r['title']}\n"
        content += f"**Tier:** {r.get('tier', 'A')}\n"
        content += f"**Promoted:** {r['promoted']}\n"
        content += f"**Rule:** {r['rule_text']}\n\n"
    path.write_text(content, encoding="utf-8")


class TestLearnPromotion:
    def test_promotion_propagated(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        candidates = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
        candidates.parent.mkdir(parents=True, exist_ok=True)
        rule_text = "always validate input before touching database records"
        _write_candidates(candidates, [{
            "id": "L-042", "title": "Input validation",
            "promoted": past, "rule_text": rule_text,
        }])

        # Create run AFTER promotion timestamp with rule in prompt
        capture_prompt(
            run_id="run-new", task_seq=1, agent_type="x",
            prompt_text=f"task text\n{rule_text}\n",
            repo_root=tmp_path,
        )

        r = _run(PROMOTION_VALIDATOR,
                 ["--lookback-days", "7", "--quiet"], cwd=tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_promotion_not_propagated(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        candidates = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
        candidates.parent.mkdir(parents=True, exist_ok=True)
        rule_text = "always validate input before touching database records"
        _write_candidates(candidates, [{
            "id": "L-099", "title": "Input validation",
            "promoted": past, "rule_text": rule_text,
        }])

        # Run AFTER promotion but NO rule in prompt
        capture_prompt(
            run_id="run-forgot", task_seq=1, agent_type="x",
            prompt_text="task text with no rule injected",
            repo_root=tmp_path,
        )

        r = _run(PROMOTION_VALIDATOR, ["--lookback-days", "7"], cwd=tmp_path)
        assert r.returncode == 1
        assert "L-099" in r.stdout

    def test_no_recent_promotions_passes(self, tmp_path):
        candidates = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
        candidates.parent.mkdir(parents=True, exist_ok=True)
        candidates.write_text("", encoding="utf-8")

        r = _run(PROMOTION_VALIDATOR,
                 ["--lookback-days", "7", "--quiet"], cwd=tmp_path)
        assert r.returncode == 0

    def test_json_output(self, tmp_path):
        candidates = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
        candidates.parent.mkdir(parents=True, exist_ok=True)
        candidates.write_text("", encoding="utf-8")

        r = _run(PROMOTION_VALIDATOR,
                 ["--lookback-days", "7", "--json"], cwd=tmp_path)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["promotions_checked"] == 0
