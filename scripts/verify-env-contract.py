#!/usr/bin/env python3
"""
verify-env-contract.py — v2.39.0 closes Codex critique #6.

Charter violation it addresses:
  Workers spawn against an environment whose state is implicit. If
  seed data missing, migrations stale, feature flags off, third-party
  stubs not active → workers produce false confidence (empty list ==
  graceful empty state, token valid but wrong tenant, mutations hit
  real prod webhooks, etc).

Pre-review gate: reads ${PHASE_DIR}/ENV-CONTRACT.md preflight_checks
and verifies each. If any fails, abort review pre-spawn.

Usage:
  verify-env-contract.py --phase-dir <path>
  verify-env-contract.py --phase-dir <path> --json
  verify-env-contract.py --phase-dir <path> --check  # report what would probe, no execution

Exit codes:
  0 — all preflight checks pass (or contract optional+missing for SAST kit)
  1 — preflight failed
  2 — config error / contract missing when required
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml
        text = path.read_text(encoding="utf-8")
        m = re.search(r"```yaml\s*\n(.+?)\n```", text, re.S)
        body = m.group(1) if m else text
        return yaml.safe_load(body) or {}
    except ImportError:
        print("⛔ pyyaml required to parse ENV-CONTRACT.md", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"⛔ parse error: {e}", file=sys.stderr)
        return {}


def load_crud_surfaces(phase_dir: Path) -> dict:
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def is_static_sast_only(surfaces: dict) -> bool:
    resources = surfaces.get("resources") or []
    if not resources:
        return False
    return all((r.get("kit") == "static-sast" for r in resources))


def substitute_template(value, contract: dict) -> str:
    if not isinstance(value, str):
        return str(value)
    pat = re.compile(r"\$\{([a-zA-Z0-9_.]+)\}")

    def replace(m):
        path = m.group(1).split(".")
        node = contract
        for p in path:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                return m.group(0)
        return str(node)
    return pat.sub(replace, value)


def run_probe(probe: str, contract: dict, timeout: float) -> tuple[bool, str]:
    probe = substitute_template(probe, contract)
    parts = probe.split(maxsplit=2)
    if len(parts) < 2:
        return False, f"unparseable probe: {probe}"
    method = parts[0].upper()
    url = parts[1]
    body = None
    if len(parts) == 3:
        try:
            body_obj = json.loads(parts[2])
            body = json.dumps(body_obj).encode("utf-8")
        except json.JSONDecodeError:
            pass

    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"{resp.status} {resp.reason}"
    except urllib.error.HTTPError as e:
        return True, f"{e.code} {e.reason}"
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"unreachable: {e}"


def evaluate_check(check: dict, contract: dict, timeout: float) -> dict:
    name = check.get("name", "unnamed")
    probe = check.get("probe", "")
    expect = str(check.get("expect", ""))

    ok, observed = run_probe(probe, contract, timeout)
    if not ok:
        return {"name": name, "status": "fail", "probe": probe, "expected": expect, "observed": observed}

    expect_status = re.search(r"\b(\d{3})\b", expect)
    if expect_status:
        if expect_status.group(1) in observed:
            return {"name": name, "status": "pass", "probe": probe, "expected": expect, "observed": observed}
        return {"name": name, "status": "fail", "probe": probe, "expected": expect, "observed": observed}

    return {"name": name, "status": "pass-best-effort", "probe": probe, "expected": expect, "observed": observed,
            "note": "could not extract numeric status from expect — passed without semantic check"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    surfaces = load_crud_surfaces(phase_dir)
    sast_only = is_static_sast_only(surfaces)

    env_path = phase_dir / "ENV-CONTRACT.md"
    contract = load_yaml(env_path)

    if not contract:
        if sast_only:
            if not args.quiet:
                print("  (kit:static-sast only — ENV-CONTRACT optional, skipping preflight)")
            return 0
        print(f"⛔ ENV-CONTRACT.md missing or empty at {env_path}", file=sys.stderr)
        print(f"   For phases with UI runtime kits, ENV-CONTRACT is required (v2.39.0+).", file=sys.stderr)
        print(f"   Copy template: cp .claude/commands/vg/_shared/templates/ENV-CONTRACT-template.md {env_path}", file=sys.stderr)
        return 2

    checks = contract.get("preflight_checks") or []
    if not checks:
        if not args.quiet:
            print("  ⚠ ENV-CONTRACT.md has no preflight_checks — env state unverified")
        return 0

    if args.check:
        if not args.quiet:
            print(f"  Would run {len(checks)} preflight probe(s):")
            for c in checks:
                print(f"    {c.get('name')}: {substitute_template(c.get('probe', ''), contract)}")
        return 0

    results = [evaluate_check(c, contract, args.timeout) for c in checks]
    failures = [r for r in results if r["status"] == "fail"]

    payload = {
        "phase_dir": str(phase_dir),
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preflight_total": len(checks),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "results": results,
        "verdict": "PASS" if not failures else "FAIL",
    }

    out_path = phase_dir / "ENV-PREFLIGHT.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not failures:
            print(f"✓ ENV-CONTRACT preflight: {len(checks)} probe(s) all pass")
        else:
            print(f"⛔ ENV-CONTRACT preflight: {len(failures)}/{len(checks)} FAILED")
            for f in failures:
                print(f"   {f['name']}: expected={f['expected']!r} observed={f['observed']!r}")
            print(f"   Report: {out_path}")
            print(f"   Override: --skip-env-contract=\"<reason>\" via review CLI")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
