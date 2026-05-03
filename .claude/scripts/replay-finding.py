#!/usr/bin/env python3
"""
replay-finding.py — v2.39.0 closes Codex critique #5.

Charter violation: review findings can pass `gh release` flow without
preserving exact replay state. First dogfood findings will be disputed
or impossible to rerun.

This script reads a finding's replay manifest and re-executes the
exact request sequence that produced the finding. Useful for:

  - Verifying a finding still reproduces after a fix attempt
  - Disputing or confirming a finding during human triage
  - Generating regression tests from confirmed findings

Manifest schema (added to run-artifact-template.json `findings[].replay`):

```json
{
  "commit_sha": "abc123...",
  "worker_prompt_version": "crud-roundtrip.md@2026-04-30T...",
  "env": {
    "base_url": "http://localhost:3001",
    "phase_dir": ".vg/phases/3"
  },
  "fixtures_used": {"role": "user", "user_id": "u-001", "tenant": "t-001"},
  "seed_payload_pattern": "vg-review-{run_id}-create",
  "request_sequence": [
    {
      "step": "step-2-create",
      "method": "POST",
      "url": "/api/topup-requests",
      "headers": {"Authorization": "Bearer ${TOKEN}", "Content-Type": "application/json"},
      "body": {"name": "vg-review-abc123-create", "amount": 100},
      "expected_status": 201,
      "observed_status": 201,
      "response_excerpt": {...}
    },
    ...
  ]
}
```

Usage:
  replay-finding.py --phase-dir <path> --finding-id F-001
  replay-finding.py --phase-dir <path> --finding-id F-001 --dry-run
  replay-finding.py --phase-dir <path> --finding-id F-001 --json

Exit codes:
  0 — finding reproduces (observed matches recorded)
  1 — finding does NOT reproduce (drift since recording)
  2 — config / IO error (manifest missing, finding not found)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_findings(phase_dir: Path) -> dict:
    p = phase_dir / "REVIEW-FINDINGS.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def find_by_id(findings_doc: dict, finding_id: str) -> dict | None:
    for f in findings_doc.get("findings") or []:
        if f.get("id") == finding_id:
            return f
    return None


def load_tokens(phase_dir: Path) -> dict:
    candidates = [
        phase_dir / ".review-fixtures" / "tokens.local.yaml",
        REPO_ROOT / ".review-fixtures" / "tokens.local.yaml",
    ]
    for path in candidates:
        if path.is_file():
            try:
                import yaml
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except ImportError:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
    return {}


def substitute_token(value: str, role: str, tokens: dict) -> str:
    if not isinstance(value, str):
        return value
    role_token = (tokens.get(role) or {}).get("token") or ""
    return value.replace("${TOKEN}", role_token)


def replay_step(step: dict, role: str, tokens: dict, timeout: float) -> dict:
    method = step.get("method", "GET").upper()
    url = step.get("url", "")
    headers = {k: substitute_token(v, role, tokens) for k, v in (step.get("headers") or {}).items()}
    body = step.get("body")
    body_bytes = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else None

    req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            observed_status = resp.status
            observed_body = resp.read(2000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        observed_status = e.code
        try:
            observed_body = e.read(2000).decode("utf-8", errors="replace")
        except Exception:
            observed_body = ""
    except (urllib.error.URLError, TimeoutError) as e:
        return {"step": step.get("step"), "status": "unreachable", "error": str(e)}

    expected = step.get("expected_status")
    matches = expected is None or int(observed_status) == int(expected)

    return {
        "step": step.get("step"),
        "method": method,
        "url": url,
        "expected_status": expected,
        "observed_status": observed_status,
        "matches": matches,
        "response_excerpt": observed_body[:500],
    }


def get_current_commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--finding-id", required=True, help="e.g. F-001")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    findings_doc = load_findings(phase_dir)
    if not findings_doc:
        print(f"\033[38;5;208mREVIEW-FINDINGS.json missing in {phase_dir}\033[0m", file=sys.stderr)
        return 2

    finding = find_by_id(findings_doc, args.finding_id)
    if not finding:
        print(f"\033[38;5;208mFinding {args.finding_id} not found in REVIEW-FINDINGS.json\033[0m", file=sys.stderr)
        return 2

    replay = finding.get("replay") or {}
    if not replay:
        print(f"\033[38;5;208mFinding {args.finding_id} has no replay manifest (pre-v2.39 or worker did not emit it)\033[0m", file=sys.stderr)
        return 2

    sequence = replay.get("request_sequence") or []
    if not sequence:
        print(f"\033[38;5;208mReplay manifest empty for {args.finding_id}\033[0m", file=sys.stderr)
        return 2

    if args.dry_run:
        if args.json:
            print(json.dumps({"finding_id": args.finding_id, "would_replay_steps": len(sequence)}, indent=2))
        else:
            print(f"  Would replay {len(sequence)} step(s) for {args.finding_id}:")
            for s in sequence:
                print(f"    [{s.get('step', '?')}] {s.get('method', '?')} {s.get('url', '?')} → expect {s.get('expected_status', '?')}")
        return 0

    tokens = load_tokens(phase_dir)
    role = (replay.get("fixtures_used") or {}).get("role") or finding.get("role") or "admin"

    current_commit = get_current_commit()
    recorded_commit = replay.get("commit_sha", "unknown")

    results = [replay_step(s, role, tokens, args.timeout) for s in sequence]
    all_match = all(r.get("matches") for r in results)

    payload = {
        "finding_id": args.finding_id,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "recorded_commit": recorded_commit,
        "current_commit": current_commit,
        "commit_drift": recorded_commit != current_commit,
        "steps_replayed": len(results),
        "steps_matching": sum(1 for r in results if r.get("matches")),
        "verdict": "REPRODUCES" if all_match else "DOES_NOT_REPRODUCE",
        "results": results,
    }

    out_path = phase_dir / f"replay-{args.finding_id}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if all_match:
            print(f"✓ {args.finding_id} REPRODUCES — {payload['steps_matching']}/{len(results)} steps match")
        else:
            print(f"✗ {args.finding_id} DOES NOT REPRODUCE — {payload['steps_matching']}/{len(results)} steps match")
            for r in results:
                if not r.get("matches"):
                    print(f"   {r['step']}: expected {r.get('expected_status')} observed {r.get('observed_status')}")
        if payload["commit_drift"]:
            print(f"   \033[33mcommit drift: recorded {recorded_commit[:8]} vs current {current_commit[:8]}\033[0m")

    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
