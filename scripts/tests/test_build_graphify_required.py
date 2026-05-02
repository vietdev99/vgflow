from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "build-graphify-required.py"
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
BUILD_MD = REPO_ROOT / "commands" / "vg" / "build.md"
BUILD_REFS_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "build"
GRAPHIFY_SAFE = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "graphify-safe.sh"


def _combined_build_text() -> str:
    """Slim entry + all refs concatenated — equivalent to pre-R2 monolithic view.

    R2 split build.md (4571 -> 203 lines) by moving step bodies into refs under
    _shared/build/. Tests that grep step content / wave markers / config flags
    must read across both surfaces.
    """
    parts = [BUILD_MD.read_text(encoding="utf-8")]
    for ref in sorted(BUILD_REFS_DIR.glob("*.md")):
        parts.append(ref.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _repo(tmp_path: Path, *, enabled: bool = True, graph: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".vg" / "phases" / "99-test").mkdir(parents=True)
    (repo / ".vg" / "current-run.json").write_text(
        json.dumps({"run_id": "run-1", "command": "vg:build", "phase": "99"}),
        encoding="utf-8",
    )
    (repo / ".claude" / "vg.config.md").write_text(
        "graphify:\n"
        f"  enabled: {'true' if enabled else 'false'}\n"
        "  graph_path: \"graphify-out/graph.json\"\n"
        "  fallback_to_grep: true\n",
        encoding="utf-8",
    )
    if graph:
        (repo / "graphify-out").mkdir()
        (repo / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
    return repo


def _events_db(repo: Path, *, graphify_event: bool) -> None:
    db = repo / ".vg" / "events.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "run_id TEXT, event_type TEXT, actor TEXT, outcome TEXT, payload_json TEXT)"
        )
        if graphify_event:
            conn.execute(
                "INSERT INTO events(run_id, event_type, actor, outcome, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-1", "graphify_auto_rebuild", "orchestrator", "PASS", "{}"),
            )
        conn.commit()
    finally:
        conn.close()


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    env["VG_GRAPHIFY_REQUIRED_ASSUME_IMPORTABLE"] = "1"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "99"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_graphify_enabled_blocks_without_current_run_rebuild_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _events_db(repo, graphify_event=False)

    result = _run(repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["verdict"] == "BLOCK"
    assert payload["evidence"][0]["type"] == "graphify_rebuild_event_missing"


def test_graphify_enabled_passes_with_rebuild_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _events_db(repo, graphify_event=True)

    result = _run(repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["verdict"] == "PASS"


def test_graphify_disabled_skips_gate(tmp_path: Path) -> None:
    repo = _repo(tmp_path, enabled=False, graph=False)
    _events_db(repo, graphify_event=False)

    result = _run(repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["verdict"] == "PASS"


def test_build_workflow_wires_graphify_cold_wave_final_and_validator() -> None:
    build = _combined_build_text()
    orch = (REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py").read_text(encoding="utf-8")
    graphify_safe = GRAPHIFY_SAFE.read_text(encoding="utf-8")

    assert "build-step4-cold" in build
    assert "build-wave-${N}-complete" in build
    assert "build-final" in build
    assert "GRAPHIFY_ENABLED" in build
    assert 'local payload="${3:-}"' in graphify_safe
    assert 'payload="{}"' in graphify_safe
    assert "[ -e \"${REPO_ROOT:-.}/.claude/scripts/vg-orchestrator\" ]" in graphify_safe
    assert "emit-event \"$event_type\"" in graphify_safe
    assert "build-graphify-required" in orch
    assert ORCH.exists()
