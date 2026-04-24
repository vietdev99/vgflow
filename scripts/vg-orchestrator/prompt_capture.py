"""
prompt_capture.py — Phase P of v2.5.2 hardening.

Problem closed:
  v2.5.1 bootstrap layer checked `bootstrap.loaded` event existed in log =
  paperwork check. AI could emit event without actually injecting the
  active rule into executor prompt. Codex review of v2.5.1 plan flagged
  this as the "validators still soft" finding.

This module captures the *actual* prompt text sent to each executor
subagent before spawn. Downstream validators (verify-bootstrap-carryforward,
verify-executor-context-scope) grep the captured text for:
  - Active LEARN-RULES.md rule text (should appear verbatim)
  - Declared <context-refs> D-XX IDs (should be present)
  - No D-XX IDs beyond those declared (no context leak)

Storage:
  .vg/runs/<run_id>/executor-prompts/task-<seq>.prompt.txt
  .vg/runs/<run_id>/executor-prompts/manifest.json  (sha256 per prompt)

Retention: 30 days default (orchestrator cron sweeps older). Dedup via
sha256 — identical prompts across runs share one storage entry via
`.vg/prompts/dedup/<sha256>.txt` symlink-or-copy (platform-dependent).

Usage:
  from vg_orchestrator.prompt_capture import capture_prompt, read_prompt

  record_id = capture_prompt(run_id, task_seq=7, agent_type="general-purpose",
                              prompt_text="...", context_refs=["D-01","D-02"])

  text, meta = read_prompt(run_id, task_seq=7)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    data = text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _run_prompt_dir(run_id: str, repo_root: Path | None = None) -> Path:
    root = repo_root or Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())
    return root / ".vg" / "runs" / run_id / "executor-prompts"


def _manifest_path(run_id: str, repo_root: Path | None = None) -> Path:
    return _run_prompt_dir(run_id, repo_root) / "manifest.json"


def _load_manifest(run_id: str, repo_root: Path | None = None) -> dict:
    path = _manifest_path(run_id, repo_root)
    if not path.exists():
        return {"run_id": run_id, "entries": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"run_id": run_id, "entries": []}


def _save_manifest(manifest: dict, repo_root: Path | None = None) -> None:
    run_id = manifest["run_id"]
    path = _manifest_path(run_id, repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def capture_prompt(
    run_id: str,
    task_seq: int,
    agent_type: str,
    prompt_text: str,
    context_refs: list[str] | None = None,
    meta: dict | None = None,
    repo_root: Path | None = None,
) -> dict:
    """
    Persist the full prompt text sent to an executor subagent.

    Returns the manifest entry dict on success:
        {
          "task_seq": N,
          "agent_type": "general-purpose",
          "file": "task-N.prompt.txt",
          "sha256": "<hash>",
          "size_bytes": N,
          "captured_at": "<iso>",
          "context_refs": [...],
          "meta": {...}
        }

    Raises OSError on storage failure (caller should degrade gracefully;
    capture failure should not crash executor spawn).
    """
    if not run_id or not isinstance(run_id, str):
        raise ValueError("run_id must be non-empty string")
    if task_seq < 0:
        raise ValueError("task_seq must be non-negative")
    if not isinstance(prompt_text, str):
        raise TypeError("prompt_text must be str")

    prompt_dir = _run_prompt_dir(run_id, repo_root)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"task-{task_seq:03d}.prompt.txt"
    file_path = prompt_dir / file_name
    file_path.write_text(prompt_text, encoding="utf-8", newline="\n")

    entry = {
        "task_seq": task_seq,
        "agent_type": agent_type,
        "file": file_name,
        "sha256": _sha256(prompt_text),
        "size_bytes": len(prompt_text.encode("utf-8")),
        "captured_at": _now_iso(),
        "context_refs": list(context_refs or []),
        "meta": dict(meta or {}),
    }

    manifest = _load_manifest(run_id, repo_root)
    # Replace entry if same task_seq already exists (retry case).
    manifest["entries"] = [e for e in manifest["entries"]
                           if e.get("task_seq") != task_seq]
    manifest["entries"].append(entry)
    manifest["entries"].sort(key=lambda e: e.get("task_seq", 0))
    manifest["updated_at"] = _now_iso()
    _save_manifest(manifest, repo_root)

    return entry


def read_prompt(
    run_id: str,
    task_seq: int,
    repo_root: Path | None = None,
) -> tuple[str, dict] | None:
    """
    Read back prompt text + its manifest entry. Returns None if not found.
    """
    manifest = _load_manifest(run_id, repo_root)
    entry = next((e for e in manifest["entries"]
                  if e.get("task_seq") == task_seq), None)
    if entry is None:
        return None

    file_path = _run_prompt_dir(run_id, repo_root) / entry["file"]
    if not file_path.exists():
        return None

    text = file_path.read_text(encoding="utf-8")

    # Verify hash integrity — tampered file returns None to signal drift
    if _sha256(text) != entry.get("sha256"):
        return None

    return text, entry


def list_prompts(run_id: str, repo_root: Path | None = None) -> list[dict]:
    """Return manifest entries for this run (sorted by task_seq)."""
    return list(_load_manifest(run_id, repo_root)["entries"])


def verify_prompt_integrity(
    run_id: str, repo_root: Path | None = None,
) -> dict:
    """
    Walk all captured prompts, re-hash content, compare to manifest sha256.
    Returns {verified: N, drift: [{task_seq, reason}], missing_files: [...]}.
    """
    manifest = _load_manifest(run_id, repo_root)
    verified = 0
    drift: list[dict] = []
    missing: list[int] = []

    for entry in manifest["entries"]:
        file_path = _run_prompt_dir(run_id, repo_root) / entry["file"]
        if not file_path.exists():
            missing.append(entry["task_seq"])
            continue
        actual = _sha256(file_path.read_text(encoding="utf-8"))
        if actual != entry.get("sha256"):
            drift.append({
                "task_seq": entry["task_seq"],
                "reason": "hash mismatch — prompt tampered or recorded with drift",
                "expected": entry.get("sha256"),
                "actual": actual,
            })
        else:
            verified += 1

    return {
        "run_id": run_id,
        "verified": verified,
        "drift": drift,
        "missing_files": missing,
        "total_entries": len(manifest["entries"]),
    }


def sweep_old_runs(
    retention_days: int = 30,
    repo_root: Path | None = None,
) -> dict:
    """
    Delete executor-prompts directories for runs older than retention_days.
    Returns {swept: [run_id], kept: [run_id], errors: [...]}.
    """
    root = repo_root or Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())
    runs_dir = root / ".vg" / "runs"
    if not runs_dir.exists():
        return {"swept": [], "kept": [], "errors": []}

    cutoff = time.time() - (retention_days * 86400)
    swept: list[str] = []
    kept: list[str] = []
    errors: list[dict] = []

    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        prompt_dir = run_dir / "executor-prompts"
        if not prompt_dir.exists():
            continue
        try:
            mtime = prompt_dir.stat().st_mtime
            if mtime < cutoff:
                import shutil
                shutil.rmtree(prompt_dir)
                swept.append(run_dir.name)
            else:
                kept.append(run_dir.name)
        except OSError as e:
            errors.append({"run_id": run_dir.name, "error": str(e)})

    return {"swept": swept, "kept": kept, "errors": errors}
