"""Task 44b — Rule V2 + V3 (tasklist depth enforcement).

Audit P4 (smoking gun): vg-post-tool-use-todowrite.sh line ~36 EXPLICITLY
filtered ↳ sub-items, REWARDING flat tasklists. This suite locks the
required behavior:

- V2 (PostToolUse depth check): each contract group MUST have at least
  one ↳-prefixed child in the TodoWrite payload, or the evidence is
  written with ``depth_valid=false``.
- V3 (PreToolUse depth gate): hook BLOCKs ``step-active`` whenever
  ``depth_valid=false`` is present in the evidence file.

Sub-item prefix is ``↳`` (Unicode U+21B3) — tests use this exact char.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")
POST_HOOK = str(REPO_ROOT / "scripts/hooks/vg-post-tool-use-todowrite.sh")
EMIT_SIGNED = str(REPO_ROOT / "scripts/vg-orchestrator-emit-evidence-signed.py")


CONTRACT_FIVE_GROUPS = {
    "schema": "native-tasklist.v2",
    "command": "vg:test",
    "phase": "test-1.0",
    "checklists": [
        {"id": "g1", "title": "Group One", "items": ["s1a", "s1b"], "status": "pending"},
        {"id": "g2", "title": "Group Two", "items": ["s2a"], "status": "pending"},
        {"id": "g3", "title": "Group Three", "items": ["s3a", "s3b"], "status": "pending"},
        {"id": "g4", "title": "Group Four", "items": ["s4a", "s4b"], "status": "pending"},
        {"id": "g5", "title": "Group Five", "items": ["s5a"], "status": "pending"},
    ],
}


def _setup_run(tmp: Path, run_id: str = "run-depth-test") -> str:
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    contract = dict(CONTRACT_FIVE_GROUPS)
    contract["run_id"] = run_id
    (runs_dir / "tasklist-contract.json").write_text(
        json.dumps(contract, sort_keys=True), encoding="utf-8"
    )

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:test", "phase": "test-1.0"}),
        encoding="utf-8",
    )
    return run_id


def _mk_key(tmp: Path) -> Path:
    """Create a stable HMAC evidence key."""
    key_path = tmp / ".vg" / ".evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    # 48-byte base64-like blob (>32 chars) — passes length check.
    key_path.write_bytes(b"A" * 48)
    os.chmod(key_path, 0o600)
    return key_path


def _run_post_hook(tmp: Path, todos: list[dict], session_id: str = "test-session"):
    payload = json.dumps({"tool_input": {"todos": todos}})
    return subprocess.run(
        ["bash", POST_HOOK],
        input=payload,
        env={
            **os.environ,
            "CLAUDE_HOOK_SESSION_ID": session_id,
            "VG_REPO_ROOT": str(tmp),
            "VG_EVIDENCE_KEY_PATH": str(tmp / ".vg" / ".evidence-key"),
        },
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=15,
    )


def _run_pre_hook(tmp: Path, command: str, session_id: str = "test-session"):
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", PRE_HOOK],
        input=payload,
        env={
            **os.environ,
            "CLAUDE_HOOK_SESSION_ID": session_id,
            "VG_REPO_ROOT": str(tmp),
            "VG_EVIDENCE_KEY_PATH": str(tmp / ".vg" / ".evidence-key"),
        },
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=15,
    )


def test_flat_todowrite_writes_depth_invalid_evidence(tmp_path: Path) -> None:
    """5 group-headers, ZERO ↳ sub-items → evidence depth_valid=false."""
    run_id = _setup_run(tmp_path)
    _mk_key(tmp_path)

    todos = [
        {"content": "g1: Group One", "status": "pending", "activeForm": "g1"},
        {"content": "g2: Group Two", "status": "pending", "activeForm": "g2"},
        {"content": "g3: Group Three", "status": "pending", "activeForm": "g3"},
        {"content": "g4: Group Four", "status": "pending", "activeForm": "g4"},
        {"content": "g5: Group Five", "status": "pending", "activeForm": "g5"},
    ]
    result = _run_post_hook(tmp_path, todos)
    assert result.returncode == 0, f"post hook failed: {result.stderr}"

    ev_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    assert ev_path.exists(), "post hook did not write evidence file"
    data = json.loads(ev_path.read_text())
    payload = data.get("payload", {})
    assert payload.get("depth_valid") is False, (
        f"flat projection MUST set depth_valid=false; got: {payload}"
    )
    flat_groups = payload.get("flat_groups", [])
    assert len(flat_groups) == 5, (
        f"expected all 5 groups flagged as flat; got: {flat_groups}"
    )


def test_2layer_todowrite_writes_depth_valid_evidence(tmp_path: Path) -> None:
    """5 groups + ≥2 sub-items each → evidence depth_valid=true."""
    run_id = _setup_run(tmp_path)
    _mk_key(tmp_path)

    todos = []
    for cl in CONTRACT_FIVE_GROUPS["checklists"]:
        todos.append({
            "content": f"{cl['id']}: {cl['title']}",
            "status": "pending",
            "activeForm": cl["id"],
        })
        # at least 2 ↳ sub-items per group (use stable padding so groups
        # with only 1 contract item still get 2 children in the projection)
        for i, sub in enumerate(cl["items"] + ["pad_extra_a", "pad_extra_b"][: max(0, 2 - len(cl["items"]))]):
            todos.append({
                "content": f"  ↳ {sub}: detail {i}",
                "status": "pending",
                "activeForm": sub,
            })

    result = _run_post_hook(tmp_path, todos)
    assert result.returncode == 0, f"post hook failed: {result.stderr}"

    ev_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    assert ev_path.exists()
    data = json.loads(ev_path.read_text())
    payload = data.get("payload", {})
    assert payload.get("depth_valid") is True, (
        f"2-layer projection MUST set depth_valid=true; got: {payload}"
    )
    assert payload.get("groups_with_subs_count") == 5, (
        f"expected 5 groups_with_subs_count; got: {payload}"
    )
    assert payload.get("flat_groups", []) == [], (
        f"flat_groups must be empty for valid 2-layer projection; got: {payload}"
    )


def _seed_evidence(tmp: Path, run_id: str, depth_valid: bool) -> None:
    """Manually emit a signed evidence file with chosen depth_valid value.

    Uses the canonical signer so HMAC verifies, then PreToolUse hook can
    proceed past signature_valid into the depth check.
    """
    contract_path = tmp / ".vg" / "runs" / run_id / "tasklist-contract.json"
    import hashlib
    payload = {
        "run_id": run_id,
        "todowrite_at": "2026-05-04T00:00:00Z",
        "todo_count": 5,
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "todo_ids": ["g1", "g2", "g3", "g4", "g5"],
        "contract_ids": ["g1", "g2", "g3", "g4", "g5"],
        "match": True,
        "depth_valid": depth_valid,
        "groups_with_subs_count": 5 if depth_valid else 0,
        "flat_groups": [] if depth_valid else ["g1", "g2", "g3", "g4", "g5"],
    }
    out = tmp / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    subprocess.run(
        ["python3", EMIT_SIGNED, "--out", str(out), "--payload", json.dumps(payload)],
        env={
            **os.environ,
            "VG_EVIDENCE_KEY_PATH": str(tmp / ".vg" / ".evidence-key"),
        },
        check=True,
        capture_output=True,
    )


def test_pretooluse_blocks_on_depth_invalid_evidence(tmp_path: Path) -> None:
    """Evidence with depth_valid=false → step-active BLOCKED with depth diagnostic."""
    run_id = _setup_run(tmp_path)
    _mk_key(tmp_path)
    _seed_evidence(tmp_path, run_id, depth_valid=False)

    cmd = "python3 .claude/scripts/vg-orchestrator step-active phase1_code_scan"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode == 2, (
        f"expected BLOCK exit 2, got {result.returncode}: {result.stderr}"
    )
    assert "depth" in result.stderr.lower() or "flat" in result.stderr.lower() or "2-layer" in result.stderr, (
        f"diagnostic must mention depth/flat/2-layer; got:\n{result.stderr}"
    )


def test_pretooluse_passes_on_depth_valid_evidence(tmp_path: Path) -> None:
    """Evidence with depth_valid=true → step-active passes the depth check."""
    run_id = _setup_run(tmp_path)
    _mk_key(tmp_path)
    _seed_evidence(tmp_path, run_id, depth_valid=True)

    cmd = "python3 .claude/scripts/vg-orchestrator step-active phase1_code_scan"
    result = _run_pre_hook(tmp_path, cmd)
    # pass — no depth diagnostic. Other checks (run_id binding, block.handled) may
    # still succeed because we're using a fresh evidence/run.
    assert result.returncode == 0, (
        f"expected PASS exit 0 for depth_valid=true; got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
