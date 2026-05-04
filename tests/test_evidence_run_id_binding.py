"""Task 44b — Rule V1 (evidence run_id binding).

Audit P3: cross-session evidence reuse confirmed in events.db run
70ca6e31 (step.active fired same-second as tasklist_shown, zero
native_tasklist_projected events). The HMAC verifier was checking
contract_sha but NOT run_id, so a prior run's evidence with same
contract_sha could satisfy a fresh run.

This suite locks: evidence ``payload.run_id`` MUST equal the active
run's run_id, else PreToolUse-bash hook BLOCKs. Pre-Task-44b evidence
(no run_id field) is also rejected — additive backward-compat.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")
EMIT_SIGNED = str(REPO_ROOT / "scripts/vg-orchestrator-emit-evidence-signed.py")


def _setup_run(tmp: Path, run_id: str) -> None:
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:test",
        "phase": "test-1.0",
        "checklists": [
            {"id": "g1", "title": "Group One", "items": ["s1"], "status": "pending"},
        ],
    }
    (runs_dir / "tasklist-contract.json").write_text(
        json.dumps(contract, sort_keys=True), encoding="utf-8"
    )

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:test", "phase": "test-1.0"}),
        encoding="utf-8",
    )


def _mk_key(tmp: Path) -> Path:
    key_path = tmp / ".vg" / ".evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(b"K" * 48)
    os.chmod(key_path, 0o600)
    return key_path


def _seed_signed_evidence(tmp: Path, run_id: str, payload: dict) -> Path:
    """Sign + write evidence with arbitrary payload (caller controls run_id)."""
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
    return out


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


def _make_payload(tmp: Path, run_id: str, ev_run_id: str | None,
                  include_run_id: bool = True, depth_valid: bool = True) -> dict:
    contract_path = tmp / ".vg" / "runs" / run_id / "tasklist-contract.json"
    sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    payload: dict = {
        "todowrite_at": "2026-05-04T00:00:00Z",
        "todo_count": 1,
        "contract_sha256": sha,
        "todo_ids": ["g1"],
        "contract_ids": ["g1"],
        "match": True,
        "depth_valid": depth_valid,
        "groups_with_subs_count": 1,
        "flat_groups": [],
    }
    if include_run_id:
        payload["run_id"] = ev_run_id if ev_run_id is not None else run_id
    return payload


def test_evidence_with_matching_run_id_passes(tmp_path: Path) -> None:
    """payload.run_id == current run_id → exit 0."""
    run_id = "run-binding-match"
    _setup_run(tmp_path, run_id)
    _mk_key(tmp_path)
    payload = _make_payload(tmp_path, run_id, ev_run_id=run_id)
    _seed_signed_evidence(tmp_path, run_id, payload)

    cmd = "python3 .claude/scripts/vg-orchestrator step-active s1"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode == 0, (
        f"expected PASS exit 0; got {result.returncode}\nstderr: {result.stderr}"
    )


def test_evidence_with_mismatching_run_id_blocks(tmp_path: Path) -> None:
    """payload.run_id != current run_id → BLOCK with mismatch cause."""
    run_id = "run-binding-current"
    _setup_run(tmp_path, run_id)
    _mk_key(tmp_path)
    # Sign evidence claiming it belongs to a DIFFERENT, prior run.
    payload = _make_payload(tmp_path, run_id, ev_run_id="run-binding-prior")
    _seed_signed_evidence(tmp_path, run_id, payload)

    cmd = "python3 .claude/scripts/vg-orchestrator step-active s1"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode == 2, (
        f"expected BLOCK exit 2; got {result.returncode}: {result.stderr}"
    )
    diag = result.stderr
    assert "run_id" in diag and ("mismatch" in diag.lower() or "cross-session" in diag.lower()), (
        f"diagnostic must mention run_id mismatch / cross-session reuse; got:\n{diag}"
    )


def test_evidence_without_run_id_field_blocks(tmp_path: Path) -> None:
    """Pre-Task-44b evidence with no run_id field → BLOCK with re-projection hint."""
    run_id = "run-binding-legacy"
    _setup_run(tmp_path, run_id)
    _mk_key(tmp_path)
    payload = _make_payload(tmp_path, run_id, ev_run_id=None, include_run_id=False)
    _seed_signed_evidence(tmp_path, run_id, payload)

    cmd = "python3 .claude/scripts/vg-orchestrator step-active s1"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode == 2, (
        f"expected BLOCK exit 2; got {result.returncode}: {result.stderr}"
    )
    diag = result.stderr
    assert "run_id" in diag and ("missing" in diag.lower() or "re-run" in diag.lower()), (
        f"diagnostic must hint re-run TodoWrite + tasklist-projected; got:\n{diag}"
    )
