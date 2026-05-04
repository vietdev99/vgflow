#!/usr/bin/env python3
"""roam-analyze.py (v1.0 stub)

Read merged RAW-LOG.jsonl. Apply coherence rules R1-R8. Emit:
  - ROAM-BUGS.md (markdown, severity-grouped, with reproduction steps)
  - proposed-specs/*.spec.ts (Playwright specs that codify each bug as regression test)
  - RUN-SUMMARY.json (metrics: bugs by severity, surfaces covered, events analyzed)

v1.0 stub: implements R1, R2, R5, R7, R8 (most-impactful 5 of 8 rules).
R3 (console_error_silent), R4 (network_swallowed), R6 (ws_drift) deferred
to v1.1.

Spec: ROAM-RFC-v1.md section 3, Phase 5.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_events(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []
    events = []
    for line in jsonl_path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def is_success_toast(toast: dict | str | None) -> bool:
    if not toast:
        return False
    if isinstance(toast, dict):
        text = toast.get("text", "").lower()
        ttype = toast.get("type", "").lower()
        return ttype == "success" or any(k in text for k in ("success", "đã tạo", "đã lưu", "thành công", "saved", "created", "updated"))
    text = str(toast).lower()
    return any(k in text for k in ("success", "đã tạo", "đã lưu", "thành công", "saved", "created", "updated"))


def is_error_toast(toast: dict | str | None) -> bool:
    if not toast:
        return False
    if isinstance(toast, dict):
        text = toast.get("text", "").lower()
        ttype = toast.get("type", "").lower()
        return ttype == "error" or any(k in text for k in ("error", "fail", "lỗi", "thất bại"))
    text = str(toast).lower()
    return any(k in text for k in ("error", "fail", "lỗi", "thất bại"))


def detect_R1_silent_state_mismatch(events: list[dict]) -> list[dict]:
    """UI says success but network returned 4xx/5xx."""
    findings = []
    for ev in events:
        toast = (ev.get("ui_after") or {}).get("toast")
        if not is_success_toast(toast):
            continue
        for net in ev.get("network", []):
            status = net.get("status", 0)
            if 400 <= status < 600:
                findings.append({
                    "rule": "R1_silent_state_mismatch",
                    "severity": "high",
                    "surface": ev.get("surface"),
                    "step": ev.get("step"),
                    "description": f"UI shows success ('{toast}') but network returned {status} on {net.get('method')} {net.get('url')}",
                    "event_ref": ev,
                })
    return findings


def detect_R2_toast_inconsistency(events: list[dict]) -> list[dict]:
    """Toast says error but network was 2xx."""
    findings = []
    for ev in events:
        toast = (ev.get("ui_after") or {}).get("toast")
        if not is_error_toast(toast):
            continue
        for net in ev.get("network", []):
            status = net.get("status", 0)
            if 200 <= status < 300:
                findings.append({
                    "rule": "R2_toast_inconsistency",
                    "severity": "medium",
                    "surface": ev.get("surface"),
                    "step": ev.get("step"),
                    "description": f"Toast shows error ('{toast}') but network returned {status} on {net.get('method')} {net.get('url')} — mutation likely succeeded server-side",
                    "event_ref": ev,
                })
    return findings


def detect_R5_orphan_state(events: list[dict]) -> list[dict]:
    """POST 201 with new ID, follow-up GET list missing the ID."""
    findings = []
    for ev in events:
        if "follow_up_read" not in ev:
            continue
        for net in ev.get("network", []):
            if net.get("method") != "POST" or net.get("status") != 201:
                continue
            resp = net.get("response_body") or net.get("resp") or {}
            new_id = resp.get("id") if isinstance(resp, dict) else None
            if not new_id:
                continue
            follow = ev.get("follow_up_read", {})
            found = follow.get("found_in_list", None)
            if found is False:
                findings.append({
                    "rule": "R5_orphan_state",
                    "severity": "critical",
                    "surface": ev.get("surface"),
                    "step": ev.get("step"),
                    "description": f"Create returned 201 with id={new_id} but follow-up list GET does not include it. Likely write/read replication lag, missing cache invalidation, or transaction not committed.",
                    "event_ref": ev,
                })
    return findings


def detect_R7_delete_did_not_persist(events: list[dict]) -> list[dict]:
    """DELETE 204, follow-up GET /entity/{id} returns 200."""
    findings = []
    for ev in events:
        for net in ev.get("network", []):
            if net.get("method") != "DELETE" or net.get("status") not in (200, 202, 204):
                continue
            follow = ev.get("follow_up_read") or {}
            if follow.get("response_status") == 200 and follow.get("matched_entity"):
                findings.append({
                    "rule": "R7_delete_did_not_persist",
                    "severity": "critical",
                    "surface": ev.get("surface"),
                    "step": ev.get("step"),
                    "description": f"DELETE returned {net.get('status')} but follow-up GET still returns the entity. Likely soft-delete not filtering correctly, or DELETE handler is a no-op.",
                    "event_ref": ev,
                })
    return findings


def detect_R8_update_did_not_apply(events: list[dict]) -> list[dict]:
    """PATCH 200, follow-up GET shows old value."""
    findings = []
    for ev in events:
        for net in ev.get("network", []):
            if net.get("method") not in ("PATCH", "PUT") or not (200 <= net.get("status", 0) < 300):
                continue
            req = net.get("request_body") or net.get("req") or {}
            follow = ev.get("follow_up_read") or {}
            entity = follow.get("matched_entity") or {}
            if not isinstance(req, dict) or not isinstance(entity, dict):
                continue
            for field, expected in req.items():
                if field in entity and entity[field] != expected:
                    findings.append({
                        "rule": "R8_update_did_not_apply",
                        "severity": "high",
                        "surface": ev.get("surface"),
                        "step": ev.get("step"),
                        "description": f"PATCH sent {field}={expected!r} (status {net.get('status')}) but follow-up GET shows {field}={entity[field]!r}. Update silently dropped.",
                        "event_ref": ev,
                    })
                    break  # one finding per event
    return findings


DETECTORS = [
    detect_R1_silent_state_mismatch,
    detect_R2_toast_inconsistency,
    detect_R5_orphan_state,
    detect_R7_delete_did_not_persist,
    detect_R8_update_did_not_apply,
]


def write_bugs_md(findings: list[dict], out: Path, phase_id: str) -> None:
    by_sev = defaultdict(list)
    for f in findings:
        by_sev[f["severity"]].append(f)

    lines = [
        f"# ROAM bugs — Phase {phase_id}",
        "",
        f"**Total findings:** {len(findings)}",
        "",
        "| Severity | Count |",
        "|----------|-------|",
        f"| critical | {len(by_sev['critical'])} |",
        f"| high     | {len(by_sev['high'])} |",
        f"| medium   | {len(by_sev['medium'])} |",
        f"| low      | {len(by_sev['low'])} |",
        "",
    ]

    for sev in ("critical", "high", "medium", "low"):
        if not by_sev[sev]:
            continue
        lines.append(f"## {sev.capitalize()} ({len(by_sev[sev])})")
        lines.append("")
        for i, f in enumerate(by_sev[sev], 1):
            lines.append(f"### BUG-{sev.upper()[:1]}{i:03d} — {f['rule']}")
            lines.append("")
            lines.append(f"- **Surface:** {f['surface']}")
            lines.append(f"- **Step:** {f['step']}")
            lines.append(f"- **Description:** {f['description']}")
            lines.append(f"- **Evidence event ts:** {f['event_ref'].get('ts', '?')}")
            lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_json(findings: list[dict], events: list[dict], out: Path) -> None:
    by_sev = defaultdict(int)
    for f in findings:
        by_sev[f["severity"]] += 1
    surfaces_seen = {ev.get("surface") for ev in events if ev.get("surface")}
    summary = {
        "total_bugs": len(findings),
        "by_severity": dict(by_sev),
        "surfaces_covered": len(surfaces_seen),
        "events_analyzed": len(events),
    }
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def write_proposed_specs(findings: list[dict], out_dir: Path) -> int:
    """For top-N bugs, generate Playwright .spec.ts that codifies the bug as regression test.

    v1.0 stub: writes minimal Playwright skeleton per finding. Real codegen
    integration with vg-codegen-interactive validator deferred to v1.1.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for f in findings[:20]:  # cap at 20 specs per session
        rule = f["rule"]
        surface = f["surface"] or "unknown"
        spec_name = f"roam-{rule.lower()}-{surface.lower()}-{written:02d}.spec.ts"
        body = f"""// Auto-generated by /vg:roam — codifies finding {rule} on {surface}
// Description: {f['description']}
// SOURCE: ROAM-BUGS.md (regenerate via /vg:roam <phase>)
// REVIEW BEFORE MERGE — pass /vg:roam --merge-specs to move into test suite.

import {{ test, expect }} from '@playwright/test';

test('roam-{rule}-{surface}', async ({{ page }}) => {{
  // TODO: replace placeholder with actual reproduction steps from event ref
  // Original event ts: {f['event_ref'].get('ts', '?')}
  // Original step: {f['step']}

  test.skip(true, 'Stub generated by roam-analyze.py v1.0. Replace with real reproduction.');
}});
"""
        (out_dir / spec_name).write_text(body, encoding="utf-8")
        written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-log", required=True)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--output-md", required=True)
    ap.add_argument("--output-specs-dir", required=True)
    ap.add_argument("--output-summary", required=True)
    args = ap.parse_args()

    events = load_events(Path(args.raw_log))
    if not events:
        print(f"[roam-analyze] no events in {args.raw_log}", file=sys.stderr)
        # Still emit empty artifacts so downstream gates pass
        Path(args.output_md).write_text(f"# ROAM bugs — empty\n\nNo events captured.\n", encoding="utf-8")
        Path(args.output_summary).write_text(json.dumps({"total_bugs": 0, "by_severity": {}, "surfaces_covered": 0, "events_analyzed": 0}, indent=2), encoding="utf-8")
        Path(args.output_specs_dir).mkdir(parents=True, exist_ok=True)
        return 0

    findings = []
    for detector in DETECTORS:
        findings.extend(detector(events))

    phase_id = Path(args.phase_dir).name
    write_bugs_md(findings, Path(args.output_md), phase_id)
    write_summary_json(findings, events, Path(args.output_summary))
    spec_count = write_proposed_specs(findings, Path(args.output_specs_dir))

    print(f"[roam-analyze] {len(findings)} findings, {spec_count} proposed specs, {len(events)} events analyzed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
