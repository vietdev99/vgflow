#!/usr/bin/env python3
"""
verify-routes-live.py — v2.35.0 live-endpoint verifier (closes #50).

Probes every registered route from `routes-static.json` (or
`CRUD-SURFACES.md` declared routes) against the actual running app to
detect URL drift between contract/code and what the server serves.

Why this exists (issue #50):
  CRUD-SURFACES.md declares routes; build executor produces routes; if
  they diverge, downstream test/review can't trust either source. This
  script catches drift via cheap HEAD/GET probes against a running
  instance.

Output: route-status.json with per-route classification:
  - live      — 2xx / 3xx, route serves
  - drift     — declared but 404 (registered in code, not served — major bug)
  - error     — 5xx (server error on probe; not a drift but flag for triage)
  - auth_only — 401/403 (route exists but requires auth — expected for many routes)
  - unknown   — connect error / timeout

Usage:
  verify-routes-live.py --routes routes-static.json --base-url http://localhost:3001
  verify-routes-live.py --crud-surfaces .vg/phases/3/CRUD-SURFACES.md --base-url ...
  verify-routes-live.py --routes-and-surfaces ...        # union of both sources
  verify-routes-live.py ... --gate                       # exit 1 if any drift detected
  verify-routes-live.py ... --json                       # stdout payload only
  verify-routes-live.py ... --concurrency 10             # parallel probes (default 5)

Exit codes:
  0 — all routes live (or --gate not set)
  1 — drift detected (--gate active) or arg/IO error
  2 — config error (no routes / no base URL)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_routes_static(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data.get("routes", [])


def load_routes_crud_surfaces(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    code_block = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not code_block:
        return []
    try:
        data = json.loads(code_block.group(1))
    except json.JSONDecodeError:
        return []

    routes: list[dict] = []
    for resource in data.get("resources", []):
        platforms = resource.get("platforms", {})
        web = platforms.get("web", {})
        list_block = web.get("list", {})
        if list_block.get("route"):
            routes.append({"method": "GET", "path": list_block["route"], "source_file": "CRUD-SURFACES.md", "framework": "crud-surfaces", "line": 0})
        for k in ("route_admin", "route_merchant"):
            if list_block.get(k):
                routes.append({"method": "GET", "path": list_block[k], "source_file": "CRUD-SURFACES.md", "framework": "crud-surfaces", "line": 0})
        form = web.get("form", {})
        for key, method in (("create_route", "GET"), ("update_route", "GET")):
            if form.get(key):
                routes.append({"method": method, "path": form[key], "source_file": "CRUD-SURFACES.md", "framework": "crud-surfaces", "line": 0})

        backend = platforms.get("backend", {})
        list_ep = backend.get("list_endpoint", {})
        if list_ep.get("path"):
            parts = list_ep["path"].split(maxsplit=1)
            if len(parts) == 2:
                routes.append({"method": parts[0].upper(), "path": parts[1], "source_file": "CRUD-SURFACES.md", "framework": "crud-surfaces", "line": 0})
        for mp in (backend.get("mutation", {}).get("paths") or []):
            parts = mp.split(maxsplit=1)
            if len(parts) == 2:
                routes.append({"method": parts[0].upper(), "path": parts[1], "source_file": "CRUD-SURFACES.md", "framework": "crud-surfaces", "line": 0})
    return routes


def normalize_path(p: str) -> str:
    """Replace path params (:id, [id], {id}) with stable test value."""
    p = re.sub(r":[a-zA-Z_][a-zA-Z0-9_]*", "1", p)
    p = re.sub(r"\[\.\.\.[^\]]+\]", "1", p)
    p = re.sub(r"\[([^\]]+)\]", "1", p)
    p = re.sub(r"\{([^\}]+)\}", "1", p)
    p = re.sub(r"<[^>]+>", "1", p)
    return p


def probe(base_url: str, route: dict, timeout: float, auth_token: str | None) -> dict:
    method = route["method"].upper()
    raw_path = route["path"]
    norm_path = normalize_path(raw_path)
    url = base_url.rstrip("/") + norm_path

    actual_method = "GET" if method in ("ANY", "ALL", "GET") else "HEAD"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        actual_method = "HEAD"

    headers = {}
    if auth_token:
        headers["Authorization"] = auth_token

    req = urllib.request.Request(url, method=actual_method, headers=headers)
    classification = "unknown"
    status_code: int | None = None
    err_msg: str | None = None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as e:
        status_code = e.code
    except (urllib.error.URLError, TimeoutError) as e:
        err_msg = str(e)
        return {**route, "probed_url": url, "probed_method": actual_method,
                "classification": "unknown", "status_code": None, "error": err_msg}

    if status_code is None:
        classification = "unknown"
    elif 200 <= status_code < 400:
        classification = "live"
    elif status_code == 404:
        classification = "drift"
    elif status_code in (401, 403):
        classification = "auth_only"
    elif 500 <= status_code < 600:
        classification = "error"
    else:
        classification = "unknown"

    return {
        **route,
        "probed_url": url,
        "probed_method": actual_method,
        "classification": classification,
        "status_code": status_code,
        "error": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--routes", help="routes-static.json (from extract-routes-static.py)")
    ap.add_argument("--crud-surfaces", help="CRUD-SURFACES.md path")
    ap.add_argument("--base-url", required=True, help="App base URL (e.g. http://localhost:3001)")
    ap.add_argument("--auth-token", default=None, help="Bearer token for routes that require auth (optional)")
    ap.add_argument("--out", default=None, help="Output route-status.json (default: stdout if --json)")
    ap.add_argument("--gate", action="store_true", help="Exit 1 if any drift detected")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    routes: list[dict] = []
    if args.routes:
        routes.extend(load_routes_static(Path(args.routes).resolve()))
    if args.crud_surfaces:
        routes.extend(load_routes_crud_surfaces(Path(args.crud_surfaces).resolve()))

    if not routes:
        print("\033[38;5;208mNo routes loaded. Pass --routes and/or --crud-surfaces.\033[0m", file=sys.stderr)
        return 2

    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for r in routes:
        key = (r["method"].upper(), r["path"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for res in ex.map(lambda r: probe(args.base_url, r, args.timeout, args.auth_token), deduped):
            results.append(res)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1

    payload = {
        "schema_version": "1",
        "base_url": args.base_url,
        "total_routes": len(results),
        "counts": counts,
        "results": results,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        out_path = Path(args.out) if args.out else (REPO_ROOT / "route-status.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"✓ Probed {len(results)} routes against {args.base_url}")
            for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                marker = "" if cls == "drift" else "  "
                print(f"  {marker}{cls}: {n}")
            print(f"  Output: {out_path}")

    drift_count = counts.get("drift", 0)
    if args.gate and drift_count > 0:
        if not args.quiet:
            print(f"\n⛔ URL drift gate: {drift_count} route(s) registered but return 404 — build/contract mismatch.", file=sys.stderr)
            for r in results:
                if r["classification"] == "drift":
                    print(f"   {r['method']} {r['path']} → 404 ({r['source_file']}:{r['line']})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
