import json, os, sqlite3, subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1].parent / "scripts/hooks/vg-session-start.sh"


def _seed_run_with_unhandled_block(repo: Path):
    (repo / ".vg/active-runs").mkdir(parents=True, exist_ok=True)
    (repo / ".vg/active-runs/sess-1.json").write_text(json.dumps({
        "run_id": "r1", "command": "vg:blueprint", "phase": "2",
    }))
    db = repo / ".vg/events.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, event_type TEXT, phase TEXT, command TEXT, run_id TEXT,"
        "payload TEXT)"
    )
    conn.execute(
        "INSERT INTO events(ts,event_type,phase,command,run_id,payload) VALUES (?,?,?,?,?,?)",
        ("2026-05-03T10:00:00Z", "vg.block.fired", "2", "vg:blueprint", "r1",
         json.dumps({"gate": "PreToolUse-tasklist", "cause": "evidence missing"})),
    )
    conn.commit()
    conn.close()


def test_session_start_basic_injects_meta_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin_root = tmp_path / "scripts/hooks"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "vg-meta-skill.md").write_text(
        "<EXTREMELY-IMPORTANT>\nVGFlow rules\n</EXTREMELY-IMPORTANT>"
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    result = subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_EVENT": "startup",
             "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "EXTREMELY-IMPORTANT" in ctx
    assert "VGFlow rules" in ctx


def test_session_start_compact_reinjects_open_diagnostics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin_root = tmp_path / "scripts/hooks"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "vg-meta-skill.md").write_text("base meta-skill")
    _seed_run_with_unhandled_block(tmp_path)
    result = subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_EVENT": "compact",
             "CLAUDE_HOOK_SESSION_ID": "sess-1",
             "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "OPEN DIAGNOSTICS" in ctx
    assert "PreToolUse-tasklist" in ctx
