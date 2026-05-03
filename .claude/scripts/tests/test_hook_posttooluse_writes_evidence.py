import hashlib, json, os, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-post-tool-use-todowrite.sh"


def test_post_tool_use_writes_signed_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))

    (tmp_path / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))

    contract_path = tmp_path / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract = {"checklists": [
        {"id": "blueprint_preflight", "title": "Preflight"},
        {"id": "blueprint_design", "title": "Design"},
    ]}
    contract_path.write_text(json.dumps(contract))

    todowrite_payload = json.dumps({
        "tool_name": "TodoWrite",
        "tool_input": {"todos": [
            {"content": "blueprint_preflight: Preflight", "status": "pending"},
            {"content": "blueprint_design: Design", "status": "pending"},
        ]},
    })

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=todowrite_payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0, result.stderr

    evidence_path = tmp_path / ".vg/runs/r1/.tasklist-projected.evidence.json"
    assert evidence_path.exists()
    evidence = json.loads(evidence_path.read_text())
    assert "hmac_sha256" in evidence
    assert evidence["payload"]["contract_sha256"] == hashlib.sha256(
        contract_path.read_bytes()
    ).hexdigest()
    assert evidence["payload"]["match"] is True


def test_post_tool_use_no_op_without_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vg").mkdir()
    todowrite_payload = json.dumps({
        "tool_name": "TodoWrite",
        "tool_input": {"todos": [{"content": "anything", "status": "pending"}]},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=todowrite_payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0  # silent no-op
