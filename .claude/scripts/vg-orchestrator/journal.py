"""
State mutation journal for rollback on failure — Phase O of v2.5.2.

Every mutation that should be reversible on run failure is logged here.
A failed run can invoke rollback_run() to replay the journal in reverse
and restore prior state (file contents or config values).

Storage:
  .vg/runs/<run_id>/journal.jsonl — append-only JSONL, one mutation per line
  Each line: {
    "journal_id": int,           # monotonic per-run
    "ts": "2026-04-24T...Z",
    "run_id": "<uuid>",
    "action": "file_write|file_delete|config_change|state_transition|manifest_append",
    "target_path": "relative/path",
    "before_hash": "<sha256>|null",
    "after_hash": "<sha256>",
    "before_content_b64": "<optional inline backup for small files>",
    "meta": {...}
  }

Rollback semantics:
  file_write   → restore before_content_b64 if present, else delete if before_hash=null
  file_delete  → restore before_content_b64 (required)
  config_change → meta.key + meta.before_value restored in target_path JSON/YAML
  state_transition → noop for MVP (logged for audit only)
  manifest_append → noop (manifest is additive; rollback handled by deleting the run dir)

API:
  journal_entry(run_id, action, target_path, before_hash, after_hash, meta) -> int
  rollback_run(run_id, dry_run=False) -> {rolled_back, skipped, failed}
  query_journal(run_id, action_prefix) -> list[dict]
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from _repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)

VALID_ACTIONS = {
    "file_write", "file_delete", "config_change",
    "state_transition", "manifest_append",
}

# Files larger than this are NOT inlined in journal (backup path via copy-to-
# tmp could be added later; for MVP we just skip content restore and log warn).
MAX_INLINE_BYTES = 1_048_576  # 1 MiB


def _journal_path(run_id: str) -> Path:
    return REPO_ROOT / ".vg" / "runs" / run_id / "journal.jsonl"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _next_journal_id(run_id: str) -> int:
    path = _journal_path(run_id)
    if not path.exists():
        return 1
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for _ in f:
                count += 1
    except OSError:
        return 1
    return count + 1


def _capture_before_content(target_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (before_hash, before_content_b64). Both None if file absent.
    before_content_b64 omitted for files larger than MAX_INLINE_BYTES."""
    if not target_path.exists():
        return None, None
    try:
        data = target_path.read_bytes()
    except OSError:
        return None, None
    before_hash = _sha256(data)
    if len(data) > MAX_INLINE_BYTES:
        return before_hash, None
    return before_hash, base64.b64encode(data).decode("ascii")


def journal_entry(run_id: str, action: str, target_path: str,
                  before_hash: Optional[str], after_hash: str,
                  meta: Optional[dict] = None) -> int:
    """Append a journal entry. Returns the assigned journal_id."""
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"invalid action {action!r}; must be one of {sorted(VALID_ACTIONS)}"
        )
    path = _journal_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    journal_id = _next_journal_id(run_id)
    entry = {
        "journal_id": journal_id,
        "ts": _utc_now(),
        "run_id": run_id,
        "action": action,
        "target_path": target_path,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "meta": meta or {},
    }
    # For file_write / file_delete: auto-capture before content if
    # meta doesn't already include it.
    meta_dict = entry["meta"]
    if action in ("file_write", "file_delete") and \
            "before_content_b64" not in meta_dict:
        target_abs = Path(target_path)
        if not target_abs.is_absolute():
            target_abs = REPO_ROOT / target_abs
        cap_hash, cap_b64 = _capture_before_content(target_abs)
        if cap_b64 is not None:
            meta_dict["before_content_b64"] = cap_b64
        if before_hash is None and cap_hash is not None:
            entry["before_hash"] = cap_hash

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return journal_id


def query_journal(run_id: Optional[str] = None,
                  action_prefix: Optional[str] = None) -> list[dict]:
    """Read journal entries for a run, optionally filtered by action prefix."""
    if run_id is None:
        return []
    path = _journal_path(run_id)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action_prefix and not entry.get("action", "").startswith(action_prefix):
                continue
            out.append(entry)
    return out


