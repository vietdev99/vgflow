#!/usr/bin/env python3
"""scripts/field-test/build-bundle.py — Stop-time field-test bundle assembler.

Reads a session directory's raw streams (marks.raw.jsonl, console.raw.jsonl,
network.raw.jsonl, nav.raw.jsonl, clicks.raw.jsonl, api-<label>.log), runs
redaction at build time on browser-side streams (API logs were redacted at
capture), correlates ±N-second windows per Mark, and writes:
  - manifest.json    (version, sid, mark_count, partial flag, redaction info)
  - marks.jsonl      (one bundle entry per Mark with correlated windows)
  - errors.jsonl     (naive timestamps + truncated lines, NEVER silent drops)

v2.1 specifics:
  - Naive (non-Z) timestamps in API logs → logged to errors.jsonl, NOT silent.
  - Partial marks.raw.jsonl (truncated mid-line) → manifest.partial=true,
    write what parsed, continue. NO crash.
  - 0-marks session still produces valid manifest.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Load redact-stream.py via importlib because its filename is hyphenated.
SCRIPT_DIR = Path(__file__).resolve().parent
_REDACT_PATH = SCRIPT_DIR / "redact-stream.py"
_spec = importlib.util.spec_from_file_location("redact_stream", _REDACT_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load redact-stream from {_REDACT_PATH}")
redact_stream = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redact_stream)

ISO_Z_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\b")


@dataclass(frozen=True)
class LogLine:
    ts_iso: str
    raw: str


def _shift_iso(ts: str, delta_sec: int) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=delta_sec)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso_log(path: Path, errors_log: Path) -> list[LogLine]:
    """Parse ISO-Z-prefixed log lines; naive ts → errors.jsonl."""
    out: list[LogLine] = []
    with errors_log.open("a", encoding="utf-8") as err:
        for ln in path.read_text(encoding="utf-8").splitlines():
            m = ISO_Z_RE.match(ln)
            if not m:
                err.write(json.dumps({"src": str(path), "naive_ts": ln}) + "\n")
                continue
            out.append(LogLine(ts_iso=m.group(1), raw=ln))
    return out


def correlate_window(lines: list[LogLine], mark_ts: str, window_sec: int) -> list[str]:
    """ISO-8601 lexicographic comparison is correct for fixed-width Z form."""
    lo = _shift_iso(mark_ts, -window_sec)
    hi = _shift_iso(mark_ts, +window_sec)
    return [ln.raw for ln in lines if lo <= ln.ts_iso <= hi]


def _slice_browser_window(stream_lines: list[str], mark_ts: str, window_sec: int) -> Iterable[str]:
    """Browser streams carry inline "ts":"..." field; extract via regex."""
    ts_field = re.compile(r'"ts"\s*:\s*"([^"]+)"')
    lo = _shift_iso(mark_ts, -window_sec)
    hi = _shift_iso(mark_ts, +window_sec)
    for ln in stream_lines:
        m = ts_field.search(ln)
        if not m:
            continue
        if lo <= m.group(1) <= hi:
            yield ln


def assemble(session_dir: Path, mark_window_sec: int) -> dict:
    session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    pat, _used_default = redact_stream.build_pattern(session.get("redaction") or "default")
    errors_log = session_dir / "errors.jsonl"
    # Truncate errors.jsonl at the start of a build so it reflects THIS build's findings.
    errors_log.write_text("", encoding="utf-8")

    # Per-source API logs.
    api_logs: dict[str, list[LogLine]] = {}
    for src in session.get("sources", []):
        label = src["label"]
        api_path = session_dir / f"api-{label}.log"
        if api_path.exists():
            api_logs[label] = parse_iso_log(api_path, errors_log)

    # Browser-side streams — redact at build (capture left them raw in memory).
    redacted_browser_streams: dict[str, list[str]] = {}
    for name in ("console.raw.jsonl", "network.raw.jsonl", "nav.raw.jsonl", "clicks.raw.jsonl"):
        p = session_dir / name
        if not p.exists():
            continue
        redacted_browser_streams[name] = [
            redact_stream.redact(ln, pat) for ln in p.read_text(encoding="utf-8").splitlines()
        ]

    # marks.raw.jsonl — tolerate truncated final line.
    marks_raw = session_dir / "marks.raw.jsonl"
    marks: list[dict] = []
    partial = False
    if marks_raw.exists():
        for ln in marks_raw.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                marks.append(json.loads(ln))
            except json.JSONDecodeError:
                partial = True
                with errors_log.open("a", encoding="utf-8") as err:
                    err.write(json.dumps({"truncated_line": ln[:200]}) + "\n")
                break

    # Per-Mark assembly.
    bundle_marks: list[dict] = []
    for mark in marks:
        ts = mark.get("ts", "")
        entry = {
            **{k: mark[k] for k in mark if k != "raw"},
            "user_note": redact_stream.redact(mark.get("user_note", ""), pat),
            "console_window": [
                redact_stream.redact(ln, pat)
                for ln in _slice_browser_window(
                    redacted_browser_streams.get("console.raw.jsonl", []), ts, mark_window_sec
                )
            ],
            "network_window": [
                redact_stream.redact(ln, pat)
                for ln in _slice_browser_window(
                    redacted_browser_streams.get("network.raw.jsonl", []), ts, mark_window_sec
                )
            ],
            "api_log_correlated": {
                label: [redact_stream.redact(raw, pat) for raw in correlate_window(lines, ts, mark_window_sec)]
                for label, lines in api_logs.items()
            },
        }
        bundle_marks.append(entry)

    manifest = {
        "version": "1",
        "sid": session["sid"],
        "phase": session.get("phase"),
        "mark_count": len(bundle_marks),
        "partial": partial,
        "redaction_applied": session.get("redaction") or "",
        "redaction_locations": ["capture", "build"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (session_dir / "marks.jsonl").write_text(
        "\n".join(json.dumps(m) for m in bundle_marks),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--mark-window-sec", type=int, default=30)
    args = ap.parse_args()
    manifest = assemble(Path(args.session_dir), args.mark_window_sec)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
