"""_telemetry_helpers.py — minimal append-only telemetry emit (v2.41).

Companion Python helper for ``commands/vg/_shared/lib/telemetry.sh`` (which
is the canonical bash implementation). The bash side is the authoritative
event emitter for shell-driven VG commands; this Python side is a narrow
helper for Python scripts (spawn_recursive_probe.py, review_batch.py) that
need to emit telemetry without spawning a shell.

Schema kept minimal + consistent with the bash emitter so downstream
``/vg:telemetry`` queries see one homogeneous stream:

    {
      "event": "<event_name>",                # e.g. recursion.state_hash_hit
      "ts":    "<ISO 8601 UTC>",
      "phase_dir": "<absolute path or null>",
      "payload": { ... event-specific fields ... }
    }

Append-only writes to ``.vg/telemetry.jsonl`` at the resolved repo root.
Path is overridable via env ``VG_TELEMETRY_PATH`` for tests.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Mapping


def _resolve_path() -> Path:
    """Return the telemetry.jsonl path. Env override > .vg/telemetry.jsonl."""
    override = os.environ.get("VG_TELEMETRY_PATH")
    if override:
        return Path(override).resolve()
    repo_root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    return repo_root / ".vg" / "telemetry.jsonl"


def emit_event(event: str,
               payload: Mapping[str, Any] | None = None,
               *,
               phase_dir: str | Path | None = None,
               telemetry_path: str | Path | None = None) -> None:
    """Append a single event to the telemetry log.

    Best-effort: a write failure (disk full, permission denied) is logged to
    the payload only via Python's exception, never raised. Telemetry must
    not break the host pipeline.
    """
    path = Path(telemetry_path).resolve() if telemetry_path else _resolve_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # cannot create — silently drop
    record = {
        "event": event,
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "phase_dir": str(phase_dir) if phase_dir is not None else None,
        "payload": dict(payload or {}),
    }
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Append failed — drop on the floor; telemetry is observability,
        # never a hard requirement.
        return


def read_events(telemetry_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return parsed events from the log (test helper)."""
    path = Path(telemetry_path).resolve() if telemetry_path else _resolve_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


__all__ = ["emit_event", "read_events"]
