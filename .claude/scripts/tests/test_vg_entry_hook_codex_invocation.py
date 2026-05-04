"""Tests for Codex-style VG skill invocation in the entry hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "vg-entry-hook.py"


def test_entry_hook_accepts_codex_dollar_skill_invocation(tmp_path):
    root = tmp_path / "project"
    orch = root / "scripts" / "vg-orchestrator"
    orch.mkdir(parents=True)
    (orch / "__main__.py").write_text(
        """
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["VG_REPO_ROOT"])
(root / ".vg").mkdir(parents=True, exist_ok=True)
(root / ".vg" / "stub-orchestrator.json").write_text(json.dumps({
    "argv": sys.argv[1:],
    "session_id": os.environ.get("CLAUDE_SESSION_ID"),
}), encoding="utf-8")
print("run-codex-123456")
""",
        encoding="utf-8",
    )

    payload = {
        "session_id": "codex-session-1",
        "cwd": str(root),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "$vg-build 12.3 --from=review",
    }
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    env["VG_RUNTIME"] = "codex"
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["continue"] is True
    assert "decision" not in output

    call = json.loads((root / ".vg" / "stub-orchestrator.json").read_text(encoding="utf-8"))
    assert call["argv"] == ["run-start", "vg:build", "12.3"]
    assert call["session_id"] == "codex-session-1"

    session_context = json.loads((root / ".vg" / ".session-context.json").read_text(encoding="utf-8"))
    assert session_context["run_id"] == "run-codex-123456"
    assert session_context["command"] == "vg:build"
    assert session_context["phase"] == "12.3"


def test_entry_hook_codex_non_vg_prompt_returns_continue_true(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    payload = {
        "session_id": "codex-session-2",
        "cwd": str(root),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hello",
    }
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    env["VG_RUNTIME"] = "codex"
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"continue": True}
