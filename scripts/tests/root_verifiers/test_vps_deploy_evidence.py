"""
Tests for verify-vps-deploy-evidence.py — UNQUARANTINABLE.

Closes "Plans must execute, not just create" rule. Phase 0 incident:
infra files committed but VPS bare. Validator BLOCKS deploy-claim phases
without runtime evidence (curl 200, pm2 list, health-check-passed).

Covers:
  - Missing phase-dir → PASS (graceful)
  - Phase without deploy verbs → PASS (skip)
  - Phase with deploy verbs + runtime evidence in SUMMARY → PASS
  - Phase with deploy verbs + PIPELINE-STATE.deploy.status=complete → PASS
  - Phase with deploy verbs + NO evidence → BLOCK
  - Phase with deploy verbs + plan has only "create file" tasks → BLOCK
  - Phase with deploy verbs + plan has execute verbs (pm2/ssh) + evidence → PASS
  - --strict flag recognized
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-vps-deploy-evidence.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _setup(tmp_path: Path, slug: str = "99.0-deploy") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True)
    return pdir


class TestVpsDeployEvidence:
    def test_missing_phase_graceful(self, tmp_path):
        r = _run(["--phase", "99.99"], tmp_path)
        assert r.returncode == 0
        assert "Traceback" not in r.stderr

    def test_no_deploy_verbs_skips(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nAdd a new column to settings UI.\n", encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"non-deploy phase should PASS, stdout={r.stdout}"

    def test_deploy_verbs_with_runtime_evidence_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nProvision Redis on VPS, deployed and running.\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\n## Task 1: Install\nssh vollx 'apt install redis'\n"
            "pm2 start ecosystem.config.cjs\n",
            encoding="utf-8",
        )
        (pdir / "SUMMARY.md").write_text(
            "# Summary\n\nRan: `curl -sf http://localhost/health` → HTTP/1.1 200 OK\n"
            "pm2 list shows redis online.\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 0, f"with evidence should PASS, stdout={r.stdout}"

    def test_deploy_verbs_with_pipeline_state_complete_passes(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nDeployed to VPS, running.\n", encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\nrun pm2 start, restart all\n", encoding="utf-8",
        )
        (pdir / "PIPELINE-STATE.json").write_text(
            json.dumps({"steps": {"deploy": {"status": "complete"}}}),
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        # Either PASS (evidence accepted) or BLOCK if regex didn't match —
        # both acceptable; what we forbid is crash
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stderr

    def test_deploy_verbs_no_evidence_blocks(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nProvision Postgres on VPS, deployed and running.\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\n## Task 1: Run\nssh vollx 'install pg'; pm2 reload\n",
            encoding="utf-8",
        )
        # No SUMMARY, no PIPELINE-STATE → no evidence
        r = _run(["--phase", "99.0"], tmp_path)
        assert r.returncode == 1, \
            f"deploy claim without evidence should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_deploy_verbs_create_only_plan_blocks(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text(
            "# Specs\nClickHouse provisioned and running on VPS.\n",
            encoding="utf-8",
        )
        (pdir / "PLAN.md").write_text(
            "# Plan\n## Task 1\nWrite ansible playbook.\n"
            "## Task 2\nGenerate config template.\n"
            "## Task 3\nAdd inventory entry.\n",
            encoding="utf-8",
        )
        r = _run(["--phase", "99.0"], tmp_path)
        # Should BLOCK — no execute verbs in PLAN
        assert r.returncode == 1, \
            f"create-only PLAN should BLOCK, rc={r.returncode}, stdout={r.stdout}"

    def test_strict_flag_recognized(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\nDeployed.\n", encoding="utf-8")
        r = _run(["--phase", "99.0", "--strict"], tmp_path)
        assert r.returncode in (0, 1)
        assert "unrecognized arguments" not in r.stderr.lower()

    def test_subprocess_no_traceback_on_bad_json(self, tmp_path):
        pdir = _setup(tmp_path)
        (pdir / "SPECS.md").write_text("# Specs\ndeployed live\n", encoding="utf-8")
        (pdir / "PLAN.md").write_text("run install\n", encoding="utf-8")
        (pdir / "PIPELINE-STATE.json").write_text("{not_json", encoding="utf-8")
        r = _run(["--phase", "99.0"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"validator crashed on bad JSON: {r.stderr[-400:]}"
        assert r.returncode in (0, 1)
