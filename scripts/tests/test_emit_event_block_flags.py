"""P0 fix 2026-05-03 — emit-event must accept --gate / --cause / --resolution
/ --block-file as first-class flags and merge them into payload_json.

History: hooks (`vg-pre-tool-use-bash.sh:67-69`, `vg-pre-tool-use-write.sh:73-77`,
`vg-pre-tool-use-agent.sh:64-67`) call:

    vg-orchestrator emit-event vg.block.fired --gate <id> --cause <text>

with `|| true`. Pre-fix, argparse rejected unknown args with exit 2 → all
fired/handled events were silently swallowed → 0 vg.block.* rows ever
recorded in events.db across hundreds of runs → Stop hook pairing gate
(`scripts/hooks/vg-stop.sh:20-29`) compared 0=0 = PASS forever, never
catching unpaired blocks. Codex GPT-5.5 cross-AI review surfaced this.

This test pins the new contract: fired/handled flags merge into payload,
exit 0, schema observable. Companion test
test_stop_hook_requires_block_handled_pair.py covers the Stop hook side.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = str(REPO_ROOT / ".claude/scripts/vg-orchestrator")


def _setup_repo(tmp: Path) -> dict:
    """Init a tmp dir as a git repo + run-start a vg:accept run.
    Returns env dict with VG_REPO_ROOT + CLAUDE_SESSION_ID set.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp)
    env["CLAUDE_SESSION_ID"] = "test-sess-emit"
    rs = subprocess.run(
        [sys.executable, ORCH, "run-start", "vg:accept", "99.9.9"],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=15,
    )
    assert rs.returncode == 0, f"run-start failed: {rs.stderr}"
    return env


def _events(repo: Path, event_type: str) -> list[dict]:
    """Return all events of the given type as parsed dicts (payload included)."""
    conn = sqlite3.connect(str(repo / ".vg/events.db"))
    rows = conn.execute(
        "SELECT event_type, outcome, payload_json FROM events "
        "WHERE event_type = ? ORDER BY id",
        (event_type,),
    ).fetchall()
    conn.close()
    return [
        {"event_type": r[0], "outcome": r[1], "payload": json.loads(r[2])}
        for r in rows
    ]


def test_emit_block_fired_with_gate_cause_block_file(tmp_path):
    """Fired event accepts --gate/--cause/--block-file and merges into payload."""
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "vg.block.fired",
         "--actor", "hook",
         "--outcome", "BLOCK",
         "--gate", "PreToolUse-tasklist",
         "--cause", "evidence file missing",
         "--block-file", ".vg/blocks/r1/PreToolUse-tasklist.md"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode == 0, f"emit-event failed: {rc.stderr}"

    fired = _events(tmp_path, "vg.block.fired")
    assert len(fired) == 1
    pl = fired[0]["payload"]
    assert pl["gate"] == "PreToolUse-tasklist"
    assert pl["cause"] == "evidence file missing"
    assert pl["block_file"] == ".vg/blocks/r1/PreToolUse-tasklist.md"
    assert fired[0]["outcome"] == "BLOCK"


def test_emit_block_handled_with_gate_resolution(tmp_path):
    """Handled event accepts --gate + --resolution, merged into payload."""
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "vg.block.handled",
         "--actor", "user",
         "--outcome", "PASS",
         "--gate", "PreToolUse-tasklist",
         "--resolution", "TodoWrite called, evidence regenerated"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode == 0, f"emit-event failed: {rc.stderr}"

    handled = _events(tmp_path, "vg.block.handled")
    assert len(handled) == 1
    pl = handled[0]["payload"]
    assert pl["gate"] == "PreToolUse-tasklist"
    assert pl["resolution"] == "TodoWrite called, evidence regenerated"


def test_explicit_payload_wins_over_flag(tmp_path):
    """When both --payload and --gate are passed, --payload's gate key wins.

    Backwards-compat: callers that already use --payload must not have their
    keys silently overwritten by the new convenience flags.
    """
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "vg.block.fired",
         "--actor", "hook",
         "--outcome", "BLOCK",
         "--payload", json.dumps({"gate": "explicit-from-payload",
                                  "extra": "kept"}),
         "--gate", "from-flag-should-lose"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode == 0, f"emit-event failed: {rc.stderr}"

    fired = _events(tmp_path, "vg.block.fired")
    assert len(fired) == 1
    pl = fired[0]["payload"]
    assert pl["gate"] == "explicit-from-payload"
    assert pl["extra"] == "kept"


def test_no_block_flags_remains_payload_only(tmp_path):
    """Backwards-compat: callers that pass neither flags nor block-related
    --payload still produce an event with empty payload (sans schema marker)."""
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "skill.custom.test_event",
         "--actor", "hook",
         "--outcome", "INFO"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode == 0, f"emit-event failed: {rc.stderr}"

    rows = _events(tmp_path, "skill.custom.test_event")
    assert len(rows) == 1
    pl = rows[0]["payload"]
    # payload should not contain block-event keys when not requested
    assert "gate" not in pl
    assert "cause" not in pl
    assert "resolution" not in pl
    assert "block_file" not in pl


def test_emit_event_with_unknown_flag_still_rejects(tmp_path):
    """Negative path: argparse must still reject genuinely unknown flags so
    typos don't slip through silently. Only the four documented flags
    (--gate/--cause/--resolution/--block-file) are accepted; others fail."""
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "vg.block.fired",
         "--actor", "hook",
         "--outcome", "BLOCK",
         "--bogus-flag", "should-fail"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode != 0, "expected non-zero on unknown flag"
    assert "unrecognized" in rc.stderr.lower() or "error" in rc.stderr.lower()


def test_fail_outcome_is_accepted(tmp_path):
    """vg-verify-claim.py:439 emits with --outcome FAIL (added to choices in
    P0 fix). Pre-fix this argparse-failed silently → block file written but
    no event recorded → pairing gate broken even when emit_block ran."""
    env = _setup_repo(tmp_path)
    rc = subprocess.run(
        [sys.executable, ORCH, "emit-event",
         "vg.block.fired",
         "--actor", "hook",
         "--outcome", "FAIL",
         "--gate", "Stop-stale-run",
         "--cause", "stale run smoke"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path), timeout=15,
    )
    assert rc.returncode == 0, f"emit-event with --outcome FAIL must succeed; got: {rc.stderr}"

    fired = _events(tmp_path, "vg.block.fired")
    assert len(fired) == 1
    assert fired[0]["outcome"] == "FAIL"
