#!/usr/bin/env python3
"""
verify-layout-fingerprint.py — L2 forcing function gate.

Verifies the executor wrote LAYOUT-FINGERPRINT.md with required H2 sections
before code was committed. Called from build.md at phase end (or per-task)
for any task whose body declares a SLUG-form <design-ref>.

The fingerprint forces the executor to LOOK at the PNG instead of skim it.
If they cannot articulate the grid/spacing/hierarchy in one paragraph, they
have not seen the design well enough to code it.

USAGE
  python verify-layout-fingerprint.py \
    --phase-dir .vg/phases/07.10-... \
    --task-num 4 \
    [--require true|false] \
    [--output report.json]

EXIT
  0 — PASS or SKIP (require=false + missing file)
  1 — BLOCK (file missing while required, sections missing, body too thin)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = ("Grid", "Spacing", "Hierarchy", "Breakpoints")
MIN_BODY_CHARS = 60  # per section — one short paragraph
HEADING_RE = re.compile(r"^##\s+([A-Za-z][A-Za-z _-]*)\s*$")


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(body).strip()
            current = m.group(1).strip().split()[0]  # take first word — "Grid", "Spacing", etc.
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body).strip()
    return sections


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--task-num", type=int, required=True)
    ap.add_argument("--require", default="true", choices=["true", "false"])
    ap.add_argument("--output", default=None, help="Optional JSON report path")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    fp_file = phase_dir / ".fingerprints" / f"task-{args.task_num}.fingerprint.md"

    result: dict = {
        "task": args.task_num,
        "path": str(fp_file),
        "verdict": "PASS",
        "missing_sections": [],
        "thin_sections": [],
    }

    def emit(rc: int) -> int:
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return rc

    if not fp_file.exists():
        if args.require == "false":
            result["verdict"] = "SKIP"
            result["reason"] = "fingerprint not required for this task"
            return emit(0)
        result["verdict"] = "BLOCK"
        result["reason"] = "LAYOUT-FINGERPRINT.md missing — executor skipped L2 forcing function"
        return emit(1)

    text = fp_file.read_text(encoding="utf-8", errors="replace")
    sections = parse_sections(text)

    for req in REQUIRED_SECTIONS:
        if req not in sections:
            result["missing_sections"].append(req)
        elif len(sections[req]) < MIN_BODY_CHARS:
            result["thin_sections"].append(
                {"section": req, "chars": len(sections[req]), "min": MIN_BODY_CHARS}
            )

    if result["missing_sections"] or result["thin_sections"]:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"missing={result['missing_sections']} "
            f"thin={[s['section'] for s in result['thin_sections']]}"
        )
        return emit(1)

    result["sections_chars"] = {k: len(sections[k]) for k in REQUIRED_SECTIONS}
    return emit(0)


if __name__ == "__main__":
    sys.exit(main())
