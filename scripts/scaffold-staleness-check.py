#!/usr/bin/env python3
"""
scaffold-staleness-check.py — P20 D-03b auto-regen detection.

Compares the SHA256 of DESIGN.md at scaffold time (recorded in
.scaffold-evidence/<slug>.json) against current DESIGN.md SHA256.
Stale entries → caller regenerates the mockup.

USAGE
  python scaffold-staleness-check.py \
    --evidence-dir <PHASE_DIR>/.scaffold-evidence \
    --design-md <PLANNING_DIR>/design/DESIGN.md \
    [--output report.json]

OUTPUT
  JSON: {
    "design_md_sha256": "...",
    "stale": [{slug, evidence_path, recorded_sha, current_sha}],
    "fresh": [{slug}],
    "orphan": [{slug}]    // evidence references a non-scaffold-managed file
  }

EXIT
  0 — always (caller decides what to do with results)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--design-md", required=True)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    evidence_dir = Path(args.evidence_dir)
    design_md = Path(args.design_md)

    result: dict = {
        "evidence_dir": str(evidence_dir),
        "design_md": str(design_md),
        "stale": [],
        "fresh": [],
        "orphan": [],
    }

    current_sha = file_sha256(design_md)
    result["design_md_sha256"] = current_sha or "missing"

    if not evidence_dir.exists():
        result["reason"] = "no evidence dir — first scaffold run"
        return _emit(result, args)

    for evidence_file in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(evidence_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        slug = data.get("slug") or evidence_file.stem
        recorded_sha = (data.get("design_md_sha256") or "").lower()
        mockup_file = data.get("file") or ""

        if not mockup_file or not Path(mockup_file).exists():
            result["orphan"].append({"slug": slug, "evidence": str(evidence_file)})
            continue

        if not recorded_sha or not current_sha:
            # Unknown state — treat as fresh (don't force regen if we can't tell)
            result["fresh"].append({"slug": slug})
            continue

        if recorded_sha == current_sha:
            result["fresh"].append({"slug": slug})
        else:
            result["stale"].append({
                "slug": slug,
                "evidence": str(evidence_file),
                "recorded_sha": recorded_sha[:16],
                "current_sha": current_sha[:16],
                "mockup_file": mockup_file,
            })

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
