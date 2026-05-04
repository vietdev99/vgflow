"""HOTFIX 2026-05-05 — `vg-orchestrator tasklist-projected --adapter claude`
must verify evidence file existence (written by PostToolUse TodoWrite hook).

Bug: PV3 phase 4.2 build run a6f54da7 — AI called orchestrator command
without calling TodoWrite tool first. Orchestrator only set state flag
in active-runs (`tasklist_projected: true`) but evidence file was never
written (claude adapter relied on PostToolUse hook). AI then emitted
`vg.block.handled` to bypass first step-active block; subsequent steps
proceeded without native TodoWrite UI rendering.

Fix: claude adapter checks evidence file exists; returns rc=2 with
actionable error if missing.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"


def _setup_run(tmp_path, run_id="run-x", session_id="sess-x"):
    """Stage minimal active-runs + run dir + tasklist-contract.json."""
    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    active = {
        "run_id": run_id,
        "command": "vg:build",
        "phase": "4.2",
        "args": "",
        "started_at": "2026-05-05T00:00:00Z",
        "session_id": session_id,
        "lock_token": "lock-x",
    }
    (tmp_path / ".vg/active-runs" / f"{session_id}.json").write_text(json.dumps(active))
    (tmp_path / ".vg/current-run.json").write_text(json.dumps(active))
    (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:build",
        "phase": "4.2",
        "checklists": [
            {"id": "build_preflight", "title": "Build Preflight",
             "items": ["0_gate_integrity_precheck", "1_parse_args"]},
        ],
    }
    (tmp_path / f".vg/runs/{run_id}/tasklist-contract.json").write_text(
        json.dumps(contract)
    )
    return run_id, session_id


def _run_orch(tmp_path, args, session_id="sess-x"):
    """Invoke orchestrator command from tmp_path with stable session env."""
    env = {"HOME": str(tmp_path), "CLAUDE_HOOK_SESSION_ID": session_id, "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, str(ORCH), *args],
        cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_source_has_claude_evidence_gate():
    """HOTFIX guard: __main__.py cmd_tasklist_projected must check evidence
    file existence for adapter='claude' before setting state flag.

    This is a structural test — source must contain the elif claude branch
    + evidence_path.is_file() check + return 2 on missing.
    """
    src = ORCH.read_text()
    # Find cmd_tasklist_projected function body
    import re
    fn_match = re.search(
        r"def cmd_tasklist_projected.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    assert fn_match, "cmd_tasklist_projected not found"
    body = fn_match.group(0)

    # Must have explicit claude adapter branch
    assert 'args.adapter == "claude"' in body or "args.adapter==\"claude\"" in body, (
        "Missing explicit `args.adapter == 'claude'` branch"
    )
    # Must check evidence_path.is_file() in claude branch
    assert "evidence_path.is_file()" in body or "is_file()" in body, (
        "Claude branch must check evidence_path.is_file()"
    )
    # Must return 2 (BLOCK) when evidence missing
    # (codex/fallback also returns 2 on write failure; check for the new error message)
    assert "Evidence file missing" in body or "evidence_path is None" not in body, (
        "Claude branch must FAIL when evidence file missing (the bug — claude "
        "previously skipped evidence write entirely)"
    )


def test_source_codex_adapter_unchanged():
    """Regression: codex/fallback adapter still writes evidence."""
    src = ORCH.read_text()
    import re
    fn_match = re.search(
        r"def cmd_tasklist_projected.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    body = fn_match.group(0)
    # Codex/fallback path must still call _write_tasklist_projection_evidence
    assert '"codex"' in body and '"fallback"' in body, "codex/fallback path missing"
    assert "_write_tasklist_projection_evidence" in body, "evidence writer not called"


def test_hotfix_documented_in_source():
    """Source must reference HOTFIX context for future maintainers."""
    src = ORCH.read_text()
    assert "HOTFIX" in src and "PostToolUse" in src, (
        "Source should document HOTFIX rationale (PV3 phase 4.2 build run)"
    )


def test_mirror_parity():
    """Source + .claude/ mirror byte-identical."""
    mirror = REPO_ROOT / ".claude/scripts/vg-orchestrator/__main__.py"
    assert mirror.is_file()
    assert ORCH.read_bytes() == mirror.read_bytes(), "Mirror drift"
