"""Tests for Codex Stop hook output normalization."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "codex-hooks" / "vg-stop.py"


def _run_stop(root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    env["VG_RUNTIME"] = "codex"
    payload = {
        "session_id": "codex-stop-test",
        "cwd": str(root),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def test_stop_hook_normalizes_claude_approve_json_to_codex_continue(tmp_path):
    root = tmp_path / "project"
    verifier = root / ".claude" / "scripts" / "vg-verify-claim.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        "import json\n"
        "print(json.dumps({'decision': 'approve', 'reason': 'no-active-run'}))\n",
        encoding="utf-8",
    )

    result = _run_stop(root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"continue": True}


def test_stop_hook_preserves_block_as_codex_stop_failure(tmp_path):
    root = tmp_path / "project"
    verifier = root / ".claude" / "scripts" / "vg-verify-claim.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        "import sys\n"
        "print('contract violation', file=sys.stderr)\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )

    result = _run_stop(root)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "contract violation" in result.stderr
