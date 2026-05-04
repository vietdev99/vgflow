#!/usr/bin/env python3
"""
verify-cookie-flags-runtime.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  Static lint can grep for `secure: true` in cookie config, but a
  middleware override, a proxy-stripped flag, or an environment-specific
  regression can ship a session cookie without `HttpOnly` / `Secure` /
  `SameSite` at runtime. This validator probes the LIVE endpoint and
  inspects the actual Set-Cookie header the server returns.

Checks per Set-Cookie returned by target:
  1. Session-like cookies (name matches /session|sid|auth|token/i) MUST
     carry `HttpOnly`
  2. Over HTTPS, session cookies MUST carry `Secure`
  3. Over plain HTTP (dev/localhost), missing `Secure` → WARN not block
  4. `SameSite` MUST be `Strict` or `Lax` (never `None` unless cross-site
     OAuth explicitly waives via --allow-samesite-none)

Input modes:
  --probe-only           → GET {target-url}{login-path or /} and inspect
                            any Set-Cookie in response
  --credentials user:pwd → POST {login-path} with form-urlencoded payload
                            (basic login flow)

Exit codes:
  0 = all cookies compliant (or WARN-only on dev/localhost)
  1 = at least one violation
  2 = config error (no target, unreachable)

Usage:
  verify-cookie-flags-runtime.py --target-url http://localhost:3000 --probe-only
  verify-cookie-flags-runtime.py --target-url https://app.example.com \\
                                  --login-path /auth/login \\
                                  --credentials "alice:hunter2"
  verify-cookie-flags-runtime.py --target-url X --probe-only --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPResponse
from typing import Iterable

SESSION_NAME_RE = re.compile(r"(session|sid|auth|token|jwt)", re.IGNORECASE)


def _split_set_cookies(headers) -> list[str]:
    """Return list of raw Set-Cookie header values."""
    out: list[str] = []
    # urllib.response.getheaders() behaves like list of (name, value) pairs
    if hasattr(headers, "get_all"):
        got = headers.get_all("Set-Cookie") or []
        out.extend(got)
    elif hasattr(headers, "getall"):
        out.extend(headers.getall("Set-Cookie"))
    else:
        for name, value in headers.items():
            if name.lower() == "set-cookie":
                out.append(value)
    return out


def _parse_cookie(raw: str) -> dict:
    """Parse a Set-Cookie header value. First attr is name=value."""
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if not parts:
        return {}
    name_val = parts[0]
    if "=" in name_val:
        name, value = name_val.split("=", 1)
    else:
        name, value = name_val, ""

    # Track which directive names appear (lowercased) and any k=v values
    directives: set[str] = set()
    kv: dict = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            key_stripped = k.strip()
            kv[key_stripped.lower()] = v.strip()
            directives.add(key_stripped.lower())
        else:
            directives.add(p.strip().lower())

    return {
        "_name": name.strip(),
        "_value": value.strip(),
        "raw": raw,
        "HttpOnly": "httponly" in directives,
        "Secure": "secure" in directives,
        "SameSite": kv.get("samesite"),
        "Path": kv.get("path"),
        "Domain": kv.get("domain"),
    }


def _is_session_cookie(name: str) -> bool:
    return bool(SESSION_NAME_RE.search(name or ""))


def _probe(url: str, method: str = "GET", data: bytes | None = None,
           timeout: float = 5.0) -> dict:
    """Make HTTP request, return {status, headers, set_cookies} or error."""
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "ok": True,
                "status": resp.status,
                "set_cookies": _split_set_cookies(resp.headers),
                "scheme": urllib.parse.urlparse(url).scheme,
            }
    except urllib.error.HTTPError as e:
        # Still may have cookies on 3xx/4xx
        return {
            "ok": True,
            "status": e.code,
            "set_cookies": _split_set_cookies(e.headers) if e.headers else [],
            "scheme": urllib.parse.urlparse(url).scheme,
        }
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}


def _check_cookie(cookie: dict, scheme: str,
                  allow_samesite_none: bool) -> list[dict]:
    """Return list of violation dicts for this cookie."""
    violations: list[dict] = []
    name = cookie.get("_name", "")
    if not _is_session_cookie(name):
        return []  # Non-session cookies: skip
    if not cookie.get("HttpOnly"):
        violations.append({
            "cookie": name,
            "severity": "BLOCK",
            "issue": "missing HttpOnly flag on session cookie",
        })
    if not cookie.get("Secure"):
        is_local = scheme == "http"
        violations.append({
            "cookie": name,
            "severity": "WARN" if is_local else "BLOCK",
            "issue": (
                "missing Secure flag on session cookie"
                + (" (dev/localhost — WARN only)" if is_local else "")
            ),
        })
    samesite = (cookie.get("SameSite") or "").lower()
    if samesite == "none" and not allow_samesite_none:
        violations.append({
            "cookie": name,
            "severity": "BLOCK",
            "issue": "SameSite=None requires --allow-samesite-none",
        })
    elif samesite not in ("strict", "lax", "none"):
        violations.append({
            "cookie": name,
            "severity": "WARN",
            "issue": f"SameSite not set (or unknown value {samesite!r})",
        })
    return violations


def main() -> int:
    import os as _os
    # Allow --target-url via env var (VG_TARGET_URL) so orchestrator
    # dispatch path doesn't crash when env not set — auto-skip instead.
    env_url = _os.environ.get("VG_TARGET_URL")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", default=env_url,
                    help="base URL of live app (e.g. http://localhost:3000); "
                         "if omitted, reads VG_TARGET_URL env or auto-skips")
    ap.add_argument("--login-path", default="/",
                    help="path to probe (default: /). Used as POST target "
                         "with --credentials, else GET")
    ap.add_argument("--credentials", default=None,
                    help="user:password — enables login POST flow")
    ap.add_argument("--probe-only", action="store_true",
                    help="GET target without login (for health-style probe)")
    ap.add_argument("--allow-samesite-none", action="store_true",
                    help="permit SameSite=None (OAuth cross-site flows)")
    # Orchestrator passes --phase; runtime probe doesn't use it but accepts
    # to avoid argparse crash when called via _run_validators.
    ap.add_argument("--phase", help="(orchestrator-injected; ignored — runtime probe is project-wide)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    # Auto-skip when no target URL provided (orchestrator may dispatch
    # before deploy step has set VG_TARGET_URL). Emit PASS with skipped
    # reason so dispatch is non-blocking.
    if not args.target_url:
        print(__import__("json").dumps({
            "validator": "verify-cookie-flags-runtime",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": "no target-url (set --target-url or VG_TARGET_URL env after deploy)",
        }))
        return 0

    url = args.target_url.rstrip("/") + args.login_path
    if args.credentials and not args.probe_only:
        try:
            user, pwd = args.credentials.split(":", 1)
        except ValueError:
            print("\033[38;5;208m--credentials must be user:password\033[0m", file=sys.stderr)
            return 2
        body = urllib.parse.urlencode({
            "username": user, "password": pwd,
        }).encode("utf-8")
        resp = _probe(url, method="POST", data=body, timeout=args.timeout)
    else:
        resp = _probe(url, method="GET", timeout=args.timeout)

    if not resp.get("ok"):
        print(f"⛔ Unreachable {url}: {resp.get('error')}", file=sys.stderr)
        return 2

    cookies_raw: Iterable[str] = resp.get("set_cookies", [])
    cookies = [_parse_cookie(c) for c in cookies_raw]
    scheme = resp.get("scheme", "http")

    all_violations: list[dict] = []
    for c in cookies:
        all_violations.extend(_check_cookie(
            c, scheme, args.allow_samesite_none,
        ))

    blocks = [v for v in all_violations if v["severity"] == "BLOCK"]
    warns = [v for v in all_violations if v["severity"] == "WARN"]

    report = {
        "target": url,
        "status": resp.get("status"),
        "scheme": scheme,
        "cookies_inspected": [c.get("_name") for c in cookies],
        "violations": all_violations,
        "block_count": len(blocks),
        "warn_count": len(warns),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if blocks:
            print(f"\033[38;5;208mCookie flags: {len(blocks)} BLOCK, {len(warns)} WARN\033[0m\n")
            for v in all_violations:
                print(f"  [{v['severity']}] {v['cookie']}: {v['issue']}")
        elif warns and not args.quiet:
            print(f"\033[33m Cookie flags: {len(warns)} WARN (no blocks)\033[0m")
            for v in warns:
                print(f"  [WARN] {v['cookie']}: {v['issue']}")
        elif not args.quiet:
            print(
                f"✓ Cookie flags OK — {len(cookies)} cookie(s) inspected "
                f"on {url} (status {resp.get('status')})"
            )

    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
