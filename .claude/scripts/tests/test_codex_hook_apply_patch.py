"""Tests for the Codex apply_patch protected-path gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "codex-hooks" / "vg-pre-tool-use-apply-patch.py"


def _run_hook(root: Path, patch: str, session_id: str = "sess-1") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(root)
    payload = {
        "session_id": session_id,
        "cwd": str(root),
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": patch},
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


def test_apply_patch_hook_blocks_protected_evidence_paths(tmp_path):
    root = tmp_path / "project"
    run_id = "run-123"
    active = root / ".vg" / "active-runs" / "sess-1.json"
    active.parent.mkdir(parents=True)
    active.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    patch = """*** Begin Patch
*** Update File: .vg/runs/run-123/.tasklist-projected.evidence.json
@@
-{}
+{"forged": true}
*** End Patch
"""
    result = _run_hook(root, patch)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "PreToolUse-ApplyPatch-protected" in result.stderr
    assert (root / ".vg" / "blocks" / run_id / "PreToolUse-ApplyPatch-protected.md").is_file()


def test_apply_patch_hook_blocks_marker_and_event_paths_without_active_run(tmp_path):
    root = tmp_path / "project"
    patch = """*** Begin Patch
*** Add File: .vg/phases/1/.step-markers/8_execute_waves.done
+done
*** End Patch
"""
    result = _run_hook(root, patch, session_id="no-active")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "direct apply_patch write to protected path" in result.stderr
    assert (root / ".vg" / "blocks" / "unknown" / "PreToolUse-ApplyPatch-protected.md").is_file()


def test_apply_patch_hook_blocks_codex_spawn_evidence_forgery(tmp_path):
    root = tmp_path / "project"
    patch = """*** Begin Patch
*** Add File: .vg/runs/run-1/.codex-spawn-manifest.jsonl
+{"role":"vg-test-codegen","exit_code":0}
*** End Patch
"""
    result = _run_hook(root, patch)
    assert result.returncode == 2
    assert result.stdout == ""
    assert ".codex-spawn-manifest.jsonl" in result.stderr


def test_apply_patch_hook_allows_normal_project_files(tmp_path):
    root = tmp_path / "project"
    patch = """*** Begin Patch
*** Add File: src/app.py
+print("ok")
*** End Patch
"""
    result = _run_hook(root, patch)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
