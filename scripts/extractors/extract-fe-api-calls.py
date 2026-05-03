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
    r"""axios\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*([^,)]+?)\s*(?:,|\))""",
    re.IGNORECASE,
)
FETCH_RE = re.compile(
    r"""fetch\s*\(\s*['"]([^'"]+)['"]\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)
TEMPLATE_FETCH_RE = re.compile(
    r"""fetch\s*\(\s*`([^`]+)`\s*(?:,\s*\{[^}]*method\s*:\s*['"`]([A-Z]+)['"`])?""",
)
# Match a single quoted/backtick string OR a concatenation chain like
#   '/a/' + id + '/b' + foo + '/c'
# Captures runtime expressions between string segments and replaces with `:param`.
_STRING_LIT_RE = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""")
_CONCAT_RE = re.compile(r"""\s*\+\s*""")


def _normalize(template: str) -> str:
    """Replace `${var}` and `${expr}` with `:param` markers for comparison."""
    return re.sub(r"\$\{[^}]+\}", ":param", template)


def _resolve_first_arg(arg: str) -> str | None:
    """Resolve an axios first arg into a path template.

    Handles three shapes:
      - 'literal' or "literal" or `template`
      - 'a/' + expr + '/b'  (string concatenation chain → expr becomes :param)
      - bare template literal with ${var}

    Returns None if the arg starts with a non-string identifier (variable URL),
    since we cannot resolve those statically.
    """
    arg = arg.strip()
    if not arg:
        return None
    # Single quoted/backtick string with no concatenation.
    m = _STRING_LIT_RE.fullmatch(arg)
    if m:
        return _normalize(m.group(2))
    # Concatenation chain: scan tokens separated by `+`.
    # Bail if first token isn't a string literal (variable URL — out of scope).
    if not arg[0] in "'\"`":
        return None
    parts: list[str] = []
    pos = 0
    while pos < len(arg):
        # Expect string literal at pos.
        m = _STRING_LIT_RE.match(arg, pos)
        if not m:
            # Non-string token between `+` separators → runtime expr → :param.
            # Find next `+` or end.
            plus = _CONCAT_RE.search(arg, pos)
            if plus is None:
                # Trailing junk; bail.
                break
            parts.append(":param")
            pos = plus.end()
            continue
        parts.append(_normalize(m.group(2)))
        pos = m.end()
        # Expect `+` separator or end.
        plus = _CONCAT_RE.match(arg, pos)
        if plus is None:
            break
        pos = plus.end()
    if not parts:
        return None
    return "".join(parts)


def _scan_file(path: Path, calls: list[dict]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for i, line in enumerate(text.splitlines(), 1):
        for m in AXIOS_RE.finditer(line):
            resolved = _resolve_first_arg(m.group(2))
            if resolved is None:
                continue
            calls.append({
                "file": str(path),
                "line": i,
                "method": m.group(1).upper(),
                "path_template": resolved,
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