def _resolve_target(target_path: str) -> Path:
    p = Path(target_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


def _rollback_file_write(entry: dict, dry_run: bool) -> tuple[bool, str]:
    """Restore before state for a file_write entry."""
    target = _resolve_target(entry["target_path"])
    before_hash = entry.get("before_hash")
    meta = entry.get("meta", {})
    before_b64 = meta.get("before_content_b64")

    if before_hash is None:
        # File was newly created — rollback = delete
        if dry_run:
            return True, "would delete (newly created)"
        if target.exists():
            try:
                target.unlink()
            except OSError as e:
                return False, f"unlink failed: {e}"
        return True, "deleted (was newly created)"

    # File pre-existed — restore content
    if before_b64 is None:
        return False, (
            f"before_content_b64 missing — cannot restore "
            f"(file too large or pre-dates capture)"
        )
    try:
        data = base64.b64decode(before_b64)
    except (ValueError, TypeError) as e:
        return False, f"b64 decode failed: {e}"
    # Verify before_hash matches
    if _sha256(data) != before_hash:
        return False, "inlined content hash mismatch — journal corrupt"
    if dry_run:
        return True, f"would restore {len(data)} bytes"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as e:
        return False, f"write failed: {e}"
    return True, f"restored {len(data)} bytes"


def _rollback_file_delete(entry: dict, dry_run: bool) -> tuple[bool, str]:
    """Restore a file that was deleted during the run."""
    target = _resolve_target(entry["target_path"])
    meta = entry.get("meta", {})
    before_b64 = meta.get("before_content_b64")
    if before_b64 is None:
        return False, "before_content_b64 missing — cannot restore deleted file"
    try:
        data = base64.b64decode(before_b64)
    except (ValueError, TypeError) as e:
        return False, f"b64 decode failed: {e}"
    if dry_run:
        return True, f"would restore {len(data)} bytes"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as e:
        return False, f"write failed: {e}"
    return True, f"restored {len(data)} bytes"


def _rollback_config_change(entry: dict, dry_run: bool) -> tuple[bool, str]:
    """Revert a single config key change. Supports JSON files only for MVP."""
    target = _resolve_target(entry["target_path"])
    meta = entry.get("meta", {})
    key = meta.get("key")
    before_value = meta.get("before_value")
    if key is None:
        return False, "config_change meta.key missing"
    if not target.exists():
        return False, f"config target {target} missing"
    if target.suffix.lower() != ".json":
        return False, "config_change rollback supports .json only in MVP"
    try:
        conf = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"config read failed: {e}"
    # Support dotted key path
    parts = key.split(".")
    node = conf
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            return False, f"config key path {key!r} not found"
        node = node[p]
    if not isinstance(node, dict):
        return False, f"config key path {key!r} parent not dict"
    if before_value is None:
        # Key didn't exist before — remove it
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = before_value
    if dry_run:
        return True, f"would revert key {key}"
    try:
        target.write_text(
            json.dumps(conf, indent=2, sort_keys=True), encoding="utf-8",
        )
    except OSError as e:
        return False, f"config write failed: {e}"
    return True, f"reverted key {key}"


def rollback_run(run_id: str, dry_run: bool = False) -> dict:
    """Replay journal in reverse. Returns {rolled_back, skipped, failed}.

    skipped = entries whose action is intentionally non-reversible
              (state_transition, manifest_append)
    failed  = entries that errored during rollback
    rolled_back = entries successfully reverted
    """
    entries = query_journal(run_id)
    result = {
        "run_id": run_id,
        "dry_run": dry_run,
        "rolled_back": 0,
        "skipped": 0,
        "failed": [],
    }
    # Reverse order
    for entry in reversed(entries):
        action = entry.get("action", "")
        if action == "file_write":
            ok, msg = _rollback_file_write(entry, dry_run)
        elif action == "file_delete":
            ok, msg = _rollback_file_delete(entry, dry_run)
        elif action == "config_change":
            ok, msg = _rollback_config_change(entry, dry_run)
        elif action in ("state_transition", "manifest_append"):
            result["skipped"] += 1
            continue
        else:
            result["failed"].append({
                "journal_id": entry.get("journal_id"),
                "action": action,
                "reason": f"unknown action {action!r}",
            })
            continue
        if ok:
            result["rolled_back"] += 1
        else:
            result["failed"].append({
                "journal_id": entry.get("journal_id"),
                "action": action,
                "reason": msg,
            })
    return result
