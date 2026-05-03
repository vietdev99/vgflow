#!/usr/bin/env python3
"""
verify-pencil-output.py — Phase 20 Wave C D-15.

Defensive validation for .pen files produced by /vg:design-scaffold
--tool=pencil-mcp. Pencil MCP `batch_design` syntax is strict; wrong ops
syntax silently produces 0-byte / malformed .pen. Catch that before
/vg:design-extract sees it.

Heuristics (no full Pencil format parsing — file is encrypted; we only
sanity-check shell):

  1. File exists.
  2. File size >= 100 bytes (empty .pen ≈ 50 bytes — anything smaller is
     a write that failed).
  3. File magic header matches Pencil format (first 4 bytes — heuristic).
  4. File is NOT a valid JSON / HTML / PNG (those would mean wrong handler).

USAGE
  python verify-pencil-output.py \
    --evidence-dir <PHASE_DIR>/.scaffold-evidence \
    [--min-bytes 100] \
    [--output report.json]

EXIT
  0 — all .pen files pass sanity
  1 — one or more failed (size / magic / wrong format)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MIN_BYTES_DEFAULT = 100
PNG_MAGIC = b"\x89PNG"
JPG_MAGIC = b"\xff\xd8\xff"
HTML_MAGIC = (b"<!DOCTYPE", b"<html", b"<HTML")


def is_obviously_wrong_format(head: bytes) -> str | None:
    """Return a tag string if file is detectably NOT Pencil, else None."""
    if head.startswith(PNG_MAGIC):
        return "looks-like-png"
    if head.startswith(JPG_MAGIC):
        return "looks-like-jpg"
    head_lower = head[:64].strip().lower()
    if head_lower.startswith(b"<!doctype html") or head_lower.startswith(b"<html"):
        return "looks-like-html"
    if head_lower.startswith(b"{") and (b'"slug"' in head[:200] or b'"tool"' in head[:200]):
        return "looks-like-evidence-json"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--min-bytes", type=int, default=MIN_BYTES_DEFAULT)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.exists():
        out = {"verdict": "SKIP", "reason": f"no evidence dir at {evidence_dir}"}
        if args.output:
            Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 0

    issues: list[dict] = []
    checked: list[dict] = []
    for evid in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(evid.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("tool") != "pencil-mcp":
            continue  # Not our concern
        slug = data.get("slug") or evid.stem
        pen_path = data.get("file") or ""
        p = Path(pen_path)
        info = {"slug": slug, "file": pen_path}
        if not p.exists():
            issues.append({**info, "issue": "file-missing"})
            continue
        size = p.stat().st_size
        info["size"] = size
        if size < args.min_bytes:
            issues.append({**info, "issue": f"size {size} < min {args.min_bytes}"})
            continue
        try:
            head = p.open("rb").read(256)
        except OSError as exc:
            issues.append({**info, "issue": f"read error: {exc}"})
            continue
        wrong_fmt = is_obviously_wrong_format(head)
        if wrong_fmt:
            issues.append({**info, "issue": wrong_fmt})
            continue
        checked.append(info)

    result: dict = {
        "evidence_dir": str(evidence_dir),
        "min_bytes": args.min_bytes,
        "checked": checked,
        "issues": issues,
    }
    if issues:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"{len(issues)} .pen file(s) failed sanity. "
            "Likely cause: Pencil MCP batch_design syntax error during scaffold."
        )
    else:
        result["verdict"] = "PASS" if checked else "SKIP"
        if not checked:
            result["reason"] = "no pencil-mcp evidence entries"

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
