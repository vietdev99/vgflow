#!/usr/bin/env python3
"""
verify-security-headers-runtime.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  Static config check can confirm a `helmet()` / security middleware is
  imported, but a broken deploy, CDN re-write, or reverse-proxy
  mis-configuration can strip the headers before they reach the
  browser. Only a live probe of the running target can confirm the
  actual response shape.

Required headers on every probed path:
  Strict-Transport-Security : max-age >= {config hsts_min_max_age}
                              (localhost http:// WARN only — HSTS is
                              ignored by browsers for http anyway)
  X-Content-Type-Options    : nosniff
  X-Frame-Options           : DENY or SAMEORIGIN (wildcard ALLOWALL → WARN)
  Content-Security-Policy   : present (policy text not validated here)

Recommended (BLOCK only with --require-recommended):
  Referrer-Policy           : strict-origin-when-cross-origin (or stricter)
  Permissions-Policy        : present

Exit codes:
  0 = all required headers present on all paths
  1 = one or more required headers missing
  2 = target unreachable / config error

Usage:
  verify-security-headers-runtime.py --target-url http://localhost:3000
  verify-security-headers-runtime.py --target-url X --paths "/,/api/health"
  verify-security-headers-runtime.py --target-url X --require-recommended
  verify-security-headers-runtime.py --target-url X --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HSTS_MIN_MAX_AGE_DEFAULT = 31_536_000  # 1 year


REQUIRED_HEADERS = [
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Content-Security-Policy",
]

RECOMMENDED_HEADERS = [
    "Referrer-Policy",
    "Permissions-Policy",
]


def _probe(url: str, timeout: float = 5.0) -> dict:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "ok": True,
                "status": resp.status,
                "headers": {k: v for k, v in resp.headers.items()},
                "scheme": urllib.parse.urlparse(url).scheme,
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": True,
            "status": e.code,
            "headers": {k: v for k, v in (e.headers or {}).items()},
            "scheme": urllib.parse.urlparse(url).scheme,
        }
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}


def _parse_hsts_max_age(value: str) -> int | None:
    m = re.search(r"max-age\s*=\s*(\d+)", value, re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1))


def _check_headers(headers: dict, scheme: str, hsts_min: int,
                   require_recommended: bool) -> list[dict]:
    """Return list of violations."""
    violations: list[dict] = []
    hdrs_lower = {k.lower(): v for k, v in headers.items()}

    for h in REQUIRED_HEADERS:
        val = hdrs_lower.get(h.lower())
        if val is None:
            sev = "WARN" if (h == "Strict-Transport-Security"
                             and scheme == "http") else "BLOCK"
            violations.append({
                "header": h, "severity": sev,
                "issue": "missing"
                         + (" (http scheme — HSTS warn-only)"
                            if sev == "WARN" else ""),
            })
            continue
        if h == "Strict-Transport-Security":
            age = _parse_hsts_max_age(val)
            if age is None:
                violations.append({
                    "header": h, "severity": "BLOCK",
                    "issue": f"no max-age directive (value={val!r})",
                })
            elif age < hsts_min:
                violations.append({
                    "header": h, "severity": "BLOCK",
                    "issue": f"max-age={age} < required {hsts_min}",
                })
        elif h == "X-Content-Type-Options":
            if val.strip().lower() != "nosniff":
                violations.append({
                    "header": h, "severity": "BLOCK",
                    "issue": f"value {val!r} != 'nosniff'",
                })
        elif h == "X-Frame-Options":
            v = val.strip().upper()
            if v not in ("DENY", "SAMEORIGIN"):
                sev = "WARN" if "ALLOW" in v else "BLOCK"
                violations.append({
                    "header": h, "severity": sev,
                    "issue": f"value {val!r} not in {{DENY,SAMEORIGIN}}",
                })

    if require_recommended:
        for h in RECOMMENDED_HEADERS:
            if h.lower() not in hdrs_lower:
                violations.append({
                    "header": h, "severity": "BLOCK",
                    "issue": "recommended header missing (--require-recommended)",
                })
    else:
        for h in RECOMMENDED_HEADERS:
            if h.lower() not in hdrs_lower:
                violations.append({
                    "header": h, "severity": "WARN",
                    "issue": "recommended header missing",
                })

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", required=True,
                    help="base URL of live app")
    ap.add_argument("--paths", default="/",
                    help="comma-separated paths to probe (default: /)")
    ap.add_argument("--hsts-min-max-age", type=int,
                    default=HSTS_MIN_MAX_AGE_DEFAULT,
                    help="minimum HSTS max-age in seconds "
                         "(default: 31536000 = 1 year)")
    ap.add_argument("--require-recommended", action="store_true",
                    help="treat Referrer-Policy/Permissions-Policy as "
                         "required (BLOCK when missing)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    base = args.target_url.rstrip("/")

    per_path: list[dict] = []
    unreachable = 0

    for path in paths:
        if not path.startswith("/"):
            path = "/" + path
        url = base + path
        resp = _probe(url, timeout=args.timeout)
        if not resp.get("ok"):
            unreachable += 1
            per_path.append({
                "path": path, "url": url,
                "error": resp.get("error"),
                "violations": [{"header": "_probe",
                                "severity": "BLOCK",
                                "issue": "unreachable"}],
            })
            continue
        violations = _check_headers(
            resp["headers"], resp["scheme"],
            args.hsts_min_max_age,
            args.require_recommended,
        )
        per_path.append({
            "path": path, "url": url,
            "status": resp["status"],
            "violations": violations,
        })

    all_violations = [v for p in per_path for v in p.get("violations", [])]
    blocks = [v for v in all_violations if v["severity"] == "BLOCK"]
    warns = [v for v in all_violations if v["severity"] == "WARN"]

    report = {
        "target": base,
        "paths_probed": [p["path"] for p in per_path],
        "unreachable": unreachable,
        "block_count": len(blocks),
        "warn_count": len(warns),
        "results": per_path,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if blocks or unreachable:
            print(f"⛔ Security headers: {len(blocks)} BLOCK, "
                  f"{len(warns)} WARN across {len(paths)} path(s)\n")
            for p in per_path:
                for v in p.get("violations", []):
                    print(f"  [{v['severity']}] {p['path']} :: "
                          f"{v['header']} — {v['issue']}")
        elif warns and not args.quiet:
            print(f"⚠  Security headers: {len(warns)} WARN (no blocks)")
            for p in per_path:
                for v in p.get("violations", []):
                    print(f"  [WARN] {p['path']} :: "
                          f"{v['header']} — {v['issue']}")
        elif not args.quiet:
            print(
                f"✓ Security headers OK — {len(paths)} path(s) probed on "
                f"{base}"
            )

    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
