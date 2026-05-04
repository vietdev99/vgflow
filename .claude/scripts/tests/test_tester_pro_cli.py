from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "tester-pro-cli.py"


def test_tester_pro_help_does_not_require_recipe_yaml_deps() -> None:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "validate-test-types" in proc.stdout
