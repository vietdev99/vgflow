#!/usr/bin/env python3
"""probe-fe-routes.py — Batch 26

Runtime FE route navigation probe. Reads API-CONTRACTS/<slug>.md BLOCK 5
consumers[].route, navigates each via curl (no Playwright dep — keeps it
fast + sandbox-friendly). Detects 404-fallback page patterns.

Limitation: curl-only mode catches HTTP 200 + page text patterns. For SPA
client-side 404 detection that requires JS execution, future enhancement
should integrate Playwright (out of scope at first ship).

Exit codes:
  0 — all routes navigable + render content (not 404 fallback)
  1 — one or more routes failed (unwired or 404 fallback rendered)
  2 — config error
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# BLOCK 5 typescript fence + consumers[] regex
BLOCK5_RE = re.compile(
    r"##\s+BLOCK\s+5:\s+FE consumer contract\s*\n+```(?:typescript|ts)\n(?P<body>.+?)\n```",
    re.DOTALL,
)
CONSUMER_RE = re.compile(
    r'\{\s*route:\s*"(?P<route>[^"]+)"\s*,\s*component:\s*"(?P<component>[^"]+)"',
)

# Patterns indicating 404 fallback page (heuristic)
NOT_FOUND_PATTERNS = [
    r'data-testid=["\']not-found',
    r'<h1>\s*(?:Page\s+)?Not Found\s*</h1>',
    r'<h1>\s*404\s*</h1>',
    r'class=["\'][^"\']*(?:not-found|page-404|error-404)',
    r'\bPage not found\b',
]
NOT_FOUND_RE = re.compile("|".join(NOT_FOUND_PATTERNS), re.IGNORECASE)


def _parse_routes(phase_dir: Path) -> list[dict]:
    contracts_dir = phase_dir / "API-CONTRACTS"
    if not contracts_dir.is_dir():
        return []
    routes = []
    seen: set[str] = set()
    for f in contracts_dir.glob("*.md"):
        body = f.read_text(encoding="utf-8", errors="replace")
        for bm in BLOCK5_RE.finditer(body):
            block_body = bm.group("body")
            for cm in CONSUMER_RE.finditer(block_body):
                route = cm.group("route")
                component = cm.group("component")
                if route in seen:
                    continue
                seen.add(route)
                routes.append({
                    "route": route,
                    "component": component,
                    "source_slug": f.stem,
                })
    return routes


def _probe_route(base_url: str, route: str, timeout: int = 10) -> dict:
    """Returns {ok, http_status, error?, not_found_detected?}."""
    url = f"{base_url.rstrip('/')}{route}"
    try:
        # curl -s -o body.txt -w '%{http_code}'
        r = subprocess.run(
            ["curl", "-sSL", "-w", "%{http_code}\n", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"curl exit {r.returncode}: {r.stderr[:200]}"}
        out = r.stdout
        # Last line is HTTP status, rest is body
        lines = out.rsplit("\n", 1)
        if len(lines) == 2:
            body, status = lines[0], lines[1].strip()
        else:
            body, status = "", out.strip()
        try:
            status_code = int(status)
        except ValueError:
            return {"ok": False, "error": f"unparseable status: {status!r}"}
        if status_code >= 400:
            return {"ok": False, "http_status": status_code, "error": f"HTTP {status_code}"}
        not_found = bool(NOT_FOUND_RE.search(body))
        return {
            "ok": not not_found,
            "http_status": status_code,
            "not_found_detected": not_found,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except FileNotFoundError:
        return {"ok": False, "error": "curl not found in PATH"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--base-url", default="http://localhost:5173",
                    help="FE base URL (Vite dev default)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse routes from contracts but don't probe")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    routes = _parse_routes(args.phase_dir)
    if not routes:
        msg = "No FE consumer routes found in API-CONTRACTS/*.md BLOCK 5"
        if args.json:
            print(json.dumps({"routes": [], "message": msg}))
        else:
            print(f"i {msg}")
        return 0

    if args.dry_run:
        if args.json:
            print(json.dumps({"routes": routes}))
        else:
            print(f"Routes ({len(routes)}):")
            for r in routes:
                print(f"  {r['route']} -> {r['component']} (from {r['source_slug']})")
        return 0

    results = []
    failed = 0
    for r in routes:
        probe = _probe_route(args.base_url, r["route"])
        result = {**r, **probe}
        results.append(result)
        if not probe.get("ok", False):
            failed += 1

    report = {
        "phase_dir": str(args.phase_dir),
        "base_url": args.base_url,
        "total_routes": len(routes),
        "failed_count": failed,
        "results": results,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in results:
            mark = "OK" if r.get("ok") else "FAIL"
            print(f"{mark} {r['route']:30} (HTTP {r.get('http_status', '?')}) "
                  f"{'404 fallback' if r.get('not_found_detected') else r.get('error', '')}")
        print(f"\nTotal: {len(routes)} routes, {failed} failed")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
