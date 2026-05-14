#!/usr/bin/env python3
"""verify-be-fe-consumer-parity.py — Batch 26

Compares BE endpoints declared in API-CONTRACTS.md headers vs FE consumers
declared in API-CONTRACTS/<slug>.md BLOCK 5 url field.

- Orphan BE: endpoint in BE list, no matching FE consumer -> WARN (exit 0)
- Orphan FE: consumer url not in BE list -> BLOCK (exit 1)
- Both -> exit 1

Exit codes:
  0 — parity OK (or only orphan BE endpoints, advisory)
  1 — orphan FE consumers found (BLOCK)
  2 — config error (missing API-CONTRACTS.md)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


BE_HEADER_RE = re.compile(
    r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s+(\S+)",
    re.MULTILINE,
)
BLOCK5_RE = re.compile(
    r"##\s+BLOCK\s+5:\s+FE consumer contract\s*\n+```(?:typescript|ts)\n(?P<body>.+?)\n```",
    re.DOTALL,
)
URL_FIELD_RE = re.compile(r'url:\s*"(?P<url>[^"]+)"')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    be_path = args.phase_dir / "API-CONTRACTS.md"
    if not be_path.is_file():
        print(f"BLOCK: BE API-CONTRACTS.md missing at {be_path}", file=sys.stderr)
        return 2

    be_body = be_path.read_text(encoding="utf-8")
    be_endpoints: set[str] = set()
    for m in BE_HEADER_RE.finditer(be_body):
        be_endpoints.add(m.group(2))

    fe_consumers: set[str] = set()
    contracts_dir = args.phase_dir / "API-CONTRACTS"
    fe_files = list(contracts_dir.glob("*.md")) if contracts_dir.is_dir() else []
    for f in fe_files:
        body = f.read_text(encoding="utf-8", errors="replace")
        for bm in BLOCK5_RE.finditer(body):
            for um in URL_FIELD_RE.finditer(bm.group("body")):
                fe_consumers.add(um.group("url"))

    orphan_be = sorted(be_endpoints - fe_consumers)
    orphan_fe = sorted(fe_consumers - be_endpoints)

    report = {
        "phase_dir": str(args.phase_dir),
        "be_endpoint_count": len(be_endpoints),
        "fe_consumer_count": len(fe_consumers),
        "orphan_be_endpoints": orphan_be,
        "orphan_fe_consumers": orphan_fe,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if orphan_be:
            print(f"WARN: {len(orphan_be)} BE endpoint(s) without FE consumer:")
            for e in orphan_be[:10]:
                print(f"   {e}")
        if orphan_fe:
            print(f"BLOCK: {len(orphan_fe)} FE consumer(s) reference non-existent BE endpoint (orphan FE):")
            for e in orphan_fe[:10]:
                print(f"   {e}")
        if not orphan_be and not orphan_fe:
            print(f"OK: BE-FE parity OK: {len(be_endpoints)} endpoints, {len(fe_consumers)} consumers")

    return 1 if orphan_fe else 0


if __name__ == "__main__":
    raise SystemExit(main())
