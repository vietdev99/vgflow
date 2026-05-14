"""tests/test_deploy_contract_scripts.py — Batch 20 deploy contract scripts."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "scripts" / "deploy-contract-init.py"
LOAD = REPO / "scripts" / "deploy-contract-load.py"
SCHEMA = REPO / "schemas" / "deploy-contract.schema.json"


def test_scripts_exist():
    assert INIT.is_file(), "scripts/deploy-contract-init.py must ship"
    assert LOAD.is_file(), "scripts/deploy-contract-load.py must ship"
    assert SCHEMA.is_file(), "schemas/deploy-contract.schema.json must ship"


def test_init_bootstrap_from_explicit_args(tmp_path):
    """--method ansible --restart-cmd '...' bootstraps non-interactively."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(INIT),
         "--vg-dir", str(vg_dir),
         "--method", "ansible",
         "--pre", "git push origin main",
         "--build", "ansible-playbook deploy.yml --tags build -e env={env}",
         "--restart", "ansible-playbook deploy.yml --tags restart -e env={env}",
         "--health", "ansible-playbook health.yml -e env={env}",
         "--phase", "3"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"init failed: {r.stderr}"
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    assert contract.is_file()
    data = json.loads(contract.read_text(encoding="utf-8"))
    assert data["method"] == "ansible"
    assert "ansible-playbook" in data["commands"]["build"]
    assert "fingerprint_pattern" in data
    assert "lock_sha256" in data


def test_init_idempotent(tmp_path):
    """Second init when contract exists must NOT overwrite without --force."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    contract.write_text(json.dumps({"method": "pm2", "commands": {"restart": "pm2 restart all"}, "fingerprint_pattern": "^pm2 ", "lock_sha256": "abc"}), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(INIT),
         "--vg-dir", str(vg_dir),
         "--method", "ansible",
         "--build", "x", "--restart", "y", "--health", "z",
         "--phase", "5"],
        capture_output=True, text=True,
    )
    # Without --force, should not overwrite
    assert r.returncode != 0 or "already" in (r.stdout + r.stderr).lower()
    data = json.loads(contract.read_text(encoding="utf-8"))
    assert data["method"] == "pm2"  # unchanged


def test_load_exports_env_vars(tmp_path):
    """Load script prints env-var assignments for sourcing."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    contract.write_text(json.dumps({
        "method": "ansible",
        "commands": {
            "pre": "git push",
            "build": "ansible-playbook build.yml -e env={env}",
            "restart": "ansible-playbook restart.yml -e env={env}",
            "health": "ansible-playbook health.yml -e env={env}",
            "rollback": "ansible-playbook rollback.yml -e env={env}",
        },
        "fingerprint_pattern": "^ansible-playbook ",
        "lock_sha256": "abc",
    }), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(LOAD),
         "--vg-dir", str(vg_dir),
         "--env", "sandbox"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"load failed: {r.stderr}"
    out = r.stdout
    assert "export DEPLOY_METHOD=" in out and "ansible" in out
    assert "export DEPLOY_BUILD=" in out
    assert "env=sandbox" in out  # placeholder substituted
    assert "export DEPLOY_FINGERPRINT_PATTERN=" in out


def test_load_blocks_when_contract_missing(tmp_path):
    """Missing contract → exit 1 with bootstrap hint."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(LOAD),
         "--vg-dir", str(vg_dir),
         "--env", "sandbox"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "DEPLOY-CONTRACT.json" in combined
    assert ("init" in combined.lower() or "bootstrap" in combined.lower())
