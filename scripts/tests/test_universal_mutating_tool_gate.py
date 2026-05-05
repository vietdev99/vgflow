"""HOTFIX session 2 — universal mutating-tool gate + match-coverage check.

Closes 2 bypass paths Codex flagged after Q1-Q3 review:

1. Edit/Write/MultiEdit/NotebookEdit bypass: bash gate alone doesn't stop
   AI from skipping step-active and editing code via mutating tools. Hook
   `vg-pre-tool-use-write.sh` now denies all writes outside .vg/ when run
   is active and tasklist evidence is missing.

2. TodoWrite content-match: hook checked depth_valid (≥1 ↳ child per group)
   but not match (todo IDs cover all contract checklists). AI could call
   TodoWrite with subset of groups + ≥1 child each → satisfy depth_valid
   while leaving most of the contract unprojected. Hook now also blocks
   on match=false.
"""
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITE_HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-write.sh"
BASH_HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


# ── Fix 1: pre-write hook tasklist gate ─────────────────────────────


def _run_write_hook(tmp_path, file_path, run_active=True, evidence=False,
                    session_id="test-sess"):
    run_id = "run-write-test"
    if run_active:
        (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".vg/active-runs" / f"{session_id}.json").write_text(
            json.dumps({"run_id": run_id, "command": "vg:build"})
        )
    if evidence:
        (tmp_path / f".vg/runs/{run_id}").mkdir(parents=True, exist_ok=True)
        (tmp_path / f".vg/runs/{run_id}/.tasklist-projected.evidence.json").write_text("{}")
    payload = json.dumps({"tool_input": {"file_path": file_path}})
    proc = subprocess.run(
        ["bash", str(WRITE_HOOK)],
        input=payload, cwd=tmp_path, capture_output=True, text=True,
        env={"CLAUDE_HOOK_SESSION_ID": session_id, "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_write_outside_vg_blocked_when_evidence_missing(tmp_path):
    """Run-active + evidence missing → Write to non-.vg/ path blocked."""
    rc, stdout, _ = _run_write_hook(tmp_path, "src/components/Foo.tsx",
                                     run_active=True, evidence=False)
    assert rc == 2, f"Hook should block, got rc={rc}"
    payload = json.loads(stdout)
    deny = payload["hookSpecificOutput"]
    assert deny["permissionDecision"] == "deny"
    assert "tasklist-required" in deny["permissionDecisionReason"].lower() or \
           "tasklist" in deny["permissionDecisionReason"].lower()


def test_write_inside_vg_allowed_when_evidence_missing(tmp_path):
    """.vg/ paths whitelisted (orchestrator state, contracts, blocks)."""
    rc, _, _ = _run_write_hook(tmp_path, ".vg/runs/run-write-test/tasklist-contract.json",
                                run_active=True, evidence=False)
    assert rc == 0, f"Write to .vg/ should pass, got rc={rc}"


def test_write_outside_vg_allowed_when_evidence_present(tmp_path):
    """Evidence file exists → write proceeds (gate satisfied)."""
    rc, _, _ = _run_write_hook(tmp_path, "src/components/Foo.tsx",
                                run_active=True, evidence=True)
    assert rc == 0, f"Write should pass when evidence exists, got rc={rc}"


def test_write_no_active_run_silent(tmp_path):
    """No active run → no gate (graceful exit). Protected-path checks still apply."""
    rc, _, _ = _run_write_hook(tmp_path, "src/components/Foo.tsx",
                                run_active=False, evidence=False)
    assert rc == 0


# ── Fix 2: pre-bash hook match-coverage check ────────────────────────


def test_bash_hook_validates_match_field():
    """Source must verify payload.match (not just depth_valid)."""
    src = BASH_HOOK.read_text()
    # Find the section after depth_check_result that we just added
    assert "match_check_result" in src, "match-coverage check missing"
    assert 'payload.get("match")' in src, "Must check payload.match field"
    assert "match_invalid" in src and "match_missing" in src, (
        "Must distinguish between match=false and missing match field"
    )


def test_bash_hook_match_block_message_actionable():
    """Match-invalid block must tell AI exactly what's missing."""
    src = BASH_HOOK.read_text()
    # The block message should reference contract_ids and todo_ids
    m = re.search(r"match_invalid.*?emit_block.*?\n", src, re.DOTALL)
    assert m, "match_invalid emit_block clause not found"
    block = m.group(0)
    assert "missing=" in block or "contract checklists" in block, (
        "Block message must surface what items are missing from coverage"
    )


# ── Settings matcher coverage ───────────────────────────────────────


def test_settings_matcher_includes_notebookedit():
    """Settings.json hook matcher must include NotebookEdit alongside
    Write|Edit so notebook edits also trigger the tasklist gate."""
    settings_path = REPO_ROOT / ".claude" / "settings.json"
    src = settings_path.read_text()
    # Find the matcher line for the write hook
    assert "Write|Edit|NotebookEdit" in src, (
        "Hook matcher must include NotebookEdit (was Write|Edit only)"
    )


# ── Mirror parity ────────────────────────────────────────────────────


def test_mirror_parity_write_hook():
    mirror = REPO_ROOT / ".claude/scripts/hooks/vg-pre-tool-use-write.sh"
    assert mirror.is_file()
    assert WRITE_HOOK.read_bytes() == mirror.read_bytes()


def test_mirror_parity_bash_hook():
    mirror = REPO_ROOT / ".claude/scripts/hooks/vg-pre-tool-use-bash.sh"
    assert mirror.is_file()
    assert BASH_HOOK.read_bytes() == mirror.read_bytes()
