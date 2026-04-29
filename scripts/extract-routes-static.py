#!/usr/bin/env python3
"""
extract-routes-static.py — v2.35.0 graphify-less route discovery fallback.

Regex-based extraction of HTTP route registrations from common backend
frameworks. Used by /vg:review when graphify is not configured or the
project is in a non-Node graph layout.

Output: routes-static.json with `[{method, path, source_file, line, framework}]`.

Frameworks supported:
- Express / Fastify (Node)
- Next.js Pages Router + App Router (file-based)
- React Router / Vue Router (frontend, useful for SPA route map)
- FastAPI / Flask / Django (Python)
- Hono / Elysia (Bun/Edge)
- Echo / Gin / chi (Go) — light coverage

Usage:
  extract-routes-static.py --root . --out routes-static.json
  extract-routes-static.py --root apps/api --json
  extract-routes-static.py --root . --include 'apps/**/src/**' --exclude 'node_modules,dist'

Exit codes:
  0 — extraction succeeded (even if 0 routes found)
  1 — invalid args or root not found
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


@dataclass
class Route:
    method: str
    path: str
    source_file: str
    line: int
    framework: str


PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "express",
        re.compile(r'(?<![@\w])(?:app|router|api)\.(get|post|put|patch|delete|all)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]', re.I),
        "GROUP1_GROUP2",
    ),
    (
        "fastify",
        re.compile(r'(?<![@\w])fastify\.(get|post|put|patch|delete|all)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]', re.I),
        "GROUP1_GROUP2",
    ),
    (
        "fastapi",
        re.compile(r'@(?:app|router|api)\.(get|post|put|patch|delete|head|options)\s*\(\s*[\'"]([^\'"]+)[\'"]', re.I),
        "GROUP1_GROUP2",
    ),
    (
        "flask",
        re.compile(r'@(?:app|bp|blueprint)\.route\s*\(\s*[\'"]([^\'"]+)[\'"](?:\s*,\s*methods\s*=\s*\[\s*[\'"]([^\'"]+))?', re.I),
        "GROUP2_GROUP1",
    ),
    (
        "django",
        re.compile(r'(?<![@\w])path\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,', re.I),
        "ANY_GROUP1",
    ),
    (
        "react-router",
        re.compile(r'<Route[^>]+path\s*=\s*[\'"`]([^\'"`]+)[\'"`]', re.I),
        "GET_GROUP1",
    ),
    (
        "vue-router",
        re.compile(r'\{\s*path:\s*[\'"`]([^\'"`]+)[\'"`]', re.I),
        "GET_GROUP1",
    ),
    (
        "hono",
        re.compile(r'(?<![@\w])(?:hono|new\s+Hono\(\))\.(get|post|put|patch|delete)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]', re.I),
        "GROUP1_GROUP2",
    ),
    (
        "go-echo-gin-chi",
        re.compile(r'(?<![@\w])(?:e|r|router)\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*"([^"]+)"', 0),
        "GROUP1_GROUP2",
    ),
]

NEXTJS_PAGES_RE = re.compile(r"^pages/(?:api/)?(.+?)\.(?:tsx?|jsx?|md)$")
NEXTJS_APP_RE = re.compile(r"^app/(.+?)/(?:page|route)\.(?:tsx?|jsx?)$")

DEFAULT_INCLUDE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".go", ".rs"}
DEFAULT_EXCLUDE_DIRS = {"node_modules", "dist", "build", ".next", "target", ".git", "__pycache__", "venv", ".venv", "vendor", "graphify-out"}


def normalize_nextjs_path(rel_path: str) -> tuple[str, str] | None:
    posix = rel_path.replace("\\", "/")
    m = NEXTJS_PAGES_RE.match(posix)
    if m:
        seg = m.group(1).lstrip("/")
        if seg == "index":
            return "GET", "/"
        seg = re.sub(r"\[\.\.\.([^\]]+)\]", r":\1*", seg)
        seg = re.sub(r"\[([^\]]+)\]", r":\1", seg)
        seg = seg[:-len("/index")] if seg.endswith("/index") else seg
        return "GET", "/" + seg
    m2 = NEXTJS_APP_RE.match(posix)
    if m2:
        seg = m2.group(1).lstrip("/")
        seg = re.sub(r"\[\.\.\.([^\]]+)\]", r":\1*", seg)
        seg = re.sub(r"\[([^\]]+)\]", r":\1", seg)
        return "GET", "/" + seg
    return None


def scan_file(path: Path, root: Path) -> list[Route]:
    out: list[Route] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out

    rel = str(path.relative_to(root)).replace("\\", "/")

    nextjs = normalize_nextjs_path(rel)
    if nextjs:
        method, p = nextjs
        out.append(Route(method=method, path=p, source_file=rel, line=1, framework="nextjs"))

    for fw, regex, mode in PATTERNS:
        for m in regex.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            if mode == "GROUP1_GROUP2":
                method = m.group(1).upper()
                p = m.group(2)
            elif mode == "GROUP2_GROUP1":
                method = (m.group(2) or "GET").upper()
                p = m.group(1)
            elif mode == "ANY_GROUP1":
                method = "ANY"
                p = m.group(1)
            elif mode == "GET_GROUP1":
                method = "GET"
                p = m.group(1)
            else:
                continue
            if not p or len(p) > 200:
                continue
            out.append(Route(method=method, path=p, source_file=rel, line=line, framework=fw))

    return out


def walk(root: Path, include_exts: set[str], exclude_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith(".")]
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in include_exts:
                files.append(Path(dirpath) / fn)
    return files


def dedupe(routes: list[Route]) -> list[Route]:
    seen: set[tuple[str, str]] = set()
    out: list[Route] = []
    for r in routes:
        key = (r.method.upper(), r.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Project root to scan (default: cwd)")
    ap.add_argument("--out", default=None, help="Output JSON path (default: stdout if --json, else routes-static.json in cwd)")
    ap.add_argument("--exclude-dirs", default=None, help="Comma-separated dirs to skip (overrides defaults)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"⛔ Root not found: {root}", file=sys.stderr)
        return 1

    excl = set(args.exclude_dirs.split(",")) if args.exclude_dirs else DEFAULT_EXCLUDE_DIRS
    files = walk(root, DEFAULT_INCLUDE_EXTS, excl)

    routes: list[Route] = []
    for f in files:
        routes.extend(scan_file(f, root))

    routes = dedupe(routes)
    routes.sort(key=lambda r: (r.framework, r.method, r.path, r.source_file, r.line))

    payload = {
        "schema_version": "1",
        "scanned_root": str(root),
        "files_scanned": len(files),
        "routes": [asdict(r) for r in routes],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    out_path = Path(args.out) if args.out else (root / "routes-static.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.quiet:
        framework_counts: dict[str, int] = {}
        for r in routes:
            framework_counts[r.framework] = framework_counts.get(r.framework, 0) + 1
        print(f"✓ Extracted {len(routes)} unique route(s) from {len(files)} file(s) → {out_path}")
        for fw, c in sorted(framework_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {fw}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
