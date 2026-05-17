"""tests/test_batch77_todowrite_accumulation.py — B77 TodoWrite accumulation gate.

User dogfood: TodoWrite UI carrying 699 items (10 in_progress / 116 pending /
573 completed) across runs because AI was APPENDING new run's tasks instead
of REPLACING. Native adapter string "TodoWrite per projection_items entry"
was ambiguous — strengthened with REPLACE semantics.

Fix:
  1. `_write_contract` native_adapters.claude string explicitly says
     "TodoWrite REPLACES the entire prior list in one call".
  2. `tasklist-projection-instruction.md` REPLACE HARD-GATE block.
  3. `vg-post-tool-use-todowrite.sh` writes
     `accumulation_suspected=true` when `len(todos[]) > max(1.5*contract, contract+3)`.
  4. `vg-pre-tool-use-bash.sh` BLOCKs step-active when
     `accumulation_suspected=true` in evidence payload.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EMIT_TASKLIST = REPO / "scripts" / "emit-tasklist.py"
POST_HOOK = REPO / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh"
PRE_HOOK = REPO / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"
INSTRUCTION_MD = REPO / "commands" / "vg" / "_shared" / "lib" / "tasklist-projection-instruction.md"


# ---------------------------------------------------------------------------
# Text presence — REPLACE directive surfaced everywhere.
# ---------------------------------------------------------------------------


def test_b77_emit_tasklist_native_adapter_says_replaces():
    body = EMIT_TASKLIST.read_text(encoding="utf-8")
    assert "TodoWrite REPLACES the entire prior list" in body
    assert "B77 v4.63.9" in body


def test_b77_instruction_md_has_replace_hard_gate():
    body = INSTRUCTION_MD.read_text(encoding="utf-8")
    assert "REPLACE semantics" in body
    assert "accumulation_suspected" in body
    assert "B77 v4.63.9" in body


def test_b77_post_hook_emits_accumulation_flag():
    body = POST_HOOK.read_text(encoding="utf-8")
    assert "accumulation_suspected" in body
    assert "1.5" in body  # threshold multiplier
    assert "B77 v4.63.9" in body


def test_b77_pre_hook_blocks_on_accumulation():
    body = PRE_HOOK.read_text(encoding="utf-8")
    assert "accumulation_check_result" in body
    assert 'payload.get("accumulation_suspected")' in body
    assert "TodoWrite accumulation suspected" in body
    assert "B77 v4.63.9" in body


# ---------------------------------------------------------------------------
# Mirror parity.
# ---------------------------------------------------------------------------


def test_b77_emit_tasklist_mirror_byte_identical():
    canonical = EMIT_TASKLIST.read_bytes()
    mirror = (REPO / ".claude" / "scripts" / "emit-tasklist.py").read_bytes()
    assert canonical == mirror


def test_b77_post_hook_mirror_byte_identical():
    canonical = POST_HOOK.read_bytes()
    mirror = (REPO / ".claude" / "scripts" / "hooks" / "vg-post-tool-use-todowrite.sh").read_bytes()
    assert canonical == mirror


def test_b77_pre_hook_mirror_byte_identical():
    canonical = PRE_HOOK.read_bytes()
    mirror = (REPO / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh").read_bytes()
    assert canonical == mirror


def test_b77_instruction_md_mirror_byte_identical():
    canonical = INSTRUCTION_MD.read_bytes()
    mirror = (REPO / ".claude" / "commands" / "vg" / "_shared" / "lib" / "tasklist-projection-instruction.md").read_bytes()
    assert canonical == mirror


# ---------------------------------------------------------------------------
# Behavioral — PreToolUse hook subprocess BLOCK on accumulation_suspected.
# ---------------------------------------------------------------------------


def _seed_evidence(tmp_path: Path, sid: str, rid: str,
                   todo_count: int, contract_count: int,
                   accumulation_suspected: bool,
                   match: bool = True, depth_valid: bool = True):
    """Build the synthetic project layout that PreToolUse expects."""
    project = tmp_path
    active_runs = project / ".vg" / "active-runs"
    active_runs.mkdir(parents=True, exist_ok=True)
    (active_runs / f"{sid}.json").write_text(json.dumps({
        "session_id": sid,
        "run_id": rid,
        "command": "vg:build",
        "phase": "1",
    }), encoding="utf-8")
    run_dir = project / ".vg" / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    # Minimal contract (just enough for path + sha256 read).
    contract_path = run_dir / "tasklist-contract.json"
    contract_items = [{"id": f"step{i}", "title": f"Step {i}"} for i in range(contract_count)]
    contract_body = json.dumps({
        "schema": "native-tasklist.v2",
        "run_id": rid,
        "projection_items": contract_items,
        "items": contract_items,
    })
    contract_path.write_text(contract_body, encoding="utf-8")

    # Signed evidence — HMAC required for hook pass-through but we want
    # accumulation gate to fire BEFORE depth/match gates so build a fake
    # evidence with valid HMAC + bypass-stub fields.
    key_path = project / ".vg" / ".evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_bytes = b"x" * 32
    key_path.write_bytes(key_bytes)
    import hashlib, hmac
    contract_sha = hashlib.sha256(contract_body.encode()).hexdigest()
    payload = {
        "run_id": rid,
        "adapter": "claude",
        "tool_name": "TodoWrite",
        "todowrite_at": "2026-05-18T00:00:00Z",
        "todo_count": todo_count,
        "contract_projection_count": contract_count,
        "accumulation_suspected": accumulation_suspected,
        "contract_sha256": contract_sha,
        "todo_ids": [f"step{i}" for i in range(min(todo_count, contract_count))],
        "contract_ids": [f"step{i}" for i in range(contract_count)],
        "match": match,
        "depth_valid": depth_valid,
        "groups_with_subs_count": contract_count,
        "flat_groups": [],
    }
    canonical = json.dumps(payload, sort_keys=True).encode()
    hmac_sig = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
    evidence = {
        "payload": payload,
        "hmac_sha256": hmac_sig,
        "signed_at": "2026-05-18T00:00:00Z",
    }
    (run_dir / ".tasklist-projected.evidence.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    return project


def _run_pre_hook(project: Path, sid: str, cmd_text: str) -> subprocess.CompletedProcess:
    stdin_obj = {
        "session_id": sid,
        "tool_name": "Bash",
        "tool_input": {"command": cmd_text},
    }
    env = {**os.environ,
           "VG_REPO_ROOT": str(project),
           "VG_HOME": str(REPO / ".claude"),
           "CLAUDE_HOOK_SESSION_ID": sid,
           "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        ["bash", str(PRE_HOOK)],
        input=json.dumps(stdin_obj),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(project),
        timeout=15,
    )


def test_b77_pre_hook_blocks_when_accumulation_suspected(tmp_path: Path):
    """todos=699, contract=9, accumulation_suspected=true → BLOCK."""
    project = _seed_evidence(tmp_path, "sid-1", "rid-1",
                             todo_count=699, contract_count=9,
                             accumulation_suspected=True)
    result = _run_pre_hook(project, "sid-1", "vg-orchestrator step-active 1_init")
    assert result.returncode == 2, (
        f"expected BLOCK on accumulation; got rc={result.returncode}\n"
        f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    )
    assert "accumulation" in result.stderr.lower() or "accumulation" in result.stdout.lower()


def test_b77_pre_hook_passes_when_no_accumulation(tmp_path: Path):
    """todos=9, contract=9, accumulation_suspected=false → PASS through accumulation gate."""
    project = _seed_evidence(tmp_path, "sid-2", "rid-2",
                             todo_count=9, contract_count=9,
                             accumulation_suspected=False)
    result = _run_pre_hook(project, "sid-2", "vg-orchestrator step-active 1_init")
    # Other gates may still fire (e.g. step exemption / adapter check) but
    # accumulation-block message specifically should NOT appear.
    assert "TodoWrite accumulation suspected" not in result.stderr, (
        f"unexpected accumulation block on clean evidence\n"
        f"stderr={result.stderr!r}"
    )


def test_b77_pre_hook_accumulation_only_fires_on_step_active(tmp_path: Path):
    """run-complete bypass (#189 B73) bypasses accumulation too — by design.

    Once build.completed is in events.db, run-complete is just bookkeeping.
    Even if TodoWrite UI is bloated, blocking run-complete would orphan the
    run (regression to #189).
    """
    project = _seed_evidence(tmp_path, "sid-3", "rid-3",
                             todo_count=699, contract_count=9,
                             accumulation_suspected=True)
    # Seed build.completed in events.db so B73 bypass kicks in.
    db = project / ".vg" / "events.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, event_type TEXT, payload TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO events (run_id, event_type, payload) VALUES (?, ?, ?)",
        ("rid-3", "build.completed", "{}"),
    )
    conn.commit()
    conn.close()
    result = _run_pre_hook(project, "sid-3", "vg-orchestrator run-complete")
    assert result.returncode == 0, (
        f"run-complete should bypass accumulation gate (B73 #189 contract); "
        f"got rc={result.returncode}\nstderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Bloat threshold math.
# ---------------------------------------------------------------------------


def test_b77_threshold_definition():
    """Threshold = max(1.5*contract, contract+3). Verify formula in hook source."""
    body = POST_HOOK.read_text(encoding="utf-8")
    # The threshold expression in the embedded Python.
    assert "contract_projection_count * 1.5" in body
    assert "contract_projection_count + 3" in body
