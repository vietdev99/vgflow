"""
Tests for verify-bootstrap-carryforward.py — Phase P v2.5.2.

Behavioral check: active rules in LEARN-RULES.md must appear in captured
executor prompts (not just in event log). Catches paperwork-only
bootstrap.loaded events.

NOTE: This validator does NOT emit a top-level `verdict` field in --json
output. It uses `failures` array + exit code. Schema gap noted as
discovery; not Phase O scope to canonicalize.

Covers:
  - Required --run-id missing → rc=2
  - No prompts captured → rc=2 (config-error)
  - No active rules at severity → rc=0 (PASS, nothing to enforce)
  - All active rules present in prompts → rc=0
  - Active rule missing from prompts → rc=1 (failure)
  - Min-coverage threshold respected
  - Severity filter applied
  - Subprocess resilience (malformed manifest)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-bootstrap-carryforward.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _write_rules(tmp_path: Path, *, rules: list[tuple[str, str, str, str]]) -> Path:
    """rules: list of (id, state, severity, body_text). Returns path."""
    p = tmp_path / ".vg" / "bootstrap" / "LEARN-RULES.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for rid, state, severity, text in rules:
        body.append(f"## {rid} — Test rule {rid}")
        body.append(f"**State:** {state}")
        body.append(f"**Severity:** {severity}")
        body.append(f"**Rule:** {text}")
        body.append("")
    p.write_text("\n".join(body), encoding="utf-8")
    return p


def _write_prompts(tmp_path: Path, run_id: str,
                   prompt_texts: list[str]) -> None:
    pdir = tmp_path / ".vg" / "runs" / run_id / "executor-prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, txt in enumerate(prompt_texts):
        fname = f"task-{i}.prompt.txt"
        (pdir / fname).write_text(txt, encoding="utf-8")
        entries.append({"task_seq": i, "file": fname, "sha256": "x"})
    (pdir / "manifest.json").write_text(
        json.dumps({"entries": entries}),
        encoding="utf-8",
    )


class TestBootstrapCarryforward:
    def test_run_id_required_rc2(self, tmp_path):
        r = _run([], tmp_path)
        assert r.returncode == 2

    def test_no_prompts_rc2(self, tmp_path):
        _write_rules(tmp_path, rules=[
            ("L-001", "approved", "critical",
             "Always reload after mutation to verify ghost-save layer 4 persistence"),
        ])
        r = _run(["--run-id", "ghost", "--json"], tmp_path)
        assert r.returncode == 2, f"no prompts → config-error rc=2, got {r.returncode}"

    def test_no_active_rules_passes(self, tmp_path):
        _write_rules(tmp_path, rules=[
            ("L-001", "draft", "critical",
             "Inactive rule body sufficiently long for anchor detection logic"),
        ])
        _write_prompts(tmp_path, "run-A",
                       ["You are an executor. Do task 1."])
        r = _run(["--run-id", "run-A", "--json"], tmp_path)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["active_rules_count"] == 0

    def test_active_rule_present_passes(self, tmp_path):
        rule_text = (
            "Always reload page after mutation to verify layer 4 persistence "
            "is real not ghost-save"
        )
        _write_rules(tmp_path, rules=[
            ("L-002", "approved", "critical", rule_text),
        ])
        # Prompt contains the rule body
        _write_prompts(tmp_path, "run-B", [
            f"Executor task. {rule_text}. Now go.",
        ])
        r = _run(["--run-id", "run-B", "--json"], tmp_path)
        assert r.returncode == 0, \
            f"rule present → rc=0, got {r.returncode}, stdout={r.stdout[:300]}"

    def test_active_rule_missing_fails(self, tmp_path):
        _write_rules(tmp_path, rules=[
            ("L-003", "approved", "critical",
             "Critical rule with anchor: never skip type-check before commit ever"),
        ])
        # Prompt does NOT contain the rule
        _write_prompts(tmp_path, "run-C", [
            "Generic executor prompt with no rule injection."
        ])
        r = _run(["--run-id", "run-C", "--json"], tmp_path)
        assert r.returncode == 1, \
            f"rule missing → rc=1, got {r.returncode}, stdout={r.stdout[:300]}"
        data = json.loads(r.stdout)
        assert len(data["failures"]) >= 1

    def test_min_coverage_threshold(self, tmp_path):
        rule_text = "Required policy text that lives in approved rule body length OK"
        _write_rules(tmp_path, rules=[
            ("L-004", "approved", "critical", rule_text),
        ])
        # Rule present in 1 of 2 prompts → coverage = 0.5
        _write_prompts(tmp_path, "run-D", [
            f"prompt one with {rule_text}",
            "prompt two without policy",
        ])
        r = _run(["--run-id", "run-D", "--min-coverage", "1.0", "--json"],
                 tmp_path)
        assert r.returncode == 1, \
            f"coverage 0.5 < 1.0 → fail, got {r.returncode}"
        # With looser threshold, passes
        r2 = _run(["--run-id", "run-D", "--min-coverage", "0.4", "--json"],
                  tmp_path)
        assert r2.returncode == 0

    def test_severity_filter(self, tmp_path):
        _write_rules(tmp_path, rules=[
            ("L-005", "approved", "nice",
             "Nice-to-have rule body sufficiently long for anchor matching"),
        ])
        _write_prompts(tmp_path, "run-E", ["empty prompt"])
        # severity=critical filter excludes the nice rule → no failures
        r = _run(["--run-id", "run-E", "--severity", "critical", "--json"],
                 tmp_path)
        assert r.returncode == 0

    def test_malformed_manifest_no_crash(self, tmp_path):
        pdir = tmp_path / ".vg" / "runs" / "run-bad" / "executor-prompts"
        pdir.mkdir(parents=True)
        (pdir / "manifest.json").write_text("not json {{{", encoding="utf-8")
        _write_rules(tmp_path, rules=[
            ("L-006", "approved", "critical",
             "Rule body that is reasonably long for anchor matching purposes"),
        ])
        r = _run(["--run-id", "run-bad", "--json"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad manifest: {r.stderr[-300:]}"
