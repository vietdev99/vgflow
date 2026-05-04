#!/usr/bin/env python3
"""
verify-override-debt-threshold.py — P19 D-07.

Counts unresolved override-debt entries matching a kind glob and blocks
if the count exceeds a threshold. Standalone from
verify-override-debt-sla.py (which is age-based — SLA window). This
validator is count-based: "≥N unresolved kind=design-* → BLOCK".

Wired into /vg:accept to prevent stacking design-related overrides
across the 4-layer pixel pipeline (--skip-design-pixel-gate,
--skip-fingerprint-check, --skip-build-visual, --allow-design-drift).
Without this gate, an executor that hits problem after problem can
override every layer and ship anyway.

USAGE
  python verify-override-debt-threshold.py \
    --debt-file .vg/OVERRIDE-DEBT.md \
    --kind 'design-*' \
    --threshold 2 \
    --status unresolved \
    [--output report.json]

EXIT
  0 — PASS or SKIP (no debt file)
  1 — BLOCK (count >= threshold)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

ENTRY_HEADER_RE = re.compile(
    r"^\s*-\s*id\s*:\s*\"?(?P<id>OD-[\w\-]+)\"?",
    re.IGNORECASE | re.MULTILINE,
)
KEY_RE = lambda key: re.compile(  # noqa: E731 — small helper
    rf"\*?\*?{key}\*?\*?\s*:\s*\"?(?P<v>[\w\-./*]+)\"?",
    re.IGNORECASE,
)


def parse_entries(text: str) -> list[dict]:
    """Naive YAML-ish parse — split by `- id:` blocks, extract key:value lines."""
    out: list[dict] = []
    blocks = re.split(r"(?m)^\s*-\s*id\s*:", text)
    if len(blocks) <= 1:
        return out
    # First chunk is preamble; skip
    for block in blocks[1:]:
        chunk = "- id:" + block
        entry: dict = {}
        m_id = ENTRY_HEADER_RE.search(chunk)
        if m_id:
            entry["id"] = m_id.group("id")
        for key in ("kind", "status", "severity", "flag", "reason"):
            m = KEY_RE(key).search(chunk)
            if m:
                entry[key] = m.group("v")
        if entry.get("id"):
            out.append(entry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debt-file", default=".vg/OVERRIDE-DEBT.md")
    ap.add_argument("--kind", default="*", help="glob pattern matched against entry kind field")
    ap.add_argument("--threshold", type=int, default=2)
    ap.add_argument("--status", default="unresolved", help="entry status to count (open|unresolved|resolved|all)")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    debt_path = Path(args.debt_file)
    result: dict = {
        "debt_file": str(debt_path),
        "kind_filter": args.kind,
        "threshold": args.threshold,
        "status_filter": args.status,
        "verdict": "SKIP",
        "matched": [],
    }

    if not debt_path.exists():
        result["reason"] = "no OVERRIDE-DEBT.md — nothing to check"
        return _emit(result, args)

    text = debt_path.read_text(encoding="utf-8", errors="ignore")
    entries = parse_entries(text)

    matched: list[dict] = []
    for e in entries:
        kind = (e.get("kind") or "").lower()
        status = (e.get("status") or "").lower()
        if not fnmatch.fnmatch(kind, args.kind.lower()):
            continue
        if args.status != "all" and status not in (args.status.lower(), "open"):
            # treat "open" as alias for unresolved
            if not (args.status == "unresolved" and status in ("open", "")):
                continue
        matched.append(e)

    result["matched"] = matched
    result["count"] = len(matched)

    if len(matched) >= args.threshold:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"{len(matched)} unresolved entries matching kind={args.kind!r} "
            f">= threshold {args.threshold}"
        )
    else:
        result["verdict"] = "PASS"

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
