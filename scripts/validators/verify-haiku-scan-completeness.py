#!/usr/bin/env python3
"""
verify-haiku-scan-completeness.py — v2.35.0 closes #51 invariant 1.

Hard invariant: every non-UNREACHABLE view in nav-discovery.json has a
corresponding scan-{view}.json with `elements_total >= 1`. Catches the
failure mode where Haiku scanner skill ran but produced empty artifacts
(addendum mode silent skip).

Inputs:
  --phase-dir <path>             # phase to verify
  --min-elements <int>           # threshold (default 1)
  --severity {warn|block}        # exit 1 on fail (block) or 0 with warning (warn)

Exit codes:
  0 — all non-UNREACHABLE views have populated scans (or severity=warn)
  1 — gap found (severity=block)
  2 — config error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def slug(view_url: str) -> str:
    s = view_url.strip("/").replace("/", "-")
    s = re.sub(r":[a-zA-Z_]+", "id", s)
    s = re.sub(r"[^a-zA-Z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "root"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--min-elements", type=int, default=1)
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 2

    nav = load_json(phase_dir / "nav-discovery.json")
    views = nav.get("views") or {}
    if isinstance(views, list):
        views = {v if isinstance(v, str) else (v.get("url") or v.get("path") or ""): (v if isinstance(v, dict) else {"url": v}) for v in views}

    expected_scans: list[str] = []
    for url, view in views.items():
        if not url:
            continue
        status = (view.get("status") or "").upper() if isinstance(view, dict) else ""
        if status in {"UNREACHABLE", "INFRA_PENDING", "SKIPPED"}:
            continue
        expected_scans.append(url)

    gaps: list[dict] = []
    for url in expected_scans:
        scan_path = phase_dir / f"scan-{slug(url)}.json"
        if not scan_path.is_file():
            gaps.append({"view": url, "reason": "scan_file_missing", "scan_path": str(scan_path)})
            continue
        scan = load_json(scan_path)
        elem_count = scan.get("elements_total") or len(scan.get("results") or [])
        if elem_count < args.min_elements:
            gaps.append({
                "view": url,
                "reason": "elements_below_threshold",
                "elements_total": elem_count,
                "threshold": args.min_elements,
                "scan_path": str(scan_path),
            })

    payload = {
        "phase_dir": str(phase_dir),
        "expected_scans": len(expected_scans),
        "gaps": gaps,
        "gate_pass": len(gaps) == 0,
        "severity": args.severity,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if not gaps:
            print(f"✓ Haiku scan completeness OK ({len(expected_scans)} views, all elements >= {args.min_elements})")
        else:
            tag = "⛔" if args.severity == "block" else "⚠ "
            print(f"{tag} Haiku scan completeness: {len(gaps)} gap(s)")
            for g in gaps:
                print(f"   {g['view']} — {g['reason']} (elements={g.get('elements_total', 'n/a')})")

    if gaps and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
