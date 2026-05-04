import json, hashlib, hmac, os, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-pre-tool-use-bash.sh"


def _seed_active_run(repo: Path):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
        "session_id": "sess-1",
    }))


def _seed_signed_evidence(repo: Path, payload: dict, key: bytes):
    evidence_path = repo / ".vg/runs/r1/.tasklist-projected.evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    evidence_path.write_text(json.dumps(
        {"payload": payload, "hmac_sha256": sig}, sort_keys=True
    ))


def test_blocks_when_evidence_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 2
    assert "DIAGNOSTIC REQUIRED" in result.stderr
    assert "TodoWrite" in result.stderr or "tasklist" in result.stderr


def test_passes_when_evidence_signed_and_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))
    _seed_active_run(tmp_path)
    contract_path = tmp_path / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text('{"checklists":[{"id":"blueprint_preflight"}]}')
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    _seed_signed_evidence(tmp_path, {"contract_sha256": contract_sha}, key)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0, result.stderr


def test_blocks_when_hmac_invalid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    wrong_key = b"wrong-key-32-bytes-aaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))
    _seed_active_run(tmp_path)
    contract_path = tmp_path / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text('{"checklists":[{"id":"blueprint_preflight"}]}')
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    _seed_signed_evidence(tmp_path, {"contract_sha256": contract_sha}, wrong_key)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 2
    assert "hmac" in result.stderr.lower() or "signature" in result.stderr.lower()


def test_passes_for_unrelated_bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0


def test_passes_when_no_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 2a_plan"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0
