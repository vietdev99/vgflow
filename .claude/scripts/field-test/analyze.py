#!/usr/bin/env python3
"""scripts/field-test/analyze.py — deterministic severity heuristic + KNOWN-ISSUES append.

Reads a bundled field-test session (manifest.json + marks.jsonl), classifies
each mark's severity from console + network signals, writes FIELD-REPORT.md
to the session directory, and appends entries to .vg/KNOWN-ISSUES.json.

v2.1 specifics:
  - KNOWN-ISSUES.json corruption guard: if existing file is unparseable,
    write KNOWN-ISSUES.corrupt-<ts>.json.bak, refuse append, exit non-zero.
    NEVER silently wipe.
  - Dedupe by (sid, n): re-running on same session does not duplicate entries.

Severity heuristic (priority order; FIRST match wins):
  HIGH    — any network status in [500..599] OR
            console line contains 'Uncaught' / 'Traceback' / level=error w/ exception
  MEDIUM  — any network status in [400..499]
  LOW     — otherwise (visual-only feedback)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path


HIGH_CONSOLE_PATTERNS = re.compile(r"Uncaught|Traceback|TypeError|ReferenceError", re.IGNORECASE)


def _classify_severity(mark: dict) -> str:
    """Deterministic severity from a single mark's correlated windows."""
    # Network status scan.
    has_5xx = False
    has_4xx = False
    for ln in (mark.get("network_window") or []):
        m = re.search(r'"?status"?\s*:\s*(\d{3})', ln)
        if not m:
            continue
        code = int(m.group(1))
        if 500 <= code <= 599:
            has_5xx = True
        elif 400 <= code <= 499:
            has_4xx = True
    if has_5xx:
        return "HIGH"

    # Console error / unhandled exception scan.
    for ln in (mark.get("console_window") or []):
        if HIGH_CONSOLE_PATTERNS.search(ln):
            return "HIGH"
        # Also: level=error in JSON-formatted console entries
        if '"level":"error"' in ln or "'level': 'error'" in ln:
            return "HIGH"

    if has_4xx:
        return "MEDIUM"
    return "LOW"


def _build_issue(sid: str, phase, mark: dict, severity: str, session_dir: Path) -> dict:
    """Construct a KNOWN-ISSUES.json entry from a mark."""
    return {
        "source": "field-test",
        "sid": sid,
        "phase": phase,
        "n": mark.get("n"),
        "ts": mark.get("ts"),
        "url": mark.get("url"),
        "user_note": mark.get("user_note", ""),
        "severity": severity,
        "evidence": {
            "screenshot": str(session_dir / "marks" / f'{mark.get("n")}.png'),
            "snapshot": str(session_dir / "marks" / f'{mark.get("n")}.snapshot.yml'),
            "bundle": str(session_dir / "marks.jsonl"),
        },
        "console_summary": (mark.get("console_window") or [])[:3],
        "network_summary": (mark.get("network_window") or [])[:3],
    }


def append_known_issues(known_path: Path, issues_to_add: list[dict]) -> None:
    """Append issues to KNOWN-ISSUES.json with corruption guard + dedupe."""
    if known_path.is_file():
        try:
            payload = json.loads(known_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ts = int(time.time())
            backup = known_path.parent / f"KNOWN-ISSUES.corrupt-{ts}.json.bak"
            shutil.copy2(known_path, backup)
            print(
                f"KNOWN-ISSUES.json corrupted; backed up to {backup} — refusing append",
                file=sys.stderr,
            )
            raise SystemExit(2)
    else:
        payload = {"version": "1", "issues": []}

    if "issues" not in payload or not isinstance(payload["issues"], list):
        payload["issues"] = []

    # Dedupe by (source, sid, n) — re-run on same session is idempotent.
    existing_keys = {
        (i.get("source"), i.get("sid"), i.get("n"))
        for i in payload["issues"]
    }
    added = 0
    for issue in issues_to_add:
        key = (issue.get("source"), issue.get("sid"), issue.get("n"))
        if key not in existing_keys:
            payload["issues"].append(issue)
            existing_keys.add(key)
            added += 1
    known_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"KNOWN-ISSUES.json: appended {added} new entries (total {len(payload['issues'])})", file=sys.stderr)


def write_field_report(session_dir: Path, sid: str, phase, issues: list[dict]) -> None:
    """Write FIELD-REPORT.md with per-Mark sections + severity overview."""
    lines: list[str] = []
    lines.append(f"# FIELD-REPORT — `{sid}`")
    lines.append("")
    if phase:
        lines.append(f"**Phase:** {phase}")
        lines.append("")
    severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for i in issues:
        severity_counts[i["severity"]] = severity_counts.get(i["severity"], 0) + 1
    lines.append(
        f"**Summary:** {len(issues)} marks — "
        f"HIGH={severity_counts['HIGH']} MEDIUM={severity_counts['MEDIUM']} LOW={severity_counts['LOW']}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    for i in issues:
        lines.append(f"## Mark #{i['n']} — {i['severity']}")
        lines.append("")
        lines.append(f"- **URL:** `{i['url']}`")
        lines.append(f"- **Timestamp:** `{i['ts']}`")
        lines.append(f"- **User note:** {i['user_note']}")
        lines.append("")
        if i.get("console_summary"):
            lines.append("**Console (first 3 lines):**")
            lines.append("```")
            for ln in i["console_summary"]:
                lines.append(ln)
            lines.append("```")
            lines.append("")
        if i.get("network_summary"):
            lines.append("**Network (first 3 lines):**")
            lines.append("```")
            for ln in i["network_summary"]:
                lines.append(ln)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")
    (session_dir / "FIELD-REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--known-issues", required=True,
                    help="Path to .vg/KNOWN-ISSUES.json (will be created if missing)")
    args = ap.parse_args()

    session_dir = Path(args.session_dir)
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    sid = manifest["sid"]
    phase = manifest.get("phase")

    marks_path = session_dir / "marks.jsonl"
    marks: list[dict] = []
    if marks_path.is_file():
        for ln in marks_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                marks.append(json.loads(ln))
            except json.JSONDecodeError:
                continue

    issues = []
    for m in marks:
        sev = _classify_severity(m)
        issues.append(_build_issue(sid, phase, m, sev, session_dir))

    write_field_report(session_dir, sid, phase, issues)
    append_known_issues(Path(args.known_issues), issues)
    return 0


if __name__ == "__main__":
    sys.exit(main())
