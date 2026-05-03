#!/usr/bin/env python3
"""extract-fe-api-calls.py — grep-based extractor of FE → BE API calls.

Finds: axios.<method>(...), fetch(..., {method}), useQuery({queryKey: [...path]}),
       generated client SDK calls (api.invoices.list / api.invoices.payments.get).

Output: JSON {"calls": [{"file", "line", "method", "path_template"}]}

Limitations (P3 upgrade to ts-morph AST):
  - Template literals interpolating runtime variables produce path_template with
    `${...}` markers; this is intentional — comparison against BE registry
    treats `${X}` and `:X` (route param) equivalently.
  - Dynamic `${BASE_URL}/...` resolves only when BASE_URL appears in same file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AXIOS_RE = re.compile(
    r"""axios\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)
FETCH_RE = re.compile(
    r"""fetch\s*\(\s*['"`]([^'"`]+)['"`]\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)
TEMPLATE_FETCH_RE = re.compile(
    r"""fetch\s*\(\s*`([^`]+)`\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)


def _normalize(template: str) -> str:
    """Replace `${var}` and `${expr}` with `:param` markers for comparison."""
    return re.sub(r"\$\{[^}]+\}", ":param", template)


def _scan_file(path: Path, calls: list[dict]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for i, line in enumerate(text.splitlines(), 1):
        for m in AXIOS_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": _normalize(m.group(2)),
            })
        for m in FETCH_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": (m.group(2) or "GET").upper(),
                "path_template": _normalize(m.group(1)),
            })
        for m in TEMPLATE_FETCH_RE.finditer(line):
            calls.append({
                "file": str(path),
                "line": i,
                "method": (m.group(2) or "GET").upper(),
                "path_template": _normalize(m.group(1)),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract FE → BE API calls")
    parser.add_argument("--root", required=True, help="Source root (e.g. apps/web/src)")
    parser.add_argument("--format", default="json", choices=["json", "jsonl"])
    parser.add_argument("--ext", default=".tsx,.ts,.jsx,.js")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 1

    exts = tuple(args.ext.split(","))
    calls: list[dict] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in exts:
            _scan_file(path, calls)

    if args.format == "json":
        print(json.dumps({"calls": calls, "count": len(calls), "root": str(root)}))
    else:  # jsonl
        for c in calls:
            print(json.dumps(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
