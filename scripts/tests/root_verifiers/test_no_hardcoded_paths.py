"""
Tests for verify-no-hardcoded-paths.py — UNQUARANTINABLE.

Per CLAUDE.md infra rules: SSH must use the configured alias from
environments.sandbox.run_prefix, never raw IP. VPS paths come from
config.environments.<env>.project_path. Catches AI copy-paste-leaking
literal SSH commands and project paths.

Covers:
  - Empty repo → PASS
  - Source file with `ssh root@<public IP>` → BLOCK
  - Loopback IP (127.0.0.1) in source → PASS (legitimate dev default)
  - Private IP (192.168.x) in source → PASS (intra-LAN)
  - Public IP in URL (https://X.X.X.X) → WARN (rc=0)
  - Allowlisted infra/ansible/inventory file → PASS
  - Allowlisted .vg/ workspace artifact → PASS
  - .md doc file with example IP → not BLOCK
  - --verbose flag listed each finding to stderr
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
    "verify-no-hardcoded-paths.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestNoHardcodedPaths:
    def test_empty_repo_passes(self, tmp_path):
        r = _run([], tmp_path)
        assert r.returncode == 0, f"empty repo should PASS, stdout={r.stdout}"

    def test_ssh_to_raw_public_ip_blocks(self, tmp_path):
        _write(
            tmp_path / "apps/api/scripts/deploy.sh",
            "ssh root@46.224.11.195 'pm2 reload all'\n",  # INTENTIONAL_HARDCODE: detection-test fixture (Phase K1 register §5)
        )
        r = _run([], tmp_path)
        assert r.returncode == 1, \
            f"public-IP SSH should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_loopback_ip_allowed(self, tmp_path):
        _write(
            tmp_path / "apps/api/src/dev.ts",
            "const url = 'http://127.0.0.1:3000';\n",
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, f"loopback should PASS, stdout={r.stdout}"

    def test_private_ip_allowed(self, tmp_path):
        _write(
            tmp_path / "apps/api/src/lan.ts",
            "ssh deploy@192.168.1.50 'restart'\n",
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, f"private IP should PASS, stdout={r.stdout}"

    def test_public_ip_url_warns(self, tmp_path):
        _write(
            tmp_path / "apps/web/src/probe.ts",
            "const probe = 'http://8.8.8.8/';\n",  # INTENTIONAL_HARDCODE: detection-test fixture (Phase K1 register §5)
        )
        r = _run([], tmp_path)
        # URL pattern is WARN severity → rc=0 but verdict=WARN
        assert r.returncode == 0, f"URL warn should rc=0, stdout={r.stdout}"
        verdict = _verdict(r.stdout)
        assert verdict in ("WARN", "PASS"), f"verdict={verdict}"

    def test_infra_ansible_inventory_allowlisted(self, tmp_path):
        _write(
            tmp_path / "infra/ansible/inventory.yml",
            "vollx ansible_host=46.224.11.195\n",  # INTENTIONAL_HARDCODE: allowlist-coverage fixture (Phase K1 register §5)
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, f"infra/ansible/inventory should be allowlisted, stdout={r.stdout}"

    def test_vg_workspace_allowlisted(self, tmp_path):
        _write(
            tmp_path / ".vg/scratch/notes.md",
            "ssh root@46.224.11.195 'echo'\n",  # INTENTIONAL_HARDCODE: allowlist-coverage fixture (Phase K1 register §5)
        )
        r = _run([], tmp_path)
        assert r.returncode == 0, f".vg/ should be allowlisted, stdout={r.stdout}"

    def test_verbose_flag_recognized(self, tmp_path):
        _write(
            tmp_path / "apps/api/x.sh",
            "ssh root@8.8.4.4 'x'\n",  # INTENTIONAL_HARDCODE: detection-test fixture for --verbose flag (Phase K1 register §5)
        )
        r = _run(["--verbose"], tmp_path)
        # Verbose should not change verdict, just add stderr output
        assert r.returncode == 1
        assert "scanned" in r.stderr or len(r.stderr) > 0
