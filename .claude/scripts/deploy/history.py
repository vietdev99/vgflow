"""v2.82.0 Stage 6.3 — `.vg/deploy/history.jsonl` append-only event log.

Append-only history of all deploy events (started / completed / failed /
rollback). One JSON object per line. Used for:
  - audit trail (who deployed what when, which phase context)
  - rollback target derivation when STATE.json's `rollback_target` is unset
  - deploy.completed telemetry replay during /vg:roam restart

Rotation: when `history.jsonl` exceeds 10 MB (default), the file is moved
to `history-{date}.jsonl.gz` and a fresh empty file replaces it. Caller
is responsible for compression (we just rename); compression deferred to
a separate utility so `append()` stays sync + lock-free.

Usage:
    from deploy.history import append_event
    append_event(project_root, {
        "event": "deploy.completed",
        "env": "prod",
        "sha": "abc123",
        "phase_context": "6",
        "duration_sec": 42,
    })
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


HISTORY_FILE = "history.jsonl"
ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB


def history_path(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".vg" / "deploy" / HISTORY_FILE


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_event(
    project_root: Path | str,
    payload: dict[str, Any],
    *,
    rotate_bytes: int = ROTATE_BYTES,
) -> Path:
    """Append a single event line to `.vg/deploy/history.jsonl`.

    Adds `ts` (ISO 8601 UTC) automatically when caller omits it.

    Rotates when file exceeds `rotate_bytes` (default 10 MB):
    moves `history.jsonl` → `history-YYYYMMDDTHHMMSSZ.jsonl` (uncompressed;
    a separate utility compresses old segments offline).

    Returns the absolute history path after write.
    """
    if not isinstance(payload, dict):
        raise TypeError(
            f"deploy history payload must be dict; got {type(payload).__name__}"
        )
    path = history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Rotate before write so single-line entries don't span pre/post boundary.
    if path.exists():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > rotate_bytes:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            rotated = path.parent / f"history-{stamp}.jsonl"
            os.replace(path, rotated)

    enriched = {"ts": payload.get("ts") or _now_iso(), **payload}
    line = json.dumps(enriched, separators=(",", ":"), sort_keys=False) + "\n"
    # Append-only mode; on POSIX writes < PIPE_BUF are atomic per line.
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return path


def read_events(
    project_root: Path | str,
    *,
    env: str | None = None,
    event: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read events from history.jsonl with optional filters.

    Args:
        env: filter by `env` field.
        event: filter by `event` field.
        since: ISO 8601 string; return events with ts >= since.
        limit: max events returned (most recent first).

    Returns list of decoded event dicts. Lines that fail JSON parse are
    skipped silently — corrupt history shouldn't block rollback derivation.
    """
    path = history_path(project_root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if env and ev.get("env") != env:
                continue
            if event and ev.get("event") != event:
                continue
            if since and (ev.get("ts") or "") < since:
                continue
            out.append(ev)
    if limit is not None:
        out = out[-limit:]
    return out


def latest_successful_sha(
    project_root: Path | str,
    env: str,
    *,
    before: str | None = None,
) -> str | None:
    """Return the SHA from the most-recent `deploy.completed` event for `env`.

    Used as fallback when STATE.json's `previous_sha` is missing.

    Args:
        before: ISO timestamp; return latest completed strictly before this.
          Useful for deriving the rollback target when STATE.json's current
          entry IS the bad version.
    """
    events = read_events(project_root, env=env, event="deploy.completed")
    if before:
        events = [e for e in events if (e.get("ts") or "") < before]
    if not events:
        return None
    return events[-1].get("sha")
