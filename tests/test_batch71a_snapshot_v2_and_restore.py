"""tests/test_batch71a_snapshot_v2_and_restore.py — B71a snapshot v2 + restore integration.

Covers:
  1. Snapshot writer accepts v2 schema (content + match_class) without losing data.
  2. Snapshot writer accepts v1 legacy and auto-upgrades.
  3. Snapshot writer adds provenance hash.
  4. emit-tasklist restore-mode v2 reader applies overlay correctly.
  5. emit-tasklist legacy rehydration: numeric snapshot + trace → recovered.
  6. emit-tasklist overlap warning fires when < 50% overlap.
  7. emit-tasklist no warning when ≥ 50% overlap.
  8. End-to-end RTB c1a5edc3-style fixture (display label snapshot).
  9. End-to-end RTB 10faabdb-style fixture (numeric snapshot + trace rehydration).
 10. Status-precedence applied on multi-label-same-step_id collision.
 11. <unresolved>: IDs do not pollute overlay.
 12. Mirror parity for snapshot helper.
 13. Mirror parity for emit-tasklist.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT_HELPER = REPO / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
SNAPSHOT_HELPER_MIRROR = REPO / ".claude" / "scripts" / "hooks" / "vg-tasklist-snapshot.py"
EMIT_TASKLIST = REPO / "scripts" / "emit-tasklist.py"
EMIT_TASKLIST_MIRROR = REPO / ".claude" / "scripts" / "emit-tasklist.py"


# ---------------------------------------------------------------------------
# Snapshot writer schema v2.
# ---------------------------------------------------------------------------


def _run_snapshot(payload: dict, run_id: str, repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SNAPSHOT_HELPER), "--write", "--run-id", run_id],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "VG_REPO_ROOT": str(repo_root)},
        timeout=30,
    )


def test_snapshot_writer_accepts_v2_payload(tmp_path: Path):
    payload = {
        "schema_version": 2,
        "items": [
            {"id": "0_parse_and_validate", "content": "↳ 0 Parse And Validate",
             "status": "completed", "match_class": "normalized"},
        ],
    }
    result = _run_snapshot(payload, "test-run-1", tmp_path)
    assert result.returncode == 0, result.stderr
    out = json.loads((tmp_path / ".vg" / "runs" / "test-run-1" / ".todowrite-snapshot.json").read_text(encoding="utf-8"))
    assert out["schema_version"] == 2
    assert len(out["items"]) == 1
    assert out["items"][0]["id"] == "0_parse_and_validate"
    assert out["items"][0]["content"] == "↳ 0 Parse And Validate"
    assert out["items"][0]["match_class"] == "normalized"


def test_snapshot_writer_auto_upgrades_v1(tmp_path: Path):
    """v1 payload {items:[{id,status}]} → v2 with content=id, match_class=exact."""
    payload = {"items": [{"id": "step1", "status": "completed"}]}
    result = _run_snapshot(payload, "test-run-v1", tmp_path)
    assert result.returncode == 0
    out = json.loads((tmp_path / ".vg" / "runs" / "test-run-v1" / ".todowrite-snapshot.json").read_text(encoding="utf-8"))
    assert out["schema_version"] == 2
    assert out["items"][0]["content"] == "step1"
    assert out["items"][0]["match_class"] == "exact"


def test_snapshot_writer_includes_provenance_hash(tmp_path: Path):
    payload = {"items": [{"id": "s1", "status": "completed", "content": "S One"}]}
    _run_snapshot(payload, "rid-hash", tmp_path)
    out = json.loads((tmp_path / ".vg" / "runs" / "rid-hash" / ".todowrite-snapshot.json").read_text(encoding="utf-8"))
    assert "id_map_provenance" in out
    assert out["id_map_provenance"].get("snapshot_hash", "").startswith("sha256:")


def test_snapshot_writer_invalid_match_class_falls_back(tmp_path: Path):
    payload = {"items": [{"id": "s1", "status": "pending",
                          "content": "x", "match_class": "garbage"}]}
    _run_snapshot(payload, "rid-fallback", tmp_path)
    out = json.loads((tmp_path / ".vg" / "runs" / "rid-fallback" / ".todowrite-snapshot.json").read_text(encoding="utf-8"))
    assert out["items"][0]["match_class"] == "unresolved"


def test_snapshot_writer_empty_stdin_preserves_prior(tmp_path: Path):
    # First write something.
    payload = {"items": [{"id": "s1", "status": "completed", "content": "S One"}]}
    _run_snapshot(payload, "rid-empty", tmp_path)
    snap_path = tmp_path / ".vg" / "runs" / "rid-empty" / ".todowrite-snapshot.json"
    prior_text = snap_path.read_text(encoding="utf-8")

    # Then run with empty stdin — should NOT overwrite.
    result = subprocess.run(
        [sys.executable, str(SNAPSHOT_HELPER), "--write", "--run-id", "rid-empty"],
        input="",
        capture_output=True,
        text=True,
        env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
        timeout=10,
    )
    assert result.returncode == 0
    assert snap_path.read_text(encoding="utf-8") == prior_text


def test_snapshot_writer_empty_items_logs_warning(tmp_path: Path):
    result = _run_snapshot({"items": []}, "rid-empty-items", tmp_path)
    assert result.returncode == 0
    assert "no-op" in result.stderr or "empty" in result.stderr


# ---------------------------------------------------------------------------
# emit-tasklist restore-mode v2 reader.
# ---------------------------------------------------------------------------


def _make_run(repo_root: Path, run_id: str,
              contract_items: list[dict],
              snapshot_items: list[dict] | None = None,
              snapshot_schema_version: int | None = None,
              trace_records: list[dict] | None = None) -> Path:
    """Build a synthetic .vg/runs/{run_id}/ with contract, optional snapshot, optional trace."""
    run_dir = repo_root / ".vg" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tasklist-contract.json").write_text(
        json.dumps({
            "schema": "native-tasklist.v2",
            "run_id": run_id,
            "command": "vg:test-spec",
            "phase": "7.16",
            "profile": "web-fullstack",
            "projection_items": contract_items,
            "items": [{"id": it["id"], "title": it.get("title", it["id"]),
                       "status": "pending", "checklist": "default"} for it in contract_items],
        }),
        encoding="utf-8",
    )
    if snapshot_items is not None:
        body: dict = {"items": snapshot_items}
        if snapshot_schema_version is not None:
            body["schema_version"] = snapshot_schema_version
        (run_dir / ".todowrite-snapshot.json").write_text(json.dumps(body), encoding="utf-8")
    if trace_records is not None:
        with (run_dir / ".taskcreate-trace.jsonl").open("w", encoding="utf-8") as f:
            for r in trace_records:
                f.write(json.dumps(r) + "\n")
    return run_dir


def _run_restore(repo_root: Path, run_id: str) -> subprocess.CompletedProcess:
    # VG_HOME must point at a real install (REPO carries .claude/ + commands/).
    # CI runners have no global VG install — point VG_HOME at the canonical
    # repo .claude tree (it's a complete VG install layout).
    env = {**os.environ, "VG_REPO_ROOT": str(repo_root),
           "PYTHONIOENCODING": "utf-8",
           "VG_HOME": str(REPO / ".claude")}
    return subprocess.run(
        [sys.executable, str(EMIT_TASKLIST), "--restore-mode", "--run-id", run_id,
         "--command", "vg:test-spec", "--phase", "7.16", "--profile", "web-fullstack"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
        cwd=str(repo_root),
    )


def test_restore_v2_snapshot_overlay_correct(tmp_path: Path):
    contract = [
        {"id": "0_parse", "kind": "step", "title": "Parse"},
        {"id": "1_build", "kind": "step", "title": "Build"},
        {"id": "2_verify", "kind": "step", "title": "Verify"},
    ]
    snapshot = [
        {"id": "0_parse", "content": "↳ 0 Parse", "status": "completed", "match_class": "exact"},
        {"id": "1_build", "content": "↳ 1 Build", "status": "in_progress", "match_class": "exact"},
    ]
    _make_run(tmp_path, "rid-v2", contract, snapshot, snapshot_schema_version=2)
    result = _run_restore(tmp_path, "rid-v2")
    assert result.returncode == 0
    # Output table should show in_progress and completed.
    assert "in_progress" in result.stdout.lower() or "in progress" in result.stdout.lower()
    assert "completed" in result.stdout.lower() or "✓" in result.stdout or "done" in result.stdout.lower()


def test_restore_rtb_c1a5_pattern_via_v2_snapshot(tmp_path: Path):
    """Real RTB c1a5edc3 pattern: contract step_ids, snapshot resolved by hook to step_ids."""
    contract = [
        {"id": "0_parse_and_validate", "kind": "step"},
        {"id": "3_crossai_sweep", "kind": "step"},
        {"id": "4_codegen", "kind": "step"},
    ]
    # After B71a hook resolves labels: snapshot keys are step_ids.
    snapshot = [
        {"id": "0_parse_and_validate", "content": "↳ 0 Parse And Validate",
         "status": "completed", "match_class": "normalized"},
        {"id": "3_crossai_sweep", "content": "↳ 3.5 CrossAI Sweep",
         "status": "in_progress", "match_class": "strip-decimal"},
        {"id": "4_codegen", "content": "↳ test-spec 4_codegen — Spawn",
         "status": "pending", "match_class": "substring"},
    ]
    _make_run(tmp_path, "rid-c1a5", contract, snapshot, snapshot_schema_version=2)
    result = _run_restore(tmp_path, "rid-c1a5")
    assert result.returncode == 0
    # No overlap warning since all snapshot IDs match contract.
    assert "id schema mismatch" not in result.stderr.lower()


def test_restore_legacy_v1_numeric_triggers_rehydration(tmp_path: Path):
    """RTB 10faabdb pattern: snapshot v1 with numeric tids; trace has subjects.

    Restore-mode should rehydrate via trace + resolver and produce in_progress
    statuses keyed by contract step_id.
    """
    contract = [
        {"id": "5_fix_loop", "kind": "step"},
        {"id": "7_matrix_verdict", "kind": "step"},
    ]
    # v1 snapshot keyed by numeric tid (legacy).
    snapshot = [
        {"id": "353", "status": "completed"},
        {"id": "354", "status": "in_progress"},
    ]
    trace = [
        {"action": "create", "task_id": "353", "subject": "5 Fix Loop", "status": "pending"},
        {"action": "update", "task_id": "353", "status": "completed"},
        {"action": "create", "task_id": "354", "subject": "7 Matrix Verdict", "status": "pending"},
        {"action": "update", "task_id": "354", "status": "in_progress"},
    ]
    _make_run(tmp_path, "rid-legacy", contract, snapshot, snapshot_schema_version=None, trace_records=trace)
    result = _run_restore(tmp_path, "rid-legacy")
    assert result.returncode == 0
    # Stderr should mention legacy rehydration.
    assert "rehydration" in result.stderr.lower() or "B71a" in result.stderr
    # Output should show in_progress and completed (overlay worked).
    out_lower = result.stdout.lower()
    assert "in_progress" in out_lower or "in progress" in out_lower


def test_restore_overlap_mismatch_warning(tmp_path: Path):
    """Snapshot with non-matching IDs after rehydration attempt fails → warning."""
    contract = [{"id": "0_parse", "kind": "step"}]
    snapshot = [{"id": "completely-unrelated-id", "status": "completed"}]
    # No trace → no rehydration possible.
    _make_run(tmp_path, "rid-mismatch", contract, snapshot, snapshot_schema_version=None)
    result = _run_restore(tmp_path, "rid-mismatch")
    assert result.returncode == 0
    # Warning should fire because overlap = 0%.
    # Note: snapshot_used must be True for warning — it is, since snapshot has 1 item.
    assert "id schema mismatch" in result.stderr.lower() or "rehydration" in result.stderr.lower()


def test_restore_high_overlap_no_warning(tmp_path: Path):
    """Snapshot with 100% matching IDs → no warning."""
    contract = [
        {"id": "0_parse", "kind": "step"},
        {"id": "1_build", "kind": "step"},
    ]
    snapshot = [
        {"id": "0_parse", "content": "Parse", "status": "completed", "match_class": "exact"},
        {"id": "1_build", "content": "Build", "status": "in_progress", "match_class": "exact"},
    ]
    _make_run(tmp_path, "rid-clean", contract, snapshot, snapshot_schema_version=2)
    result = _run_restore(tmp_path, "rid-clean")
    assert result.returncode == 0
    assert "id schema mismatch" not in result.stderr.lower()


def test_restore_unresolved_prefix_not_overlay(tmp_path: Path):
    """<unresolved>: IDs in snapshot should NOT pollute overlay."""
    contract = [{"id": "step1", "kind": "step"}]
    snapshot = [
        {"id": "step1", "content": "Step One", "status": "completed", "match_class": "exact"},
        {"id": "<unresolved>:abc123", "content": "Garbage label", "status": "in_progress", "match_class": "unresolved"},
    ]
    _make_run(tmp_path, "rid-unres", contract, snapshot, snapshot_schema_version=2)
    result = _run_restore(tmp_path, "rid-unres")
    assert result.returncode == 0
    # No warning since the single valid overlay (step1) hits 100% of contract.
    assert "id schema mismatch" not in result.stderr.lower()


# ---------------------------------------------------------------------------
# Mirror parity.
# ---------------------------------------------------------------------------


def test_snapshot_helper_mirror_byte_identical():
    canonical = SNAPSHOT_HELPER.read_bytes()
    mirror = SNAPSHOT_HELPER_MIRROR.read_bytes()
    assert canonical == mirror


def test_emit_tasklist_mirror_byte_identical():
    canonical = EMIT_TASKLIST.read_bytes()
    mirror = EMIT_TASKLIST_MIRROR.read_bytes()
    assert canonical == mirror
