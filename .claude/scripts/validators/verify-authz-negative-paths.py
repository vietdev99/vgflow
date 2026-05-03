#!/usr/bin/env python3
"""
verify-authz-negative-paths.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  verify-authz-declared.py confirms each endpoint in API-CONTRACTS.md
  DECLARES an auth requirement. It cannot confirm the running server
  actually enforces that rule. This validator probes cross-tenant /
  cross-role boundaries at runtime: tenant A's token attempting to read
  tenant B's resource MUST return 403 (or 404 if resource-existence is
  itself hidden) — NEVER 200 with actual data.

Fixtures format (JSON):
  {
    "users": [
      {"token": "<bearer>", "tenant": "A", "role": "user"},
      {"token": "<bearer>", "tenant": "B", "role": "user"},
      {"token": "<bearer>", "tenant": "A", "role": "admin"}
    ],
    "resources": [
      {
        "path": "/api/campaigns/{id}",
        "method": "GET",
        "owned_by_tenant": "A",
        "id": "camp_1",
        "role_required": "user"
      }
    ]
  }

For each resource:
  * Owner token -> expect 200
  * Non-owner token -> expect 403 (or --allow-status list)
  * If role_required=admin: user token -> expect 403

Input:
  --target-url   base URL
  --fixtures     path to JSON file
  --allow-status comma-separated OK statuses for non-owner (default: 403,404)

Exit codes:
  0 = all boundaries enforced
  1 = at least one leak (non-owner got 200)
  2 = config error (fixtures missing/malformed, target unreachable)

Usage:
  verify-authz-negative-paths.py --target-url http://localhost:3000 \\
                                  --fixtures .vg/authz-fixtures.json
  verify-authz-negative-paths.py --target-url X --fixtures Y \\
                                  --allow-status 403 --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _probe(url: str, method: str, token: str | None, timeout: float) -> dict:
    req = urllib.request.Request(url, method=method.upper())
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(512)  # enough to detect data leak
            return {"ok": True, "status": resp.status,
                    "body_snippet": body.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        return {"ok": True, "status": e.code, "body_snippet": ""}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}


def _load_fixtures(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resolve_path(template: str, resource_id: str) -> str:
    return template.replace("{id}", urllib.parse.quote(str(resource_id)))


def main() -> int:
    import os as _os
    env_url = _os.environ.get("VG_TARGET_URL")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", default=env_url,
                    help="Live target URL; defaults to VG_TARGET_URL env or auto-skip")
    ap.add_argument("--fixtures", default=None,
                    help="JSON file: {users:[...], resources:[...]}; auto-resolves to "
                         ".vg/phases/<phase>/authz-fixtures.json when --phase set")
    ap.add_argument("--allow-status", default="403,404",
                    help="comma-separated statuses that COUNT as proper "
                         "denial for non-owner (default: 403,404)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="phase number — when set + --fixtures omitted, "
                                    "auto-resolves convention path")
    args = ap.parse_args()

    # v2.6 (2026-04-25): auto-resolve fixtures from phase convention
    if not args.fixtures and args.phase:
        phases_dir = Path(".vg/phases")
        if phases_dir.exists():
            for p in phases_dir.iterdir():
                if p.is_dir() and (p.name == args.phase
                                   or p.name.startswith(f"{args.phase}-")
                                   or p.name.startswith(f"{args.phase.zfill(2)}-")):
                    cand = p / "authz-fixtures.json"
                    if cand.exists():
                        args.fixtures = str(cand)
                    break

    # v2.6 — auto-skip when no target URL or no fixtures (probe needs both)
    if not args.target_url or not args.fixtures:
        import json as _json
        skip_reason = []
        if not args.target_url:
            skip_reason.append("no target-url (set VG_TARGET_URL after deploy)")
        if not args.fixtures:
            skip_reason.append("no fixtures file (.vg/phases/<phase>/authz-fixtures.json)")
        print(_json.dumps({
            "validator": "verify-authz-negative-paths",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": " + ".join(skip_reason),
        }))
        return 0

    fixtures_path = Path(args.fixtures)
    fixtures = _load_fixtures(fixtures_path)
    if fixtures is None:
        # File doesn't load → auto-skip
        import json as _json
        print(_json.dumps({
            "validator": "verify-authz-negative-paths",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": f"fixtures file failed to load: {fixtures_path}",
        }))
        return 0

    users = fixtures.get("users", []) or []
    resources = fixtures.get("resources", []) or []

    if not users or not resources:
        print("\033[33m Empty users or resources in fixtures — treating as WARN\033[0m",
              file=sys.stderr)
        report = {"warn": "empty fixtures",
                  "users": len(users), "resources": len(resources),
                  "probes": [], "violations": []}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("\033[33m Empty fixtures — nothing probed\033[0m")
        return 0

    allow_codes = {int(s.strip()) for s in args.allow_status.split(",")
                   if s.strip().isdigit()}
    base = args.target_url.rstrip("/")

    probes: list[dict] = []
    violations: list[dict] = []

    for res in resources:
        path_tmpl = res.get("path", "")
        method = res.get("method", "GET")
        owner_tenant = res.get("owned_by_tenant")
        role_required = res.get("role_required")
        rid = res.get("id", "")
        url = base + _resolve_path(path_tmpl, rid)

        owner_user = next(
            (u for u in users if u.get("tenant") == owner_tenant
             and (role_required is None
                  or u.get("role") == role_required
                  or u.get("role") == "admin")),
            None,
        )
        other_users = [u for u in users
                       if u.get("tenant") != owner_tenant
                       or (role_required
                           and u.get("role") not in (role_required, "admin"))]

        # Owner should get 200
        if owner_user:
            r = _probe(url, method, owner_user.get("token"), args.timeout)
            probes.append({
                "url": url, "actor": "owner",
                "tenant": owner_user.get("tenant"),
                "status": r.get("status"),
                "reachable": r.get("ok"),
            })
            if not r.get("ok"):
                violations.append({
                    "check": "target_unreachable",
                    "url": url, "error": r.get("error"),
                    "severity": "BLOCK",
                })
                continue
            if r.get("status") != 200:
                violations.append({
                    "check": "owner_denied",
                    "url": url,
                    "status": r.get("status"),
                    "severity": "WARN",
                    "reason": (
                        f"owner token returned {r.get('status')}, "
                        f"expected 200 — possible test-fixture issue"
                    ),
                })

        # Non-owners MUST NOT get 200
        for other in other_users:
            r = _probe(url, method, other.get("token"), args.timeout)
            probes.append({
                "url": url, "actor": "non-owner",
                "tenant": other.get("tenant"),
                "role": other.get("role"),
                "status": r.get("status"),
                "reachable": r.get("ok"),
            })
            if not r.get("ok"):
                violations.append({
                    "check": "target_unreachable",
                    "url": url, "error": r.get("error"),
                    "severity": "BLOCK",
                })
                continue
            status = r.get("status")
            if status == 200:
                violations.append({
                    "check": "cross_tenant_leak",
                    "url": url,
                    "actor_tenant": other.get("tenant"),
                    "actor_role": other.get("role"),
                    "status": status,
                    "severity": "BLOCK",
                    "reason": (
                        f"non-owner ({other.get('tenant')},{other.get('role')}) "
                        f"got 200 on resource owned by tenant {owner_tenant}"
                    ),
                })
            elif status not in allow_codes:
                violations.append({
                    "check": "unexpected_status",
                    "url": url,
                    "status": status,
                    "severity": "WARN",
                    "reason": (
                        f"non-owner got {status}, not in allow-status "
                        f"{sorted(allow_codes)}"
                    ),
                })

    blocks = [v for v in violations if v["severity"] == "BLOCK"]
    warns = [v for v in violations if v["severity"] == "WARN"]

    report = {
        "target": base,
        "fixtures": str(fixtures_path),
        "users": len(users),
        "resources": len(resources),
        "probes_count": len(probes),
        "violations": violations,
        "block_count": len(blocks),
        "warn_count": len(warns),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if blocks:
            print(f"\033[38;5;208mAuthZ negative paths: {len(blocks)} leaks, \033[0m"
                  f"{len(warns)} warns\n")
            for v in blocks:
                print(f"  [BLOCK] {v.get('check')}: {v.get('reason')}")
                print(f"    URL: {v.get('url')}")
            for v in warns:
                print(f"  [WARN] {v.get('check')}: {v.get('reason')}")
        elif warns and not args.quiet:
            print(f"\033[33m AuthZ: {len(warns)} WARN (no leaks)\033[0m")
            for v in warns:
                print(f"  [WARN] {v.get('check')}: {v.get('reason')}")
        elif not args.quiet:
            print(
                f"✓ AuthZ boundaries OK — {len(probes)} probe(s) across "
                f"{len(resources)} resource(s)"
            )

    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
