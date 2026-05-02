"""
Verify vg:test slim entry triggers test.native_tasklist_projected emission.

Audit FAIL #8 fix verification (R2 Task 2).

Baseline: 0 events of type test.native_tasklist_projected.
Fix inherited via R1a blueprint pilot's PostToolUse hook on TodoWrite +
imperative TodoWrite call in slim entry.

Two-part assertion:
  Part A — Contract declaration: commands/vg/test.md declares
    test.native_tasklist_projected in must_emit_telemetry.
    (Skipped if test.md is still bloated >1000 lines = Task 13 not done.)
  Part B — Hook integration: given proper run state + TodoWrite payload,
    vg-post-tool-use-todowrite.sh writes the evidence file.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

# ── conftest imports (BASH_AVAILABLE) ────────────────────────────────────
from conftest import BASH_AVAILABLE, BASH_UNAVAILABLE_REASON

needs_bash = pytest.mark.skipif(
    not BASH_AVAILABLE,
    reason=(
        "Phase R: bash subprocess unavailable on this platform "
        f"(probe: {BASH_UNAVAILABLE_REASON}). "
        "See .claude/scripts/tests/PLATFORM-COMPAT.md."
    ),
)


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "sync.sh").exists() and (candidate / "commands" / "vg").exists():
            return candidate
        if (
            (candidate / ".claude" / "commands" / "vg").exists()
            and (candidate / ".claude" / "scripts" / "emit-tasklist.py").exists()
        ):
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
CMDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
HOOK_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh"
EVIDENCE_SIGNER = REPO_ROOT / "scripts" / "vg-orchestrator-emit-evidence-signed.py"

# Task 13 detection heuristic: test.md > 1000 lines → Task 13 not done yet.
_TEST_MD = CMDS_DIR / "test.md"
_TEST_MD_LINE_COUNT = len(_TEST_MD.read_text(encoding="utf-8").splitlines()) if _TEST_MD.exists() else 0
_TASK13_DONE = _TEST_MD_LINE_COUNT <= 1000

_TASK13_SKIP_REASON = (
    f"Task 13 (slim entry replacement) not yet landed — "
    f"test.md is {_TEST_MD_LINE_COUNT} lines (threshold: <=1000)."
)


# ── Part A: Contract declaration ──────────────────────────────────────────

class TestContractDeclaration:
    """test.md must declare test.native_tasklist_projected in must_emit_telemetry."""

    @pytest.mark.xfail(
        not _TASK13_DONE,
        reason=_TASK13_SKIP_REASON,
        strict=False,
    )
    def test_test_md_declares_native_tasklist_projected(self):
        """commands/vg/test.md must declare test.native_tasklist_projected."""
        assert _TEST_MD.exists(), f"Missing {_TEST_MD}"
        text = _TEST_MD.read_text(encoding="utf-8")
        assert "test.native_tasklist_projected" in text, (
            "test.md missing test.native_tasklist_projected declaration "
            "(audit FAIL #8 not fixed — task.md still missing the event)"
        )

    @pytest.mark.xfail(
        not _TASK13_DONE,
        reason=_TASK13_SKIP_REASON,
        strict=False,
    )
    def test_test_md_frontmatter_declares_todowrite(self):
        """test.md frontmatter must expose TodoWrite for native tasklist."""
        import re
        assert _TEST_MD.exists(), f"Missing {_TEST_MD}"
        text = _TEST_MD.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert m, "test.md missing YAML frontmatter"
        frontmatter = m.group(1)
        assert "TodoWrite" in frontmatter, (
            "test.md frontmatter must expose Claude Code's native TodoWrite tool"
        )

    @pytest.mark.xfail(
        not _TASK13_DONE,
        reason=_TASK13_SKIP_REASON,
        strict=False,
    )
    def test_test_md_binds_tasklist_contract_json(self):
        """test.md must bind native tasklist to tasklist-contract.json."""
        assert _TEST_MD.exists(), f"Missing {_TEST_MD}"
        text = _TEST_MD.read_text(encoding="utf-8")
        assert "tasklist-contract.json" in text, (
            "test.md must bind native tasklist to tasklist-contract.json"
        )

    @pytest.mark.xfail(
        not _TASK13_DONE,
        reason=_TASK13_SKIP_REASON,
        strict=False,
    )
    def test_test_md_lifecycle_replace_on_start(self):
        """test.md must declare replace-on-start tasklist lifecycle."""
        assert _TEST_MD.exists(), f"Missing {_TEST_MD}"
        text = _TEST_MD.read_text(encoding="utf-8")
        assert "replace-on-start" in text, (
            "test.md must replace stale native tasklists at workflow start"
        )

    @pytest.mark.xfail(
        not _TASK13_DONE,
        reason=_TASK13_SKIP_REASON,
        strict=False,
    )
    def test_test_md_lifecycle_close_on_complete(self):
        """test.md must declare close-on-complete tasklist lifecycle."""
        assert _TEST_MD.exists(), f"Missing {_TEST_MD}"
        text = _TEST_MD.read_text(encoding="utf-8")
        assert "close-on-complete" in text, (
            "test.md must close/clear native tasklists at workflow completion"
        )


# ── Part B: Hook integration ──────────────────────────────────────────────

class TestHookIntegration:
    """PostToolUse hook writes evidence file when given proper run state + TodoWrite payload."""

    @needs_bash
    def test_hook_scripts_exist(self):
        """Prerequisite: hook and evidence signer must exist."""
        assert HOOK_SCRIPT.exists(), f"Missing hook script: {HOOK_SCRIPT}"
        assert EVIDENCE_SIGNER.exists(), f"Missing evidence signer: {EVIDENCE_SIGNER}"

    @needs_bash
    def test_hook_exits_zero_when_no_active_run_file(self, tmp_path):
        """Hook must silently exit 0 when .vg/active-runs/<session>.json is missing."""
        env = os.environ.copy()
        env["CLAUDE_HOOK_SESSION_ID"] = "test-session"

        result = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input='{"tool_input": {"todos": []}}',
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Hook should silently exit 0 when active-run file missing. "
            f"stderr: {result.stderr}"
        )

    @needs_bash
    def test_hook_exits_zero_when_contract_missing(self, tmp_path):
        """Hook must silently exit 0 when tasklist-contract.json is missing."""
        run_id = "test-run-missing-contract"
        session_id = "test-session"

        # Create active-runs entry but NO contract file.
        active_dir = tmp_path / ".vg" / "active-runs"
        active_dir.mkdir(parents=True)
        (active_dir / f"{session_id}.json").write_text(
            json.dumps({"run_id": run_id, "command": "vg:test"}),
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["CLAUDE_HOOK_SESSION_ID"] = session_id

        result = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input='{"tool_input": {"todos": []}}',
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Hook should silently exit 0 when contract missing. "
            f"stderr: {result.stderr}"
        )

    @needs_bash
    def test_hook_writes_evidence_file(self, tmp_path):
        """Core assertion: hook writes signed evidence file when prerequisites present.

        This is the primary verification of audit FAIL #8 being fixed.
        The evidence file existing with match=True proves the PostToolUse chain
        fired correctly (emit-event is best-effort downstream).
        """
        run_id = "test-run-1"
        session_id = "test-session"

        # 1. Scaffold .vg/active-runs/<session>.json
        active_dir = tmp_path / ".vg" / "active-runs"
        active_dir.mkdir(parents=True)
        (active_dir / f"{session_id}.json").write_text(
            json.dumps({"run_id": run_id, "command": "vg:test"}),
            encoding="utf-8",
        )

        # 2. Scaffold .vg/runs/<run_id>/tasklist-contract.json
        contract = {
            "schema": "native-tasklist.v1",
            "run_id": run_id,
            "command": "vg:test",
            "phase": "3.2",
            "profile": "web-fullstack",
            "projection_required": True,
            "checklists": [
                {"id": "test_preflight", "title": "Test Preflight", "items": ["1_parse_args"]},
                {"id": "test_runtime", "title": "Test Runtime", "items": ["5b_runtime_contract_verify"]},
            ],
            "items": [
                {"id": "1_parse_args", "title": "Parse args"},
                {"id": "5b_runtime_contract_verify", "title": "Runtime contract verify"},
            ],
        }
        contract_path = tmp_path / ".vg" / "runs" / run_id / "tasklist-contract.json"
        contract_path.parent.mkdir(parents=True)
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        # 3. Create evidence key (required by emit-evidence-signed.py)
        vg_dir = tmp_path / ".vg"
        key_path = vg_dir / ".evidence-key"
        import secrets
        import base64
        key_bytes = base64.b64encode(secrets.token_bytes(32))
        key_path.write_bytes(key_bytes)
        key_path.chmod(0o600)

        # 4. Stub vg-orchestrator on PATH (best-effort; records args but always exits 0)
        stub_dir = tmp_path / "_stubs"
        stub_dir.mkdir()
        stub_bin = stub_dir / "vg-orchestrator"
        stub_bin.write_text(
            "#!/usr/bin/env bash\n"
            "echo \"vg-orchestrator called: $*\" >> \"$(dirname \"$0\")/../_vg_orch_calls.log\"\n"
            "exit 0\n"
        )
        stub_bin.chmod(0o755)

        env = os.environ.copy()
        env["CLAUDE_HOOK_SESSION_ID"] = session_id
        env["VG_EVIDENCE_KEY_PATH"] = str(key_path)
        env["PATH"] = str(stub_dir) + os.pathsep + env.get("PATH", "")

        # 5. Build TodoWrite payload matching contract checklist IDs
        todo_payload = json.dumps({
            "tool_input": {
                "todos": [
                    {"content": "test_preflight: Set up test environment"},
                    {"content": "test_runtime: Verify runtime contracts"},
                ]
            }
        })

        result = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input=todo_payload,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Hook exited {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

        # 6. Assert evidence file was written
        evidence_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
        assert evidence_path.exists(), (
            f"Evidence file not written at {evidence_path}. "
            "PostToolUse hook chain did not fire correctly (audit FAIL #8 not fixed). "
            f"hook stderr: {result.stderr}"
        )

        # 7. Assert evidence file has valid signed structure
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert "payload" in evidence, "Evidence file missing 'payload' key"
        assert "hmac_sha256" in evidence, "Evidence file missing 'hmac_sha256' key"
        assert "signed_at" in evidence, "Evidence file missing 'signed_at' key"

        # 8. Assert payload content
        payload = evidence["payload"]
        assert payload["run_id"] == run_id, f"run_id mismatch: {payload['run_id']!r}"
        assert payload["todo_count"] == 2, f"todo_count mismatch: {payload['todo_count']}"
        assert "contract_sha256" in payload, "Missing contract_sha256 in payload"

        # Verify the SHA256 matches the contract we wrote
        expected_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        assert payload["contract_sha256"] == expected_sha256, (
            f"contract_sha256 mismatch: {payload['contract_sha256']!r} != {expected_sha256!r}"
        )

        # 9. Assert match=True (todo IDs matched contract checklist IDs)
        assert payload["match"] is True, (
            f"match=False — todo IDs did not match contract checklist IDs.\n"
            f"todo_ids: {payload.get('todo_ids')}\n"
            f"contract_ids: {payload.get('contract_ids')}"
        )

    @needs_bash
    def test_hook_match_false_when_todos_mismatch_contract(self, tmp_path):
        """Hook still writes evidence when IDs mismatch; match=False is correct signal."""
        run_id = "test-run-mismatch"
        session_id = "test-session-mismatch"

        active_dir = tmp_path / ".vg" / "active-runs"
        active_dir.mkdir(parents=True)
        (active_dir / f"{session_id}.json").write_text(
            json.dumps({"run_id": run_id, "command": "vg:test"}),
            encoding="utf-8",
        )

        contract = {
            "checklists": [
                {"id": "test_preflight", "title": "Test Preflight"},
                {"id": "test_deploy", "title": "Test Deploy"},
            ],
        }
        contract_path = tmp_path / ".vg" / "runs" / run_id / "tasklist-contract.json"
        contract_path.parent.mkdir(parents=True)
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        vg_dir = tmp_path / ".vg"
        key_path = vg_dir / ".evidence-key"
        import secrets, base64
        key_path.write_bytes(base64.b64encode(secrets.token_bytes(32)))
        key_path.chmod(0o600)

        env = os.environ.copy()
        env["CLAUDE_HOOK_SESSION_ID"] = session_id
        env["VG_EVIDENCE_KEY_PATH"] = str(key_path)

        # Todos use WRONG IDs — mismatch with contract
        mismatched_payload = json.dumps({
            "tool_input": {
                "todos": [
                    {"content": "wrong_id_1: Something completely different"},
                ]
            }
        })

        result = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input=mismatched_payload,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Hook should exit 0 even on mismatch. stderr: {result.stderr}"
        )

        evidence_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
        assert evidence_path.exists(), "Evidence file not written even on mismatch"

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        payload = evidence["payload"]
        assert payload["match"] is False, (
            "Expected match=False for mismatched todos vs contract"
        )

    @needs_bash
    def test_hook_emit_event_called_for_vg_test(self, tmp_path):
        """Stub vg-orchestrator records emit-event call with test.native_tasklist_projected."""
        run_id = "test-run-emit"
        session_id = "test-session-emit"

        active_dir = tmp_path / ".vg" / "active-runs"
        active_dir.mkdir(parents=True)
        (active_dir / f"{session_id}.json").write_text(
            json.dumps({"run_id": run_id, "command": "vg:test"}),
            encoding="utf-8",
        )

        contract = {
            "checklists": [
                {"id": "test_preflight", "title": "Test Preflight"},
            ],
        }
        contract_path = tmp_path / ".vg" / "runs" / run_id / "tasklist-contract.json"
        contract_path.parent.mkdir(parents=True)
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        vg_dir = tmp_path / ".vg"
        key_path = vg_dir / ".evidence-key"
        import secrets, base64
        key_path.write_bytes(base64.b64encode(secrets.token_bytes(32)))
        key_path.chmod(0o600)

        # Stub dir for vg-orchestrator + call log
        stub_dir = tmp_path / "_stubs"
        stub_dir.mkdir()
        call_log = tmp_path / "_vg_orch_calls.log"
        stub_bin = stub_dir / "vg-orchestrator"
        stub_bin.write_text(
            f"#!/usr/bin/env bash\n"
            f'echo "vg-orchestrator $*" >> {str(call_log)!r}\n'
            f"exit 0\n"
        )
        stub_bin.chmod(0o755)

        env = os.environ.copy()
        env["CLAUDE_HOOK_SESSION_ID"] = session_id
        env["VG_EVIDENCE_KEY_PATH"] = str(key_path)
        env["PATH"] = str(stub_dir) + os.pathsep + env.get("PATH", "")

        todo_payload = json.dumps({
            "tool_input": {
                "todos": [
                    {"content": "test_preflight: Run test preflight checks"},
                ]
            }
        })

        result = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input=todo_payload,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Hook failed. stderr: {result.stderr}"
        )

        # Check that vg-orchestrator was called with emit-event + correct event name
        assert call_log.exists(), (
            "vg-orchestrator was never called — stub log not created. "
            "Either vg-orchestrator is not on PATH or the hook's best-effort call was skipped."
        )
        log_text = call_log.read_text(encoding="utf-8")
        assert "emit-event" in log_text, (
            f"vg-orchestrator emit-event not called. log: {log_text!r}"
        )
        assert "test.native_tasklist_projected" in log_text, (
            f"Expected 'test.native_tasklist_projected' in vg-orchestrator call log. "
            f"Actual log: {log_text!r}\n"
            "Audit FAIL #8 not fixed: emit-event not triggered for vg:test command."
        )
