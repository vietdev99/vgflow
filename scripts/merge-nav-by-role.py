#!/usr/bin/env python3
"""
merge-nav-by-role.py — v2.35.0 auth-aware navigator output merger.

Per-role nav-discovery runs produce `nav-discovery-{role}.json`. This
script merges them into a single `nav-discovery.json` with a
role-visibility matrix per view:

```json
{
  "views": {
    "/admin/users": {
      "url": "/admin/users",
      "visible_to":  ["admin"],
      "denied_for":  ["user", "anon"],
      "discovery_role_evidence": {
        "admin": {"http_status": 200, "in_sidebar": true},
        "user":  {"http_status": 403, "in_sidebar": false},
        "anon":  {"http_status": 401, "in_sidebar": false}
      }
    }
  }
}
```

Workers spawned by spawn-crud-roundtrip.py read this matrix to know
expected behavior per role per view (admin sees X, user expected 403, etc).

Inputs:
  --phase-dir  : path containing nav-discovery-{role}.json files
  --roles      : comma-separated role list (default: admin,user,anon)
  --out        : output path (default: ${PHASE_DIR}/nav-discovery.json)

Exit codes:
  0 — merge succeeded (output written)
  1 — no per-role files found
  2 — arg/IO error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_nav(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def view_url(view: dict | str) -> str:
    if isinstance(view, str):
        return view
    return view.get("url") or view.get("path") or view.get("route") or ""


def view_status(view: dict | str) -> int | None:
    if isinstance(view, dict):
        s = view.get("http_status") or view.get("status")
        if isinstance(s, int):
            return s
    return None


def view_in_sidebar(view: dict | str) -> bool:
    if isinstance(view, dict):
        return bool(view.get("in_sidebar") or view.get("source") == "sidebar")
    return False


def merge(per_role: dict[str, dict], roles_order: list[str]) -> dict:
    matrix: dict[str, dict] = {}

    for role in roles_order:
        nav = per_role.get(role) or {}
        views = nav.get("views") or nav.get("discovered") or []
        if isinstance(views, dict):
            views = list(views.values())

        for view in views:
            url = view_url(view)
            if not url:
                continue
            entry = matrix.setdefault(url, {
                "url": url,
                "visible_to": [],
                "denied_for": [],
                "discovery_role_evidence": {},
            })
            status = view_status(view)
            in_sidebar = view_in_sidebar(view)

            if status is None:
                if isinstance(view, dict) and view.get("source"):
                    entry["visible_to"].append(role)
            elif 200 <= status < 400:
                entry["visible_to"].append(role)
            elif status in (401, 403):
                entry["denied_for"].append(role)

            entry["discovery_role_evidence"][role] = {
                "http_status": status,
                "in_sidebar": in_sidebar,
            }

    for entry in matrix.values():
        entry["visible_to"] = sorted(set(entry["visible_to"]))
        entry["denied_for"] = sorted(set(entry["denied_for"]))

    return {
        "schema_version": "2",
        "roles_scanned": roles_order,
        "view_count": len(matrix),
        "views": matrix,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--roles", default="admin,user,anon")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    per_role: dict[str, dict] = {}
    for role in roles:
        path = phase_dir / f"nav-discovery-{role}.json"
        nav = load_nav(path)
        if nav:
            per_role[role] = nav
            if not args.quiet:
                print(f"  Loaded nav-discovery-{role}.json ({len(nav.get('views', []))} views)")
        else:
            if not args.quiet:
                print(f"  (no nav-discovery-{role}.json found — skipping role)")

    if not per_role:
        print(f"\033[38;5;208mNo per-role nav-discovery files found in {phase_dir}\033[0m", file=sys.stderr)
        return 1

    merged = merge(per_role, roles)

    out_path = Path(args.out) if args.out else (phase_dir / "nav-discovery.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps({
            "out_path": str(out_path.resolve()),
            "view_count": merged["view_count"],
            "roles_scanned": merged["roles_scanned"],
        }, indent=2))
    elif not args.quiet:
        print(f"✓ Merged → {out_path}")
        print(f"  Total views: {merged['view_count']}")
        print(f"  Roles: {', '.join(roles)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
