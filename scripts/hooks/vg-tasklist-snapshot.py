#!/usr/bin/env python3
"""
vg-tasklist-snapshot.py — Capture latest TodoWrite state per active VG run.

F1 v2.60.0 placeholder. Provides a stable, side-effect-free interface that a
PostToolUse hook can call to persist the most recent TodoWrite payload to
`.vg/runs/{run_id}/.todowrite-snapshot.json`. The companion `--restore-mode`
in emit-tasklist.py reads this snapshot on session resume/compact and overlays
its statuses on top of the contract default so the AI can re-project the
tasklist with up-to-date progress (instead of starting back at all-pending).

The actual wiring of the post-tool hook to invoke this helper is OUT OF
SCOPE for F1 (separate F2 task wires it). For F1 we ship the helper itself
so emit-tasklist's restore path has a documented contract to read against.

Usage:
  echo '{"items":[{"id":"step1","status":"completed"}]}' \\
    | python vg-tasklist-snapshot.py --write --run-id RID

Exit codes:
  0 — snapshot written (or input was empty/no-op)
  1 — invalid args
  2 — input JSON malformed
  3 — write failed (filesystem error)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _snapshot_path(run_id: str) -> Path:
    return REPO_ROOT / ".vg" / "runs" / run_id / ".todowrite-snapshot.json"


def _validate_payload(data: object) -> dict | None:
    """Accept either {"items":[{id,status},...]} or a raw list of items.
    Returns a normalised dict ready to write, or None if invalid.
    """
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items")
    else:
        return None
    if not isinstance(items, list):
        return None
    cleaned: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("id") or it.get("content") or "").strip()
        sstatus = str(it.get("status") or "").strip()
        if sid and sstatus:
            cleaned.append({"id": sid, "status": sstatus})
    return {"items": cleaned}


def _write_snapshot(run_id: str, raw_stdin: str) -> int:
    if not run_id:
        print("vg-tasklist-snapshot: --run-id required", file=sys.stderr)
        return 1
    if not raw_stdin.strip():
        # Empty input → no-op; do not clobber existing snapshot.
        return 0
    try:
        data = json.loads(raw_stdin)
    except json.JSONDecodeError as exc:
        print(f"vg-tasklist-snapshot: malformed JSON ({exc})", file=sys.stderr)
        return 2
    payload = _validate_payload(data)
    if payload is None:
        print("vg-tasklist-snapshot: payload missing items[]", file=sys.stderr)
        return 2
    if not payload["items"]:
        # No usable rows → don't overwrite a possibly-good prior snapshot.
        return 0
    out = _snapshot_path(run_id)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(out))
    except OSError as exc:
        print(f"vg-tasklist-snapshot: write failed ({exc})", file=sys.stderr)
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Write stdin JSON to .vg/runs/{run_id}/.todowrite-snapshot.json")
    ap.add_argument("--run-id", required=False, default="",
                    help="Active run ID")
    args = ap.parse_args()
    if not args.write:
        # Reserved for future read/show modes; for now require --write.
        print("vg-tasklist-snapshot: pass --write (F1 v2.60.0 placeholder)",
              file=sys.stderr)
        return 1
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    return _write_snapshot(args.run_id.strip(), raw)


if __name__ == "__main__":
    sys.exit(main())
