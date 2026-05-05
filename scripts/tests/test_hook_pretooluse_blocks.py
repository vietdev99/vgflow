import json, hashlib, hmac, os, sqlite3, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-pre-tool-use-bash.sh"


def _seed_active_run(repo: Path):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
        "session_id": "sess-1",
    }))


def _seed_session_context(repo: Path, current_step=None, step_history=None):
    (repo / ".vg").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/.session-context.json").write_text(json.dumps({
        "session_id": "sess-1",
        "run_id": "r1",
        "command": "vg:blueprint",
        "phase": "2",
        "current_step": current_step,
        "step_history": step_history or [],
    }))


def _seed_step_active_event(repo: Path):
    db_path = repo / ".vg/events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        run_id TEXT,
        command TEXT,
        event_type TEXT,
        step TEXT,
        ts TEXT,
        payload_json TEXT,
        actor TEXT,
        outcome TEXT
    )""")
    conn.execute(
        "INSERT INTO events(run_id, command, event_type, step, ts, payload_json, actor, outcome) VALUES (?,?,?,?,?,?,?,?)",
        ("r1", "vg:blueprint", "step.active", "0_design_discovery", "2026-05-04T00:00:00Z", "{}", "hook", "INFO"),
    )
    conn.commit()
    conn.close()


def _run_hook(command: str, env=None):
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    return subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1", **(env or {})},
    )


def _seed_signed_evidence(repo: Path, payload: dict, key: bytes):
    evidence_path = repo / ".vg/runs/r1/.tasklist-projected.evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": "r1", "depth_valid": True, "match": True, **payload}
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    evidence_path.write_text(json.dumps(
        {"payload": payload, "hmac_sha256": sig}, sort_keys=True
    ))


def _seed_contract(repo: Path):
    contract_path = repo / ".vg/runs/r1/tasklist-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text('{"checklists":[{"id":"blueprint_preflight"}]}')
    return contract_path


def test_blocks_when_evidence_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_contract(tmp_path)
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
    assert "PreToolUse-tasklist" in result.stderr
    assert ".vg/blocks/r1/PreToolUse-tasklist.md" in result.stderr
    assert "TodoWrite" in result.stderr or "tasklist" in result.stderr


def test_allows_bootstrap_step_before_contract_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    cmd_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "vg-orchestrator step-active 0_design_discovery"},
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=cmd_input, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": "sess-1"},
    )
    assert result.returncode == 0, result.stderr


def test_blocks_non_bootstrap_step_when_contract_missing(tmp_path, monkeypatch):
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
    assert "tasklist contract missing" in result.stderr


def test_passes_when_evidence_signed_and_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".vg/.evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))
    _seed_active_run(tmp_path)
    contract_path = _seed_contract(tmp_path)
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
    contract_path = _seed_contract(tmp_path)
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


def test_codex_blocks_broad_rg_files_before_first_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    result = _run_hook("rg --files", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-prestep-scope" in result.stderr
    block_file = tmp_path / ".vg/blocks/r1/PreToolUse-codex-prestep-scope.md"
    assert block_file.exists()
    assert "rg --files" in block_file.read_text()


def test_codex_blocks_broad_workflow_find_before_first_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    result = _run_hook("find .claude -maxdepth 3 -type f", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-prestep-scope" in result.stderr


def test_codex_blocks_broad_root_find_before_first_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    result = _run_hook("find . -maxdepth 4 -type f", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-prestep-scope" in result.stderr


def test_codex_blocks_broad_scan_after_first_step_before_tasklist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_step_active_event(tmp_path)
    result = _run_hook(
        "rg --files .claude/scripts .claude/commands/vg/_shared",
        env={"VG_RUNTIME": "codex"},
    )
    assert result.returncode == 2
    assert "PreToolUse-codex-pretasklist-scope" in result.stderr
    assert (tmp_path / ".vg/blocks/r1/PreToolUse-codex-pretasklist-scope.md").exists()

def test_codex_blocks_vg_find_after_first_step_before_tasklist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_step_active_event(tmp_path)
    result = _run_hook("find .vg -maxdepth 4 -type f", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-pretasklist-scope" in result.stderr

def test_codex_allows_broad_scan_after_tasklist_projection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_step_active_event(tmp_path)
    evidence = tmp_path / ".vg/runs/r1/.tasklist-projected.evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("{}", encoding="utf-8")
    result = _run_hook(
        "rg --files .claude/scripts .claude/commands/vg/_shared",
        env={"VG_RUNTIME": "codex"},
    )
    assert result.returncode == 0, result.stderr

def test_codex_allows_exact_blueprint_file_read_before_first_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    result = _run_hook(
        "rg -n step .claude/commands/vg/_shared/blueprint/preflight.md",
        env={"VG_RUNTIME": "codex"},
    )
    assert result.returncode == 0, result.stderr


def test_codex_pretasklist_scope_guard_blocks_after_first_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path, current_step="0_design_discovery")
    result = _run_hook("rg --files", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-pretasklist-scope" in result.stderr


def test_codex_pretasklist_scope_guard_blocks_after_step_active_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    _seed_step_active_event(tmp_path)
    result = _run_hook("rg --files", env={"VG_RUNTIME": "codex"})
    assert result.returncode == 2
    assert "PreToolUse-codex-pretasklist-scope" in result.stderr


def test_codex_prestep_scope_guard_does_not_affect_non_codex(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_active_run(tmp_path)
    _seed_session_context(tmp_path)
    result = _run_hook("rg --files")
    assert result.returncode == 0, result.stderr
