#!/usr/bin/env python3
"""
findings-broker.py — v2.37.0 inter-worker findings broker.

Polls `${PHASE_DIR}/runs/` while CRUD round-trip dispatch is in flight.
When a worker emits a critical finding, broadcasts it to other in-flight
workers via `${PHASE_DIR}/runs/.broker-context.json`. Workers MAY check
this file at step boundaries and adjust strategy.

Inspired by Strix's "real-time finding sharing" pattern: agent A finds
valid credentials → other agents can pick them up to test privilege
escalation paths immediately.

Two operating modes:

1. **Daemon mode** (`--daemon`): runs alongside spawn-crud-roundtrip.py,
   polls every N seconds, updates broker context. Exits when INDEX.json
   shows all workers complete.

2. **Snapshot mode** (no flag): one-shot scan of current runs/ state,
   writes broker context, exits. Useful for non-parallel dispatch or
   post-hoc context refresh.

Broadcast triggers (default — configurable via --triggers):
- Severity >= critical AND security_impact == auth_bypass
- Severity >= critical AND security_impact == tenant_leakage
- Finding includes data_created with valid auth tokens (credential leak)

Output: ${PHASE_DIR}/runs/.broker-context.json
```json
{
  "schema_version": "1",
  "updated_at": "2026-04-30T...",
  "broadcasts": [
    {
      "from_run_id": "...",
      "from_resource": "...",
      "from_role": "...",
      "trigger": "auth_bypass_critical",
      "summary": "User role can POST to admin route /api/admin/foo",
      "evidence_ref": "...",
      "actionable_for_other_workers": [
        "Test if same user role can perform other admin mutations",
        "Test if admin token leaked appears in another response body"
      ]
    }
  ]
}
```

Usage:
  findings-broker.py --phase-dir <path>             # snapshot mode
  findings-broker.py --phase-dir <path> --daemon --interval 5
  findings-broker.py --phase-dir <path> --check     # report what would broadcast, no write

Exit codes:
  0 — success
  1 — config / IO error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_runs(phase_dir: Path) -> list[dict]:
    runs_dir = phase_dir / "runs"
    if not runs_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(runs_dir.glob("*.json")):
        if p.name in {"INDEX.json", ".broker-context.json"}:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["_source_path"] = str(p)
        out.append(data)
    return out


def is_dispatch_complete(phase_dir: Path) -> bool:
    idx = phase_dir / "runs" / "INDEX.json"
    if not idx.is_file():
        return False
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("artifacts_present", 0) + data.get("failures", 0) >= data.get("spawned", 1)


DEFAULT_TRIGGERS = {
    "auth_bypass_critical": lambda f: f.get("severity") == "critical" and f.get("security_impact") == "auth_bypass",
    "tenant_leakage_critical": lambda f: f.get("severity") == "critical" and f.get("security_impact") == "tenant_leakage",
    "credential_in_response": lambda f: any(
        kw in str(f.get("response", "")).lower() for kw in ("token", "secret", "api_key", "session=", "bearer ")
    ) and f.get("severity") in ("critical", "high"),
}


def derive_actionable(trigger: str, finding: dict) -> list[str]:
    if trigger == "auth_bypass_critical":
        role = finding.get("actor", {}).get("role", "?")
        resource = finding.get("resource", "?")
        return [
            f"If you are testing the same role ({role}), try other admin routes — the bypass may be middleware-wide",
            f"If you are testing a different resource than {resource}, probe for the same auth_bypass pattern",
        ]
    if trigger == "tenant_leakage_critical":
        return [
            "Workers testing list endpoints: include cross-tenant ID enumeration in your scan",
            "Workers testing detail endpoints: try GET with another tenant's resource ID",
        ]
    if trigger == "credential_in_response":
        return [
            "Inspect your own scan responses for token/secret leakage",
            "If you observe a leaked token, attempt to use it for elevated operations as a privilege-escalation probe",
        ]
    return []


def build_broadcasts(runs: list[dict], triggers: dict[str, callable]) -> list[dict]:
    out: list[dict] = []
    for run in runs:
        for f in run.get("findings") or []:
            for trigger_name, predicate in triggers.items():
                try:
                    if predicate(f):
                        out.append({
                            "from_run_id": run.get("run_id"),
                            "from_resource": run.get("resource"),
                            "from_role": run.get("role"),
                            "trigger": trigger_name,
                            "severity": f.get("severity"),
                            "security_impact": f.get("security_impact"),
                            "summary": f.get("title", ""),
                            "evidence_ref": f.get("step_ref"),
                            "actionable_for_other_workers": derive_actionable(trigger_name, f),
                        })
                except Exception:
                    continue
    return out


def write_context(phase_dir: Path, broadcasts: list[dict]) -> Path:
    runs_dir = phase_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = runs_dir / ".broker-context.json"
    payload = {
        "schema_version": "1",
        "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "broadcast_count": len(broadcasts),
        "broadcasts": broadcasts,
    }
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=5, help="Poll interval seconds (daemon mode)")
    ap.add_argument("--max-iterations", type=int, default=120, help="Daemon safety cap (10min @5s)")
    ap.add_argument("--check", action="store_true", help="Snapshot what would broadcast, do not write")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 1

    triggers = DEFAULT_TRIGGERS

    if not args.daemon:
        runs = load_runs(phase_dir)
        broadcasts = build_broadcasts(runs, triggers)
        if args.check:
            if args.json:
                print(json.dumps({"phase_dir": str(phase_dir), "would_broadcast": len(broadcasts), "broadcasts": broadcasts}, indent=2))
            elif not args.quiet:
                print(f"  Would broadcast: {len(broadcasts)}")
                for b in broadcasts:
                    print(f"    {b['trigger']}: {b['summary']}")
            return 0

        out_path = write_context(phase_dir, broadcasts)
        if args.json:
            print(json.dumps({"out_path": str(out_path), "broadcasts": len(broadcasts)}, indent=2))
        elif not args.quiet:
            print(f"✓ Broker context updated: {out_path} ({len(broadcasts)} broadcast(s))")
        return 0

    iter_count = 0
    last_broadcast_count = -1
    while iter_count < args.max_iterations:
        iter_count += 1
        runs = load_runs(phase_dir)
        broadcasts = build_broadcasts(runs, triggers)
        if len(broadcasts) != last_broadcast_count:
            write_context(phase_dir, broadcasts)
            if not args.quiet:
                print(f"  iter {iter_count}: {len(broadcasts)} broadcast(s) (Δ from {last_broadcast_count})")
            last_broadcast_count = len(broadcasts)

        if is_dispatch_complete(phase_dir):
            if not args.quiet:
                print(f"  iter {iter_count}: dispatch complete — broker exits")
            break
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
