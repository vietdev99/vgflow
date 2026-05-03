#!/usr/bin/env python3
"""extract-be-route-registry.py — grep-based BE route registry extractor.

Finds: Express (router.get/post/put/patch/delete),
       Fastify (app.get/post/...),
       NestJS (@Get('/path'), @Post('/path')),
       Hono (app.get/post/...).

Output: JSON {"routes": [{"file", "line", "method", "path_template"}]}.

Same `:param` normalization as FE extractor for direct cross-comparison.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROUTER_RE = re.compile(
    r"""(?:router|app|r)\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)
NEST_RE = re.compile(
    r"""@(Get|Post|Put|Patch|Delete|Head|Options)\s*\(\s*['"`]([^'"`]*)['"`]""",
)


def _scan_file(path: Path, routes: list[dict]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for i, line in enumerate(text.splitlines(), 1):
        for m in ROUTER_RE.finditer(line):
            routes.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": m.group(2),
            })
        for m in NEST_RE.finditer(line):
            routes.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": m.group(2),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract BE route registry")
    parser.add_argument("--root", required=True, help="Source root (e.g. apps/api/src)")
    parser.add_argument("--format", default="json", choices=["json", "jsonl"])
    parser.add_argument("--ext", default=".ts,.js")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 1

    exts = tuple(args.ext.split(","))
    routes: list[dict] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in exts:
            _scan_file(path, routes)

    if args.format == "json":
        print(json.dumps({"routes": routes, "count": len(routes), "root": str(root)}))
    else:
        for r in routes:
            print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
